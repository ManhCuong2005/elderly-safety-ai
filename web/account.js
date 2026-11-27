'use strict';

const accountForm = element('account-form');
const passwordInput = element('account-password');
const workspace = element('workspace');
const screens = document.querySelectorAll('[data-screen]');
const ROUTE_TITLES = {
  camera: 'Theo dõi camera',
  'thu-video': 'Thử video',
  'lich-su': 'Lịch sử cảnh báo',
  'cai-dat-camera': 'Cài đặt camera',
  'tai-khoan': 'Tài khoản & Telegram',
};

let registering = false;
let telegramStep = '';
let currentRoute;
let lastModalTrigger = null;

function accountMessage(id, text, tone = '') {
  const item = element(id);
  if (!item) return;
  item.textContent = text || '';
  item.hidden = !text;
  item.dataset.tone = tone;
}

/* ===== MOBILE DRAWER & DROPDOWN POPOVERS ===== */
function setDrawerOpen(open) {
  const drawer = element('mobile-drawer');
  const btn = element('mobile-menu-btn');
  if (open) {
    document.body.dataset.menuOpen = 'true';
    if (drawer) drawer.inert = false;
    if (btn) btn.setAttribute('aria-expanded', 'true');
  } else {
    delete document.body.dataset.menuOpen;
    if (drawer) drawer.inert = true;
    if (btn) btn.setAttribute('aria-expanded', 'false');
  }
}

function closeAllDropdowns(except = null) {
  for (const dd of document.querySelectorAll('[data-dropdown]')) {
    if (dd === except) continue;
    dd.querySelector('[data-dropdown-btn]')?.setAttribute('aria-expanded', 'false');
    const panel = dd.querySelector('[data-dropdown-panel]');
    if (panel) panel.dataset.open = 'false';
  }
}

element('mobile-menu-btn')?.addEventListener('click', () => {
  setDrawerOpen(document.body.dataset.menuOpen !== 'true');
});
element('drawer-backdrop')?.addEventListener('click', () => setDrawerOpen(false));
element('drawer-close-sr')?.addEventListener('click', () => setDrawerOpen(false));
for (const link of document.querySelectorAll('[data-drawer-link]')) {
  link.addEventListener('click', () => setDrawerOpen(false));
}

for (const dd of document.querySelectorAll('[data-dropdown]')) {
  const btn = dd.querySelector('[data-dropdown-btn]');
  const panel = dd.querySelector('[data-dropdown-panel]');
  if (!btn || !panel) continue;
  btn.addEventListener('click', event => {
    event.stopPropagation();
    const willOpen = panel.dataset.open !== 'true';
    closeAllDropdowns(willOpen ? dd : null);
    btn.setAttribute('aria-expanded', String(willOpen));
    panel.dataset.open = String(willOpen);
  });
  for (const closer of dd.querySelectorAll('[data-dropdown-close]')) {
    closer.addEventListener('click', () => closeAllDropdowns());
  }
}

document.addEventListener('click', event => {
  for (const dd of document.querySelectorAll('[data-dropdown]')) {
    if (!dd.contains(event.target)) {
      dd.querySelector('[data-dropdown-btn]')?.setAttribute('aria-expanded', 'false');
      const panel = dd.querySelector('[data-dropdown-panel]');
      if (panel) panel.dataset.open = 'false';
    }
  }
});

/* ===== PHOTO PREVIEW MODAL (LỊCH SỬ) ===== */
const photoModal = element('photo-modal');

function setPhotoModalOpen(open) {
  if (!photoModal) return;
  photoModal.dataset.open = String(open);
  photoModal.inert = !open;
  if (!open && lastModalTrigger) {
    lastModalTrigger.focus();
    lastModalTrigger = null;
  }
}

function openPhotoModal({src, title, desc, trigger}) {
  if (!photoModal) return;
  lastModalTrigger = trigger || null;
  element('photo-modal-title').textContent = title;
  element('photo-modal-desc').textContent = desc;
  element('photo-modal-img').src = src;
  element('photo-modal-raw').href = src;
  setPhotoModalOpen(true);
  element('photo-modal-close')?.focus();
}

element('photo-modal-close')?.addEventListener('click', () => setPhotoModalOpen(false));
photoModal?.addEventListener('click', event => {
  if (event.target === photoModal) setPhotoModalOpen(false);
});

