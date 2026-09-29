#!/usr/bin/env python3
"""A plan sold on some servers only.

What has to hold: with more than one server, each plan has a tick per
server, and any number may be ticked - none, or all, is every server; a
customer on a plan ticked for some is on those servers' allowlists and DoH
only, and on no other, so a cheaper plan for one server is no way into
another - there they are sent to the customer panel like anybody not let in;
they are shown those servers' DNS only; a plan whose servers are all gone is
on every one again rather than on none; when all its servers go out of one
server abroad, its customers go out of that one from any relay; a plan made
when a plan named a server abroad instead is shown ticked for the relays
that go out of it; and an admin who may not pick servers leaves them be.
"""
import importlib.machinery
import importlib.util
import os
import shutil
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
admin.log = panel.log = lambda *a: None

TR, DE, SG = "198.51.100.1", "198.51.100.2", "198.51.100.3"     # relays
MAIN, NODE = "203.0.113.1", "203.0.113.9"                         # servers abroad
tmp = tempfile.mkdtemp()
db = os.path.join(tmp, "panel.db")
store = panel.Store(db)
admin.DB = db
admin.CFG = {"ADMIN_PATH": "p"}
admin.STORE = admin.Store(db)
admin.PANEL_ENV = os.path.join(tmp, "panel.env")
with open(admin.PANEL_ENV, "w") as fh:
    fh.write("RELAY_IP=%s,%s,%s\n" % (TR, DE, SG))
admin.INSTALL_STATE = os.path.join(tmp, "install-state")
with open(admin.INSTALL_STATE, "w") as fh:
    fh.write("exit-ip %s\n" % MAIN)
admin.SYNC_ENV_HERE = os.path.join(tmp, "no-sync.env")
store.run("INSERT INTO templates (name, is_default, created_at) VALUES ('کامل', 1, ?)",
          (panel.now(),))


class Rec:
    def __init__(self):
        self._headers_buffer = []
        self.sent = {}
        self.written = b""
        self.wfile = self
        self.path = "/p/plans"
        self.headers = {}

    def write(self, b):
        self.written += b

    def send_response(self, code):
        self.sent["code"] = code

    def send_header(self, k, v):
        self.sent[k] = v

    def end_headers(self):
        pass


for name in ("action", "redirect", "send", "plans"):
    setattr(Rec, name, getattr(admin.Admin, name))
Rec.one = staticmethod(admin.Admin.one)


def act(rest, **form):
    admin.REQ.admin = None
    r = Rec()
    r.action(rest, {k: (v if isinstance(v, list) else [v]) for k, v in form.items()})
    return urllib.parse.unquote(r.sent.get("Location", ""))


def plan_form(**extra):
    base = dict(name="ترکیه", template_id="1", days="30", quota_gb="50", price="100000",
                devices="1")
    base.update(extra)
    return base


print("the plans page")
page = Rec().plans()
check("a tick for each server, any number of them", page.count("name='relay'") >= 3
      and "سرورها (DNS)" in page and "type='checkbox' name='relay' value='%s'" % DE in page)
loc = act("plan-save", **plan_form(relay=[TR]))
p_tr = store.one("SELECT * FROM plans WHERE name = 'ترکیه'")
check("a plan ticked for one server is sold on that one", "m=!" not in loc
      and p_tr["relays"] == TR, loc)
act("plan-save", **plan_form(name="اروپا", relay=[SG, DE]))
p_eu = store.one("SELECT * FROM plans WHERE name = 'اروپا'")
check("  or on two, in the order customers see them", p_eu["relays"] == "%s,%s" % (DE, SG))
act("plan-save", **plan_form(name="همه", relay=[TR, DE, SG]))
check("all of them ticked is every server",
      store.one("SELECT relays FROM plans WHERE name = 'همه'")["relays"] is None)
act("plan-save", **plan_form(name="بدون تیک"))
check("  so is none", store.one("SELECT relays FROM plans WHERE name = 'بدون تیک'")["relays"]
      is None)
check("a server that is not one is refused",
      "m=!" in act("plan-save", **plan_form(name="بد", relay=["192.0.2.50"])))
check("the page shows each plan's ticks",
      "value='%s' checked" % TR in Rec().plans())

print("customers")


