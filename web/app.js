'use strict';

const element = id => document.getElementById(id);
const video = element('video');
const stage = element('stage');
const canvas = element('skeleton');
const pen = canvas.getContext('2d');
const capture = document.createElement('canvas');
const pixels = capture.getContext('2d');
const limbs = [[0, 5], [0, 6], [5, 6], [5, 7], [7, 9], [6, 8], [8, 10],
  [5, 11], [6, 12], [11, 12], [11, 13], [13, 15], [12, 14], [14, 16]];
let mode = 'camera';
let status;
let active;
let opening = 0;
let cameraId;
let traceData;
let uploadRequest;
let viewLoader = 0;
let points;
let uploadUrl;
let lastAlarmClock = '';

const SVG_NS = 'http://www.w3.org/2000/svg';
const ICON_DEFS = {
  'triangle-alert': [
    ['path', {d: 'm21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3'}],
    ['path', {d: 'M12 9v4'}],
    ['path', {d: 'M12 17h.01'}],
  ],
  'user-x': [
    ['path', {d: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2'}],
    ['circle', {cx: '9', cy: '7', r: '4'}],
    ['line', {x1: '17', x2: '22', y1: '8', y2: '13'}],
    ['line', {x1: '22', x2: '17', y1: '8', y2: '13'}],
  ],
  check: [
    ['path', {d: 'M20 6 9 17l-5-5'}],
  ],
  'rotate-cw': [
    ['path', {d: 'M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8'}],
    ['path', {d: 'M21 3v5h-5'}],
  ],
};

function createSvgIcon(name, className = 'icon') {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('data-lucide', name);
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '2');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('class', className);
  for (const [tag, attrs] of (ICON_DEFS[name] || [])) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    svg.append(node);
  }
  return svg;
}

function setBadgeTone(node, tone) {
  if (!node) return;
  node.classList.remove('badge-neutral', 'badge-success', 'badge-warning', 'badge-error');
  node.classList.add(`badge-${tone || 'neutral'}`);
}

function renderEmail(container, email) {
  if (!container) return;
  container.replaceChildren();
  const text = String(email || '');
  const wrapper = document.createElement('span');
  wrapper.className = 'email-text';
  const at = text.lastIndexOf('@');
  if (at < 0) {
    wrapper.textContent = text;
    container.append(wrapper);
    return;
  }
  const localSpan = document.createElement('span');
  const parts = text.slice(0, at + 1).split('.');
  parts.forEach((part, index) => {
    if (index > 0) localSpan.append(document.createElement('wbr'));
    localSpan.append(document.createTextNode((index > 0 ? '.' : '') + part));
  });
  const domainSpan = document.createElement('span');
  domainSpan.textContent = text.slice(at + 1);
  wrapper.append(localSpan, domainSpan);
  container.append(wrapper);
}

function formatClock(seconds) {
  const whole = Math.max(0, Math.floor(Number.isFinite(seconds) ? seconds : 0));
  return [Math.floor(whole / 60), whole % 60].map(n => String(n).padStart(2, '0')).join(':');
}

function formatSecVi(seconds) {
  return seconds.toFixed(2).replace('.', ',');
}

function formatSizeVi(bytes) {
  if (bytes >= 1048576) return `${(bytes / 1048576).toFixed(1).replace('.', ',')} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${bytes} B`;
}

function splitMiddleFilename(name) {
  const dot = name.lastIndexOf('.');
  const ext = dot > 0 ? name.slice(dot) : '';
  const stem = dot > 0 ? name.slice(0, dot) : name;
  if (stem.length <= 14) return {head: name, tail: ''};
  const keep = Math.min(8, Math.max(4, Math.floor(stem.length / 3)));
  return {
    head: stem.slice(0, stem.length - keep),
    tail: stem.slice(stem.length - keep) + ext,
  };
}

