# SubFish Chrome 扩展（M5）

捕获**当前标签页**播放的音频，实时推给本地 SubFish 服务识别翻译。音频不出本机。

## 安装（加载已解压的扩展程序）

1. 先把本地服务跑起来：双击项目根目录的 `启动.bat`（会同时拉起字幕小窗）
2. Chrome / Edge 打开 `chrome://extensions`（Edge 是 `edge://extensions`）
3. 右上角打开「**开发者模式**」
4. 点「**加载已解压的扩展程序**」，选择本目录（`SubFish/extension`）
5. 工具栏出现 SubFish 图标；建议点图钉固定

## 使用

1. 播放你要看的视频/音频页面
2. 点 SubFish 图标 → 弹窗里点「**开始采集**」
3. 字幕实时出现在桌面小窗；再点一次（变成红色「停止采集」）结束
4. 图标角标 `ON` = 正在采集；采集的标签页被关闭会自动停

弹窗里能看到：本地服务连接状态、当前采集页面、实时音量条。**音频端口**默认 8765，
和 `config.yaml` 的 `server.audio_port` 对应，改了端口要两边一起改。

## 为什么开了插件视频就没声音？这是我该怎么调

**这是 Chrome 的既定行为，不是 bug**：拿到标签页的 MediaStream 后，Chrome 就不再把这个标签页的声音
播给本机扬声器（等同于 `getDisplayMedia` 设了 `suppressLocalAudioPlayback: true`），否则你会在字幕之外
再听一遍自己的回声。

本扩展的做法是把采集到的音频**回放到默认扬声器**，所以正常情况下你听得到声音：

- 弹窗里的「**视频声音继续播放**」默认勾选 = 开启回放（设置会被记住）
- 万一听到**声音重叠/回声**（极少数环境），取消这个勾选即可，采集和字幕不受影响
- 回放走 Web Audio，会比原声晚几十毫秒，正常情况下听不出来

## 常见问题

- **弹窗提示"本地服务未连接"**：先运行 `启动.bat`；服务晚于采集启动也没关系，扩展会自动重连
- **点开始没反应/报"不能采集"**：浏览器内部页（chrome://、商店页等）没有音频可抓，切到视频页再点
- **采集了但没字幕**：看弹窗音量条有没有动——不动说明页面其实没出声；动了但没字幕，看服务端控制台日志
- **没有声音了**：采集不影响页面正常播放，声音照常；标签页上的"正在共享"提示是正常现象

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `manifest.json` | MV3 清单（权限：tabCapture / offscreen / activeTab / storage，Chrome ≥ 116） |
| `background.js` | Service Worker：拿 streamId、管理 offscreen 生命周期、状态广播、角标 |
| `offscreen.html/js` | 采集主体：getUserMedia → AudioContext 16kHz → AudioWorklet → ws 8765 |
| `audio-worklet.js` | 立体声下混单声道 + Int16 分块（1024 采样 ≈ 64ms）+ RMS 电平 |
| `popup.html/js` | 开始/停止、连接状态、音量条、端口配置 |
| `icons/` | 图标（`scripts/make_icons.py` 生成） |

## 数据流

```
标签页音频 ──tabCapture──▶ offscreen(AudioWorklet, 16kHz s16le)
                              │ ws://127.0.0.1:8765（二进制 PCM + JSON 控制）
                              ▼
                     SubFish 本地服务（VAD → Whisper → Ollama）
                              │ ws://127.0.0.1:8766（字幕 JSON）
                              ▼
                          桌面字幕小窗
```
