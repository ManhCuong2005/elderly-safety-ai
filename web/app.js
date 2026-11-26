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

function showState(text, activity) {
  const state = element('state');
  if (state.textContent !== text) state.textContent = text;
  state.dataset.tone = text === 'Nghi té ngã' ? 'alert' : text === 'Đang theo dõi' ? 'tracking' : '';
  const posture = element('posture-value');
  const visible = text === 'Đang theo dõi' && Boolean(activity);
  element('posture-label').hidden = posture.hidden = !visible;
  if (posture.textContent !== (activity || '')) posture.textContent = activity || '';
}

function showTimer(t) {
  const whole = Math.floor(t);
  element('timer').textContent = [Math.floor(whole / 60), whole % 60].map(n => String(n).padStart(2, '0')).join(':');
}

function clearEvents() {
  element('event-list').replaceChildren();
  element('empty-events').hidden = false;
}

function showAlarm(t, seekable = false, kind = 'Nghi té ngã') {
  const event = document.createElement('li');
  const label = `${t.toFixed(2)} giây · ${kind}`;
  if (seekable) {
    const jump = document.createElement('button');
    jump.type = 'button';
    jump.textContent = label;
    jump.addEventListener('click', () => {
      if (video.readyState >= 1) video.currentTime = t;
    });
    event.append(jump);
  } else {
    event.textContent = label;
  }
  element('event-list').append(event);
  element('empty-events').hidden = true;
}

function updateControls() {
  element('camera-running').hidden = !active;
  element('start').disabled = Boolean(!status?.ready || active || opening);
  element('stop').disabled = !active && !opening;
  element('flip').disabled = !active || active.devices.length < 2;
  element('analyze').disabled = !status?.ready || !element('upload-file').files.length || Boolean(uploadRequest);
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
video.addEventListener('loadedmetadata', draw);
element('show-bones').addEventListener('change', draw);

function stopCamera(text = 'Camera đang tắt', error = false) {
  const run = active;
  active = null;
  opening = 0;
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
  showState(result.state, result.activity);
  if (mode === 'camera') message(result.warming ? 'Đang tích lũy quan sát tư thế…' : '');
  points = result.points;
  draw();
  if (result.alarm) showAlarm(result.t);
  if (result.absence_alarm) showAlarm(result.t, false, `Không thấy người trong ${result.absence_alarm} giây`);
}

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
  element('monitor-title').textContent = isUpload ? 'Thử video' : 'Theo dõi té ngã';
  element('monitor-description').textContent = isUpload ? 'Phân tích video từ thiết bị của bạn.'
    : 'Theo dõi trực tiếp từ camera của thiết bị này.';
  element('viewer-title').textContent = isUpload ? 'Xem trước video' : 'Khung camera';
  element('timer-label').textContent = isUpload ? 'Thời gian video' : 'Thời gian phiên';
  element('camera-actions').hidden = isUpload;
  element('upload-actions').hidden = !isUpload;
  element('upload-result').hidden = true;
  element('upload-source').hidden = true;
  element('upload-telegram').hidden = true;
  video.pause();
  video.removeAttribute('src');
  video.load();
  if (uploadUrl) {
    URL.revokeObjectURL(uploadUrl);
    uploadUrl = null;
  }
  video.hidden = true;
  element('placeholder').hidden = false;
  element('placeholder-text').textContent = isUpload ? 'Chưa chọn video' : 'Camera đang tắt';
  points = traceData = null;
  draw();
  message('');
  showState(isUpload ? 'Chờ video' : 'Camera đang tắt');
  showTimer(0);
  clearEvents();
  updateControls();
}

element('upload-file').addEventListener('change', updateControls);
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
  element('placeholder').hidden = false;
  showState('Đang phân tích video…');
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
    summary.hidden = false;
    const telegram = element('upload-telegram');
    const delivery = {
      sent: 'Đã gửi ảnh kiểm thử qua Telegram.',
      sent_text: 'Đã gửi thông báo chữ qua Telegram. Ảnh không gửi được.',
      unlinked: 'Hãy kết nối Telegram trong mục Tôi để nhận ảnh kiểm thử.',
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
    for (const time of data.alarms) showAlarm(time, true);
    element('empty-events').hidden = true;
    if (!video.error) {
      video.hidden = false;
      element('placeholder').hidden = true;
    }
    updateVideoPreview();
  } catch (error) {
    if (!controller.signal.aborted) {
      showState('Chưa phân tích được video');
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
  showState(event?.state || 'Đang chờ khung hình', event?.activity);
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
    element('backend').textContent = status.message || (status.ready ? 'Sẵn sàng' : 'Chưa sẵn sàng');
    element('backend-status').dataset.ready = String(status.ready && !status.message);
    element('upload-nav').hidden = !status.local;
    if (status.local) {
      element('upload-limit').textContent = `MP4 hoặc WebM, tối đa ${status.upload_max_bytes / 1048576} MiB và ${status.upload_max_seconds} giây.`;
    }
  } catch {
    element('backend').textContent = 'Mất kết nối';
    element('backend-status').dataset.ready = 'false';
  }
  updateControls();
}
