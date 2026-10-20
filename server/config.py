"""配置加载：读取项目根目录 config.yaml，与内置默认值深合并。

可用环境变量 SUBFISH_CONFIG 指定另一份配置（测试/多实例时用不同端口很方便）。
"""
import copy
import os
from pathlib import Path

import yaml

DEFAULTS = {
    "server": {"host": "127.0.0.1", "audio_port": 8765, "subtitle_port": 8766},
    "audio": {"sample_rate": 16000, "channels": 1, "frame_ms": 20},
    "languages": ["zh", "en", "ja"],
    "asr": {"model": "medium", "device": "auto", "compute_type": "auto"},
    "vad": {"silence_ms": 600, "min_speech_ms": 250, "max_segment_ms": 8000, "threshold": 0.5},
    "translate": {
        "engine": "ollama",
        "ollama": {
            "base_url": "http://localhost:11434/v1",
            "model": "qwen2.5:7b",
            "temperature": 0.3,
            "max_tokens": 200,
        },
        "deepseek": {"base_url": "https://api.deepseek.com", "api_key": "", "model": "deepseek-chat"},
    },
    "display": {"show_source": True},
    "log": {"dir": "logs"},
}


def _deep_merge(base, override):
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def load_config(path=None):
    """加载配置；文件不存在时用默认值。"""
    cfg = copy.deepcopy(DEFAULTS)
    default_path = Path(__file__).resolve().parent.parent / "config.yaml"
    config_path = Path(path or os.environ.get("SUBFISH_CONFIG") or default_path)
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
        _deep_merge(cfg, user_cfg)
    return cfg
