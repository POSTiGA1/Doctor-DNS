#!/usr/bin/env python3
"""WireGuard with more than one relay, and in the operator's numbers.

What has to hold: a customer may have configs on every relay that has
WireGuard ready, the admin left on and serves them - Server 1, Server 2, as
beside their DNS - and chooses which when there is more than one, on their
page, in the bot and in the admin panel; a relay that is not one of those is
refused. A relay taken off the panel takes its configs, and the devices they
held, with it. The home page counts WireGuard online beside online, and the
morning report says how many configs there are and how many are connected;
typed addresses are counted apart from configs.
"""
import importlib.machinery
import importlib.util
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
fails = []


def check(label, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + label +
          ((" - " + detail) if detail and not cond else ""))
    if not cond:
        fails.append(label)


def load(path, mod):
    spec = importlib.util.spec_from_loader(
        mod, importlib.machinery.SourceFileLoader(mod, os.path.join(ROOT, path)))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


panel = load("templates/smartdns-panel", "panel")
sync = load("templates/smartdns-sync", "sync")
admin = load("templates/smartdns-admin", "admin")
bot = load("examples/telegram-bot/bot.py", "bot")
panel.log = sync.log = admin.log = lambda *a: None
bot.log = lambda *a: None
A, B = "198.51.100.1", "198.51.100.2"
relays = [A, B]

tmp = tempfile.mkdtemp()
db = os.path.join(tmp, "panel.db")
store = panel.Store(db)
now = panel.now()
store.run("INSERT INTO templates (name, is_default, created_at) VALUES ('کامل', 1, ?)", (now,))
store.run("INSERT INTO users (username, telegram_id, created_at, status, max_ips, expires_at)"
          " VALUES ('ali', 111, ?, 'active', 3, '2099-01-01T00:00:00+00:00')", (now,))
user = lambda: store.one("SELECT * FROM users WHERE id = 1")
store.set_setting("wg_on", "1")
for r in relays:
    store.set_setting("wg_pub:" + r, panel.wg_keypair()[1])

store.run("INSERT INTO users (username, telegram_id, created_at, status, max_ips)"
          " VALUES ('sara', 222, ?, 'active', 1)", (now,))
sara = lambda: store.one("SELECT * FROM users WHERE id = 2")

print("which server")
view = panel.wg_view(store, user(), relays)
check("both relays offered, named as beside the DNS",
      view["relays"] == [{"ip": A, "label": "سرور 1"}, {"ip": B, "label": "سرور 2"}]
      and view["room"] == 2)
r = panel.wg_customer_new(store, user(), relays, B)
check("a config on the server chosen", r.get("ok") and store.one(
    "SELECT relay FROM wg_devices WHERE id = ?", (r["device_id"],))["relay"] == B)
r = panel.wg_customer_new(store, user(), relays)
check("  none chosen: the first without one", r.get("ok") and store.one(
    "SELECT relay FROM wg_devices WHERE id = ?", (r["device_id"],))["relay"] == A)
r = panel.wg_customer_new(store, user(), relays)
check("  one for each relay and no more", r.get("error") == "wg_have"
      and panel.wg_view(store, user(), relays)["room"] == 0)
check("  a server that is not one of those: refused",
      panel.wg_customer_new(store, sara(), relays, "203.0.113.9").get("error") == "wg_bad_relay")
store.set_setting("wg_relays", '["%s"]' % A)
check("  nor one the admin left off",
      panel.wg_customer_new(store, sara(), relays, B).get("error") == "wg_bad_relay"
      and [x["ip"] for x in panel.wg_view(store, sara(), relays)["relays"]] == [A])
store.set_setting("wg_relays", "")
devices = panel.wg_view(store, user(), relays)["devices"]
check("each config says its server", {d["server"] for d in devices} == {"سرور 1", "سرور 2"})
psrc = open(os.path.join(ROOT, "templates", "smartdns-panel"), encoding="utf-8").read()
check("the customer's page and the bot pass the server chosen",
      'wg_customer_new(self.store, user, self.relays, body.get("relay"))' in psrc
      and psrc.count('body.get("relay")') >= 2)

print("the customer's page")
box = sync.wg_box({"wg": panel.wg_view(store, sara(), relays)})
check("two servers without a config: the customer picks",
      "<select name='relay'>" in box and "value='%s'" % B in box and "سرور 2" in box)
