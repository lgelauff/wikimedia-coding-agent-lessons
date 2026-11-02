#!/usr/bin/env python3
"""machine_check.py — what do memory, disk and the connection look like before a big job?

Agents run this before a big Mac-side transfer, before a heavy local run, and every ~30 minutes
inside long loops. See agent-tooling/playbooks/machine-check.md. Stdlib only; macOS first, and it
degrades to "unknown" elsewhere instead of failing.

  machine_check.py                           # report: one line per item
  machine_check.py --gate big-transfer       # also decide: >500 MB through the Mac
  machine_check.py --gate heavy-local        #   local job >2 GB RAM or long CPU
  machine_check.py --gate light              #   everything else (never stops)
      [--json] [--caution-swap-pct 85] [--stop-swap-pct 90] [--min-free-disk-gib 15]
      [--metered-file FILE]                  # default ~/agent/state/metered-networks.txt

Items
  memory      swap used % (sysctl vm.swapusage), pressure level, free RAM (vm_stat, free + inactive
              + speculative pages). Linux: /proc/meminfo.
  disk        free GiB on the home volume.
  connection  metered / unmetered / unknown, with the evidence. Metered if ANY of: the default
              gateway is in 172.20.10.0/28 (iPhone Personal Hotspot); the primary interface is an
              "iPhone USB" or Bluetooth PAN port; the Wi-Fi SSID is a line in the metered file;
              the primary interface is flagged expensive/constrained (Low Data Mode) in
              `scutil --nwi`. Unmetered needs positive evidence (wired, or a readable SSID that is
              not listed). Anything else is unknown. MAC addresses, IPs and SSIDs are never printed.

Exit (gate or not): 0 ok, 1 caution, 2 stop — stop and ask Lodewijk in chat.
  big-transfer  2 if connection is metered or unknown;       1 if swap > caution
  heavy-local   2 if swap > stop or free disk < minimum;     1 if swap > caution
  light         never 2;                                     1 if swap > caution
  (no gate)     as heavy-local, connection not considered.
"""
import argparse
import ipaddress
import json
import pathlib
import re
import shutil
import subprocess
import sys

HOTSPOT_NET = ipaddress.ip_network("172.20.10.0/28")
PAN_PORT = re.compile(r"iphone usb|bluetooth.?pan", re.I)
DEFAULT_METERED = pathlib.Path.home() / "agent" / "state" / "metered-networks.txt"
GIB = 1024 ** 3
PRESSURE = {1: "normal", 2: "warn", 4: "critical"}
KINDS = ("big-transfer", "heavy-local", "light")


class System:
    """The only place that touches the machine; tests replace it."""

    def __init__(self, home=None, metered_file=DEFAULT_METERED):
        self.home = pathlib.Path(home) if home else pathlib.Path.home()
        self.metered_file = pathlib.Path(metered_file)

    def run(self, argv, timeout=5):
        """stdout of a command, or None if it is missing, fails or times out."""
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            return None
        return r.stdout if r.returncode == 0 else None

    def read(self, path):
        try:
            return pathlib.Path(path).read_text()
        except (OSError, UnicodeError):
            return None

    def free_disk_bytes(self):
        try:
            return shutil.disk_usage(self.home).free
        except OSError:
            return None


# -- memory ------------------------------------------------------------------------------------
def _mib(text):
    n, unit = float(text[:-1]), text[-1].upper()
    return n * {"K": 1 / 1024, "M": 1, "G": 1024}.get(unit, 1)


def parse_swapusage(out):
    """'total = 10240.00M  used = 8772.31M  free = ...' -> (used_pct, used_gib, total_gib) or None."""
    m = re.search(r"total = ([\d.]+[KMG]).*?used = ([\d.]+[KMG])", out or "")
    if not m:
        return None
    total, used = _mib(m.group(1)), _mib(m.group(2))
    pct = 100.0 * used / total if total else 0.0  # no swap configured: nothing to be full
    return pct, used / 1024, total / 1024


def parse_vm_stat_free(out):
    """Free + inactive + speculative pages in GiB (what the OS can hand out without swapping)."""
    ps = re.search(r"page size of (\d+) bytes", out or "")
    if not ps:
        return None
    pages = 0
    for key in ("free", "inactive", "speculative"):
        m = re.search(rf"Pages {key}:\s+(\d+)", out)
        if not m:
            return None
        pages += int(m.group(1))
    return pages * int(ps.group(1)) / GIB


