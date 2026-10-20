# 参与开发

欢迎提 Issue 和 PR。代码风格跟着现有文件走即可，几个约定：

## 环境

```bat
安装依赖.bat          :: 建 venv 并装依赖
venv\Scripts\python scripts\fetch_model.py   :: 下 Whisper 模型（约 1.5G）
启动_控制台.bat --source wav:test_audio\en_sample.wav --loop   :: 免扩展验证
```

Windows 优先，依赖全本地（faster-whisper + Silero ONNX + 本地 Ollama）。

## 结构约定

| 目录 | 职责 |
| --- | --- |
| `server/` | 本地服务：WebSocket 双通道 + VAD + Whisper + 翻译 + 日志 |
| `widget/` | Tkinter 桌面字幕小窗（订阅 8766） |
| `extension/` | Chrome MV3 扩展（采集标签页音频推 8765） |
| `tray/` | 系统托盘常驻，拉起服务与小窗 |
| `scripts/` | 辅助脚本（自检、模型下载、图标、快捷键方式） |

## 通道协议

改协议要**同时**改三处：`server/main.py`、`extension/offscreen.js`、`widget/widget.py`。

- `ws://127.0.0.1:8765` 音频入口：二进制帧 = 16kHz 单声道 s16le PCM；文本帧 = `{"type":"start","tab":"标题"}` / `{"type":"stop"}`
- `ws://127.0.0.1:8766` 字幕出口：`{"type":"subtitle","seg_id":n,"lang":"en","src":"...","zh":"...","latency_ms":n,"pending":bool}` 与 `{"type":"stat",...}`

`pending:true` 表示"先出原文、译文还没回来"，小窗收到同一 `seg_id` 的 `pending:false` 后原地替换。

## 提交前

- Python：`venv\Scripts\python -m py_compile <改动文件>`
- JS：`node --check <改动文件>`
- 有行为改动就跑一遍 `启动_控制台.bat --source wav:... --loop` 确认字幕链路通