def customer(name, plan, ip):
    store.run("INSERT INTO users (username, created_at, status, plan_id) VALUES (?, ?, 'active', ?)",
              (name, panel.now(), plan))
    uid = store.one("SELECT id FROM users WHERE username = ?", (name,))["id"]
    store.run("INSERT INTO ips (user_id, ip, added_at) VALUES (?, ?, ?)", (uid, ip, panel.now()))
    return uid


alice = customer("alice", p_tr["id"], "192.0.2.10")
bob = customer("bob", store.one("SELECT id FROM plans WHERE name = 'همه'")["id"], "192.0.2.11")
eve = customer("eve", p_eu["id"], "192.0.2.12")
relays = [TR, DE, SG]
check("the Turkey plan's customer is kept off the other servers",
      alice in panel.kept_off(store, DE, relays) and alice in panel.kept_off(store, SG, relays)
      and alice not in panel.kept_off(store, TR, relays))
check("  the two-server plan's off the third only",
      eve in panel.kept_off(store, TR, relays) and eve not in panel.kept_off(store, DE, relays)
      and eve not in panel.kept_off(store, SG, relays))
check("  and one on a plan for all, off none", all(bob not in panel.kept_off(store, r, relays)
                                               for r in relays))
check("a plan whose servers are all gone is on every one again",
      alice not in panel.kept_off(store, DE, [DE, SG]))
row = lambda uid: store.one("SELECT * FROM users WHERE id = ?", (uid,))
check("each is shown those servers' DNS only",
      panel.shown_relays(store, row(alice), relays) == [TR]
      and panel.shown_relays(store, row(eve), relays) == [DE, SG]
      and panel.shown_relays(store, row(bob), relays) == relays)
store.run("UPDATE users SET relays = ? WHERE id = ?", (SG, eve))
check("  within those, the ones ticked for the customer",
      panel.shown_relays(store, row(eve), relays) == [SG])
store.run("UPDATE users SET relays = ? WHERE id = ?", (TR, eve))
check("  but never a server the plan is not on", panel.shown_relays(store, row(eve), relays)
      == [DE, SG])
psrc = open(os.path.join(HERE, "..", "templates", "smartdns-panel"), encoding="utf-8").read()
sync_part = psrc[psrc.index('if self.path == "/sync":'):psrc.index('"extra_domains": extra')]
check("each relay's allowlist and DoH leave out those not on it",
      "off = kept_off(self.store, who, self.relays)" in sync_part
      and 'if v["uid"] not in off' in sync_part and 'if t["uid"] not in off' in sync_part)

print("the server abroad")
with open(admin.PANEL_ENV, "a") as fh:
    fh.write("NODE_IP=%s\n" % NODE)
store.set_setting("relay_exit:" + TR, NODE)
act("plan-save", id=str(p_tr["id"]), **plan_form(relay=[TR]))
check("all its servers out of one abroad: its customers go out of that one from any relay",
      store.one("SELECT exit FROM plans WHERE id = ?", (p_tr["id"],))["exit"] == NODE)
act("plan-save", id=str(p_eu["id"]), **plan_form(name="اروپا", relay=[TR, DE]))
check("  out of two: each relay's own",
      store.one("SELECT exit FROM plans WHERE id = ?", (p_eu["id"],))["exit"] is None)
store.set_setting("single:" + SG, "1")
act("plan-save", id=str(p_eu["id"]), **plan_form(name="اروپا", relay=[SG]))
check("  and a single server is its own way out",
      store.one("SELECT exit FROM plans WHERE id = ?", (p_eu["id"],))["exit"] is None)
store.run("DELETE FROM settings WHERE key = ?", ("single:" + SG,))

print("picking the server abroad")
page = Rec().plans()
check("with more than one abroad, a column to pick it, automatic first",
      "<th>سرور خارج</th>" in page and "<option value=''" in page and "خودکار" in page)
act("plan-save", id=str(p_eu["id"]), **plan_form(name="اروپا", relay=[TR, DE], exit=MAIN))
row = store.one("SELECT exit, exit_pick FROM plans WHERE id = ?", (p_eu["id"],))
check("a pick is kept, whatever its relays go out of", row["exit"] == MAIN
      and row["exit_pick"] == MAIN)
check("  and shown picked", "value='%s' selected" % MAIN in Rec().plans())
check("  only one of the servers abroad",
      "m=!" in act("plan-save", id=str(p_eu["id"]), **plan_form(name="اروپا", exit="192.0.2.9")))
