"""把字幕日志导出成 SRT 字幕文件，可直接挂到播放器里回看。

时间轴怎么算的：
    jsonl 里的 ts = 这句字幕"产出"的时刻，latency_ms = 从语音段结束到出字幕的耗时。
    所以 语音段结束 ≈ ts - latency_ms，语音段开始 ≈ 结束 - seg_ms（再加上一点 padding）。
    最后整体平移，让第一句从 00:00:00,000 开始。

用法：
    venv\\Scripts\\python scripts\\export_srt.py              导出今天
    venv\\Scripts\\python scripts\\export_srt.py 2026-10-19    导出指定日期
    venv\\Scripts\\python scripts\\export_srt.py all -o a.srt  导出所有
"""
import argparse
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
PAD_MS = 200  # 语音段尾部留白，让字幕稍微晚一点点消失


def _fmt(seconds):
    if seconds < 0:
        seconds = 0.0
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def load_records(day):
    if day == "all":
        files = sorted(LOG_DIR.glob("subtitles_*.jsonl"))
    else:
        files = [LOG_DIR / f"subtitles_{day}.jsonl"]
    rows = []
    for f in files:
        if not f.exists():
            continue
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    return rows


def build_srt(rows):
    items = []
    for r in rows:
        text = (r.get("zh") or r.get("src") or "").strip()
        if not text:
            continue
        end = (r.get("ts") or 0) - (r.get("latency_ms") or 0) / 1000
        # 语音段本身时长 + 尾部留白；没有就按 2 秒兜底
        dur = ((r.get("seg_ms") or 1500) + PAD_MS) / 1000
        items.append((max(0.0, end - dur), end, text, r.get("src") or ""))

    if not items:
        return ""

    # 时间轴是估算的，相邻两条可能重叠：前一条最多显示到后一条开始前 50ms
    for i in range(len(items) - 1):
        start, end, text, src = items[i]
        nxt = items[i + 1][0]
        if end > nxt - 0.05:
            items[i] = (start, max(start + 0.3, nxt - 0.05), text, src)

    offset = items[0][0]
    out = []
    for i, (start, end, text, src) in enumerate(items, 1):
        s, e = start - offset, end - offset
        if e <= s:
            e = s + 1.0
        # 中英双语：译文为主，原文作为第二行
        body = text if not src or src.strip() == text else f"{text}\n{src.strip()}"
        out.append(f"{i}\n{_fmt(s)} --> {_fmt(e)}\n{body}\n")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="SubFish 字幕导出 SRT")
    ap.add_argument("day", nargs="?", default=date.today().isoformat(),
                    help="日期 YYYY-MM-DD，或 all（默认今天）")
    ap.add_argument("-o", "--out", help="输出文件（默认 logs/subtitles_<日期>.srt）")
    args = ap.parse_args()

    LOG_DIR.mkdir(exist_ok=True)
    rows = load_records(args.day)
    if not rows:
        print(f"没有找到字幕记录（{args.day}），确认 logs/ 下有 subtitles_*.jsonl")
        return
    srt = build_srt(rows)
    if not srt:
        print("记录里没有可用的字幕文本")
        return
    out = Path(args.out) if args.out else LOG_DIR / f"subtitles_{args.day}.srt"
    out.write_text(srt, encoding="utf-8")
    print(f"已导出 {len(rows)} 条 -> {out}")


if __name__ == "__main__":
    main()