// Thanh cuộn tự ẩn khi đang cuộn (I18 — references/tokens.css)
let scrollTimer;
document.addEventListener('scroll', event => {
  const target = event.target === document ? document.documentElement : event.target;
  if (!target?.classList) return;
  target.classList.add('is-scrolling');
  clearTimeout(scrollTimer);
  scrollTimer = setTimeout(() => target.classList.remove('is-scrolling'), 700);
}, {capture: true, passive: true});

async function api(url, options) {
  const response = await fetch(url, options);
  if (response.status === 204) return null;
  const data = response.headers.get('content-type')?.includes('application/json') ? await response.json() : {};
  if (response.status === 401 && !['/api/account/login', '/api/account/register'].includes(url)) {
    window.dispatchEvent(new Event('account-expired'));
  }
  if (!response.ok) throw new Error(data.error || `Máy xử lý trả về mã ${response.status}.`);
  return data;
}

function message(text, error = false) {
  const item = element('message');
  item.textContent = text || '';
  item.hidden = !text;
  item.dataset.tone = error ? 'alert' : '';
}

const ALARM_REASON_LABELS = {
  fall: 'Nghi té ngã',
  convulsion: 'Nghi co giật / giãy giụa',
  stroke_slump: 'Nghi đột quỵ / ngồi gục bất động',
  slow_collapse: 'Trượt ngã chậm / nằm gục bất động',
};

function showState(text, activity, alarmReason = null, alertLocked = false) {
  const state = element('state');
  const reasonLabel = alarmReason && ALARM_REASON_LABELS[alarmReason] ? ALARM_REASON_LABELS[alarmReason] : 'Nghi té ngã';
  const displayText = text === 'Nghi té ngã' && alarmReason && ALARM_REASON_LABELS[alarmReason]
    ? `${ALARM_REASON_LABELS[alarmReason]}${alertLocked ? ' · Khóa' : ''}`
    : (text === 'Nghi té ngã' && alertLocked ? 'Nghi té ngã · Khóa' : text);
  if (state.textContent !== displayText) state.textContent = displayText;
  const isAlert = text === 'Nghi té ngã';
  const isTracking = text === 'Đang theo dõi';
  const isBusy = text === 'Đang mở camera…' || text === 'Đang phân tích video…';
  state.dataset.tone = isAlert ? 'alert' : isTracking ? 'tracking' : '';
  setBadgeTone(state, isAlert ? 'error' : isTracking ? 'success' : isBusy ? 'warning' : 'neutral');

  const posture = element('posture-value');
  const visible = (isTracking || isAlert) && Boolean(activity);
  const postureText = visible ? activity : '—';
  if (posture.textContent !== postureText) posture.textContent = postureText;

  const lockedLive = mode === 'camera' && Boolean(active) && Boolean(alertLocked);
  const confirmBtn = element('confirm-safe');
  const alertBanner = element('alert-banner');
  if (confirmBtn) confirmBtn.hidden = !lockedLive;
  if (alertBanner) {
    alertBanner.hidden = !lockedLive;
    if (lockedLive) {
      element('alert-banner-title').textContent = `${reasonLabel} · Đã khóa báo động`;
      element('alert-banner-desc').textContent = lastAlarmClock
        ? `Phát hiện lúc ${lastAlarmClock} · Đã gửi ảnh cảnh báo qua Telegram. Kiểm tra an toàn rồi mở khóa để tiếp tục theo dõi.`
        : 'Đã gửi ảnh cảnh báo qua Telegram. Kiểm tra an toàn rồi mở khóa để tiếp tục theo dõi.';
    }
  }

  const runningPill = element('camera-running');
  if (runningPill && active) {
    runningPill.textContent = lockedLive ? 'Đã khóa báo động' : 'Camera đang bật';
    setBadgeTone(runningPill, lockedLive ? 'error' : 'success');
  }

  const liveBadge = element('stage-live-badge');
  const ramBadge = element('stage-ram-badge');
  if (liveBadge && ramBadge) {
    const showLive = mode === 'camera' && Boolean(active);
    liveBadge.hidden = !showLive;
    ramBadge.hidden = !showLive;
    if (showLive) {
      liveBadge.dataset.tone = (isAlert || lockedLive) ? 'alert' : 'tracking';
      element('stage-live-text').textContent = lockedLive ? 'ĐÃ KHÓA BÁO ĐỘNG' : 'ĐANG THEO DÕI';
    }
  }
}

