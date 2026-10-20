/* SubFish 后台服务（MV3 service worker）
 *
 * 职责：
 *   1. 用 chrome.tabCapture.getMediaStreamId 拿到当前标签页的音频流 ID
 *   2. 创建 offscreen 文档（MV3 里只有它能长时间跑 AudioContext / WebSocket）
 *   3. 把采集状态广播给 popup，并在扩展图标上显示角标
 */

const OFFSCREEN_URL = 'offscreen.html';
const DEFAULT_PORT = 8765;

const state = {
  capturing: false,
  tabId: null,
  title: '',
  ws: 'closed',        // closed | connecting | open
  level: 0,
  rate: 0,             // 音频到达速率（1.0 = 实时）
  clockRate: 0,        // 浏览器音频图时钟速度（<1 说明被限速）
  dropped: 0,          // 因 ws 未连接丢掉的音频块
  error: '',
  port: DEFAULT_PORT,
  monitor: true,       // 采集会把原标签页静音，回放开关决定是否送回扬声器
};

// ---------- 持久化配置 ----------
async function loadPrefs() {
  const got = await chrome.storage.local.get({ audioPort: DEFAULT_PORT, monitor: true });
  state.port = Number(got.audioPort) || DEFAULT_PORT;
  state.monitor = got.monitor !== false;
}
loadPrefs();

// ---------- offscreen 文档 ----------
async function hasOffscreen() {
  if (chrome.offscreen && chrome.offscreen.hasDocument) {
    return await chrome.offscreen.hasDocument();
  }
  // 老版本兜底：查已打开的客户端
  const clients = await self.clients.matchAll();
  return clients.some((c) => c.url.endsWith(OFFSCREEN_URL));
}

async function ensureOffscreen() {
  if (await hasOffscreen()) return;
  await chrome.offscreen.createDocument({
    url: OFFSCREEN_URL,
    reasons: ['USER_MEDIA'],
    justification: '在后台采集标签页音频并实时推送给本地 SubFish 字幕服务',
  });
}

async function closeOffscreen() {
  if (!(await hasOffscreen())) return;
  await chrome.offscreen.closeDocument();
}

// ---------- 采集控制 ----------
async function startCapture() {
  state.error = '';
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || tab.id == null) throw new Error('找不到当前标签页');
  if (tab.url && /^(chrome|edge|about|devtools|chrome-extension)/.test(tab.url)) {
    throw new Error('这个页面不能采集音频（浏览器内部页）');
  }

  const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tab.id });
  await ensureOffscreen();
  await chrome.runtime.sendMessage({
    type: 'offscreen-start',
    streamId,
    tabId: tab.id,
    title: tab.title || '',
    port: state.port,
    monitor: state.monitor,
  });

  state.capturing = true;
  state.tabId = tab.id;
  state.title = tab.title || '';
  updateBadge();
}

async function stopCapture() {
  state.capturing = false;
  state.level = 0;
  state.rate = 0;
  state.clockRate = 0;
  state.dropped = 0;
  state.ws = 'closed';
  try {
    await chrome.runtime.sendMessage({ type: 'offscreen-stop' });
  } catch (_) {
    /* offscreen 可能已被回收，忽略 */
  }
  await closeOffscreen();
  updateBadge();
}

function updateBadge() {
  const on = state.capturing;
  chrome.action.setBadgeText({ text: on ? 'ON' : '' });
  chrome.action.setBadgeBackgroundColor({ color: '#4ade80' });
  const tip = on
    ? `SubFish：正在采集「${truncate(state.title, 24)}」`
    : 'SubFish 实时字幕（点击开始）';
  chrome.action.setTitle({ title: tip });
}

function truncate(s, n) {
  return s && s.length > n ? s.slice(0, n - 1) + '…' : s || '';
}

// ---------- 消息路由 ----------
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  switch (msg && msg.type) {
    case 'get-state':
      sendResponse({ ...state });
      return false;

    case 'start':
      startCapture()
        .then(() => sendResponse({ ok: true, state: { ...state } }))
        .catch((e) => {
          state.capturing = false;
          state.error = e.message || String(e);
          updateBadge();
          sendResponse({ ok: false, error: state.error, state: { ...state } });
        });
      return true; // 异步响应

    case 'stop':
      stopCapture()
        .then(() => sendResponse({ ok: true, state: { ...state } }))
        .catch((e) => sendResponse({ ok: false, error: e.message || String(e) }));
      return true;

    case 'set-port':
      state.port = Number(msg.port) || DEFAULT_PORT;
      chrome.storage.local.set({ audioPort: state.port });
      sendResponse({ ok: true, port: state.port });
      return false;

    case 'set-monitor':
      state.monitor = msg.on !== false;
      chrome.storage.local.set({ monitor: state.monitor });
      // 立刻生效：采集中也通知 offscreen 改增益
      if (state.capturing) {
        chrome.runtime.sendMessage({ type: 'offscreen-monitor', on: state.monitor }).catch(() => {});
      }
      sendResponse({ ok: true, monitor: state.monitor });
      return false;

    // 来自 offscreen 的状态上报
    case 'offscreen-status':
      if (typeof msg.ws === 'string') state.ws = msg.ws;
      if (typeof msg.level === 'number') state.level = msg.level;
      if (typeof msg.rate === 'number') state.rate = msg.rate;
      if (typeof msg.clockRate === 'number') state.clockRate = msg.clockRate;
      if (typeof msg.dropped === 'number') state.dropped = msg.dropped;
      if (typeof msg.error === 'string' && msg.error) state.error = msg.error;
      sendResponse({ ok: true });
      return false;

    default:
      return false;
  }
});

// ---------- 收尾 ----------
// 被采集的标签页关掉就自动停
chrome.tabs.onRemoved.addListener((tabId) => {
  if (state.capturing && tabId === state.tabId) stopCapture();
});

chrome.runtime.onInstalled.addListener(() => {
  updateBadge();
});
chrome.runtime.onStartup.addListener(() => {
  // 扩展重启后不自动恢复采集，先清空角标
  state.capturing = false;
  updateBadge();
});
