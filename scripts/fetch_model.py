"""下载 Whisper 模型到 server/models/。

模型体积大（medium 约 1.5G），不进仓库，用这个脚本按需下载：

    venv\\Scripts\\python scripts\\fetch_model.py               默认 medium
    venv\\Scripts\\python scripts\\fetch_model.py --model small  小一点、更快
    venv\\Scripts\\python scripts\\fetch_model.py --endpoint https://huggingface.co   国外网络

国内网络默认走 hf-mirror，并关掉 Xet（不关会在 CAS 下载时 401 失败）。
支持断点续传，中断了再跑一次就行。
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser(description="下载 Whisper 模型")
    ap.add_argument("--model", default="medium",
                    help="模型名：tiny/base/small/medium/large-v3（默认 medium）")
    ap.add_argument("--endpoint", default="https://hf-mirror.com",
                    help="HF 镜像（默认 hf-mirror，国外可改成 https://huggingface.co）")
    args = ap.parse_args()

    # 必须在 import huggingface_hub 之前设置
    os.environ["HF_ENDPOINT"] = args.endpoint
    os.environ["HF_HUB_DISABLE_XET"] = "1"

    repo = f"Systran/faster-whisper-{args.model}"
    dest = ROOT / "server" / "models" / f"whisper-{args.model}"
    dest.mkdir(parents=True, exist_ok=True)

    print(f"从 {args.endpoint} 下载 {repo} 到 {dest} ...")
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("缺少 huggingface_hub，请先运行 安装依赖.bat")
        sys.exit(1)

    patterns = [
        "model.bin", "config.json", "tokenizer.json",
        "vocabulary.txt", "preprocessor_config.json",
    ]
    try:
        snapshot_download(
            repo,
            local_dir=str(dest),
            allow_patterns=patterns,
            resume_download=True,
        )
    except Exception as exc:
        print(f"下载失败：{exc}")
        print("换个镜像再试，或手动从 HF 下载后放到上面目录。")
        sys.exit(1)

    size = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file())
    print(f"完成，共 {size / 1024 / 1024:.0f} MB")


if __name__ == "__main__":
    main()
