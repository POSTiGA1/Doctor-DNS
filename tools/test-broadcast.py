#!/usr/bin/env python3
"""A message to many customers, through the bot.

What has to hold: the admin picks who - everyone, the active, those whose
period ends soon, the expired, those with no plan, a plan's customers - and
sees how many each is before sending; only customers with a Telegram are
sent it, one message each to the bot, which passes it on at a pace Telegram
accepts; and the page says how many have reached the bot.
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import urllib.parse
from datetime import datetime, timedelta, timezone

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
botmod = load("examples/telegram-bot/bot.py", "bot")
for m in (panel, admin, botmod):
    m.log = lambda *a: None
panel.print = lambda *a, **k: None

tmp = tempfile.mkdtemp()
db_path = os.path.join(tmp, "panel.db")
store = panel.Store(db_path)
admin.DB = db_path
admin.CFG = {"ADMIN_PATH": "p"}
admin.STORE = admin.Store(db_path)
store.run("INSERT INTO templates (name, is_default, created_at) VALUES ('کامل', 1, ?)",
          (panel.now(),))
store.run("INSERT INTO plans (name, template_id, days, quota_bytes, price, created_at)"
          " VALUES ('ماهانه', 1, 30, 1, 1000, ?)", (panel.now(),))
soon = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(timespec="seconds")
later = (datetime.now(timezone.utc) + timedelta(days=20)).isoformat(timespec="seconds")
for i, (status, tg, plan, ends) in enumerate([
        ("active", 101, 1, soon), ("active", 102, 1, later), ("active", None, 1, later),
        ("expired", 103, 1, None), ("pending", 104, None, None), ("pending", None, None, None)]):
    store.run("INSERT INTO users (telegram_id, username, created_at, status, plan_id, expires_at)"
              " VALUES (?, ?, ?, ?, ?, ?)", (tg, "u%d" % i, panel.now(), status, plan, ends))


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


for name in ("action", "redirect", "send"):
    setattr(Rec, name, getattr(admin.Admin, name))
Rec.one = staticmethod(admin.Admin.one)


def act(rest, **form):
    r = Rec()
    r.action(rest, {k: [v] for k, v in form.items()})
    return urllib.parse.unquote(r.sent.get("Location", ""))


print("who gets it")
aud = lambda t: admin.broadcast_audience(t)
check("everyone with a Telegram, and a count of those without",
      len(aud("all")[0]) == 4 and aud("all")[1] == 2)
check("the active", len(aud("active")[0]) == 2 and aud("active")[1] == 1)
check("those whose period ends within 3 days", len(aud("expiring3")[0]) == 1)
check("the expired, and those with no plan",
      len(aud("expired")[0]) == 1 and len(aud("noplan")[0]) == 1)
check("a plan's customers", len(aud("plan:1")[0]) == 2)
card = admin.broadcast_card("p")
check("the bot page shows each choice with its count",
      "همهٔ مشتری‌ها — 4 نفر (2 نفر دیگر تلگرام ندارند)" in card
      and "مشتری‌های پلن «ماهانه»" in card)

print("sending")
check("not without a bot", "!" in act("broadcast-send", text="سلام", target="all"))
store.run("INSERT INTO api_tokens (name, token_hash, scope, webhook_url, webhook_secret,"
          " created_at) VALUES ('b', 'h', 'admin', 'http://127.0.0.1:1/', 'w', ?)",
          (panel.now(),))
check("not with no text", "!" in act("broadcast-send", text="  ", target="all"))
where = act("broadcast-send", text="تعطیلات: پشتیبانی تا شنبه جواب نمی‌دهد", target="active")
rows = store.q("SELECT * FROM webhook_outbox WHERE event = 'broadcast'")
check("one message to the bot per customer with a Telegram",
      len(rows) == 2 and "2 نفر" in where, where)
ev = json.loads(rows[0]["payload"])
check("  each for that customer, with the text", ev["telegram_id"] in (101, 102)
      and "تعطیلات" in ev["data"]["text"])
store.run("UPDATE webhook_outbox SET delivered_at = ? WHERE id = ?", (panel.now(), rows[0]["id"]))
check("the page says how many reached the bot", "1 از 2" in admin.broadcast_card("p"))

print("the bot")


class FakeTelegram:
    def __init__(self):
        self.out = []

    def send(self, chat, text, markup=None):
        self.out.append((chat, text))


tg = FakeTelegram()
bot = botmod.Bot(botmod.settings({"BOT_TOKEN": "t", "API_URL": "x", "API_KEY": "k"}),
                 telegram=tg)
slept = []
botmod.time.sleep = lambda s: slept.append(s)
bot.on_event(dict(ev, id=1))
check("passes it on to that customer, pausing between them",
      tg.out == [(ev["telegram_id"], ev["data"]["text"])] and slept)

shutil.rmtree(tmp, ignore_errors=True)
print()
if fails:
    print("%d FAILED: %s" % (len(fails), "; ".join(fails)))
    sys.exit(1)
print("all checks passed")
