'use strict';

const accountForm = element('account-form');
const confirmationForm = element('account-confirmation');
const passwordInput = element('account-password');
const codeInput = element('account-code');
const resendButton = element('confirmation-resend');
const confirmButton = element('confirmation-submit');
const confirmationBack = element('confirmation-back');
const workspace = element('workspace');
const screens = document.querySelectorAll('[data-screen]');
let registering = false;
let confirmationEmail = '';
let confirmationBusy = false;
let resendAfter = 0;
let resendTimer;
let telegramStep = '';
let currentRoute;

function accountMessage(id, text, error = false) {
  const item = element(id);
  item.textContent = text;
  item.hidden = !text;
  item.dataset.tone = error ? 'alert' : '';
}

function accountsMode(signup) {
  registering = signup;
  const label = signup ? 'Đăng ký' : 'Đăng nhập';
  element('account-heading').textContent = label;
  element('account-submit').textContent = label;
  element('account-switch').textContent = signup ? 'Về đăng nhập' : 'Tạo tài khoản';
  element('account-name-field').hidden = !signup;
  passwordInput.autocomplete = signup ? 'new-password' : 'current-password';
  passwordInput.minLength = signup ? 8 : 1;
  passwordInput.value = '';
}

function showMonitor(user) {
  clearTimeout(resendTimer);
  confirmationForm.hidden = true;
  const name = (user.name || '').trim();
  element('profile-name').textContent = element('me-name').textContent = name || 'Chưa đặt tên';
  element('profile-email').textContent = element('me-email').textContent = user.email;
  const initial = Array.from(name || user.email.trim())[0]?.toLocaleUpperCase('vi-VN') || '';
  element('account-avatar').textContent = element('me-avatar').textContent = initial;
  element('account-screen').hidden = true;
  workspace.hidden = false;
  element('skip-link').href = '#main-content';
  renderRoute();
  init().then(renderRoute);
}

function renderRoute() {
  if (workspace.hidden) return;
  let route = location.hash.slice(1);
  if (route === 'main-content' && currentRoute) {
    history.replaceState(null, '', `#${currentRoute}`);
    return;
  }
  if (!['camera', 'thu-video', 'toi', 'tai-khoan', 'cai-dat-camera', 'lich-su'].includes(route)) route = 'camera';
  if (route === 'thu-video' && status?.local === false) {
    route = 'camera';
    history.replaceState(null, '', '#camera');
  }
  if (route === currentRoute) return;
  const first = currentRoute === undefined;
  currentRoute = route;
  const screen = route === 'camera' || route === 'thu-video' ? 'monitor' : route;
  for (const view of screens) view.hidden = view.dataset.screen !== screen;
  if (screen === 'monitor') selectMode(route === 'thu-video' ? 'upload' : 'camera');
  for (const link of document.querySelectorAll('[data-route]')) {
    if (link.dataset.route === route) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  }
  element('open-account').classList.toggle('selected', screen !== 'monitor');
  if (!first) {
    window.scrollTo(0, 0);
    document.querySelector(`[data-screen="${screen}"] h1`).focus({preventScroll: true});
  }
  if (route === 'tai-khoan') loadTelegram();
  if (route === 'cai-dat-camera') loadCameraSettings();
  if (route === 'lich-su') loadHistory();
}

window.addEventListener('hashchange', renderRoute);

function showSignIn(configured) {
  confirmationForm.hidden = true;
  accountForm.hidden = !configured;
  accountMessage('account-message', configured ? '' : 'Máy chủ chưa cấu hình Supabase. Kiểm tra cấu hình rồi tải lại trang.');
  const hash = new URLSearchParams(location.hash.slice(1));
  if (hash.has('access_token') || hash.has('error_code')) {
    history.replaceState(null, '', location.pathname + location.search);
    if (configured) accountMessage('account-message', hash.has('error_code')
      ? 'Liên kết xác nhận không hợp lệ hoặc đã hết hạn.' : 'Email đã được xác nhận. Bạn có thể đăng nhập.');
  }
}

element('account-switch').addEventListener('click', () => {
  accountsMode(!registering);
  accountMessage('account-message', '');
  element(registering ? 'account-name' : 'account-email').focus();
});