box = sync.wg_box({"wg": panel.wg_view(store, user(), relays)})
check("  one for each already: each named by its server, nothing more to get",
      " — سرور 1" in box and " — سرور 2" in box and "action='/wg-new'" not in box)
one = {"on": True, "self": True, "room": 1, "relays": [{"ip": A, "label": "سرور 1"}],
       "devices": []}
check("  one server: nothing to pick, the server sent along",
      "<select" not in sync.wg_box({"wg": one})
      and "name='relay' value='%s'" % A in sync.wg_box({"wg": one}))
ssrc = open(os.path.join(ROOT, "templates", "smartdns-sync"), encoding="utf-8").read()
check("  the choice reaches the panel", '"relay": form.get("relay") or ""' in ssrc)

print("the bot")
said, posted = [], []


class FakePanel:
    def call(self, method, path, body=None, idem=None):
        posted.append((method, path, body))
        return {"wg": panel.wg_view(store, sara(), relays)}


b = bot.Bot.__new__(bot.Bot)
b.panel, b.en = FakePanel(), False
b.say = lambda chat, text, markup=None: said.append((text, markup))
bot.Bot.show_wg(b, 5, {"id": 222})
text, markup = said[-1]
flat = [x for row in markup["inline_keyboard"] for x in row]
check("a button for each server without a config, its address in the button's data",
      any(x["callback_data"] == "wgnew:" + A for x in flat)
      and any(x["callback_data"] == "wgnew:" + B for x in flat))
bsrc = open(os.path.join(ROOT, "examples", "telegram-bot", "bot.py"), encoding="utf-8").read()
check("  and the server sent with the new config",
      '{"relay": arg} if arg else None' in bsrc)

print("the admin panel")
admin.DB = db
admin.CFG = {"ADMIN_PATH": "p"}
admin.STORE = admin.Store(db)
admin.PANEL_ENV = os.path.join(tmp, "panel.env")
open(admin.PANEL_ENV, "w").write("RELAY_IP=%s,%s\n" % (A, B))
admin.REQ.admin = None
check("a config on the relay chosen", not admin.wg_create(2, B).startswith("!")
      and store.one("SELECT count(*) c FROM wg_devices WHERE relay = ?", (B,))["c"] == 2)
check("  not a second on it", admin.wg_create(2, B).startswith("!"))
check("  a relay without it ready: refused", admin.wg_create(2, "203.0.113.9").startswith("!"))
page = admin.wg_page("/p/wg?u=2")
check("  the customer's page in the admin panel lets the admin pick",
      "<select name='relay'>" in page and "value='%s'" % B in page)
gone = [d["address"] for d in store.q("SELECT address FROM wg_devices WHERE relay = ?", (B,))]
admin.forget_server(B)
check("a relay taken off the panel: its configs gone, their rows with them, its key forgotten",
      store.one("SELECT count(*) c FROM wg_devices WHERE relay = ?", (B,))["c"] == 0
      and all(store.one("SELECT 1 FROM ips WHERE ip = ?", (a,)) is None for a in gone)
      and store.setting("wg_pub:" + B) == ""
      and store.one("SELECT count(*) c FROM wg_devices WHERE relay = ?", (A,))["c"] == 1)

print("the numbers")
store.run("UPDATE wg_devices SET last_handshake = ?",
          (datetime.now(timezone.utc).isoformat(timespec="seconds"),))
stats = panel.admin_stats(store)
check("the morning numbers: configs, and connected now",
      stats["wg_configs"] == 1 and stats["wg_online"] == 1)
report = panel.daily_report_text(stats)
check("  and the report says so", "وایرگارد: 1 کانفیگ، 1 آنلاین" in report)
check("  nothing about it where there are none",
      "وایرگارد" not in panel.daily_report_text(dict(stats, wg_configs=0, wg_online=0)))
asrc = open(os.path.join(ROOT, "templates", "smartdns-admin"), encoding="utf-8").read()
check("the home page: WireGuard online beside online, configs not counted as addresses",
      '"🛡 وایرگارد آنلاین"' in asrc and '" WHERE i.wg = 0" + extra, args)' in asrc)

store.db.close()
admin.STORE.db.close()
shutil.rmtree(tmp, ignore_errors=True)
print()
if fails:
    print("%d failed" % len(fails))
    sys.exit(1)
print("all passed")
