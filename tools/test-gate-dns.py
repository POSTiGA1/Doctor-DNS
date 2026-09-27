#!/usr/bin/env python3
"""The way back: the customer panel's name for an address not registered.

What has to hold: while the relay's door is closed, port 53 from an address
that is not registered goes to a resolver of its own, which knows the
customer panel's name and nothing else - no service, no hijack, no upstream
for the rest; the redirect and the resolver are set once, not rebuilt every
sync; and when the door opens, or there is no panel name to give, both go.
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


spec = importlib.util.spec_from_loader("sync", importlib.machinery.SourceFileLoader(
    "sync", os.path.join(HERE, "..", "templates", "smartdns-sync")))
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)
sync.log = lambda *a: None

tmp = tempfile.mkdtemp()
main = os.path.join(tmp, "smart-dns.conf")
with open(main, "w") as fh:
    fh.write("server=1.1.1.1\ncache-size=10000\ndomain-needed\nbogus-priv\nno-hosts\n"
             "bind-interfaces\nlisten-address=127.0.0.1,198.51.100.7\n"
             "address=/tiktok.com/198.51.100.7\n")
sync.HIJACK_CONF = main
sync.PROFILE_DIR = os.path.join(tmp, "prof")
sync.GATE_CONF = os.path.join(sync.PROFILE_DIR, "gate.conf")
sync.ENFORCE_FILE = os.path.join(tmp, "enforce.conf")
sync.GATE_UNIT_FILE = os.path.join(tmp, "gate.service")
open(sync.GATE_UNIT_FILE, "w").close()
sync.current_upstream = lambda: ["1.1.1.1", "9.9.9.9"]
sync.CFG = {"PANEL_DOMAIN": "users.example.com", "SELF_IP": "198.51.100.7"}


class R:
    def __init__(self, out="", rc=0):
        self.stdout, self.returncode, self.stderr = out, rc, ""


calls, chain, active = [], {"exists": False, "rules": []}, set()


def fake_nft(*args):
    calls.append(("nft",) + args)
    if args[:2] == ("list", "chain"):
        if not chain["exists"]:
            return R("", 1)
        return R("\n".join(chain["rules"]))
    if args[:2] == ("add", "chain"):
        chain["exists"] = True
    if args[:2] == ("flush", "chain"):
        chain["rules"] = []
    if args[:2] == ("add", "rule"):
        chain["rules"].append(" ".join(args[5:]))
    return R()


def fake_sh(*args):
    calls.append(args)
    if args[:2] == ("systemctl", "is-active"):
        return R("active\n" if args[2] in active else "inactive\n")
    if args[:2] == ("systemctl", "restart"):
        active.add(args[2])
    if args[:2] == ("systemctl", "stop"):
        active.discard(args[2])
    return R()


sync.nft, sync.sh = fake_nft, fake_sh

print("with the door open")
check("nothing is set up", sync.apply_gate_dns() is False
      and not os.path.exists(sync.GATE_CONF) and not chain["exists"])

print("with the door closed")
open(sync.ENFORCE_FILE, "w").close()
check("the way back is set up", sync.apply_gate_dns() is True)
conf = open(sync.GATE_CONF).read()
check("its resolver knows the customer panel's name, asked of the relay's upstream",
      "server=/users.example.com/1.1.1.1" in conf and "server=/users.example.com/9.9.9.9" in conf)
check("  and nothing else: no upstream for the rest, no service rule",
      "\nserver=1.1.1.1" not in conf and "tiktok" not in conf and "no-resolv" in conf)
check("  on its own port, listening where the main resolver does",
      "port=5299" in conf and "listen-address=127.0.0.1,198.51.100.7" in conf
      and "cache-size=10000" not in conf)
check("  and it runs", "smartdns-dns-gate" in active)
check("unregistered port 53 goes to it, both kinds",
      any("udp dport 53 redirect to :5299" in r for r in chain["rules"])
      and any("tcp dport 53 redirect to :5299" in r for r in chain["rules"])
      and all("saddr != @allowed" in r for r in chain["rules"]))
calls.clear()
sync.apply_gate_dns()
check("the next sync changes nothing", not any(c[:2] in (("nft", "flush"), ("nft", "add"))
                                                or c[:2] == ("systemctl", "restart")
                                                for c in calls), str(calls))

print("undone")
sync.CFG = {"PANEL_DOMAIN": ""}
sync.apply_gate_dns()
check("with no panel name, the redirect goes and the resolver stops",
      not chain["rules"] and "smartdns-dns-gate" not in active)
sync.CFG = {"PANEL_DOMAIN": "users.example.com"}
sync.apply_gate_dns()
os.remove(sync.ENFORCE_FILE)
sync.apply_gate_dns()
check("with the door open again, the same", not chain["rules"]
      and "smartdns-dns-gate" not in active)

print("the installer")
logic = open(os.path.join(HERE, "installer-logic.sh"), encoding="utf-8").read()
check("carries the unit, and takes it away on uninstall",
      "install_payload DNS_GATE_UNIT /etc/systemd/system/smartdns-dns-gate.service" in logic
      and "systemctl disable --now smartdns-dns-gate.service" in logic
      and "nft delete chain inet smartdns gatedns" in logic)
unit = open(os.path.join(HERE, "..", "templates", "smartdns-dns-gate.service"),
            encoding="utf-8").read()
check("  a unit that reads its own file and nothing else",
      "--conf-file=/etc/smartdns-profiles/gate.conf" in unit and "conf-dir" not in unit)

shutil.rmtree(tmp, ignore_errors=True)
print()
if fails:
    print("%d FAILED: %s" % (len(fails), "; ".join(fails)))
    sys.exit(1)
print("all checks passed")