function postAccount(action, body) {
  return api(`/api/account/${action}`, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
  });
}

function updateResendButton() {
  clearTimeout(resendTimer);
  const seconds = Math.max(0, Math.ceil((resendAfter - Date.now()) / 1000));
  resendButton.disabled = confirmationBusy || seconds > 0;
  resendButton.textContent = seconds ? `Gửi lại sau ${seconds} giây` : 'Gửi lại mã';
  if (seconds && !confirmationForm.hidden) resendTimer = setTimeout(updateResendButton, 1000);
}

function showConfirmation(email, waitSeconds = 0) {
  if (confirmationEmail !== email) resendAfter = 0;
  if (waitSeconds) resendAfter = Date.now() + waitSeconds * 1000;
  confirmationEmail = email;
  element('confirmation-email').textContent = email;
  codeInput.value = '';
  accountForm.hidden = true;
  confirmationForm.hidden = false;
  accountMessage('account-message', '');
  updateResendButton();
  codeInput.focus();
}

function setConfirmationBusy(busy) {
  confirmationBusy = busy;
  confirmButton.disabled = confirmationBack.disabled = busy;
  updateResendButton();
}

accountForm.addEventListener('submit', async event => {
  event.preventDefault();
  const submit = element('account-submit');
  const toggle = element('account-switch');
  const email = element('account-email').value.trim();
  submit.disabled = toggle.disabled = true;
  accountMessage('account-message', 'Đang xử lý…');
  try {
    const data = await postAccount(registering ? 'register' : 'login', {
      email, password: passwordInput.value, name: element('account-name').value,
    });
    passwordInput.value = '';
    if (data.confirmation_required) showConfirmation(email, 60);
    else showMonitor(data.user);
  } catch (error) {
    if (error.code === 'email_not_confirmed') {
      passwordInput.value = '';
      showConfirmation(email);
    } else {
      if (registering && error.retryAfter > 0) {
        passwordInput.value = '';
        showConfirmation(email, error.retryAfter);
      }
      accountMessage('account-message', error.message, true);
    }
  } finally {
    submit.disabled = toggle.disabled = false;
  }
});

confirmationForm.addEventListener('submit', async event => {
  event.preventDefault();
  if (confirmationBusy) return;
  setConfirmationBusy(true);
  accountMessage('account-message', 'Đang xác nhận mã…');
  try {
    const data = await postAccount('verify-email', {email: confirmationEmail, token: codeInput.value});
    codeInput.value = '';
    showMonitor(data.user);
  } catch (error) {
    accountMessage('account-message', error.message, true);
    codeInput.focus();
    codeInput.select();
  } finally {
    setConfirmationBusy(false);
  }
});

resendButton.addEventListener('click', async () => {
  if (confirmationBusy || Date.now() < resendAfter) return;
  setConfirmationBusy(true);
  accountMessage('account-message', 'Đang yêu cầu mã mới…');
  try {
    await postAccount('resend-email', {email: confirmationEmail});
    resendAfter = Date.now() + 60_000;
    codeInput.value = '';
    accountMessage('account-message', 'Đã yêu cầu gửi lại. Mở thư mới nhất, kể cả khi Gmail gộp nhiều thư cùng tiêu đề.');
    codeInput.focus();
  } catch (error) {
    if (error.retryAfter > 0) resendAfter = Date.now() + error.retryAfter * 1000;
    accountMessage('account-message', error.message, true);
  } finally {
    setConfirmationBusy(false);
  }
});

confirmationBack.addEventListener('click', () => {
  codeInput.value = '';
  accountsMode(false);
  showSignIn(true);
  updateResendButton();
  passwordInput.focus();
});

window.addEventListener('account-expired', () => {
  if (!workspace.hidden) {
    stopCamera();
    location.reload();
  }
});

const logoutButton = element('logout');
logoutButton.addEventListener('click', async () => {
  logoutButton.disabled = true;
  accountMessage('logout-message', '');
  try {
    await api('/api/account/logout', {method: 'POST'});
    stopCamera();
    location.reload();
  } catch (error) {
    accountMessage('logout-message', error.message, true);
    logoutButton.disabled = false;
  }
});

const cameraSettingsFields = element('camera-settings-fields');
const absenceEnabled = element('absence-enabled');
const absenceSeconds = element('absence-seconds');
let cameraSettingsBusy = false;

