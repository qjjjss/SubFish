# SubFish

浏览器里正在播放的音视频 → 实时语音识别 → 英/日内容翻译成中文字幕 → 桌面置顶小窗显示。

**全部在本地跑**：音频不出本机，识别用本地 Whisper，翻译用本地 Ollama。看生肉视频/网课/会议录像时挂在旁边就行。

- 支持语言：中文 / 英语 / 日语（中文直接显示识别文本，不翻译）
- 实测端到端延迟（RTX 4060 Laptop 8G，Whisper medium + qwen2.5:7b）：
  识别约 0.5s + 翻译 0.3-0.8s ≈ **1.1-1.7 秒/句**
  为了更跟手，会**先显示识别出的原文**（约 0.5-1.2s），翻译好了再原地换成中文

---

## 快速开始

### 1. 装依赖（每台机器只需一次）

双击 `安装依赖.bat`。它会：建 venv → 装依赖（走清华镜像）→ 下 Whisper 模型 → 在**桌面和开始菜单**创建 `SubFish` 快捷方式。

> 需要 Python 3.10+（脚本优先用 `py -3`）。本机实测 Python 3.13 可用。
> 想要 GPU 加速需要 NVIDIA 显卡；没有独显也能跑，把 `config.yaml` 里 `asr.model` 改成 `small`。

### 2. 确认 Ollama 在跑

```bat
ollama list          :: 列表里要有 qwen2.5:7b
ollama pull qwen2.5:7b
```

### 3. 启动

双击桌面上的 **SubFish 图标**。服务会在后台起来，图标常驻**系统托盘**（右下角，可能要展开隐藏图标），并自动拉起字幕小窗。
以后右键这个图标就能开关服务，不用再去文件夹找脚本了。

### 4. 装 Chrome 扩展

`chrome://extensions` → 打开「开发者模式」→ 「加载已解压的扩展程序」→ 选本项目的 `extension/` 目录。
然后在**正在播放声音的那个标签页**上点扩展图标 →「开始采集」。详见 [`extension/README.md`](extension/README.md)。

---

## 怎么用

托盘右键菜单：