document.addEventListener('keydown', event => {
  if (event.key !== 'Escape') return;
  if (photoModal?.dataset.open === 'true') setPhotoModalOpen(false);
  closeAllDropdowns();
  setDrawerOpen(false);
});

/* ===== ĐĂNG NHẬP / ĐĂNG KÝ ===== */
function setPasswordVisible(visible) {
  passwordInput.type = visible ? 'text' : 'password';
  element('toggle-password')?.setAttribute('aria-label', visible ? 'Ẩn mật khẩu' : 'Hiện mật khẩu');
  if (element('icon-eye')) element('icon-eye').hidden = visible;
  if (element('icon-eye-off')) element('icon-eye-off').hidden = !visible;
}

element('toggle-password')?.addEventListener('click', () => {
  setPasswordVisible(passwordInput.type === 'password');
});

function accountsMode(signup) {
  registering = signup;
  const label = signup ? 'Đăng ký' : 'Đăng nhập';
  element('account-heading').textContent = signup ? 'Tạo tài khoản' : 'Đăng nhập';
  element('account-submit').textContent = label;
  element('account-switch-prompt').textContent = signup ? 'Đã có tài khoản?' : 'Chưa có tài khoản?';
  element('account-switch').textContent = signup ? 'Về đăng nhập' : 'Tạo tài khoản';
  element('account-name-field').hidden = !signup;
  element('password-hint').hidden = !signup;
  passwordInput.autocomplete = signup ? 'new-password' : 'current-password';
  passwordInput.placeholder = signup ? 'Tạo mật khẩu' : 'Nhập mật khẩu';
  passwordInput.minLength = signup ? 8 : 1;
  passwordInput.value = '';
  setPasswordVisible(false);
}

function showMonitor(user) {
  const displayName = user.name || 'Chưa đặt tên';
  const initials = Array.from((user.name || '').trim() || (user.email || '').trim())[0]?.toLocaleUpperCase('vi-VN') || 'U';
  element('profile-name').textContent = displayName;
  renderEmail(element('profile-email'), user.email);
  element('sidebar-user-name').textContent = displayName;
  if (displayName.length > 18) element('sidebar-user-name').title = displayName;
  else element('sidebar-user-name').removeAttribute('title');
  renderEmail(element('sidebar-user-email'), user.email);
  if (element('drawer-user-name')) element('drawer-user-name').textContent = displayName;
  renderEmail(element('drawer-user-email'), user.email);
  element('account-avatar').textContent = initials;
  if (element('drawer-avatar')) element('drawer-avatar').textContent = initials;
  if (element('profile-avatar')) element('profile-avatar').textContent = initials;
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
  if (route === 'toi') {
    route = 'tai-khoan';
    history.replaceState(null, '', '#tai-khoan');
  }
  if (!['camera', 'thu-video', 'tai-khoan', 'cai-dat-camera', 'lich-su'].includes(route)) route = 'camera';
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

  element('page-title').textContent = ROUTE_TITLES[route] || 'Theo dõi camera';
  element('header-history-link').hidden = route !== 'camera';

  for (const link of document.querySelectorAll('[data-route]')) {
    if (link.dataset.route === route) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  }

  closeAllDropdowns();
  setDrawerOpen(false);

  if (!first) {
    window.scrollTo(0, 0);
    element('page-title').focus({preventScroll: true});
  }
  if (route === 'tai-khoan') loadTelegram();
  if (route === 'cai-dat-camera') loadCameraSettings();
  if (route === 'lich-su') loadHistory();
}

window.addEventListener('hashchange', renderRoute);

function showSignIn(configured) {
  accountForm.hidden = !configured;
  accountMessage('account-boot-message', configured ? '' : 'Máy chủ chưa cấu hình Supabase. Kiểm tra cấu hình rồi tải lại trang.', configured ? '' : 'alert');
  accountMessage('account-message', '');
  const hash = new URLSearchParams(location.hash.slice(1));
  if (hash.has('access_token') || hash.has('error_code')) {
    history.replaceState(null, '', location.pathname + location.search);
    if (configured) {
      const isErr = hash.has('error_code');
      accountMessage('account-message', isErr
        ? 'Liên kết xác nhận không hợp lệ hoặc đã hết hạn.' : 'Email đã được xác nhận. Bạn có thể đăng nhập.', isErr ? 'alert' : '');
    }
  }
}

