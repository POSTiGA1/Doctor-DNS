#!/usr/bin/env python3
"""Setting up the Telegram bot from the admin panel.

The operator pastes a token and their Telegram id; the panel checks the token
with Telegram, makes the key and the webhook, writes the bot's settings and
starts it. What has to hold: a bad token goes no further; the settings file
is readable by root alone and holds what the bot needs; setting up again
reuses the key rather than piling up new ones; the token is never shown back
whole, nor written to the log; and the installer carries the bot and stops it
on uninstall.
"""
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import urllib.parse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
fails = []


def check(label, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + label +
          ((" - " + detail) if detail and not cond else ""))
    if not cond:
        fails.append(label)


def load(path, mod):
    spec = importlib.util.spec_from_loader(
        mod, importlib.machinery.SourceFileLoader(mod, os.path.join(HERE, "..", path)))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


panel = load("templates/smartdns-panel", "panel")
admin = load("templates/smartdns-admin", "admin")
logged = []
admin.log = lambda level, msg: logged.append(msg)

tmp = tempfile.mkdtemp()
db_path = os.path.join(tmp, "panel.db")
store = panel.Store(db_path)
admin.DB = db_path
admin.CFG = {"ADMIN_PATH": "p", "ADMIN_CERT": "/etc/letsencrypt/live/panel.example.com/f"}
admin.STORE = admin.Store(db_path)
admin.BOT_BIN = os.path.join(tmp, "doctor-dns-bot")
admin.BOT_ENV = os.path.join(tmp, "doctor-dns-bot.env")
calls = []
admin.systemctl = lambda *a: calls.append(a) or True
TOKEN = "123456789:AAH" + "x" * 32
admin.bot_getme = lambda token: ("my_shop_bot", None) if token == TOKEN \
    else (None, "تلگرام این توکن را نمی‌شناسد")


class Rec:
    def __init__(self):
        self._headers_buffer = []
        self.sent = {}
        self.written = b""
        self.wfile = self
        self.path = "/p/bot"
        self.headers = {}

    def write(self, b):
        self.written += b

    def send_response(self, code):
        self.sent["code"] = code

    def send_header(self, k, v):
        self.sent[k] = v

    def end_headers(self):
        pass


for name in ("action", "redirect", "send", "bot_page", "queue_bot_test"):
    setattr(Rec, name, getattr(admin.Admin, name))
Rec.one = staticmethod(admin.Admin.one)


def act(rest, **form):
    r = Rec()
    r.action(rest, {k: [v] for k, v in form.items()})
    return urllib.parse.unquote(r.sent.get("Location", ""))


print("before the installer has put the bot here")
check("the page says to run the installer", "نصب‌کننده" in Rec().bot_page())
check("and setting up is refused", "m=!" in act("bot-setup", token=TOKEN, admins="42"))
open(admin.BOT_BIN, "w").close()

print("what is refused")
check("a token that is not one", "m=!" in act("bot-setup", token="hello", admins="42"))
check("a token Telegram does not know", "نمی‌شناسد" in act(
    "bot-setup", token="123456789:AAH" + "y" * 32, admins="4242"))
check("no Telegram id of the operator's", "m=!" in act("bot-setup", token=TOKEN, admins="x"))
check("and nothing was made", not store.one("SELECT 1 FROM api_tokens")
      and not os.path.exists(admin.BOT_ENV))

print("setting it up")
page = Rec().bot_page()
check("the page walks through BotFather, Start and the id",
      "@BotFather" in page and "Start" in page and "@userinfobot" in page)
where = act("bot-setup", token=TOKEN, admins="100200300, 11112", support="سلام")
check("it is up", "@my_shop_bot" in where and "m=!" not in where, where)
env = admin.read_env(admin.BOT_ENV)
check("the settings hold the token, the API and the operator",
      env["BOT_TOKEN"] == TOKEN and env["API_URL"] == "https://panel.example.com:8445/api/v1"
      and env["ADMIN_IDS"] == "100200300,11112" and env["SUPPORT_TEXT"] == "سلام")
key = store.one("SELECT * FROM api_tokens")
check("with a key of admin rights, of which only the hash is kept",
      key["scope"] == "admin" and key["token_hash"] == panel.token_hash(env["API_KEY"]))
check("told to tell the bot what happens",
      key["webhook_url"] == "http://127.0.0.1:18990/"
      and key["webhook_secret"] == env["WEBHOOK_SECRET"])
check("the customer panel's Telegram button opens this bot",
      store.setting("bot_link") == "https://t.me/my_shop_bot")
if os.name == "posix":
    check("readable by root alone", stat.S_IMODE(os.stat(admin.BOT_ENV).st_mode) == 0o600)
check("the bot is enabled and started", ("enable", "doctor-dns-bot") in calls
      and ("restart", "doctor-dns-bot") in calls)
check("and a test message is on its way", store.one(
    "SELECT event FROM webhook_outbox WHERE token_id = ?", (key["id"],))["event"] == "ping")
check("the token is not in the log", not any(TOKEN in m for m in logged))

print("setting it up again")
act("bot-setup", token="", admins="100200300")
check("an empty token keeps the one it has", admin.read_env(admin.BOT_ENV)["BOT_TOKEN"] == TOKEN)
check("and the same key - no pile of new ones",
      store.one("SELECT count(*) c FROM api_tokens")["c"] == 1
      and admin.read_env(admin.BOT_ENV)["API_KEY"] == env["API_KEY"])
store.run("UPDATE api_tokens SET revoked_at = ?", (panel.now(),))
act("bot-setup", token="", admins="100200300")
check("a revoked key is replaced by a new one",
      store.one("SELECT count(*) c FROM api_tokens WHERE revoked_at IS NULL")["c"] == 1
      and admin.read_env(admin.BOT_ENV)["API_KEY"] != env["API_KEY"])

print("the page afterwards")
page = Rec().bot_page()
check("the token is shown only by its last four", TOKEN not in page and "...xxxx" in page)
check("with the bot's name and the buttons", "@my_shop_bot" in page and "bot-power" in page
      and "bot-test" in page)
calls.clear()
act("bot-power", to="off")
check("it can be switched off", ("disable", "--now", "doctor-dns-bot") in calls)
act("bot-power", to="on")
check("and on", ("enable", "--now", "doctor-dns-bot") in calls)
before = store.one("SELECT count(*) c FROM webhook_outbox")["c"]
act("bot-test")
check("a test message on request", store.one("SELECT count(*) c FROM webhook_outbox")["c"]
      == before + 1)

print("the installer")
logic = open(os.path.join(HERE, "installer-logic.sh"), encoding="utf-8").read()
build = open(os.path.join(HERE, "build-installer.py"), encoding="utf-8").read()
check("carries the bot and its service", '("BOT", "examples/telegram-bot/bot.py")' in build
      and "payload BOT > /usr/local/bin/doctor-dns-bot" in logic)
check("restarts one already set up, so an upgrade reaches it",
      "systemctl try-restart doctor-dns-bot.service" in logic)
check("and on uninstall stops it and removes its token",
      "systemctl disable --now doctor-dns-bot.service" in logic
      and "rm -f /etc/doctor-dns-bot.env" in logic)

shutil.rmtree(tmp, ignore_errors=True)
print()
if fails:
    print("%d FAILED: %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("all checks passed")