async function loadCameraSettings() {
  if (cameraSettingsBusy) return;
  cameraSettingsBusy = cameraSettingsFields.disabled = true;
  accountMessage('camera-settings-status', 'Đang tải cài đặt…');
  try {
    const settings = await api('/api/account/camera-settings');
    absenceEnabled.checked = settings.enabled;
    absenceSeconds.value = settings.seconds;
    cameraSettingsFields.disabled = false;
    accountMessage('camera-settings-status', '');
  } catch (error) {
    accountMessage('camera-settings-status', error.message);
  } finally {
    cameraSettingsBusy = false;
  }
}

for (const preset of cameraSettingsFields.querySelectorAll('[data-absence-seconds]')) {
  preset.addEventListener('click', () => { absenceSeconds.value = preset.dataset.absenceSeconds; });
}

element('camera-settings-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (cameraSettingsBusy) return;
  cameraSettingsBusy = cameraSettingsFields.disabled = true;
  accountMessage('camera-settings-status', 'Đang lưu cài đặt…');
  try {
    await api('/api/account/camera-settings', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({enabled: absenceEnabled.checked, seconds: absenceSeconds.valueAsNumber}),
    });
    accountMessage('camera-settings-status', 'Đã lưu cài đặt.');
  } catch (error) {
    accountMessage('camera-settings-status', error.message);
  } finally {
    cameraSettingsBusy = cameraSettingsFields.disabled = false;
  }
});

const deliveryLabels = {pending: 'Đang xử lý', sent: 'Đã gửi Telegram', unlinked: 'Chưa kết nối Telegram', error: 'Gửi Telegram thất bại'};
const historyDate = element('history-date');
const historyDay = new Intl.DateTimeFormat('vi-VN', {
  weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'Asia/Ho_Chi_Minh',
});
const historyClock = new Intl.DateTimeFormat('vi-VN', {
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23', timeZone: 'Asia/Ho_Chi_Minh',
});
let historyRequest;
let historyPage = 1;

async function loadHistory(page = historyPage) {
  historyRequest?.abort();
  const controller = new AbortController();
  historyRequest = controller;
  const reload = element('history-refresh');
  const list = element('history-events');
  const selected = historyDate.value;
  const query = new URLSearchParams({page});
  if (selected) query.set('date', selected);
  element('history-clear').hidden = !selected;
  element('history-pages').hidden = true;
  reload.disabled = true;
  list.replaceChildren();
  accountMessage('history-status', 'Đang tải lịch sử…');
  try {
    const {events, has_more} = await api(`/api/account/history?${query}`, {signal: controller.signal});
    if (historyRequest !== controller) return;
    historyPage = page;
    accountMessage('history-status', events.length ? '' : selected ? 'Không có cảnh báo trong ngày này.'
      : 'Chưa có cảnh báo trong lịch sử.');
    element('history-pages').hidden = page === 1 && !has_more;
    element('history-prev').disabled = page === 1;
    element('history-next').disabled = !has_more;
    element('history-page').textContent = `Trang ${page}`;
    let dayLabel;
    let rows;
    for (const event of events) {
      const occurred = new Date(event.occurred_at);
      const day = historyDay.format(occurred);
      if (day !== dayLabel) {
        const section = document.createElement('section');
        section.className = 'history-day';
        const heading = document.createElement('h2');
        heading.textContent = day;
        rows = document.createElement('ol');
        rows.className = 'panel history-rows';
        section.append(heading, rows);
        list.append(section);
        dayLabel = day;
      }
      const item = document.createElement('li');
      item.className = 'history-event';
      const time = document.createElement('time');
      time.dateTime = event.occurred_at;
      time.textContent = historyClock.format(occurred);
      const detail = document.createElement('div');
      const title = document.createElement('strong');
      title.textContent = event.source === 'camera_absence' ? 'Không thấy người' : 'Nghi té ngã';
      const source = document.createElement('p');
      source.textContent = event.source === 'video_test' ? 'Thử video' : 'Camera';
      detail.append(title, source);
      const delivery = document.createElement('span');
      delivery.className = 'delivery';
      delivery.dataset.status = event.telegram_status;
      delivery.textContent = deliveryLabels[event.telegram_status] || 'Chưa rõ trạng thái';
      item.append(time, detail, delivery);
      if (event.has_photo) {
        const link = document.createElement('a');
        link.className = 'history-photo';
        link.href = `/api/account/history/${encodeURIComponent(event.id)}/photo`;
        link.target = '_blank';
        link.rel = 'noopener';
        const image = document.createElement('img');
        image.alt = 'Mở ảnh tại mốc cảnh báo';
        image.loading = 'lazy';
        image.src = link.href;
        link.append(image);
        detail.append(link);
      }
      rows.append(item);
    }
  } catch (error) {
    if (historyRequest === controller && error.name !== 'AbortError') accountMessage('history-status', error.message);
  } finally {
    if (historyRequest === controller) reload.disabled = false;
  }
}

