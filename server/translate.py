"""翻译引擎：本地 Ollama（默认，全本地）/ DeepSeek（config 可选回退）。

两者均为 OpenAI 兼容接口，同一套代码切 base_url / api_key / model。
带上一行原文+译文作上下文，保证术语与代词连贯；失败返回 None（调用方回退显示原文）。
"""
import logging

import requests

log = logging.getLogger("subfish.translate")

SYSTEM_PROMPT = (
    "你是专业的字幕翻译，把用户给出的外语台词翻译成自然、口语化的简体中文。要求：\n"
    "1. 简短口语化，像日常说话，避免书面腔和翻译腔\n"
    "2. 人名、地名、品牌、专有名词保留原文，不要硬译\n"
    "3. 结合上文语境，保证代词、术语与前文一致\n"
    "4. 只输出译文本身：不要引号、不要解释、不要备注\n"
    "5. 如果原文已经是中文，原样返回"
)


class Translator:
    def __init__(self, cfg):
        tcfg = cfg["translate"]
        self.engine = tcfg["engine"]
        if self.engine == "ollama":
            oc = tcfg["ollama"]
            self.base_url = oc["base_url"].rstrip("/")
            self.model = oc["model"]
            self.api_key = "ollama"  # 占位，Ollama 不校验 key
            self.temperature = float(oc["temperature"])
            self.max_tokens = int(oc["max_tokens"])
            self.keep_alive = oc.get("keep_alive", "10m")
        else:
            dc = tcfg["deepseek"]
            self.base_url = dc["base_url"].rstrip("/")
            self.model = dc["model"]
            self.api_key = dc["api_key"]
            self.temperature = 0.3
            self.max_tokens = 200
            if not self.api_key:
                raise ValueError("translate.engine=deepseek 但未配置 api_key")
        self._last_src = ""
        self._last_zh = ""
        self._session = requests.Session()
        if self.engine == "ollama":
            # Ollama 在本地：绕过系统代理（否则 localhost 请求可能被代理拦截超时）
            self._session.trust_env = False

    def remember(self, src, zh):
        """记录上一行原文+译文，作为下一行的翻译上下文。"""
        self._last_src, self._last_zh = src, zh

    def check(self):
        """启动探活：返回 (ok, 错误信息)。"""
        try:
            resp = self._session.get(f"{self.base_url}/models", timeout=3)
            resp.raise_for_status()
            return True, ""
        except Exception as exc:
            return False, str(exc)

    def warmup(self):
        """启动时先把模型 load 进显存/内存，避免第一句字幕等 10s+。结果丢弃。"""
        import time

        t0 = time.time()
        try:
            self.translate("hi", "en")
            log.info("翻译模型预热完成（%.1fs）", time.time() - t0)
        except Exception as exc:
            log.warning("翻译模型预热失败（%s）", exc)

    def translate(self, text: str, lang: str):
        """-> 中文字幕字符串；失败返回 None。"""
        user = f"待译原文（{lang}）：{text}"
        if self._last_src:
            user = f"上文原文：{self._last_src}\n上文译文：{self._last_zh}\n\n{user}"
        try:
            resp = self._session.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user},
                    ],
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                    "stream": False,
                } | ({"keep_alive": self.keep_alive} if self.engine == "ollama" else {}),
                timeout=30,
            )
            resp.raise_for_status()
            zh = resp.json()["choices"][0]["message"]["content"].strip()
            return zh or None
        except Exception as exc:
            log.warning("翻译请求失败（%s）", exc)
            return None
