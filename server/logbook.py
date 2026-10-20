"""字幕日志：按天追加 jsonl，方便看完回看复习。"""
import json
import threading
import time
from pathlib import Path


class SubtitleLog:
    def __init__(self, log_dir):
        self._lock = threading.Lock()
        self._dir = Path(log_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def append(self, record: dict):
        line = json.dumps(record, ensure_ascii=False)
        day = time.strftime("%Y-%m-%d")
        with self._lock:
            with open(self._dir / f"subtitles_{day}.jsonl", "a", encoding="utf-8") as f:
                f.write(line + "\n")
