/* SubFish offscreen 文档：真正干活的采集端
 *
 * MV3 的 service worker 不能长时间跑 AudioContext/WebSocket，所以音频采集放在 offscreen 文档里：
 *   getUserMedia(标签页流) -> AudioContext(16kHz) -> AudioWorklet -> Int16 PCM -> ws://127.0.0.1:8765
 *
 * 协议（与 server/main.py 对齐）：
 *   二进制帧 = 16kHz 单声道 s16le PCM
 *   文本帧   = JSON 控制：{"type":"start","tab":"页面标题"} / {"type":"stop"}
 */

let ws = null;
let ctx = null;
let stream = null;
let node = null;
let muteGain = null;
let monitorGain = null; // 把标签页音频回放到扬声器用（Chrome 采集后会让原标签页静音）
let running = false;
let port = 8765;
let tabTitle = '';
let reconnectTimer = null;
let backoff = 500;

// 速率诊断：区分「浏览器音频图被限速」和「WebSocket 丢包」
let producedSamples = 0; // 工作线程产出的采样数
let sentChunks = 0;
let droppedChunks = 0; // ws 没连上时丢掉的块
let lastWall = 0;
let lastCtxTime = 0;
let meterTimer = null;
let monitorOn = true;

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === 'offscreen-start') {
    start(msg.streamId, msg.tabId, msg.title, msg.port, msg.monitor !== false);
  } else if (msg.type === 'offscreen-stop') {
    stop();
  } else if (msg.type === 'offscreen-monitor') {
    setMonitor(msg.on !== false);
  }
});

function report(patch) {
  chrome.runtime.sendMessage({ type: 'offscreen-status', ...patch }).catch(() => {});
}

// ---------- 取标签页音频流 ----------
async function getTabStream(streamId) {
  const modern = {
    audio: { chromeMediaSource: 'tab', chromeMediaSourceId: streamId },
    video: false,
  };
  const legacy = {
    audio: { mandatory: { chromeMediaSource: 'tab', chromeMediaSourceId: streamId } },
    video: false,
  };
  try {
    return await navigator.mediaDevices.getUserMedia(modern);
  } catch (e) {
    return await navigator.mediaDevices.getUserMedia(legacy);
  }
}

// ---------- WebSocket ----------
function connectWs() {
  clearTimeout(reconnectTimer);
  report({ ws: 'connecting' });
  const url = `ws://127.0.0.1:${port}`;
  ws = new WebSocket(url);
  ws.binaryType = 'arraybuffer';

  ws.onopen = () => {
    backoff = 500;
    report({ ws: 'open', error: '' });
    ws.send(JSON.stringify({ type: 'start', tab: tabTitle || 'extension' }));
  };

  ws.onclose = () => {
    ws = null;
    if (!running) return;
    report({ ws: 'closed', error: '本地服务未连接（先运行 启动.bat）' });
    // 服务可能晚一步启动，退避重连
    reconnectTimer = setTimeout(connectWs, backoff);
    backoff = Math.min(backoff * 2, 5000);
  };

  ws.onerror = () => {
    /* onclose 会接着重连，这里不重复处理 */
  };
}

function sendPcm(buf, samples) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(buf);
    sentChunks++;
  } else {
    droppedChunks++;
  }
  producedSamples += samples || 0;
}

function startMeter() {
  stopMeter();
  lastWall = performance.now();
  lastCtxTime = ctx ? ctx.currentTime : 0;
  meterTimer = setInterval(() => {
    if (!running) return stopMeter();
    const now = performance.now();
    const wallMs = now - lastWall;
    lastWall = now;

    // 音频图时钟速度：ctx.currentTime 走得比墙钟慢 = 浏览器在限速采集
    let clockRate = 0;
    if (ctx) {
      const dt = ctx.currentTime - lastCtxTime;
      lastCtxTime = ctx.currentTime;
      clockRate = wallMs > 0 ? (dt * 1000) / wallMs : 0;
      // Chrome 有可能把隐藏文档的 AudioContext 挂起，发现就拉起来
      if (ctx.state !== 'running') ctx.resume().catch(() => {});
    }

    const audioMs = producedSamples / 16; // 16kHz：1ms = 16 采样
    const rate = wallMs > 0 ? audioMs / wallMs : 0;
    producedSamples = 0;
    report({
      rate: Math.round(rate * 100) / 100,
      clockRate: Math.round(clockRate * 100) / 100,
      dropped: droppedChunks,
    });
  }, 1000);
}

function stopMeter() {
  if (meterTimer) clearInterval(meterTimer);
  meterTimer = null;
}

// ---------- 启动 / 停止 ----------
/** Chrome 采集标签页后会让它静音，靠这条链路把声音送回默认扬声器。
 *  如果发现声音重叠（极少见），在弹窗里关掉「视频声音」即可。 */
function enableMonitor(source) {
  if (!ctx || !source) return;
  monitorGain = ctx.createGain();
  monitorGain.gain.value = monitorOn ? 1 : 0;
  source.connect(monitorGain);
  monitorGain.connect(ctx.destination);
}

function setMonitor(on) {
  monitorOn = !!on;
  if (monitorGain) monitorGain.gain.value = monitorOn ? 1 : 0;
}

async function start(streamId, tabId, title, audioPort, monitor) {
  if (running) return;
  running = true;
  monitorOn = monitor !== false;
  port = Number(audioPort) || 8765;
  tabTitle = title || `tab:${tabId}`;

  try {
    stream = await getTabStream(streamId);

    ctx = new AudioContext({ sampleRate: 16000 });
    await ctx.resume();
    await ctx.audioWorklet.addModule('audio-worklet.js');

    const source = ctx.createMediaStreamSource(stream);
    node = new AudioWorkletNode(ctx, 'pcm-capture', {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      outputChannelCount: [1],
      processorOptions: { chunkSize: 1024 },
    });
    // 立体声下混成单声道
    node.channelCount = 1;
    node.channelCountMode = 'explicit';

    node.port.onmessage = (e) => {
      const d = e.data;
      // chunkSize=1024 采样（64ms），与 audio-worklet.js 保持一致
      if (d.type === 'pcm') sendPcm(d.pcm, 1024);
      else if (d.type === 'level') report({ level: d.level });
    };

    source.connect(node);
    // 必须接到 destination 才会被拉取；用 0 增益避免把声音再播一遍
    muteGain = ctx.createGain();
    muteGain.gain.value = 0;
    node.connect(muteGain);
    muteGain.connect(ctx.destination);

    // 采集会让原标签页静音 → 把声音回放到扬声器，用户才能继续听到视频
    enableMonitor(source);

    connectWs();
    startMeter();
    report({ error: '' });
  } catch (e) {
    running = false;
    report({ ws: 'closed', error: `采集失败：${e && e.message ? e.message : e}` });
    stop();
  }
}

function stop() {
  running = false;
  stopMeter();
  producedSamples = 0;
  sentChunks = 0;
  droppedChunks = 0;
  clearTimeout(reconnectTimer);
  if (ws) {
    try {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'stop' }));
      ws.close();
    } catch (_) {}
    ws = null;
  }
  if (stream) {
    stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }
  if (node) {
    node.port.onmessage = null;
    node.disconnect();
    node = null;
  }
  if (muteGain) {
    muteGain.disconnect();
    muteGain = null;
  }
  if (monitorGain) {
    monitorGain.disconnect();
    monitorGain = null;
  }
  if (ctx) {
    ctx.close().catch(() => {});
    ctx = null;
  }
  report({ ws: 'closed', level: 0, rate: 0, clockRate: 0, dropped: 0 });
}