element('account-switch').addEventListener('click', () => {
  accountsMode(!registering);
  accountMessage('account-message', '');
  element(registering ? 'account-name' : 'account-email').focus();
});

accountForm.addEventListener('submit', async event => {
  event.preventDefault();
  const submit = element('account-submit');
  const toggle = element('account-switch');
  submit.disabled = toggle.disabled = true;
  accountMessage('account-message', 'Đang xử lý…');
  try {
    const data = await api(registering ? '/api/account/register' : '/api/account/login', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        email: element('account-email').value,
        password: passwordInput.value,
        name: element('account-name').value,
      }),
    });
    passwordInput.value = '';
    if (data.confirmation_required) {
      accountsMode(false);
      accountMessage('account-message', 'Hãy mở email xác nhận, sau đó quay lại đăng nhập.');
      passwordInput.focus();
    } else showMonitor(data.user);
  } catch (error) {
    accountMessage('account-message', error.message, 'alert');
  } finally {
    submit.disabled = toggle.disabled = false;
  }
});

window.addEventListener('account-expired', () => {
  if (!workspace.hidden) {
    stopCamera();
    location.reload();
  }
});

async function performLogout(triggerBtn) {
  if (triggerBtn) triggerBtn.disabled = true;
  try {
    await api('/api/account/logout', {method: 'POST'});
    stopCamera();
    location.reload();
  } catch (error) {
    accountMessage('logout-message', error.message, 'alert');
  } finally {
    if (triggerBtn) triggerBtn.disabled = false;
  }
}

element('logout').addEventListener('click', () => performLogout(element('logout')));
for (const btn of document.querySelectorAll('[data-logout-action]')) {
  btn.addEventListener('click', () => performLogout(btn));
}

/* ===== CÀI ĐẶT CAMERA (#cai-dat-camera) ===== */
const cameraSettingsFields = element('camera-settings-fields');
const absenceSwitch = element('absence-enabled');
const absenceSeconds = element('absence-seconds');
const absencePresets = [...cameraSettingsFields.querySelectorAll('[data-absence-seconds]')];
const cameraSettingsSubmit = element('camera-settings-submit');
let cameraSettingsBusy = false;

function isAbsenceEnabled() {
  return absenceSwitch.getAttribute('aria-checked') === 'true';
}

function syncPresetChips() {
  const val = String(absenceSeconds.value).trim();
  const enabled = isAbsenceEnabled();
  absenceSeconds.disabled = !enabled;
  for (const preset of absencePresets) {
    preset.disabled = !enabled;
    preset.setAttribute('aria-pressed', String(preset.dataset.absenceSeconds === val));
  }
  const num = Number(val);
  const invalid = enabled && (!Number.isInteger(num) || num < 10 || num > 3600);
  absenceSeconds.setAttribute('aria-invalid', String(invalid));
  element('absence-help').classList.toggle('is-error', invalid);
}

function setAbsenceEnabled(enabled) {
  absenceSwitch.setAttribute('aria-checked', String(Boolean(enabled)));
  syncPresetChips();
}

function setCameraSettingsStatus(text, tone = '') {
  const el = element('camera-settings-status');
  el.replaceChildren();
  el.dataset.tone = tone;
  if (!text) return;
  if (tone === 'success') el.append(createSvgIcon('check', 'icon'));
  el.append(document.createTextNode(text));
}

absenceSwitch.addEventListener('click', () => {
  if (cameraSettingsBusy) return;
  setAbsenceEnabled(!isAbsenceEnabled());
  setCameraSettingsStatus('');
});

absenceSeconds.addEventListener('input', () => {
  syncPresetChips();
  setCameraSettingsStatus('');
});

for (const preset of absencePresets) {
  preset.addEventListener('click', () => {
    absenceSeconds.value = preset.dataset.absenceSeconds;
    syncPresetChips();
    setCameraSettingsStatus('');
  });
}

async function loadCameraSettings() {
  if (cameraSettingsBusy) return;
  cameraSettingsBusy = true;
  cameraSettingsFields.disabled = true;
  cameraSettingsSubmit.disabled = true;
  setCameraSettingsStatus('Đang tải cài đặt…');
  try {
    const settings = await api('/api/account/camera-settings');
    absenceSeconds.value = settings.seconds;
    setAbsenceEnabled(settings.enabled);
    cameraSettingsFields.disabled = false;
    cameraSettingsSubmit.disabled = false;
    syncPresetChips();
    setCameraSettingsStatus(settings.enabled ? '' : 'Tính năng đang tắt sẵn.');
  } catch (error) {
    setCameraSettingsStatus(error.message, 'alert');
  } finally {
    cameraSettingsBusy = false;
  }
}