function showTimer(t) {
  const formatted = formatClock(t);
  element('timer').textContent = formatted;
  if (mode === 'upload' && video.duration && Number.isFinite(video.duration)) {
    element('viewer-meta').textContent = `${formatted} / ${formatClock(video.duration)}`;
  }
}

function updateEventCount() {
  const count = element('event-list').children.length;
  const badge = element('event-count');
  if (badge) {
    badge.textContent = `${count} mốc`;
    badge.hidden = count === 0;
  }
}

function clearEvents() {
  element('event-list').replaceChildren();
  element('empty-events').hidden = false;
  updateEventCount();
}

function showAlarm(t, seekable = false, kind = 'Nghi té ngã') {
  const list = element('event-list');
  const event = document.createElement('li');
  if (seekable) {
    list.className = 'event-list event-list-seek';
    const jump = document.createElement('button');
    jump.type = 'button';
    jump.className = 'seek-btn';
    const labelSpan = document.createElement('span');
    labelSpan.className = 'seek-btn-label';
    labelSpan.textContent = kind;
    const timeSpan = document.createElement('span');
    timeSpan.className = 'seek-btn-time tabular-nums';
    timeSpan.textContent = `${formatSecVi(t)} giây`;
    jump.append(labelSpan, timeSpan);
    jump.addEventListener('click', () => {
      if (video.readyState >= 1) video.currentTime = t;
    });
    event.append(jump);
  } else {
    list.className = 'event-list event-list-live';
    const nowClock = new Intl.DateTimeFormat('vi-VN', {
      hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
    }).format(new Date());
    lastAlarmClock = nowClock;
    const iconBox = document.createElement('span');
    iconBox.className = 'event-icon-box';
    iconBox.setAttribute('aria-hidden', 'true');
    iconBox.append(createSvgIcon(kind.startsWith('Không thấy') ? 'user-x' : 'triangle-alert'));
    const body = document.createElement('div');
    body.className = 'min-w-0';
    const title = document.createElement('p');
    title.className = 'event-item-title';
    title.textContent = kind;
    const meta = document.createElement('p');
    meta.className = 'event-item-meta tabular-nums';
    meta.textContent = `${nowClock} · Mốc ${formatSecVi(t)} giây`;
    body.append(title, meta);
    event.append(iconBox, body);
  }
  list.append(event);
  element('empty-events').hidden = true;
  updateEventCount();
}

function updateSelectedFileUI(statusText = '') {
  const input = element('upload-file');
  const file = input.files[0];
  const row = element('upload-selected');
  if (!file) {
    row.hidden = true;
    return;
  }
  const {head, tail} = splitMiddleFilename(file.name);
  const headEl = element('upload-file-head');
  const tailEl = element('upload-file-tail');
  const nameEl = element('upload-filename');
  headEl.textContent = head;
  tailEl.textContent = tail;
  if (tail) nameEl.title = file.name;
  else nameEl.removeAttribute('title');
  const metaParts = [formatSizeVi(file.size)];
  if (statusText) metaParts.push(statusText);
  element('upload-file-meta').textContent = metaParts.join(' · ');
  row.hidden = false;
}