def parse_meminfo(text):
    """Linux: (swap_pct, swap_used_gib, swap_total_gib, available_gib); None parts if absent."""
    kb = {k: int(v) for k, v in re.findall(r"^(\w+):\s+(\d+) kB", text or "", re.M)}
    swap = None
    if "SwapTotal" in kb and "SwapFree" in kb:
        total, used = kb["SwapTotal"], kb["SwapTotal"] - kb["SwapFree"]
        swap = (100.0 * used / total if total else 0.0, used / 1024 ** 2, total / 1024 ** 2)
    free = kb["MemAvailable"] / 1024 ** 2 if "MemAvailable" in kb else None
    return swap, free


def check_memory(sysm):
    swap = free = pressure = None
    out = sysm.run(["sysctl", "-n", "vm.swapusage"])
    if out:
        swap = parse_swapusage(out)
        lvl = sysm.run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"])
        if lvl and lvl.strip().isdigit():
            pressure = PRESSURE.get(int(lvl), f"level {int(lvl)}")
        vm = sysm.run(["vm_stat"])
        free = parse_vm_stat_free(vm) if vm else None
    else:
        swap, free = parse_meminfo(sysm.read("/proc/meminfo"))
    return {"swap_pct": None if swap is None else round(swap[0], 1),
            "swap_used_gib": None if swap is None else round(swap[1], 2),
            "swap_total_gib": None if swap is None else round(swap[2], 2),
            "pressure": pressure,
            "free_ram_gib": None if free is None else round(free, 2)}


# -- disk --------------------------------------------------------------------------------------
def check_disk(sysm):
    b = sysm.free_disk_bytes()
    return {"free_gib": None if b is None else round(b / GIB, 1)}


# -- connection --------------------------------------------------------------------------------
def parse_default_route(out):
    gw = re.search(r"^\s*gateway:\s*(\S+)", out or "", re.M)
    ifc = re.search(r"^\s*interface:\s*(\S+)", out or "", re.M)
    return (gw.group(1) if gw else None), (ifc.group(1) if ifc else None)


def in_hotspot_net(gateway):
    try:
        return ipaddress.ip_address(gateway) in HOTSPOT_NET
    except ValueError:
        return False


def parse_ports(out):
    """networksetup -listnetworkserviceorder -> {device: hardware port name}."""
    return {dev: port for port, dev in re.findall(r"\(Hardware Port: (.+?), Device: (\w+)\)", out or "")}


def parse_ssid(out):
    """From `ipconfig getsummary` ('SSID : x') or `networksetup -getairportnetwork`."""
    m = re.search(r"^\s*SSID\s*:\s*(.+?)\s*$", out or "", re.M) or \
        re.search(r"Current Wi-Fi Network:\s*(.+?)\s*$", out or "", re.M)
    return m.group(1) if m else None


def parse_metered_list(text):
    return {l.strip() for l in (text or "").splitlines() if l.strip() and not l.lstrip().startswith("#")}


def nwi_expensive(out, device):
    """True if the `scutil --nwi` block of `device` carries an Expensive/Constrained flag [guess:
    format not documented; the word is looked for inside the device's own block only]."""
    blocks = re.split(r"(?m)^(?=\s*\w+ : flags)", out or "")
    for b in blocks:
        if re.match(rf"\s*{re.escape(device)} : flags", b) and re.search(r"expensive|constrained", b, re.I):
            return True
    return False


