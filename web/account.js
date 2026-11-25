'use strict';

const accountForm = element('account-form');
const accountDialog = element('account-dialog');
const passwordInput = element('account-password');
let registering = false;
let telegramStep = '';

function accountMessage(id, text) {
  const item = element(id);
  item.textContent = text;
  item.hidden = !text;
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
  element('profile-name').textContent = user.name || 'Chưa đặt tên';
  element('profile-email').textContent = user.email;
  element('account-screen').hidden = true;
  element('monitor').hidden = false;
  init();
}

function showSignIn(configured) {
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

accountForm.addEventListener('submit', async event => {
  event.preventDefault();
  const submit = element('account-submit');
  const toggle = element('account-switch');
  submit.disabled = toggle.disabled = true;
  accountMessage('account-message', 'Đang xử lý…');
  try {
    const data = await api(registering ? '/api/account/register' : '/api/account/login', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({email: element('account-email').value, password: passwordInput.value,
        name: element('account-name').value}),
    });
    passwordInput.value = '';
    if (data.confirmation_required) {
      accountsMode(false);
      accountMessage('account-message', 'Hãy mở email xác nhận, sau đó quay lại đăng nhập.');
      passwordInput.focus();
    } else showMonitor(data.user);
  } catch (error) {
    accountMessage('account-message', error.message);
  } finally {
    submit.disabled = toggle.disabled = false;
  }
});

window.addEventListener('account-expired', () => {
  if (!element('monitor').hidden) {
    stopCamera();
    location.reload();
  }
});

element('logout').addEventListener('click', async () => {
  const button = element('logout');
  button.disabled = true;
  try {
    await api('/api/account/logout', {method: 'POST'});
    stopCamera();
    location.reload();
  } catch (error) {
    accountMessage('logout-message', error.message);
  } finally {
    button.disabled = false;
  }
});

const deliveryLabels = {pending: 'Đang xử lý', sent: 'Đã gửi Telegram', unlinked: 'Chưa kết nối Telegram', error: 'Gửi Telegram thất bại'};

async function loadHistory() {
  const reload = element('history-refresh');
  const list = element('history-events');
  reload.disabled = true;
  list.replaceChildren();
  accountMessage('history-status', 'Đang tải lịch sử…');
  try {
    const {events} = await api('/api/account/history');
    accountMessage('history-status', events.length ? '' : 'Chưa có cảnh báo từ camera trực tiếp.');
    const formatDate = new Intl.DateTimeFormat('vi-VN', {dateStyle: 'short', timeStyle: 'medium', timeZone: 'Asia/Ho_Chi_Minh'});
    for (const event of events) {
      const item = document.createElement('li');
      const time = document.createElement('time');
      time.dateTime = event.occurred_at;
      time.textContent = formatDate.format(new Date(event.occurred_at));
      item.append(time, ` · Nghi té ngã · ${deliveryLabels[event.telegram_status] || 'Chưa rõ trạng thái'}`);
      list.append(item);
    }
  } catch (error) {
    accountMessage('history-status', error.message);
  } finally {
    reload.disabled = false;
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

element('open-account').addEventListener('click', () => {
  accountDialog.showModal();
  loadHistory();
  loadTelegram();
});
element('history-refresh').addEventListener('click', loadHistory);

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
