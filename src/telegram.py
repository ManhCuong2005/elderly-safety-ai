import argparse
import http.client
import json
import re
import secrets
from datetime import timedelta, timezone

from .storage import read_json, safe, write_json

CONFIG_FILE = ".secrets/telegram.json"
HOST = "api.telegram.org"
VN_TIME = timezone(timedelta(hours=7))


class TelegramError(Exception):
    def __init__(self, message, *, status=None):
        super().__init__(message)
        self.status = status


def read_config():
    try:
        values = read_json(safe(CONFIG_FILE))
    except (OSError, ValueError):
        raise TelegramError("Không đọc được cấu hình Telegram.") from None
    if values is not None and (not isinstance(values, dict)
                               or not isinstance(values.get("bot_token"), str)
                               or not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", values["bot_token"])):
        raise TelegramError("Kiểm tra bot_token trong .secrets/telegram.json.")
    return values


def api(token, method, payload, *, photo=None):
    if photo is None:
        body = json.dumps(payload).encode("utf-8")
        content_type = "application/json"
    else:
        boundary = secrets.token_hex(24)
        content_type = f"multipart/form-data; boundary={boundary}"
        fields = [f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
                  for name, value in payload.items()]
        fields.extend([
            f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="fall-test.jpg"\r\n'
            'Content-Type: image/jpeg\r\n\r\n'.encode(),
            photo,
            f"\r\n--{boundary}--\r\n".encode(),
        ])
        body = b"".join(fields)
    connection = http.client.HTTPSConnection(HOST, timeout=6)
    try:
        connection.request("POST", f"/bot{token}/{method}", body, {"Content-Type": content_type})
        response = connection.getresponse()
        if response.status != 200:
            raise TelegramError(f"Telegram trả HTTP {response.status} khi gọi {method}.", status=response.status)
        data = json.loads(response.read(1024 * 1024))
        if not isinstance(data, dict) or data.get("ok") is not True or "result" not in data:
            raise TelegramError(f"Telegram chưa xác nhận yêu cầu {method}.")
        return data["result"]
    except TimeoutError:
        raise TelegramError(f"Hết thời gian chờ Telegram khi gọi {method}.") from None
    except http.client.RemoteDisconnected:
        raise TelegramError(f"Kết nối Telegram bị đóng trước khi nhận phản hồi {method}.") from None
    except (http.client.HTTPException, ValueError):
        raise TelegramError(f"Phản hồi Telegram không hợp lệ khi gọi {method}.") from None
    except OSError as error:
        raise TelegramError(f"Lỗi kết nối Telegram khi gọi {method} ({type(error).__name__}).") from None
    finally:
        connection.close()


def linked_chat(config):
    chat_id = config.get("chat_id")
    if type(chat_id) is not int or chat_id <= 0:
        raise TelegramError("Chưa ghép chat riêng. Chạy TelegramPair.")
    return chat_id


def private_start(message, code):
    chat = message.get("chat", {})
    sender = message.get("from", {})
    if (message.get("text") == f"/start {code}" and chat.get("type") == "private"
            and not sender.get("is_bot") and type(chat.get("id")) is int and chat["id"] > 0):
        username = chat.get("username", "")
        label = f"@{username}" if username else chat.get("first_name", "Telegram")
        return {"chat_id": chat["id"], "label": label[:120]}


def pair(config, code):
    if not code or not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", code):
        raise TelegramError("Mã ghép chat cần từ 6 đến 64 chữ cái, số, dấu gạch hoặc gạch dưới.")
    updates = api(config["bot_token"], "getUpdates", {"timeout": 0, "allowed_updates": ["message"]})
    matches = set()
    for update in updates:
        chat = private_start(update.get("message", {}), code)
        if chat:
            matches.add(chat["chat_id"])
    if len(matches) != 1:
        raise TelegramError("Chưa tìm thấy đúng một chat riêng gửi mã ghép.")
    chat_id = matches.pop()
    chat = api(config["bot_token"], "getChat", {"chat_id": chat_id})
    if chat.get("id") != chat_id or chat.get("type") != "private":
        raise TelegramError("Telegram chưa xác nhận đúng chat riêng.")
    write_json(safe(CONFIG_FILE), {**config, "chat_id": chat_id})


def fall_text(occurred_at):
    when = occurred_at.astimezone(VN_TIME).strftime("%H:%M:%S %d/%m/%Y")
    return (f"⚠️ Nghi té ngã qua camera\nThời điểm: {when} (giờ Việt Nam).\n"
            "Hãy kiểm tra tình trạng người đang được theo dõi.")


def absence_text(occurred_at, seconds):
    when = occurred_at.astimezone(VN_TIME).strftime("%H:%M:%S %d/%m/%Y")
    return (f"CameraAI · Không thấy người trong khung hình ít nhất {seconds} giây.\n"
            f"Thời điểm cảnh báo: {when} (giờ Việt Nam).\n"
            "Hãy kiểm tra vùng quan sát nếu cần.")


def video_test_text(timestamp):
    minutes, seconds = divmod(round(timestamp * 100), 6000)
    return ("🧪 [THỬ VIDEO] CameraAI phát hiện nghi té ngã trong video tải lên.\n"
            f"Mốc phát hiện đầu tiên: {minutes:02}:{seconds / 100:05.2f} trong video.\n"
            "Đây là thông báo kiểm thử.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["pair", "test"])
    parser.add_argument("--code")
    args = parser.parse_args()
    try:
        config = read_config()
        if config is None:
            raise TelegramError(f"Hãy lưu bot_token vào {CONFIG_FILE}.")
        if args.command == "pair":
            pair(config, args.code)
            print("Đã ghép chat riêng Telegram.")
        else:
            api(config["bot_token"], "sendMessage", {
                "chat_id": linked_chat(config), "text": "Tin nhắn thử từ dự án theo dõi té ngã. Đây là kiểm tra kết nối.",
            })
            print("Telegram đã xác nhận gửi tin nhắn thử.")
    except TelegramError as error:
        raise SystemExit(str(error)) from None