function updateControls() {
  const isLive = Boolean(active || opening);
  const runningPill = element('camera-running');
  runningPill.hidden = !active;
  if (!active) {
    runningPill.textContent = 'Camera đang bật';
    setBadgeTone(runningPill, 'success');
  }

  const startBtn = element('start');
  const stopBtn = element('stop');
  startBtn.disabled = Boolean(!status?.ready || isLive);
  startBtn.hidden = isLive;
  stopBtn.disabled = !isLive;
  stopBtn.hidden = !isLive;

  element('flip').disabled = !active || active.devices.length < 2;
  element('analyze').disabled = !status?.ready || !element('upload-file').files.length || Boolean(uploadRequest);
  const dropzone = element('upload-dropzone');
  if (dropzone) dropzone.dataset.disabled = String(Boolean(uploadRequest));
}

function positionMedia() {
  const width = video.videoWidth;
  const height = video.videoHeight;
  stage.classList.toggle('portrait', height > width && !video.hidden);
  if (!width || !height) return null;
  const scale = Math.min(stage.clientWidth / width, stage.clientHeight / height);
  video.style.width = `${width * scale}px`;
  video.style.height = `${height * scale}px`;
  return [width * scale, height * scale];
}

function draw() {
  const size = positionMedia();
  const w = stage.clientWidth;
  const h = stage.clientHeight;
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }
  pen.clearRect(0, 0, w, h);
  if (!points || !size || !element('show-bones').checked) return;
  const coords = points.map(point => point && [
    (w - size[0]) / 2 + point[0] * size[0],
    (h - size[1]) / 2 + point[1] * size[1],
  ]);
  pen.strokeStyle = '#75f4dc';
  pen.fillStyle = '#d6fff7';
  pen.lineWidth = 2;
  for (const [a, b] of limbs) {
    if (!coords[a] || !coords[b]) continue;
    pen.beginPath();
    pen.moveTo(...coords[a]);
    pen.lineTo(...coords[b]);
    pen.stroke();
  }
  for (const pt of coords) {
    if (!pt) continue;
    pen.beginPath();
    pen.arc(...pt, 2.7, 0, Math.PI * 2);
    pen.fill();
  }
}

new ResizeObserver(draw).observe(stage);
video.addEventListener('loadedmetadata', () => {
  draw();
  if (mode === 'upload' && Number.isFinite(video.duration)) {
    element('viewer-meta').textContent = `${formatClock(video.currentTime)} / ${formatClock(video.duration)}`;
  }
});
element('show-bones').addEventListener('change', draw);

function stopCamera(text = 'Camera đang tắt', error = false) {
  const run = active;
  active = null;
  opening = 0;
  lastAlarmClock = '';
  if (run) {
    run.controller.abort();
    run.stream.getTracks().forEach(track => track.stop());
    fetch(`/api/session/${run.token}`, {method: 'DELETE', keepalive: true}).catch(() => {});
  }
  if (mode === 'camera') {
    video.srcObject = null;
    video.hidden = true;
    element('placeholder').hidden = false;
    points = null;
    draw();
    showState(text);
    if (error) message(text, true);
  }
  updateControls();
}

function cameraError(error) {
  if (error.name === 'NotAllowedError' || error.name === 'SecurityError') return 'Hãy cấp quyền camera trong trình duyệt rồi thử lại.';
  if (error.name === 'NotFoundError') return 'Thiết bị chưa có camera khả dụng.';
  if (error.name === 'NotReadableError') return 'Camera đang bận hoặc thiết bị không đọc được camera.';
  if (error.name === 'OverconstrainedError') return 'Camera đã chọn không còn khả dụng. Bấm bắt đầu để dùng camera mặc định.';
  if (error instanceof TypeError) return 'Mất kết nối với máy xử lý.';
  return error.message;
}

