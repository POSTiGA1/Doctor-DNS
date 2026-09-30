#!/usr/bin/env python3
"""Searching the users page.

What has to hold: one box above the table finds customers by any part of
their name or username - in any case, and a name however its yeh and kaf
were typed, Arabic or Persian - or by their phone, Telegram id, number or one
of their IPs. The count says how many of how many; nothing found says so and
leaves the box to try again; a link shows everybody again. A seller's search
finds their own customers only, and a search cannot be turned into SQL.
"""
import importlib.machinery
import importlib.util
import os
import shutil
import sys
import tempfile

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

tmp = tempfile.mkdtemp()
db = os.path.join(tmp, "panel.db")
store = panel.Store(db)
admin.DB = db
admin.CFG = {"ADMIN_PATH": "p"}
admin.STORE = admin.Store(db)
admin.PANEL_ENV = os.path.join(tmp, "panel.env")
open(admin.PANEL_ENV, "w").write("RELAY_IP=198.51.100.1\n")
store.run("INSERT INTO admins (username, password_hash, password_salt, own_only, created_at)"
          " VALUES ('shop', 'x', 'x', 1, ?)", (panel.now(),))
shop = store.one("SELECT * FROM admins WHERE username = 'shop'")


def customer(username, name, tg=None, phone=None, ip=None, owner=None):
    store.run("INSERT INTO users (username, first_name, telegram_id, phone, created_at, status,"
              " owner_admin) VALUES (?, ?, ?, ?, ?, 'active', ?)",
              (username, name, tg, phone, panel.now(), owner))
    uid = store.one("SELECT id FROM users WHERE username = ?", (username,))["id"]
    if ip:
        store.run("INSERT INTO ips (user_id, ip, added_at) VALUES (?, ?, ?)",
                  (uid, ip, panel.now()))
    return uid


ali = customer("ali_gamer", "علی رضایی", tg=111222333, ip="192.0.2.10")
sara = customer("Sara.K", "سارا کریمی", phone="09121234567", ip="192.0.2.20")
yas = customer("yas", "ياسمن كاظمي")                 # typed with an Arabic keyboard
shops = customer("shop_one", "علی فروشنده", owner=shop["id"])


class Rec:
    def __init__(self, path):
        self.path = path


def page(q=None, as_seller=False):
    admin.REQ.admin = shop if as_seller else None
    r = Rec("/p/users" + ("?q=" + __import__("urllib.parse").parse.quote(q) if q else ""))
    try:
        return admin.Admin.users(r)
    finally:
        admin.REQ.admin = None


def found(q, as_seller=False):
    extra, args = admin.mine() if not as_seller else (" AND u.owner_admin = ?", (shop["id"],))
    find, fargs = admin.user_search(q)
    return {r["id"] for r in store.q("SELECT u.id FROM users u WHERE 1 = 1" + extra + find,
                                     tuple(args) + fargs)}


print("by name and username")
check("part of a username", found("gamer") == {ali})
check("  in any case", found("sara.k") == {sara} and found("SARA") == {sara})
check("part of a name", found("رضایی") == {ali} and found("علی") == {ali, shops})
check("a name typed with an Arabic keyboard, found typed with a Persian one",
      found("یاسمن") == {yas} and found("کاظمی") == {yas})
check("  and the other way round", found("علي") == {ali, shops})

print("by the rest")
check("a phone", found("0912123") == {sara})
check("a Telegram id, whole", found("111222333") == {ali} and found("111") == set())
check("a number", found("#%d" % sara) == {sara})
check("an IP, or part of one", found("192.0.2.10") == {ali} and found("192.0.2") == {ali, sara})

print("nothing that is not asked")
check("a % or _ is a letter, not a wildcard", found("%") == set() and found("_") == {ali, shops})
check("a quote is only a quote", found("' OR 1=1 --") == set())

print("the page")
html = page()
check("a box above the table, empty", "name='q' value=''" in html and "کاربران (4)" in html)
html = page("علی")
check("the count says how many of how many", "کاربران (2 از 4)" in html, html[:200])
check("  the rows are theirs", "ali_gamer" in html and "shop_one" in html and "Sara.K" not in html)
check("  the box keeps what was searched, with a link to everybody",
      "value='علی'" in html and "href='/p/users'>همه</a>" in html)
html = page("nobody-at-all")
check("nothing found says so, and the box is still there",
      "کسی با «nobody-at-all» پیدا نشد" in html and "name='q'" in html)
html = page("علی", as_seller=True)
check("a seller's search finds their own only",
      "shop_one" in html and "ali_gamer" not in html and "کاربران (1 از 1)" in html)

store.db.close()
admin.STORE.db.close()
shutil.rmtree(tmp, ignore_errors=True)
print()
if fails:
    print("%d failed" % len(fails))
    sys.exit(1)
print("all passed")