element('camera-settings-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (cameraSettingsBusy) return;
  const enabled = isAbsenceEnabled();
  const parsed = parseInt(absenceSeconds.value, 10);
  const seconds = Number.isInteger(parsed) ? parsed : 60;
  if (enabled && (seconds < 10 || seconds > 3600)) {
    syncPresetChips();
    setCameraSettingsStatus('Nhập số giây từ 10 đến 3600.', 'alert');
    absenceSeconds.focus();
    return;
  }
  cameraSettingsBusy = true;
  cameraSettingsFields.disabled = true;
  cameraSettingsSubmit.disabled = true;
  setCameraSettingsStatus('Đang lưu cài đặt…');
  try {
    await api('/api/account/camera-settings', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({enabled, seconds}),
    });
    setCameraSettingsStatus('Đã lưu cài đặt.', 'success');
  } catch (error) {
    setCameraSettingsStatus(error.message, 'alert');
  } finally {
    cameraSettingsBusy = false;
    cameraSettingsFields.disabled = false;
    cameraSettingsSubmit.disabled = false;
    syncPresetChips();
  }
});

/* ===== LỊCH SỬ CẢNH BÁO (#lich-su) ===== */
const deliveryLabels = {
  pending: 'Đang xử lý',
  sent: 'Đã gửi Telegram',
  unlinked: 'Chưa kết nối Telegram',
  error: 'Gửi Telegram thất bại',
};
const deliveryTones = {
  pending: 'warning',
  sent: 'success',
  unlinked: 'neutral',
  error: 'error',
};
const typeLabels = {
  all: 'Tất cả loại',
  camera: 'Nghi té ngã',
  camera_absence: 'Không thấy người',
  video_test: 'Nguồn thử video',
};

const historyDate = element('history-date');
const historyDay = new Intl.DateTimeFormat('vi-VN', {
  weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'Asia/Ho_Chi_Minh',
});
const historyClock = new Intl.DateTimeFormat('vi-VN', {
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23', timeZone: 'Asia/Ho_Chi_Minh',
});

let historyRequest;
let historyPage = 1;
let historyEventsCache = [];
let historyHasMore = false;
let historyTypeFilter = 'all';

// Lấy ngày hôm nay theo giờ Việt Nam (UTC+7)
function todayIsoVn() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Ho_Chi_Minh', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(new Date());
  const map = Object.fromEntries(parts.map(p => [p.type, p.value]));
  return `${map.year}-${map.month}-${map.day}`;
}

function formatDateVi(iso) {
  if (!iso) return '';
  const [y, m, d] = iso.split('-');
  return `${d}/${m}/${y}`;
}

// Custom Date Picker 6 hàng cố định (components/choice-controls.md)
const todayIso = todayIsoVn();
const [initY, initM] = todayIso.split('-').map(Number);
let calYear = initY;
let calMonth = initM - 1; // 0..11
let calPickMonth = false;