async function startCamera() {
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    stopCamera('Camera cần localhost hoặc HTTPS được thiết bị tin cậy.', true);
    return;
  }
  if (active || opening) return;
  const attempt = ++viewLoader;
  opening = attempt;
  updateControls();
  message('');
  clearEvents();
  showTimer(0);
  showState('Đang mở camera…');
  let stream;
  let setup;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: false, video: {
        ...(cameraId ? {deviceId: {exact: cameraId}} : {facingMode: {ideal: 'environment'}}),
        width: {ideal: 960}, height: {ideal: 720},
      },
    });
    if (opening !== attempt) return;
    setup = await api('/api/session', {method: 'POST', signal: AbortSignal.timeout(6000)});
    if (opening !== attempt) return;
    video.muted = true;
    video.controls = false;
    video.srcObject = stream;
    video.hidden = false;
    element('placeholder').hidden = true;
    await video.play();
    if (opening !== attempt) return;
    const run = {
      stream, token: setup.token, hz: setup.sample_hz, controller: new AbortController(),
      first: null, lastSent: -Infinity, devices: [],
    };
    active = run;
    opening = 0;
    switchCameraAvailable(run);
    stream.getVideoTracks()[0].addEventListener('ended', () => {
      if (active === run) stopCamera('Camera đã mất kết nối.', true);
    });
    showState('Chưa thấy người');
    updateControls();
    nextFrame(run);
  } catch (error) {
    if (error.name === 'OverconstrainedError') cameraId = undefined;
    if (opening === attempt) stopCamera(cameraError(error), true);
  } finally {
    if (active?.stream !== stream) stream?.getTracks().forEach(track => track.stop());
    if (setup && active?.token !== setup.token) {
      fetch(`/api/session/${setup.token}`, {method: 'DELETE', keepalive: true}).catch(() => {});
    }
  }
}

async function switchCameraAvailable(run) {
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    run.devices = [...new Set(devices.filter(device => device.kind === 'videoinput' && device.deviceId)
      .map(device => device.deviceId))];
    if (run === active) updateControls();
  } catch {
    // Some browsers expose the front and rear cameras only after granting permissions.
  }
}

function nextFrame(run) {
  if (active !== run) return;
  if (video.requestVideoFrameCallback) {
    const callback = video.requestVideoFrameCallback((_, data) => {
      clearTimeout(wakeup);
      sendFrame(run, data.mediaTime);
    });
    const wakeup = setTimeout(() => {
      video.cancelVideoFrameCallback(callback);
      sendFrame(run, video.currentTime);
    }, 300);
  } else {
    requestAnimationFrame(() => sendFrame(run, video.currentTime));
  }
}

async function sendFrame(run, time) {
  if (active !== run) return;
  run.first ??= time;
  const t = time - run.first;
  if (!video.videoWidth || t - run.lastSent + 0.00001 < 1 / run.hz) {
    nextFrame(run);
    return;
  }
  run.lastSent = t;
  showTimer(t);
  const scale = Math.min(1, 768 / Math.max(video.videoWidth, video.videoHeight));
  capture.width = Math.round(video.videoWidth * scale);
  capture.height = Math.round(video.videoHeight * scale);
  pixels.drawImage(video, 0, 0, capture.width, capture.height);
  const jpeg = await new Promise(resolve => capture.toBlob(resolve, 'image/jpeg', .85));
  if (active !== run) return;
  if (!jpeg) {
    stopCamera('Trình duyệt không tạo được khung camera.', true);
    return;
  }
  const deadline = setTimeout(() => run.controller.abort(), 6000);
  try {
    const result = await api(`/api/frame/${run.token}`, {
      method: 'POST', headers: {'Content-Type': 'image/jpeg', 'X-Frame-Time': t.toFixed(6)},
      body: jpeg, signal: run.controller.signal,
    });
    if (active !== run) return;
    if (result) display(result);
  } catch (error) {
    if (active === run) stopCamera(error.name === 'AbortError' ? 'Máy xử lý không phản hồi.' : cameraError(error), true);
  } finally {
    clearTimeout(deadline);
  }
  nextFrame(run);
}

