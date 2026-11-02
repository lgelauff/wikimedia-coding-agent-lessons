#!/usr/bin/env python3
"""Tests for scripts/machine_check.py — every signal is injected; nothing touches the real network."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "machine_check.py"
spec = importlib.util.spec_from_file_location("machine_check", SCRIPT)
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

PORTS = """(1) Wi-Fi
(Hardware Port: Wi-Fi, Device: en0)

(2) iPhone USB
(Hardware Port: iPhone USB, Device: en7)

(3) Bluetooth PAN
(Hardware Port: Bluetooth PAN, Device: en8)

(4) USB 10/100/1000 LAN
(Hardware Port: USB 10/100/1000 LAN, Device: en6)
"""


def swap(pct, total=10240.0):
    return f"total = {total:.2f}M  used = {total * pct / 100:.2f}M  free = {total * (100 - pct) / 100:.2f}M  (encrypted)\n"


VM_STAT = ("Mach Virtual Memory Statistics: (page size of 16384 bytes)\nPages free:        65536.\n"
           "Pages active:      1000.\nPages inactive:    32768.\nPages speculative: 32768.\n")  # 130k pages = 2 GiB


class Fake(M.System):
    """Canned command output keyed by argv[0] (+ argv[1] where needed). Unlisted commands fail (None)."""

    def __init__(self, tmp, *, swap_pct=40, pressure="1", device="en0", gateway="192.168.1.1",
                 ssid="HomeNet", listed=(), nwi="", free_disk_gib=100, ports=PORTS, mac=True,
                 route=True, meminfo=None):
        super().__init__(home=tmp, metered_file=Path(tmp) / "metered-networks.txt")
        self.free = free_disk_gib
        self.meminfo = meminfo
        if listed is not None:
            self.metered_file.write_text("# mine\n" + "\n".join(listed) + "\n")
        self.cmds = {}
        if mac:
            self.cmds[("sysctl", "-n", "vm.swapusage")] = swap(swap_pct)
            self.cmds[("sysctl", "-n", "kern.memorystatus_vm_pressure_level")] = pressure + "\n"
            self.cmds[("vm_stat",)] = VM_STAT
            if route:
                self.cmds[("route", "-n", "get", "default")] = \
                    f"   route to: default\n    gateway: {gateway}\n  interface: {device}\n"
            self.cmds[("networksetup", "-listnetworkserviceorder")] = ports
            if ssid is not None:
                self.cmds[("ipconfig", "getsummary", device)] = f"  BSSID : aa:bb:cc:dd:ee:ff\n  SSID : {ssid}\n"
            self.cmds[("scutil", "--nwi")] = nwi

    def run(self, argv, timeout=5):
        return self.cmds.get(tuple(argv))

    def read(self, path):
        if str(path) == "/proc/meminfo":
            return self.meminfo
        return super().read(path)

    def free_disk_bytes(self):
        return int(self.free * M.GIB)


class Base(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.tmp = self._t.name

    def fake(self, **kw):
        return Fake(self.tmp, **kw)

    def gate(self, kind, *args, **kw):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = M.main(["--gate", kind, *args], sysm=self.fake(**kw))
        return rc, out.getvalue()


class TestMemory(Base):
    def test_swap_pressure_free_ram(self):
        m = M.check_memory(self.fake(swap_pct=82, pressure="2"))
        self.assertAlmostEqual(m["swap_pct"], 82.0, places=1)
        self.assertEqual(m["pressure"], "warn")
        self.assertAlmostEqual(m["free_ram_gib"], 2.0, places=2)
        self.assertAlmostEqual(m["swap_total_gib"], 10.0, places=2)

    def test_no_swap_configured_is_zero_percent(self):
        self.assertEqual(M.parse_swapusage("total = 0.00M  used = 0.00M  free = 0.00M")[0], 0.0)

    def test_linux_meminfo_fallback(self):
        info = "MemAvailable:    4194304 kB\nSwapTotal:   2097152 kB\nSwapFree:   1048576 kB\n"
        m = M.check_memory(self.fake(mac=False, meminfo=info))
        self.assertAlmostEqual(m["swap_pct"], 50.0, places=1)
        self.assertAlmostEqual(m["free_ram_gib"], 4.0, places=2)
        self.assertIsNone(m["pressure"])

    def test_nothing_readable_is_unknown_not_a_crash(self):
        m = M.check_memory(self.fake(mac=False))
        self.assertIsNone(m["swap_pct"])
        self.assertIsNone(m["free_ram_gib"])


class TestConnection(Base):
    def cls(self, **kw):
        return M.check_connection(self.fake(**kw))

    def test_hotspot_gateway_is_metered(self):
        c = self.cls(gateway="172.20.10.1")
        self.assertEqual(c["class"], "metered")
        self.assertIn("172.20.10.0/28", c["evidence"][0])

    def test_hotspot_subnet_edges(self):
        self.assertTrue(M.in_hotspot_net("172.20.10.15"))
        self.assertFalse(M.in_hotspot_net("172.20.10.16"))
        self.assertFalse(M.in_hotspot_net("172.20.11.1"))
        self.assertFalse(M.in_hotspot_net("not-an-ip"))

    def test_iphone_usb_primary_is_metered(self):
        c = self.cls(device="en7", gateway="192.168.2.1", ssid=None)
        self.assertEqual(c["class"], "metered")
        self.assertIn("iPhone USB", c["evidence"][0])

    def test_bluetooth_pan_primary_is_metered(self):
        self.assertEqual(self.cls(device="en8", ssid=None)["class"], "metered")

    def test_listed_ssid_is_metered(self):
        c = self.cls(ssid="PhoneAP", listed=["PhoneAP", "Other"])
        self.assertEqual(c["class"], "metered")
        self.assertIn("metered-networks.txt", c["evidence"][0])

    def test_ssid_list_ignores_comments_blanks_and_is_exact(self):
        self.assertEqual(M.parse_metered_list("# c\n\n PhoneAP \nX\n"), {"PhoneAP", "X"})
        self.assertEqual(self.cls(ssid="phoneap", listed=["PhoneAP"])["class"], "unmetered")

    def test_unlisted_readable_ssid_is_unmetered(self):
        self.assertEqual(self.cls(ssid="HomeNet")["class"], "unmetered")

    def test_missing_metered_file_does_not_crash(self):
        self.assertEqual(self.cls(listed=None)["class"], "unmetered")

    def test_wired_primary_is_unmetered(self):
        c = self.cls(device="en6", ssid=None)
        self.assertEqual(c["class"], "unmetered")

    def test_unreadable_ssid_on_wifi_is_unknown(self):
        c = self.cls(ssid=None)
        self.assertEqual(c["class"], "unknown")
        self.assertIn("not readable", c["evidence"][0])

    def test_no_default_route_is_unknown(self):
        self.assertEqual(self.cls(route=False)["class"], "unknown")

    def test_not_macos_is_unknown(self):
        self.assertEqual(self.cls(mac=False)["class"], "unknown")

    def test_low_data_mode_flag_is_metered(self):
        nwi = "     en0 : flags      : 0x5 (IPv4,DNS,Expensive)\n           reach : 0x2\n"
        self.assertEqual(self.cls(nwi=nwi)["class"], "metered")

    def test_expensive_flag_on_another_interface_is_ignored(self):
        nwi = ("     en0 : flags      : 0x5 (IPv4,DNS)\n           reach : 0x2\n"
               "     en9 : flags      : 0x5 (IPv4,Expensive)\n")
        self.assertEqual(self.cls(nwi=nwi)["class"], "unmetered")

    def test_any_one_signal_wins(self):
        self.assertEqual(self.cls(gateway="172.20.10.1", ssid="HomeNet")["class"], "metered")

    def test_ssid_from_networksetup_fallback(self):
        f = self.fake(ssid=None)
        f.cmds[("networksetup", "-getairportnetwork", "en0")] = "Current Wi-Fi Network: HomeNet\n"
        self.assertEqual(M.check_connection(f)["class"], "unmetered")

    def test_output_never_contains_ips_macs_or_ssids(self):
        for kw in (dict(gateway="172.20.10.1"), dict(ssid="SecretNet", listed=["SecretNet"]), dict()):
            _, out = self.gate("big-transfer", **kw)
            self.assertNotRegex(out, r"\d+\.\d+\.\d+\.\d+(?!/)")
            self.assertNotRegex(out, r"(?i)[0-9a-f]{2}(:[0-9a-f]{2}){5}")
            self.assertNotIn("SecretNet", out)
            self.assertNotIn("HomeNet", out)


class TestGate(Base):
    def test_big_transfer_stops_on_metered(self):
        rc, out = self.gate("big-transfer", gateway="172.20.10.1")
        self.assertEqual(rc, 2)
        self.assertIn("STOP", out)
        self.assertIn("ask Lodewijk", out)

    def test_big_transfer_stops_on_unknown(self):
        self.assertEqual(self.gate("big-transfer", ssid=None)[0], 2)

    def test_big_transfer_ok_on_unmetered(self):
        self.assertEqual(self.gate("big-transfer")[0], 0)

    def test_big_transfer_ignores_swap_stop_but_cautions(self):
        self.assertEqual(self.gate("big-transfer", swap_pct=95)[0], 1)

    def test_heavy_local_stops_on_swap_over_90(self):
        rc, out = self.gate("heavy-local", swap_pct=91)
        self.assertEqual(rc, 2)
        self.assertIn("swap", out)

    def test_heavy_local_swap_exactly_at_threshold_is_not_stop(self):
        self.assertEqual(self.gate("heavy-local", swap_pct=90)[0], 1)

    def test_heavy_local_stops_on_low_disk(self):
        rc, out = self.gate("heavy-local", free_disk_gib=14.9)
        self.assertEqual(rc, 2)
        self.assertIn("GiB free", out)

    def test_heavy_local_ignores_connection(self):
        self.assertEqual(self.gate("heavy-local", gateway="172.20.10.1")[0], 0)

    def test_caution_over_85(self):
        self.assertEqual(self.gate("heavy-local", swap_pct=86)[0], 1)
        self.assertEqual(self.gate("heavy-local", swap_pct=84)[0], 0)

    def test_light_never_stops(self):
        rc, _ = self.gate("light", swap_pct=99, free_disk_gib=1, gateway="172.20.10.1")
        self.assertEqual(rc, 1)  # caution only
        self.assertEqual(self.gate("light")[0], 0)

    def test_thresholds_are_flags(self):
        self.assertEqual(self.gate("heavy-local", "--stop-swap-pct", "50", swap_pct=60)[0], 2)
        self.assertEqual(self.gate("heavy-local", "--min-free-disk-gib", "5", free_disk_gib=10)[0], 0)
        self.assertEqual(self.gate("heavy-local", "--caution-swap-pct", "30", swap_pct=40)[0], 1)

    def test_unreadable_memory_does_not_stop_heavy_local(self):
        self.assertEqual(self.gate("heavy-local", mac=False)[0], 0)


class TestOutput(Base):
    def test_one_line_per_item_without_gate(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = M.main([], sysm=self.fake())
        got = out.getvalue().splitlines()
        self.assertEqual(rc, 0)
        self.assertEqual([l.split(":")[0] for l in got], ["memory", "disk", "connection"])

    def test_no_gate_exit_follows_memory_and_disk_only(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(M.main([], sysm=self.fake(gateway="172.20.10.1")), 0)
            self.assertEqual(M.main([], sysm=self.fake(free_disk_gib=3)), 2)

    def test_json_shape_and_exit(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = M.main(["--gate", "big-transfer", "--json"], sysm=self.fake(gateway="172.20.10.1"))
        d = json.loads(out.getvalue())
        self.assertEqual((rc, d["exit"], d["gate"]["kind"]), (2, 2, "big-transfer"))
        self.assertEqual(d["connection"]["class"], "metered")
        self.assertEqual(set(d), {"memory", "disk", "connection", "gate", "exit"})

    def test_real_system_runs_and_exits_in_range(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIn(M.main(["--gate", "light"]), (0, 1))


if __name__ == "__main__":
    unittest.main()