function renderCalendar() {
  const monthLabel = element('cal-month-label');
  const daysView = element('cal-days-view');
  const monthsView = element('cal-months-view');
  const grid = element('cal-days-grid');

  if (calPickMonth) {
    monthLabel.textContent = `Năm ${calYear}`;
    daysView.hidden = true;
    monthsView.hidden = false;
    monthsView.replaceChildren();
    for (let m = 0; m < 12; m += 1) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'calendar-month-cell' + (m === calMonth ? ' is-selected' : '');
      btn.textContent = `Tháng ${m + 1}`;
      btn.addEventListener('click', event => {
        event.stopPropagation();
        calMonth = m;
        calPickMonth = false;
        renderCalendar();
      });
      monthsView.append(btn);
    }
    return;
  }

  monthLabel.textContent = `Tháng ${calMonth + 1}, ${calYear}`;
  daysView.hidden = false;
  monthsView.hidden = true;
  grid.replaceChildren();

  const firstOfMonth = new Date(calYear, calMonth, 1);
  const startOffset = (firstOfMonth.getDay() + 6) % 7; // Monday = 0
  const startDate = new Date(calYear, calMonth, 1 - startOffset);
  const selectedIso = historyDate.value;
  const nowIso = todayIsoVn();

  for (let i = 0; i < 42; i += 1) {
    const cellDate = new Date(startDate.getFullYear(), startDate.getMonth(), startDate.getDate() + i);
    const y = cellDate.getFullYear();
    const m = cellDate.getMonth();
    const d = cellDate.getDate();
    const iso = `${y}-${String(m + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'calendar-day';
    if (m !== calMonth) btn.classList.add('is-outside');
    if (iso === nowIso) btn.classList.add('is-today');
    if (iso === selectedIso) btn.classList.add('is-selected');
    btn.textContent = String(d);
    btn.setAttribute('aria-label', `${d}/${m + 1}/${y}`);
    btn.addEventListener('click', () => {
      applyHistoryDate(iso);
      closeAllDropdowns();
    });
    grid.append(btn);
  }
}

function syncDateButtonLabel() {
  const label = element('history-date-label');
  if (historyDate.value) {
    label.textContent = formatDateVi(historyDate.value);
    label.classList.remove('combobox-placeholder');
  } else {
    label.textContent = 'Chọn ngày lọc';
    label.classList.add('combobox-placeholder');
  }
}

function applyHistoryDate(iso) {
  historyDate.value = iso;
  if (iso) {
    const [y, m] = iso.split('-').map(Number);
    calYear = y;
    calMonth = m - 1;
  }
  calPickMonth = false;
  syncDateButtonLabel();
  renderCalendar();
  historyPage = 1;
  loadHistory(1);
}

element('cal-month-toggle')?.addEventListener('click', event => {
  event.stopPropagation();
  calPickMonth = !calPickMonth;
  renderCalendar();
});
element('cal-prev')?.addEventListener('click', event => {
  event.stopPropagation();
  if (calPickMonth) {
    calYear -= 1;
  } else {
    calMonth -= 1;
    if (calMonth < 0) { calMonth = 11; calYear -= 1; }
  }
  renderCalendar();
});
element('cal-next')?.addEventListener('click', event => {
  event.stopPropagation();
  if (calPickMonth) {
    calYear += 1;
  } else {
    calMonth += 1;
    if (calMonth > 11) { calMonth = 0; calYear += 1; }
  }
  renderCalendar();
});
element('cal-today')?.addEventListener('click', () => {
  applyHistoryDate(todayIsoVn());
  closeAllDropdowns();
});
element('cal-clear')?.addEventListener('click', () => {
  applyHistoryDate('');
  closeAllDropdowns();
});
renderCalendar();

// Custom Select lọc loại cảnh báo
for (const option of document.querySelectorAll('[data-history-type]')) {
  option.addEventListener('click', () => {
    historyTypeFilter = option.dataset.historyType;
    element('history-type-label').textContent = typeLabels[historyTypeFilter] || 'Tất cả loại';
    for (const item of document.querySelectorAll('[data-history-type]')) {
      const selected = item === option;
      item.setAttribute('aria-selected', String(selected));
      item.classList.toggle('menu-item-active', selected);
      const oldCheck = item.querySelector('svg');
      if (oldCheck) oldCheck.remove();
      if (selected) item.append(createSvgIcon('check'));
    }
    closeAllDropdowns();
    renderHistoryEvents();
  });
}

function setHistoryStatusCard(text, {tone = '', actionLabel = '', onAction = null} = {}) {
  const card = element('history-status-card');
  const msg = element('history-status');
  const actions = element('history-status-actions');
  card.hidden = !text;
  card.dataset.tone = tone;
  msg.textContent = text || '';
  actions.replaceChildren();
  actions.hidden = !actionLabel;
  if (actionLabel && onAction) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn btn-outline';
    btn.textContent = actionLabel;
    btn.addEventListener('click', onAction);
    actions.append(btn);
  }
}

function updateHistoryClearVisibility() {
  element('history-clear').hidden = !historyDate.value && historyTypeFilter === 'all';
}

function renderHistoryEvents() {
  const list = element('history-events');
  list.replaceChildren();
  updateHistoryClearVisibility();

  const filtered = historyTypeFilter === 'all'
    ? historyEventsCache
    : historyEventsCache.filter(ev => {
      if (historyTypeFilter === 'camera') return ev.source !== 'camera_absence' && ev.source !== 'video_test';
      return ev.source === historyTypeFilter;
    });

  if (!filtered.length) {
    element('history-pages').hidden = true;
    const selectedDate = historyDate.value;
    const isFiltered = Boolean(selectedDate) || historyTypeFilter !== 'all';
    const emptyMsg = selectedDate
      ? `Không có cảnh báo nào trong ngày ${formatDateVi(selectedDate)}.`
      : historyTypeFilter !== 'all'
        ? `Không có cảnh báo thuộc nhóm "${typeLabels[historyTypeFilter]}" trong trang này.`
        : 'Chưa có cảnh báo trong lịch sử.';
    setHistoryStatusCard(emptyMsg, isFiltered ? {
      actionLabel: 'Bỏ lọc',
      onAction: () => {
        historyTypeFilter = 'all';
        element('history-type-label').textContent = 'Tất cả loại';
        for (const item of document.querySelectorAll('[data-history-type]')) {
          const isAll = item.dataset.historyType === 'all';
          item.setAttribute('aria-selected', String(isAll));
          item.classList.toggle('menu-item-active', isAll);
          item.querySelector('svg')?.remove();
          if (isAll) item.append(createSvgIcon('check'));
        }
        applyHistoryDate('');
      },
    } : {});
    return;
  }

  setHistoryStatusCard('');
  element('history-pages').hidden = historyPage === 1 && !historyHasMore;
  element('history-prev').disabled = historyPage === 1;
  element('history-next').disabled = !historyHasMore;
  element('history-page').textContent = String(historyPage);
  element('history-count').textContent = `${filtered.length} cảnh báo`;

  let dayLabel;
  let rows;
  for (const event of filtered) {
    const occurred = new Date(event.occurred_at);
    const day = historyDay.format(occurred);
    if (day !== dayLabel) {
      const section = document.createElement('section');
      const heading = document.createElement('h2');
      heading.className = 'history-day-heading';
      heading.textContent = day;
      const card = document.createElement('div');
      card.className = 'card history-card';
      rows = document.createElement('ol');
      rows.className = 'history-rows';
      card.append(rows);
      section.append(heading, card);
      list.append(section);
      dayLabel = day;
    }

    const item = document.createElement('li');
    const main = document.createElement('div');
    main.className = 'history-event-main';

    const iconBox = document.createElement('span');
    iconBox.className = 'history-icon-box';
    iconBox.setAttribute('aria-hidden', 'true');
    iconBox.append(createSvgIcon(event.source === 'camera_absence' ? 'user-x' : 'triangle-alert'));

    const body = document.createElement('div');
    body.className = 'history-event-body';

    const top = document.createElement('div');
    top.className = 'history-event-top';
    const title = document.createElement('strong');
    title.className = 'history-event-title';
    const titleText = event.source === 'camera_absence' ? 'Không thấy người' : 'Nghi té ngã';
    title.textContent = titleText;

    const clockText = historyClock.format(occurred);
    const sourceText = event.source === 'video_test' ? 'Thử video' : 'Camera';
    const time = document.createElement('time');
    time.className = 'history-event-time tabular-nums';
    time.dateTime = event.occurred_at;
    time.textContent = `${clockText} · ${sourceText}`;

    top.append(title, time);
    body.append(top);

    const statusText = deliveryLabels[event.telegram_status] || 'Chưa rõ trạng thái';
    if (event.has_photo) {
      const photoUrl = `/api/account/history/${encodeURIComponent(event.id)}/photo`;
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'history-photo-btn';
      btn.setAttribute('aria-label', `Xem ảnh lớn mốc ${clockText}`);
      const frame = document.createElement('span');
      frame.className = 'history-photo-frame';
      const image = document.createElement('img');
      image.alt = `Ảnh chụp tại mốc ${clockText}`;
      image.loading = 'lazy';
      image.src = photoUrl;
      frame.append(image);
      btn.append(frame);
      btn.addEventListener('click', () => {
        openPhotoModal({
          src: photoUrl,
          title: `Ảnh tại mốc cảnh báo · ${clockText}`,
          desc: `${titleText} · Nguồn: ${sourceText} · ${statusText}`,
          trigger: btn,
        });
      });
      body.append(btn);
    }

    main.append(iconBox, body);

    const badgeWrap = document.createElement('div');
    badgeWrap.className = 'history-event-badge-wrap';
    const delivery = document.createElement('span');
    delivery.className = 'badge';
    delivery.dataset.status = event.telegram_status;
    setBadgeTone(delivery, deliveryTones[event.telegram_status] || 'neutral');
    delivery.textContent = statusText;
    badgeWrap.append(delivery);

    item.append(main, badgeWrap);
    rows.append(item);
  }
}

async function loadHistory(page = historyPage) {
  historyRequest?.abort();
  const controller = new AbortController();
  historyRequest = controller;
  const reload = element('history-refresh');
  const list = element('history-events');
  const selected = historyDate.value;
  const query = new URLSearchParams({page});
  if (selected) query.set('date', selected);
  updateHistoryClearVisibility();
  element('history-pages').hidden = true;
  reload.disabled = true;
  list.replaceChildren();
  setHistoryStatusCard('Đang tải lịch sử…');
  try {
    const {events, has_more} = await api(`/api/account/history?${query}`, {signal: controller.signal});
    if (historyRequest !== controller) return;
    historyPage = page;
    historyEventsCache = events || [];
    historyHasMore = Boolean(has_more);
    renderHistoryEvents();
  } catch (error) {
    if (historyRequest === controller && error.name !== 'AbortError') {
      setHistoryStatusCard(error.message, {
        tone: 'alert',
        actionLabel: 'Thử lại',
        onAction: () => loadHistory(page),
      });
    }
  } finally {
    if (historyRequest === controller) reload.disabled = false;
  }
}

element('history-clear').addEventListener('click', () => {
  historyTypeFilter = 'all';
  element('history-type-label').textContent = 'Tất cả loại';
  for (const item of document.querySelectorAll('[data-history-type]')) {
    const isAll = item.dataset.historyType === 'all';
    item.setAttribute('aria-selected', String(isAll));
    item.classList.toggle('menu-item-active', isAll);
    item.querySelector('svg')?.remove();
    if (isAll) item.append(createSvgIcon('check'));
  }
  applyHistoryDate('');
});
element('history-refresh').addEventListener('click', () => loadHistory());
element('history-prev').addEventListener('click', () => loadHistory(historyPage - 1));
element('history-next').addEventListener('click', () => loadHistory(historyPage + 1));

/* ===== TÀI KHOẢN & TELEGRAM (#tai-khoan) ===== */
function telegramControls(available, linked) {
  element('telegram-start').hidden = !available || linked;
  element('telegram-test').hidden = !linked;
  element('telegram-unlink').hidden = !linked;
  element('telegram-open').hidden = !available || linked || !telegramStep;
  element('telegram-check').hidden = !available || linked || telegramStep !== 'open';
  element('telegram-confirm').hidden = !available || linked || telegramStep !== 'confirm';
  element('telegram-candidate').hidden = element('telegram-confirm').hidden;
  element('telegram-steps').hidden = !available || linked;

  const badge = element('telegram-badge');
  if (!available) {
    badge.textContent = 'Chưa cấu hình';
    setBadgeTone(badge, 'error');
  } else if (linked) {
    badge.textContent = 'Đã kết nối';
    setBadgeTone(badge, 'success');
  } else {
    badge.textContent = 'Chưa kết nối';
    setBadgeTone(badge, 'neutral');
  }
}

async function loadTelegram() {
  try {
    const state = await api('/api/account/telegram');
    if (state.linked) telegramStep = '';
    accountMessage('telegram-status', !state.available
      ? 'Máy chủ chưa cấu hình bot Telegram.'
      : state.linked
        ? `Đã liên kết với ${state.label}. Mọi ảnh báo động sẽ gửi thẳng tới cuộc trò chuyện này.`
        : 'Chưa kết nối Telegram. Tạo liên kết, mở bot và bấm Start để nhận ảnh cảnh báo.');
    telegramControls(state.available, state.linked);
  } catch (error) {
    telegramControls(false, false);
    accountMessage('telegram-status', error.message, 'alert');
  }
}

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
      accountMessage('telegram-message', error.message, 'alert');
    } finally {
      telegramButtons.forEach(item => { item.disabled = false; });
    }
  });
}

/* ===== KHỞI CHẠY PHIÊN ===== */
api('/api/account').then(data => {
  if (data.user) {
    showSignIn(data.configured);
    showMonitor(data.user);
  } else showSignIn(data.configured);
}).catch(error => {
  accountMessage('account-boot-message', error.message, 'alert');
});