function display(result) {
  if (result.alarm) {
    showAlarm(result.t, false, ALARM_REASON_LABELS[result.alarm_reason] || 'Nghi té ngã');
  }
  if (result.absence_alarm) {
    showAlarm(result.t, false, `Không thấy người trong ${result.absence_alarm} giây`);
  }
  showState(result.state, result.activity, result.alarm_reason, Boolean(result.alert_locked));
  if (mode === 'camera') message(result.warming ? 'Đang tích lũy quan sát tư thế…' : '');
  points = result.points;
  draw();
}

element('confirm-safe')?.addEventListener('click', async () => {
  if (!active) return;
  const btn = element('confirm-safe');
  btn.disabled = true;
  try {
    const res = await api(`/api/session/${active.token}/confirm-safe`, {method: 'POST'});
    if (res) {
      lastAlarmClock = '';
      showState(res.state || 'Đang theo dõi', null, null, Boolean(res.alert_locked));
      message('Đã xác nhận an toàn và mở khóa báo động.');
    }
  } catch (error) {
    message(cameraError(error), true);
  } finally {
    btn.disabled = false;
  }
});

element('start').addEventListener('click', startCamera);
element('stop').addEventListener('click', () => stopCamera());
element('flip').addEventListener('click', () => {
  const current = active.stream.getVideoTracks()[0].getSettings().deviceId;
  const devices = active.devices;
  cameraId = devices[(devices.indexOf(current) + 1) % devices.length];
  stopCamera();
  startCamera();
});
window.addEventListener('pagehide', () => stopCamera());

function selectMode(next) {
  if (mode === next) return;
  if (mode === 'camera') stopCamera();
  uploadRequest?.abort();
  uploadRequest = null;
  element('upload-file').disabled = false;
  mode = next;
  const isUpload = mode === 'upload';
  element('viewer-title').textContent = isUpload ? 'Xem trước & tải tệp video' : 'Khung camera trực tiếp';
  element('viewer-meta').textContent = isUpload ? 'Chưa chọn video' : 'Tự giải phóng bộ đệm khi dừng';
  element('session-title').textContent = isUpload ? 'Kết quả phân tích' : 'Trạng thái phiên';
  element('event-title').textContent = isUpload ? 'Mốc cảnh báo (bấm để tua)' : 'Sự kiện trong phiên';
  element('timer-label').textContent = isUpload ? 'Thời gian video' : 'Thời gian phiên';
  element('ai-mode-row').hidden = isUpload;
  element('session-stats-dl').hidden = isUpload;
  element('upload-empty-result').hidden = !isUpload;
  element('camera-actions').hidden = isUpload;
  element('upload-actions').hidden = !isUpload;
  element('upload-result').hidden = true;
  element('upload-source').hidden = true;
  element('upload-telegram').hidden = true;
  element('placeholder-icon-camera').hidden = isUpload;
  element('placeholder-icon-video').hidden = !isUpload;
  element('placeholder-text').textContent = isUpload ? 'Chưa chọn video' : 'Camera đang tắt';
  element('placeholder-hint').textContent = isUpload
    ? 'Chọn tệp MP4 hoặc WebM bên dưới để xem trước khung xương MoveNet và kiểm thử phát hiện té ngã.'
    : 'Đặt thiết bị cố định sao cho thấy rõ vai, hông và chân. Hai giây đầu dùng để làm đầy cửa sổ tư thế.';
  element('empty-events').textContent = isUpload ? 'Chưa có mốc cảnh báo.' : 'Chưa có cảnh báo.';
  video.pause();
  video.removeAttribute('src');
  video.load();
  if (uploadUrl) {
    URL.revokeObjectURL(uploadUrl);
    uploadUrl = null;
  }
  stage.hidden = isUpload;
  video.hidden = true;
  element('placeholder').hidden = false;
  element('stage-live-badge').hidden = true;
  element('stage-ram-badge').hidden = true;
  points = traceData = null;
  draw();
  message('');
  showState(isUpload ? 'Chờ video' : 'Camera đang tắt');
  showTimer(0);
  clearEvents();
  updateSelectedFileUI(isUpload && element('upload-file').files[0] ? 'Sẵn sàng phân tích' : '');
  updateControls();
}