act("plan-save", id=str(p_tr["id"]), **plan_form(relay=[TR]))
check("automatic follows the relay: Turkey's goes out of the node",
      store.one("SELECT exit FROM plans WHERE id = ?", (p_tr["id"],))["exit"] == NODE)
admin.Admin.action(Rec(), "relay-exit", {"ip": [TR], "exit": [MAIN]})
check("  and when that relay is moved to another, the plan goes with it",
      store.one("SELECT exit FROM plans WHERE id = ?", (p_tr["id"],))["exit"] == MAIN
      and store.one("SELECT exit FROM plans WHERE id = ?", (p_eu["id"],))["exit"] == MAIN)
store.set_setting("relay_exit:" + TR, NODE)
admin.refresh_auto_exits()

print("one relay, two servers abroad")
with open(admin.PANEL_ENV, "w") as fh:
    fh.write("RELAY_IP=%s\nNODE_IP=%s\n" % (TR, NODE))
page = Rec().plans()
check("no relay ticks, but the server abroad to pick",
      "name='relay'" not in page and "<th>سرور خارج</th>" in page)
act("plan-save", **plan_form(name="VIP ترکیه", exit=NODE))
act("plan-save", **plan_form(name="VIP آلمان", exit=MAIN))
vt = store.one("SELECT * FROM plans WHERE name = 'VIP ترکیه'")
vg = store.one("SELECT * FROM plans WHERE name = 'VIP آلمان'")
check("  a plan for each", vt["exit"] == NODE and vg["exit"] == MAIN and vt["relays"] is None)
act("plan-save", id=str(vt["id"]), **plan_form(name="VIP ترکیه", price="120000", exit=NODE))
check("  and saving one again keeps it", store.one("SELECT exit FROM plans WHERE id = ?",
                                                   (vt["id"],))["exit"] == NODE)
store.run("INSERT INTO users (username, created_at, status) VALUES ('tina', ?, 'active')",
          (panel.now(),))
tina = store.one("SELECT id FROM users WHERE username = 'tina'")["id"]
panel.apply_plan(store, tina, vt["id"])
check("  whose customer goes out of it", store.one("SELECT exit FROM users WHERE id = ?",
                                                   (tina,))["exit"] == NODE)

print("a plan from before")
store.run("INSERT INTO plans (name, template_id, days, quota_bytes, price, exit, created_at)"
          " VALUES ('قدیمی', 1, 30, 1, 1000, ?, ?)", (NODE, panel.now()))
old = dict(store.one("SELECT * FROM plans WHERE name = 'قدیمی'"))
check("one that named a server abroad shows it picked", admin.plan_exit_pick(old) == NODE
      and "value='%s' selected" % NODE in Rec().plans())
act("plan-save", id=str(old["id"]), **plan_form(name="قدیمی", exit=NODE))
check("  and keeps it when saved", store.one("SELECT exit, exit_pick FROM plans WHERE id = ?",
                                             (old["id"],))["exit"] == NODE)
admin.Admin.action(Rec(), "node-del", {"ip": [NODE]})
check("a node taken off: plans picked for it are on automatic again",
      store.one("SELECT exit_pick FROM plans WHERE id = ?", (vt["id"],))["exit_pick"] == ""
      and store.one("SELECT exit FROM plans WHERE id = ?", (vt["id"],))["exit"] is None)
with open(admin.PANEL_ENV, "w") as fh:
    fh.write("RELAY_IP=%s,%s,%s\n" % (TR, DE, SG))

print("an admin who may not pick servers")
store.run("INSERT INTO admins (username, password_hash, password_salt, perms, own_only,"
          " can_route, created_at) VALUES ('s', 'x', 'y', '[]', 1, 0, ?)", (panel.now(),))
seller_row = store.one("SELECT * FROM admins WHERE username = 's'")
admin.seller = lambda: seller_row
check("sees no ticks", "name='relay'" not in Rec().plans())
store.run("UPDATE plans SET owner_admin = ?, relays = ? WHERE id = ?",
          (seller_row["id"], DE, p_eu["id"]))
act("plan-save", id=str(p_eu["id"]), **plan_form(name="اروپا ۲"))
check("and saving a plan leaves its servers as they were",
      store.one("SELECT relays, name FROM plans WHERE id = ?", (p_eu["id"],))["relays"] == DE)

shutil.rmtree(tmp, ignore_errors=True)
print()
if fails:
    print("%d FAILED: %s" % (len(fails), "; ".join(fails)))
    sys.exit(1)
print("all checks passed")
