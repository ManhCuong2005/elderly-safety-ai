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
let clips = [];
let active;
let opening = 0;
let cameraId;
let currentClip;
let replay;
let replayRequest;
let viewLoader = 0;
let points;
let rotation = 0;
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

function showAlarm(t, seekable = false) {
  const event = document.createElement('li');
  const label = `${t.toFixed(2)} giây · Nghi té ngã`;
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
  element('start').disabled = Boolean(!status?.ready || active || opening);
  element('stop').disabled = !active && !opening;
  element('flip').disabled = !active || active.devices.length < 2;
  element('analyze').disabled = !status?.ready || !element('upload-file').files.length || Boolean(replayRequest);
}

function positionMedia() {
  const nativeWidth = video.videoWidth;
  const nativeHeight = video.videoHeight;
  const rotated = rotation % 180 !== 0;
  const [width, height] = rotated ? [nativeHeight, nativeWidth] : [nativeWidth, nativeHeight];
  stage.classList.toggle('portrait', height > width && !video.hidden);
  if (!width || !height) return null;
  const scale = Math.min(stage.clientWidth / width, stage.clientHeight / height);
  video.style.width = `${nativeWidth * scale}px`;
  video.style.height = `${nativeHeight * scale}px`;
  video.style.transform = `translate(-50%, -50%) rotate(${-rotation}deg)`;
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
  if (!points || !size || !element('show-bones').checked || mode === 'review') return;
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
    video.requestVideoFrameCallback((_, data) => sendFrame(run, data.mediaTime));
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

const byId = id => '/api/video?id=' + encodeURIComponent(id);
const partitions = {train: 'Train', validation: 'Validation', test: 'Test'};

function selectMode(next, clipId) {
  if (mode === 'camera') stopCamera();
  replayRequest?.abort();
  replayRequest = null;
  element('upload-file').disabled = false;
  mode = next;
  document.querySelectorAll('[data-mode]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.mode === mode)));
  element('camera-actions').hidden = mode !== 'camera';
  element('video-actions').hidden = !['review', 'replay'].includes(mode);
  element('upload-actions').hidden = mode !== 'upload';
  element('upload-result').hidden = true;
  element('upload-source').hidden = true;
  element('annotation').hidden = mode !== 'review';
  element('session-panel').hidden = mode === 'review';
  element('original').hidden = true;
  video.pause();
  video.removeAttribute('src');
  video.load();
  if (uploadUrl) {
    URL.revokeObjectURL(uploadUrl);
    uploadUrl = null;
  }
  video.hidden = true;
  element('placeholder').hidden = false;
  element('placeholder').textContent = mode === 'camera' ? 'Camera đang tắt'
    : mode === 'upload' ? 'Chọn video từ máy để phân tích' : 'Chọn video gốc';
  points = replay = null;
  rotation = 0;
  draw();
  message('');
  updateControls();
  if (mode === 'camera' || mode === 'upload') {
    showState(mode === 'camera' ? 'Camera đang tắt' : 'Chờ video');
    showTimer(0);
    clearEvents();
    return;
  }
  const select = element('clip');
  const order = mode === 'replay'
    ? [...clips].sort((a, b) => Number(b.split === 'test') - Number(a.split === 'test'))
    : [...clips].sort((a, b) => Number(b.status === 'review') - Number(a.status === 'review'));
  select.replaceChildren(new Option('Chọn một clip…', ''));
  for (const clip of order) {
    const split = partitions[clip.split] || 'Chưa chia tập';
    const subject = clip.source_folder_id !== clip.source_subject_id ? ` (${clip.source_subject_id})` : '';
    select.add(new Option(`${split} · ${clip.video_id}${subject}${clip.annotation?.label === 'unknown' ? ' · chưa rõ nhãn' : ''}`, clip.video_id));
  }
  select.value = order.some(clip => clip.video_id === clipId) ? clipId : order[0]?.video_id || '';
  openClip();
}

async function openClip() {
  replayRequest?.abort();
  const id = element('clip').value;
  currentClip = clips.find(clip => clip.video_id === id);
  video.pause();
  replay = points = null;
  clearEvents();
  showTimer(0);
  message('');
  if (!currentClip) {
    video.removeAttribute('src');
    video.load();
    video.hidden = element('save').disabled = element('original').hidden = true;
    element('placeholder').hidden = false;
    showState('Chọn một clip');
    return;
  }
  rotation = currentClip.rotation_override_ccw === '' ? 0
    : Number(currentClip.rotation_override_ccw) - Number(currentClip.rotation_ccw);
  video.muted = false;
  video.controls = true;
  video.src = byId(id);
  video.hidden = false;
  element('placeholder').hidden = true;
  element('original').href = byId(id);
  element('original').download = currentClip.relative_path.split('/').at(-1);
  element('original').hidden = false;
  video.playbackRate = Number(element('speed').value);
  fillAnnotation();
  if (mode !== 'replay') return;
  showState('Đang chuẩn bị dữ liệu tư thế…');
  const controller = new AbortController();
  replayRequest = controller;
  try {
    const data = await api('/api/replay?id=' + encodeURIComponent(id), {signal: controller.signal});
    if (controller.signal.aborted) return;
    replay = data;
    if (!data.classifier_ready) message('Đang phát lại tư thế MoveNet. Chưa có bộ phân loại té ngã.');
    updateReplay();
  } catch (error) {
    if (!controller.signal.aborted) {
      showState('Chưa xử lý được video');
      message(cameraError(error), true);
    }
  } finally {
    if (replayRequest === controller) replayRequest = null;
  }
}

element('upload-file').addEventListener('change', updateControls);
element('upload-actions').addEventListener('submit', async event => {
  event.preventDefault();
  const file = element('upload-file').files[0];
  if (mode !== 'upload' || !file || replayRequest || !status?.ready) return;
  if (!/\.(mp4|webm)$/i.test(file.name) || file.size === 0 || file.size > status.upload_max_bytes) {
    message(`Chọn video MP4 hoặc WebM, tối đa ${status.upload_max_bytes / 1048576} MiB.`, true);
    return;
  }
  replay = points = null;
  draw();
  element('upload-result').hidden = true;
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
  replayRequest = controller;
  element('upload-file').disabled = true;
  updateControls();
  try {
    const data = await api('/api/analyze-video', {
      method: 'POST', headers: {'Content-Type': 'application/octet-stream'},
      body: file, signal: controller.signal,
    });
    if (controller.signal.aborted) return;
    replay = data;
    const count = data.alarms.length;
    const summary = element('upload-result');
    summary.textContent = count ? `Nghi té ngã · ${count} cảnh báo`
      : data.has_predictions ? 'Không phát hiện té ngã trong video.' : 'Chưa đủ dữ liệu tư thế để kết luận.';
    summary.dataset.alarm = String(count > 0);
    summary.hidden = false;
    element('upload-source').hidden = !data.matches_train;
    clearEvents();
    for (const time of data.alarms) showAlarm(time, true);
    element('empty-events').hidden = true;
    if (!video.error) {
      video.hidden = false;
      element('placeholder').hidden = true;
    }
    updateReplay();
  } catch (error) {
    if (!controller.signal.aborted) {
      showState('Chưa phân tích được video');
      message(cameraError(error), true);
    }
  } finally {
    if (replayRequest === controller) {
      replayRequest = null;
      element('upload-file').disabled = false;
      updateControls();
    }
  }
});

function updateReplay() {
  if (!['replay', 'upload'].includes(mode) || !replay) return;
  const t = video.currentTime;
  let lo = 0;
  let hi = replay.trace.length;
  while (lo < hi) {
    const middle = (lo + hi) >> 1;
    if (replay.trace[middle].t <= t) lo = middle + 1;
    else hi = middle;
  }
  const event = replay.trace[lo - 1];
  showTimer(t);
  if (replay.classifier_ready) {
    if (mode === 'replay') {
      clearEvents();
      for (let i = 0; i < lo; i++) if (replay.trace[i].alarm) showAlarm(replay.trace[i].t);
    }
    showState(event?.state || 'Đang chờ frame', event?.activity);
  } else {
    showState('Chưa có bộ phân loại');
  }
  points = event?.points;
  draw();
}

for (const event of ['timeupdate', 'seeked', 'ended']) video.addEventListener(event, updateReplay);
video.addEventListener('error', () => {
  if (mode === 'upload' && uploadUrl) message('Trình duyệt không phát được video này. Máy xử lý vẫn có thể đọc tệp.', true);
  else if (mode !== 'camera' && currentClip) message('Trình duyệt không phát được MP4 này. Mở video gốc để kiểm tra.', true);
});
element('clip').addEventListener('change', openClip);
element('speed').addEventListener('change', e => { video.playbackRate = Number(e.target.value); });
document.querySelectorAll('[data-mode]').forEach(button => {
  button.addEventListener('click', () => { if (button.dataset.mode !== mode) selectMode(button.dataset.mode); });
});

function addInterval(start, end) {
  const interval = element('interval-template').content.firstElementChild.cloneNode(true);
  const startInput = interval.querySelector('.begin');
  const endInput = interval.querySelector('.end');
  startInput.value = start ?? '';
  endInput.value = end ?? '';
  interval.querySelector('.mark-begin').onclick = () => { startInput.value = video.currentTime.toFixed(3); };
  interval.querySelector('.mark-end').onclick = () => { endInput.value = video.currentTime.toFixed(3); };
  interval.querySelector('.remove-interval').onclick = () => interval.remove();
  element('intervals').append(interval);
}

function annotationControls() {
  const label = element('label').value;
  element('fall-marks').hidden = label !== 'Fall';
  element('normal-marks').hidden = label === 'unknown';
  if (label === 'No_Fall' && !element('intervals').children.length) addInterval();
}

function fillAnnotation() {
  const mark = currentClip.annotation;
  element('clip-label').textContent = `${currentClip.original_label} · ${currentClip.subject_id} · ${currentClip.reason}`;
  element('save').disabled = false;
  element('label').value = mark?.label || 'unknown';
  element('onset').value = mark?.onset_s ?? '';
  element('impact').value = mark?.impact_s ?? '';
  element('note').value = mark?.note || '';
  element('intervals').replaceChildren();
  for (const interval of mark?.negative || []) addInterval(...interval);
  annotationControls();
}

element('label').addEventListener('change', annotationControls);
element('add-interval').addEventListener('click', () => addInterval());
document.querySelectorAll('[data-mark]').forEach(button => {
  button.onclick = () => { element(button.dataset.mark).value = video.currentTime.toFixed(3); };
});

element('annotation').addEventListener('submit', async event => {
  event.preventDefault();
  const clip = currentClip;
  if (!clip) return;
  const label = element('label').value;
  const negative = label === 'unknown' ? [] : Array.from(element('intervals').children, group => [
    group.querySelector('.begin').valueAsNumber, group.querySelector('.end').valueAsNumber,
  ]);
  const payload = {label, negative, note: element('note').value};
  if (label === 'Fall') {
    payload.onset_s = element('onset').valueAsNumber;
    payload.impact_s = element('impact').valueAsNumber;
  }
  element('save').disabled = true;
  try {
    clip.annotation = await api('/api/annotation?id=' + encodeURIComponent(clip.video_id), {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
    });
    if (currentClip === clip) message('Đã lưu nhãn trong workspace.');
  } catch (error) {
    if (currentClip === clip) message(cameraError(error), true);
  } finally {
    if (currentClip === clip) element('save').disabled = false;
  }
});

async function init() {
  try {
    status = await api('/api/status');
    element('backend').textContent = status.message || `Bộ phân loại ${status.model} đã sẵn sàng`;
    if (status.local) {
      element('upload-limit').textContent = `MP4 hoặc WebM, tối đa ${status.upload_max_bytes / 1048576} MiB và ${status.upload_max_seconds} giây.`;
      clips = await api('/api/videos');
      document.querySelectorAll('[data-mode]:not([data-mode="camera"])').forEach(button => { button.hidden = false; });
      const query = new URLSearchParams(location.search);
      if (query.has('replay')) selectMode('replay', query.get('replay'));
      else if (query.has('review')) selectMode('review', query.get('review'));
    }
  } catch {
    element('backend').textContent = 'Không kết nối được với máy xử lý. Kiểm tra cửa sổ chạy web rồi tải lại trang.';
  }
  updateControls();
}
