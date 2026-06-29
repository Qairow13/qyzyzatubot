"""
Бот-уведомитель для сайта-приглашения (қыз ұзату) — БЕЗ внешних зависимостей.
Использует только стандартную библиотеку Python (http.server, urllib).
Ничего pip install'ить не нужно.

Запуск:
    python main.py

Next.js должен слать POST на http://<адрес_сервера>:5000/notify
с JSON-телом: {"message": "готовый текст уведомления"}
и заголовком X-Secret-Key (если SECRET_KEY задан).
"""

import os
import json
import re
import logging
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("rsvp-bot")


def load_dotenv(path: str = ".env") -> None:
    """Простая загрузка переменных из .env файла, без внешних библиотек."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            # не перезаписываем переменные, заданные явно через PowerShell/систему
            os.environ.setdefault(key, value)


load_dotenv()

# --- Настройки ---------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_IDS = [
    cid.strip()
    for cid in os.environ.get("CHAT_IDS", "").split(",")
    if cid.strip()
]
SECRET_KEY = os.environ.get("SECRET_KEY", "")
PORT = int(os.environ.get("PORT", 5000))

TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

if not BOT_TOKEN:
    log.warning("BOT_TOKEN не задан через переменные окружения!")
if not CHAT_IDS:
    log.warning("CHAT_IDS не задан через переменные окружения!")


def send_telegram_message(chat_id: str, text: str) -> bool:
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        TELEGRAM_API_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if not data.get("ok"):
                log.error("Telegram API ошибка для chat_id=%s: %s", chat_id, data)
                return False
            return True
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        log.error("Не удалось отправить сообщение chat_id=%s: %s", chat_id, e)
        return False


def broadcast(text: str) -> dict:
    return {chat_id: send_telegram_message(chat_id, text) for chat_id in CHAT_IDS}


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health" or self.path == "/":
            self._send_json(200, {"ok": True})
        else:
            self._send_json(404, {"ok": False, "error": "not_found"})

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()

    def do_POST(self):
        # схлопываем повторяющиеся слэши (на случай BOT_URL с / на конце,
        # из-за которого получается //notify вместо /notify)
        normalized_path = re.sub(r"/+", "/", self.path.split("?")[0]).rstrip("/")
        if normalized_path != "/notify":
            self._send_json(404, {"ok": False, "error": "not_found"})
            return

        if SECRET_KEY:
            provided = self.headers.get("X-Secret-Key", "")
            if provided != SECRET_KEY:
                self._send_json(401, {"ok": False, "error": "unauthorized"})
                return

        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length) if length else b"{}"

        try:
            data = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "invalid_json"})
            return

        message = (data.get("message") or "").strip()
        if not message:
            self._send_json(400, {"ok": False, "error": "message обязателен"})
            return

        results = broadcast(message)
        log.info("Рассылка: %s | %s", message, results)
        self._send_json(200, {"ok": True, "sent": results})

    def log_message(self, format, *args):
        log.info("%s - %s", self.address_string(), format % args)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    log.info("Бот запущен на порту %s", PORT)
    server.serve_forever()