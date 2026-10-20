"""语音识别引擎：faster-whisper 本地推理。

默认 medium + CUDA float16（RTX 4060 8G 实测可实时）；CUDA 不可用或加载失败时
自动回退 CPU int8。transcribe(pcm) -> (text, lang)。
"""
import logging
import time
from pathlib import Path

import numpy as np

log = logging.getLogger("subfish.asr")


def _ensure_cuda_dlls():
    """Windows: pip 安装的 nvidia-* 运行库不在 PATH，手动加入 DLL 搜索路径。

    ctranslate2 的 Windows wheel 只捆绑了 cuDNN，cuBLAS 需要 nvidia-cublas-cu12。
    注意 nvidia 是命名空间包，find_spec 的 origin 为 None，要取 submodule_search_locations。
    """
    import glob
    import importlib.util
    import os
    import sys

    if sys.platform != "win32":
        return
    try:
        spec = importlib.util.find_spec("nvidia")
        if spec is None:
            return
        if spec.origin:
            nvidia_root = os.path.dirname(spec.origin)
        elif spec.submodule_search_locations:
            nvidia_root = list(spec.submodule_search_locations)[0]
        else:
            return
        for bin_dir in glob.glob(os.path.join(nvidia_root, "*", "bin")):
            os.add_dll_directory(bin_dir)
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        pass


class AsrEngine:
    def __init__(self, cfg):
        asr_cfg = cfg["asr"]
        self.model_size = asr_cfg["model"]
        # beam_size=1（贪心）比 5 快很多，字幕场景精度差别很小；想要更准就调回 3/5
        self.beam_size = int(asr_cfg.get("beam_size", 1) or 1)
        self.without_timestamps = bool(asr_cfg.get("without_timestamps", True))
        model_path = asr_cfg.get("model_path") or self.model_size
        if model_path != self.model_size:
            # 相对路径按项目根目录解析；本地目录则跳过 HF 下载/缓存
            p = Path(model_path)
            if not p.is_absolute():
                p = Path(__file__).resolve().parent.parent / p
            model_path = str(p)
            if not p.is_dir():
                log.warning("model_path 不存在: %s，回退按模型名加载", p)
                model_path = self.model_size
        device, compute_type = asr_cfg["device"], asr_cfg["compute_type"]
        if device == "auto":
            _ensure_cuda_dlls()
            try:
                import ctranslate2
                device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
            except Exception:
                device = "cpu"
        if compute_type == "auto":
            compute_type = "float16" if device == "cuda" else "int8"

        from faster_whisper import WhisperModel

        self.model = None
        t0 = time.time()
        try:
            self.model = WhisperModel(model_path, device=device, compute_type=compute_type)
            self.device, self.compute_type = device, compute_type
        except Exception:
            log.warning("模型加载失败（%s/%s），回退 CPU int8", device, compute_type)
            try:
                self.device, self.compute_type = "cpu", "int8"
                self.model = WhisperModel(model_path, device="cpu", compute_type="int8")
            except Exception:
                log.exception("CPU 回退也失败，ASR 停用（修复后重启服务重试）")
                self.model = None
        if self.model is not None:
            if self.device == "cpu" and self.model_size in ("medium", "large-v3"):
                log.warning("CPU 上跑 %s 会很慢，建议把 config.yaml 的 asr.model 改成 small", self.model_size)
            log.info(
                "WhisperModel %s 就绪（%s/%s，加载 %.1fs）",
                self.model_size, self.device, self.compute_type, time.time() - t0,
            )
            self._smoke_check(model_path)

    def _smoke_check(self, model_path):
        """CUDA 缺运行库时错误只在推理时暴露；用一段静音冒烟测试，失败则回退 CPU。"""
        try:
            segments, _info = self.model.transcribe(
                np.zeros(8000, dtype=np.float32), language="en", beam_size=1,
            )
            list(segments)
        except Exception as exc:
            log.warning("推理冒烟测试失败（%s），回退 CPU int8", exc)
            try:
                from faster_whisper import WhisperModel
                self.device, self.compute_type = "cpu", "int8"
                self.model = WhisperModel(model_path, device="cpu", compute_type="int8")
                log.info("已回退 CPU int8（推理将明显变慢）")
            except Exception:
                log.exception("CPU 回退失败，ASR 停用")
                self.model = None

    def transcribe(self, pcm: bytes):
        """pcm: 16kHz 单声道 s16le -> (text, lang)。"""
        if self.model is None:
            return "", None
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, info = self.model.transcribe(
            audio,
            language=None,
            vad_filter=False,
            beam_size=self.beam_size,
            without_timestamps=self.without_timestamps,
            condition_on_previous_text=False,
        )
        text = "".join(seg.text for seg in segments).strip()
        return text, info.language
