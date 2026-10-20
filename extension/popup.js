/* Popup：开始/停止采集 + 状态显示
 * 每 300ms 向 background 拉一次状态（电平要连续刷新，只能轮询）
 */
const $ = (id) => document.getElementById(id);

const el = {
  dotSvc: $('dotSvc'), svc: $('svc'),
  dotCap: $('dotCap'), cap: $('cap'),
  dotRate: $('dotRate'), rate: $('rate'),
  monitor: $('monitor'),
  level: $('level'), toggle: $('toggle'),
  msg: $('msg'), port: $('port'), portTip: $('portTip'),
};

let busy = false;

function setDot(dot, kind) {
  dot.className = 'dot' + (kind ? ' ' + kind : '');
}

function render(st) {
  // 本地服务连接状态
  const svcMap = {
    open: ['ok', '已连接'],
    connecting: ['warn', '连接中…'],
    closed: ['err', '未连接'],
  };
  const [svcKind, svcText] = svcMap[st.ws] || ['', st.ws];
  setDot(el.dotSvc, st.capturing ? svcKind : '');
  el.svc.textContent = st.capturing ? svcText : '未采集';

  setDot(el.dotCap, st.capturing ? 'ok' : '');
  el.cap.textContent = st.capturing ? st.title || '当前标签页' : '未开始';

  // 音频到达速率：1.0 = 实时；长期 <0.95 字幕会越拖越久
  const r = st.capturing ? st.rate || 0 : 0;
  if (!st.capturing) {
    setDot(el.dotRate, '');
    el.rate.textContent = '-';
  } else {
    setDot(el.dotRate, r >= 0.95 ? 'ok' : r >= 0.8 ? 'warn' : 'err');
    el.rate.textContent =
      `${r.toFixed(2)}x` + (r >= 0.95 ? ' 实时' : r >= 0.8 ? ' 略慢' : ' 偏慢！');
  }

  if (document.activeElement !== el.monitor) el.monitor.checked = st.monitor !== false;

  el.level.style.width = Math.min(100, Math.round((st.level || 0) * 400)) + '%';

  el.toggle.textContent = st.capturing ? '停止采集' : '开始采集';
  el.toggle.className = st.capturing ? 'stop' : '';
  el.toggle.disabled = busy;

  if (st.error) {
    el.msg.className = 'msg err';
    el.msg.textContent = st.error;
  } else if (st.capturing && r > 0 && r < 0.8) {
    el.msg.className = 'msg err';
    el.msg.textContent =
      `音频只到 ${(r * 100).toFixed(0)}%，字幕会越来越滞后：把被采集的标签页保持在前台可见` +
      `（别最小化/切到别的窗口）${st.clockRate && st.clockRate < 0.95 ? '；浏览器音频时钟也被限速了' : ''}`;
  } else if (st.capturing && st.ws !== 'open') {
    el.msg.className = 'msg err';
    el.msg.textContent = '音频已采集但推不出去：确认本地服务已用 启动.bat 跑起来。';
  } else if (st.capturing) {
    el.msg.className = 'msg';
    el.msg.textContent = '正在采集，字幕会实时出现在桌面小窗。';
  } else {
    el.msg.className = 'msg';
    el.msg.textContent = '点「开始采集」抓当前标签页的声音（中/英/日）。';
  }

  if (document.activeElement !== el.port) {
    el.port.value = st.port;
  }
}

async function refresh() {
  const st = await chrome.runtime.sendMessage({ type: 'get-state' });
  render(st);
}

el.toggle.addEventListener('click', async () => {
  if (busy) return;
  busy = true;
  el.toggle.disabled = true;
  const st = await chrome.runtime.sendMessage({ type: 'get-state' });
  const res = await chrome.runtime.sendMessage({ type: st.capturing ? 'stop' : 'start' });
  busy = false;
  if (res && res.state) render(res.state);
  else if (res && res.error) {
    el.msg.className = 'msg err';
    el.msg.textContent = res.error;
  }
});

el.monitor.addEventListener('change', async () => {
  await chrome.runtime.sendMessage({ type: 'set-monitor', on: el.monitor.checked });
});

el.port.addEventListener('change', async () => {
  const p = Number(el.port.value);
  if (!p || p < 1 || p > 65535) {
    el.portTip.textContent = '无效';
    return;
  }
  await chrome.runtime.sendMessage({ type: 'set-port', port: p });
  el.portTip.textContent = '已保存';
  setTimeout(() => (el.portTip.textContent = ''), 1500);
});

refresh();
setInterval(refresh, 300);