| 菜单项 | 作用 |
| --- | --- |
| SubFish · 服务运行中 | 当前状态（不可点） |
| 启动服务 / 停止服务 | 手动开关本地服务 |
| 重新拉起字幕小窗 | 小窗被关掉时找回 |
| 打开字幕日志目录 | `logs\`，里面有 `subtitles_日期.jsonl` 和 `server.log` |
| 退出 | 一并停掉服务和小窗 |

小窗交互：左键拖拽移动，右键菜单可调原文显示、置顶、字号、透明度、宽度，也能清空或退出。位置和偏好存在 `widget/state.json`。
服务没起来时小窗会 1→10 秒自动重连。

调试（看实时日志、用测试音源）走控制台版：

```bat
启动_控制台.bat --source wav:test_audio\en_sample.wav --loop   :: 内置英语测试音
启动_控制台.bat --source mic                                :: 麦克风
venv\Scripts\python scripts\smoke_test.py                   :: 双通道自检
```

---

## 架构

```
Chrome 扩展（MV3）
  tabCapture.getMediaStreamId → offscreen 文档
    → AudioWorklet（立体声下混单声道，16kHz，Int16）
      → ws://127.0.0.1:8765  ── 二进制 PCM ──┐
                                               ▼
                              SubFish 本地服务（Python）
                                VAD（Silero，断句）
                                  → Whisper（faster-whisper）
                                    → 翻译（Ollama qwen2.5:7b）
                                      → 字幕日志 logs/*.jsonl
                                        → ws://127.0.0.1:8766 ──┐
                                                               ▼
                                                    Tkinter 桌面字幕小窗
```

扩展只负责抓音频，重活全在本地服务。服务只监听 `127.0.0.1`，外部机器连不上。

## 目录结构

```
SubFish/
├── config.yaml                所有可调参数
├── requirements.txt
├── 安装依赖.bat                首次：建 venv + 装依赖 + 下模型 + 建快捷方式
├── 启动.bat                    日常：拉起托盘（服务 + 小窗）
├── 启动_控制台.bat              调试：控制台版，支持 --source wav/mic
├── server/                    本地服务
│   ├── main.py                入口与双通道 WS
│   ├── pipeline.py            音频管线
│   ├── vad.py                 Silero VAD（纯 onnxruntime，无需 torch）
│   ├── asr.py                 faster-whisper（CUDA 优先，自动回退 CPU）
│   ├── translate.py           翻译（Ollama / DeepSeek）
│   └── models/                Silero ONNX 在库内；Whisper 需 fetch_model.py 下载
├── widget/widget.py            Tkinter 置顶小窗
├── extension/                  Chrome MV3 扩展
├── tray/tray.py                系统托盘常驻
├── scripts/                    自检 / 下模型 / 图标 / 快捷方式 / stat 观察
├── test_audio/                 测试音频
└── logs/                       字幕日志（不进仓库）
```

## 配置

`config.yaml` 集中所有参数，常用的：

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `server.audio_port` | 8765 | 音频入口（改了要同步弹窗里的端口） |
| `server.subtitle_port` | 8766 | 字幕出口（改了要同步小窗） |
| `asr.model` | medium | 显存紧张改 `small` |
| `asr.beam_size` | 1 | 贪心解码最快；调 3/5 更准但更慢 |
| `vad.silence_ms` | 450 | 静音多久算一句结束，越小越跟手 |
| `vad.max_segment_ms` | 6000 | 单句最长，超时强制切 |
| `translate.engine` | ollama | 全本地；可换 `deepseek`（需填 key） |
| `display.show_source` | true | 小窗显示英文/日文原文 |
| `display.partial_first` | true | 先出原文、后补译文（关掉就等完整译文） |

## 通道协议

想换个前端（比如网页浮层、OBS 字幕）就照这个接：

- `ws://127.0.0.1:8765` 音频入口
  - 二进制帧：16kHz 单声道 s16le PCM
  - 文本帧：`{"type":"start","tab":"页面标题"}` / `{"type":"stop"}`
- `ws://127.0.0.1:8766` 字幕出口（JSON）
  - `{"type":"hello",...}` 连上先发一条
  - `{"type":"stat","rate":1.0,"rms":0.02,...}` 每秒统计；`rate` 是音频到达速率，1.0 为实时
  - `{"type":"subtitle","seg_id":3,"lang":"en","src":"...","zh":"...","latency_ms":1200,"pending":false}`
  - 发 `{"type":"ping"}` 会回 `pong`

## 硬件要求与已知限制

| 项 | 说明 |
| --- | --- |
| GPU | 推荐 NVIDIA 8G 显存（Whisper medium + 7B 约 5.5G）。没有独显会回退 CPU，改用 `small` 模型 |
| Ollama | 必须先装并跑着，且 `ollama pull qwen2.5:7b`；服务启动时会后台预热 |
| **采集会静音原标签页** | Chrome 官方行为。本扩展已把音频回放到扬声器，正常能听到；若听到重声可在弹窗关掉 |
| **后台标签页会被限速** | 视频标签页切到后台后，音频到达速率会掉到 0.65x 左右，字幕会越拖越久。想实时就让它保持可见 |
| 只能抓浏览器标签页 | 桌面版 Zoom/Teams、手机端不在支持范围 |

## 常见问题

- **弹窗提示"本地服务未连接"**：先启动 SubFish（托盘图标）；服务晚于采集启动也没关系，会自动重连
- **音量条不动**：确认页面真的在出声；要在**播放声音的那个页面**上点开始采集
- **音量条动但不出字幕**：看控制台有没有 `Processing audio`；没有说明 VAD 没切出语音段，调 `vad.threshold` 到 0.4
- **端口被占用**：关掉多余的 SubFish，或改 `config.yaml` 两个端口 + 弹窗里的音频端口
- **翻译很慢**：第一次含模型加载；持续慢说明显存不够在 Swap，换 `qwen2.5:3b`
- **中文视频没译文**：正常，中文源不翻译

更详细的分步骤验证流程见 [`测试指南.md`](测试指南.md)。

## 参与开发

见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。

## 许可

[MIT](LICENSE)。

模型按各自许可单独处理：Whisper 见其仓库许可，Ollama 模型见 `ollama` 的模型条款；本项目不分发模型权重。