// Kéo thả & chọn tệp video (components/file-upload.md)
const uploadInput = element('upload-file');
const dropzone = element('upload-dropzone');
const dropzoneTitle = element('dropzone-title');

uploadInput.addEventListener('change', () => {
  message('');
  updateSelectedFileUI('Sẵn sàng phân tích');
  updateControls();
});

if (dropzone) {
  let dragDepth = 0;
  const setDragging = dragging => {
    dropzone.dataset.dragging = String(dragging);
    if (dropzoneTitle) {
      dropzoneTitle.textContent = dragging ? 'Thả tệp để phân tích' : 'Kéo thả video MP4 hoặc WebM vào đây';
    }
  };
  dropzone.addEventListener('dragenter', event => {
    event.preventDefault();
    dragDepth += 1;
    setDragging(true);
  });
  dropzone.addEventListener('dragover', event => {
    event.preventDefault();
  });
  dropzone.addEventListener('dragleave', () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) setDragging(false);
  });
  dropzone.addEventListener('drop', event => {
    event.preventDefault();
    dragDepth = 0;
    setDragging(false);
    if (uploadRequest) return;
    const dropped = event.dataTransfer?.files?.[0];
    if (!dropped) return;
    const transfer = new DataTransfer();
    transfer.items.add(dropped);
    uploadInput.files = transfer.files;
    message('');
    updateSelectedFileUI('Sẵn sàng phân tích');
    updateControls();
  });
}

element('upload-actions').addEventListener('submit', async event => {
  event.preventDefault();
  const file = element('upload-file').files[0];
  if (mode !== 'upload' || !file || uploadRequest || !status?.ready) return;
  if (!/\.(mp4|webm)$/i.test(file.name) || file.size === 0 || file.size > status.upload_max_bytes) {
    message(`Chọn video MP4 hoặc WebM, tối đa ${status.upload_max_bytes / 1048576} MiB.`, true);
    return;
  }
  traceData = points = null;
  draw();
  element('upload-result').hidden = true;
  element('upload-telegram').hidden = true;
  element('upload-source').hidden = true;
  clearEvents();
  showTimer(0);
  video.pause();
  if (uploadUrl) URL.revokeObjectURL(uploadUrl);
  uploadUrl = URL.createObjectURL(file);
  video.src = uploadUrl;
  video.controls = true;
  video.muted = false;
  video.hidden = true;
  stage.hidden = false;
  element('placeholder').hidden = false;
  element('upload-empty-result').hidden = true;
  element('session-stats-dl').hidden = false;
  showState('Đang phân tích video…');
  updateSelectedFileUI('Đang phân tích…');
  message('');
  const controller = new AbortController();
  uploadRequest = controller;
  element('upload-file').disabled = true;
  updateControls();
  try {
    const data = await api('/api/analyze-video', {
      method: 'POST', headers: {'Content-Type': 'application/octet-stream'},
      body: file, signal: controller.signal,
    });
    if (controller.signal.aborted) return;
    traceData = data;
    const count = data.alarms.length;
    const summary = element('upload-result');
    summary.textContent = count ? `Nghi té ngã · ${count} cảnh báo`
      : data.has_predictions ? 'Không phát hiện té ngã trong video.' : 'Chưa đủ dữ liệu tư thế để kết luận.';
    summary.dataset.alarm = String(count > 0);
    setBadgeTone(summary, count > 0 ? 'error' : data.has_predictions ? 'success' : 'neutral');
    summary.hidden = false;
    const telegram = element('upload-telegram');
    const delivery = {
      sent: 'Đã gửi ảnh kiểm thử qua Telegram.',
      sent_text: 'Đã gửi thông báo chữ qua Telegram. Ảnh không gửi được.',
      unlinked: 'Hãy kết nối Telegram trong mục Tài khoản & Telegram để nhận ảnh kiểm thử.',
      unavailable: 'Máy chủ chưa cấu hình gửi ảnh kiểm thử qua Telegram.',
      error: 'Chưa xác nhận được thông báo đã gửi. Hãy kiểm tra Telegram.',
      history_error: 'Chưa cập nhật được lịch sử thử video. Hãy kiểm tra Supabase và Telegram.',
    }[data.telegram_status] || '';
    const historyWarning = {
      error: 'Chưa lưu được sự kiện vào lịch sử.',
      status_error: 'Đã lưu sự kiện nhưng chưa cập nhật được trạng thái gửi trong lịch sử.',
    }[data.history_status] || '';
    telegram.textContent = [delivery, historyWarning].filter(Boolean).join(' ');
    telegram.hidden = !telegram.textContent;
    element('upload-source').hidden = !data.matches_train;
    clearEvents();
    const alarmReasons = new Map();
    for (const frame of data.trace || []) {
      if (frame.alarm) alarmReasons.set(frame.t, ALARM_REASON_LABELS[frame.alarm_reason] || 'Nghi té ngã');
    }
    for (const time of data.alarms) showAlarm(time, true, alarmReasons.get(time) || 'Nghi té ngã');
    element('empty-events').hidden = data.alarms.length > 0;
    if (!video.error) {
      video.hidden = false;
      element('placeholder').hidden = true;
    }
    updateSelectedFileUI('Đã phân tích xong');
    updateVideoPreview();
  } catch (error) {
    if (!controller.signal.aborted) {
      showState('Chưa phân tích được video');
      updateSelectedFileUI('Chưa phân tích được');
      message(cameraError(error), true);
    }
  } finally {
    if (uploadRequest === controller) {
      uploadRequest = null;
      element('upload-file').disabled = false;
      updateControls();
    }
  }
});