def check_connection(sysm):
    evidence, metered, unmetered = [], [], []
    route = sysm.run(["route", "-n", "get", "default"])
    gateway, device = parse_default_route(route)
    if route is None or device is None:
        return {"class": "unknown", "evidence": ["no default route readable (offline, or not macOS)"]}

    ports = parse_ports(sysm.run(["networksetup", "-listnetworkserviceorder"]))
    port = ports.get(device)

    if gateway and in_hotspot_net(gateway):
        metered.append("default gateway is in 172.20.10.0/28 (iPhone Personal Hotspot subnet)")
    if port and PAN_PORT.search(port):
        metered.append(f"primary interface is the port '{port}' (iPhone USB / Bluetooth PAN)")

    is_wifi = bool(port) and bool(re.search(r"wi-?fi|airport", port, re.I))
    ssid_note = None
    if is_wifi or port is None:
        ssid = parse_ssid(sysm.run(["ipconfig", "getsummary", device])) or \
            parse_ssid(sysm.run(["networksetup", "-getairportnetwork", device]))
        listed = parse_metered_list(sysm.read(sysm.metered_file))
        if ssid and ssid in listed:
            metered.append("Wi-Fi SSID is listed in metered-networks.txt")
        elif ssid:
            ssid_note = "Wi-Fi SSID readable and not in metered-networks.txt"
        elif is_wifi:
            ssid_note = "Wi-Fi SSID not readable, so the metered list could not be checked"

    if nwi_expensive(sysm.run(["scutil", "--nwi"]), device):
        metered.append("primary interface is flagged expensive/constrained (Low Data Mode)")

    if metered:
        return {"class": "metered", "evidence": metered}
    if port and not is_wifi and not PAN_PORT.search(port):
        unmetered.append(f"primary interface is a wired/other port ('{port}'), no metered signal")
    elif ssid_note and ssid_note.startswith("Wi-Fi SSID readable"):
        unmetered.append(ssid_note + "; gateway not a hotspot subnet")
    if unmetered:
        return {"class": "unmetered", "evidence": unmetered}
    return {"class": "unknown", "evidence": [ssid_note or "primary interface type could not be determined"]}


# -- verdict -----------------------------------------------------------------------------------
def decide(report, kind, caution_swap, stop_swap, min_disk):
    """(exit_code, reason). Unreadable values never stop a job on their own, except the
    connection for big-transfer, where 'unknown' is a stop by design."""
    swap = report["memory"]["swap_pct"]
    disk = report["disk"]["free_gib"]
    conn = report["connection"]["class"]
    if kind == "big-transfer" and conn != "unmetered":
        return 2, (f"connection is {conn}: ask Lodewijk before moving >500 MB through this Mac "
                   f"({'; '.join(report['connection']['evidence'])})")
    if kind in (None, "heavy-local"):
        if swap is not None and swap > stop_swap:
            return 2, f"swap is {swap:.1f}% (> {stop_swap:g}%): ask Lodewijk before a heavy local run"
        if disk is not None and disk < min_disk:
            return 2, f"only {disk:.1f} GiB free on the home volume (< {min_disk:g}): ask Lodewijk first"
    if swap is not None and swap > caution_swap:
        return 1, f"swap is {swap:.1f}% (> {caution_swap:g}%): keep it small, no new heavy work"
    return 0, "ok"


# -- output ------------------------------------------------------------------------------------
def fmt(v, unit="", nd=1):
    return "unknown" if v is None else f"{v:.{nd}f}{unit}"


def lines(report):
    m, d, c = report["memory"], report["disk"], report["connection"]
    out = [
        f"memory: swap {fmt(m['swap_pct'], '%')} ({fmt(m['swap_used_gib'])}/{fmt(m['swap_total_gib'])} GiB), "
        f"pressure {m['pressure'] or 'unknown'}, free RAM {fmt(m['free_ram_gib'])} GiB",
        f"disk: {fmt(d['free_gib'])} GiB free on the home volume",
        f"connection: {c['class']}: " + "; ".join(c["evidence"]),
    ]
    g = report.get("gate")
    if g:
        out.append(f"gate {g['kind']}: {('ok', 'CAUTION', 'STOP')[g['exit']]}: {g['reason']}")
    return out


def main(argv=None, sysm=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--gate", choices=KINDS)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--caution-swap-pct", type=float, default=85)
    ap.add_argument("--stop-swap-pct", type=float, default=90)
    ap.add_argument("--min-free-disk-gib", type=float, default=15)
    ap.add_argument("--metered-file", default=str(DEFAULT_METERED))
    a = ap.parse_args(argv)
    sysm = sysm or System(metered_file=a.metered_file)
    report = {"memory": check_memory(sysm), "disk": check_disk(sysm), "connection": check_connection(sysm)}
    code, reason = decide(report, a.gate, a.caution_swap_pct, a.stop_swap_pct, a.min_free_disk_gib)
    report["gate"] = {"kind": a.gate, "exit": code, "reason": reason} if a.gate else None
    if a.json:
        report["exit"] = code
        print(json.dumps(report, indent=2))
    else:
        print("\n".join(lines(report)))
        if not a.gate and code:
            print(f"{('ok', 'CAUTION', 'STOP')[code]}: {reason}")
    return code


if __name__ == "__main__":
    sys.exit(main())
