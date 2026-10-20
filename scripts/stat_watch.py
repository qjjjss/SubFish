"""调试用：订阅字幕通道 8766，打印 stat / subtitle 事件，看音频到底有没有流动。

用法（服务已启动）：
    venv\\Scripts\\python scripts\\stat_watch.py [秒数]
"""
import asyncio
import json
import sys

import websockets


async def main(seconds):
    async with websockets.connect("ws://127.0.0.1:8766") as ws:
        print("已连接字幕通道", flush=True)
        try:
            async for msg in ws:
                d = json.loads(msg)
                if d.get("type") == "stat":
                    print(f"stat chunks={d['chunks']} bytes={d['bytes']} rate={d['rate']} "
                          f"rms={d['rms']} src={d.get('source')}", flush=True)
                else:
                    print("EVT", json.dumps(d, ensure_ascii=False)[:220], flush=True)
        except Exception as e:  # noqa
            print("断开:", e, flush=True)


if __name__ == "__main__":
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0
    try:
        asyncio.run(asyncio.wait_for(main(secs), secs + 2))
    except asyncio.TimeoutError:
        pass