function updateVideoPreview() {
  if (mode !== 'upload' || !traceData) return;
  const t = video.currentTime;
  let lo = 0;
  let hi = traceData.trace.length;
  while (lo < hi) {
    const middle = (lo + hi) >> 1;
    if (traceData.trace[middle].t <= t) lo = middle + 1;
    else hi = middle;
  }
  const event = traceData.trace[lo - 1];
  showTimer(t);
  showState(event?.state || 'Đang chờ khung hình', event?.activity, event?.alarm_reason, Boolean(event?.alert_locked));
  points = event?.points;
  draw();
}

for (const event of ['timeupdate', 'seeked', 'ended']) video.addEventListener(event, updateVideoPreview);
video.addEventListener('error', () => {
  if (mode === 'upload' && uploadUrl) message('Trình duyệt không phát được video này. Máy xử lý vẫn có thể đọc tệp.', true);
});

async function init() {
  try {
    status = await api('/api/status');
    const readyText = status.message || (status.ready ? `MoveNet sẵn sàng · ${status.sample_hz || 10} Hz` : 'Chưa sẵn sàng');
    const isReady = String(Boolean(status.ready && !status.message));
    element('backend').textContent = readyText;
    element('backend-status').dataset.ready = isReady;
    if (element('backend-mobile')) element('backend-mobile').textContent = readyText;
    if (element('backend-status-mobile')) element('backend-status-mobile').dataset.ready = isReady;
    element('upload-nav').hidden = !status.local;
    if (element('upload-nav-mobile')) element('upload-nav-mobile').hidden = !status.local;
    if (status.local) {
      element('upload-limit').textContent = `MP4 hoặc WebM, tối đa ${status.upload_max_bytes / 1048576} MiB và ${status.upload_max_seconds} giây.`;
    }
  } catch {
    element('backend').textContent = 'Mất kết nối máy xử lý';
    element('backend-status').dataset.ready = 'false';
    if (element('backend-mobile')) element('backend-mobile').textContent = 'Mất kết nối máy xử lý';
    if (element('backend-status-mobile')) element('backend-status-mobile').dataset.ready = 'false';
  }
  updateControls();
}