function telegramControls(available, linked) {
  element('telegram-start').hidden = !available || linked;
  element('telegram-test').hidden = !linked;
  element('telegram-unlink').hidden = !linked;
  element('telegram-open').hidden = !available || linked || !telegramStep;
  element('telegram-check').hidden = !available || linked || telegramStep !== 'open';
  element('telegram-confirm').hidden = !available || linked || telegramStep !== 'confirm';
  element('telegram-candidate').hidden = element('telegram-confirm').hidden;
}

async function loadTelegram() {
  try {
    const state = await api('/api/account/telegram');
    if (state.linked) telegramStep = '';
    accountMessage('telegram-status', !state.available ? 'Máy chủ chưa cấu hình bot Telegram.' :
      state.linked ? `Đã kết nối với ${state.label}.` : 'Chưa kết nối Telegram.');
    telegramControls(state.available, state.linked);
  } catch (error) {
    telegramControls(false, false);
    accountMessage('telegram-status', error.message);
  }
}

historyDate.addEventListener('change', () => {
  historyPage = 1;
  loadHistory();
});
element('history-clear').addEventListener('click', () => {
  historyDate.value = '';
  historyDate.focus();
  historyPage = 1;
  loadHistory();
});
element('history-refresh').addEventListener('click', () => loadHistory());
element('history-prev').addEventListener('click', () => loadHistory(historyPage - 1));
element('history-next').addEventListener('click', () => loadHistory(historyPage + 1));

const telegramButtons = ['start', 'check', 'confirm', 'test', 'unlink'].map(action => element('telegram-' + action));
for (const button of telegramButtons) {
  button.addEventListener('click', async () => {
    const action = button.id.slice('telegram-'.length);
    telegramButtons.forEach(item => { item.disabled = true; });
    accountMessage('telegram-message', 'Đang xử lý…');
    try {
      const data = await api('/api/account/telegram/' + action, {method: 'POST'});
      if (action === 'start') {
        element('telegram-open').href = data.url;
        telegramStep = 'open';
        telegramControls(true, false);
        accountMessage('telegram-message', 'Mở bot, bấm Start trong Telegram rồi quay lại kiểm tra kết nối.');
        element('telegram-open').focus();
      } else if (action === 'check') {
        if (data.found) {
          telegramStep = 'confirm';
          element('telegram-candidate').textContent = `Telegram đã xác nhận ${data.label}.`;
          telegramControls(true, false);
          accountMessage('telegram-message', 'Kiểm tra đúng tài khoản Telegram của bạn rồi xác nhận.');
          element('telegram-confirm').focus();
        } else accountMessage('telegram-message', 'Chưa thấy xác nhận. Hãy mở bot và bấm Start.');
      } else if (action === 'test') {
        accountMessage('telegram-message', 'Đã gửi tin nhắn thử. Mở Telegram để xem.');
      } else {
        telegramStep = '';
        accountMessage('telegram-message', action === 'unlink' ? 'Đã ngắt kết nối.' : 'Đã liên kết Telegram.');
        await loadTelegram();
      }
    } catch (error) {
      accountMessage('telegram-message', error.message);
    } finally {
      telegramButtons.forEach(item => { item.disabled = false; });
    }
  });
}

api('/api/account').then(data => {
  if (data.user) {
    showSignIn(data.configured);
    showMonitor(data.user);
  } else showSignIn(data.configured);
}).catch(error => accountMessage('account-message', error.message));
