import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from pinuke.telemetry import KEYS, MeterStream, load_calibration, meter_values


class TelemetryTests(unittest.TestCase):
    def test_periodic_identity_restores_session_and_renews_metering(self):
        calls = []
        refreshed = threading.Event()
        class Amp:
            def __init__(self, **kwargs):
                self.online = False
                self.metering = False
                self.info_count = 0
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def get_info(self):
                calls.append("info")
                self.online = self.metering = False
                self.info_count += 1
                return {"firmware": "V1.3"}
            def go_online(self):
                calls.append("online")
                self.online = True
            def get_gain(self): return {}
            def get_amp_mode(self): return "DUAL"
            def meter_heartbeat(self, rate):
                calls.append("heartbeat")
                self.metering = self.online
            def poll(self, timeout_s):
                time.sleep(.01)
                if self.metering:
                    if self.info_count >= 4: refreshed.set()
                    return [{"addr": "/meter", "typetags": "ffff", "args": [.1, .2, .3, .4]}]
                return []
        stream = MeterStream(threading.Lock(), enabled=True, selector=lambda: {"path": "test"}, client=Amp, identity_interval=.04)
        try:
            stream.snapshot(touch=True)
            self.assertTrue(refreshed.wait(2), "meters did not survive three periodic identity refreshes")
            self.assertEqual(stream.snapshot()["status"], "live")
            self.assertTrue(stream.availability()["available"])
            identity_indices = [i for i, value in enumerate(calls) if value == "info"]
            for i in identity_indices[1:]:
                self.assertEqual(calls[i:i + 3], ["info", "online", "heartbeat"])
        finally:
            stream.close()

    def test_malformed_nonfinite_negative_reports_are_not_levels(self):
        valid = {"addr": "/meter", "typetags": "ffff", "args": [.1, .2, .3, .4]}
        self.assertEqual(meter_values(valid), dict(zip(KEYS, valid["args"])))
        for args in ([1, 2, 3], [0, 0, 0, float("nan")], [1, 2, 3, -1], [1, 2, 3, True]):
            self.assertIsNone(meter_values({**valid, "args": args}))
        self.assertIsNone(meter_values({**valid, "addr": "/protect"}))

    def test_explicit_verified_identity_bound_calibration(self):
        value = {"verified": True, "serial": "test", "firmware": "V1.3", "evidence": "fixture only",
                 "reference_amplitude": dict.fromkeys(KEYS, 1), "output_vp_per_amplitude": dict.fromkeys(KEYS[2:], 100)}
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "cal.json"
            p.write_text(json.dumps(value))
            self.assertEqual(load_calibration(p), value)
            for update in ({"verified": False}, {"serial": ""}, {"reference_amplitude": dict.fromkeys(KEYS, 0)}):
                p.write_text(json.dumps({**value, **update}))
                with self.assertRaises(ValueError):
                    load_calibration(p)

    def test_viewer_lease_exclusive_handoff_and_no_setters(self):
        calls = []
        opened = threading.Event()
        sample = threading.Event()
        class Amp:
            def __init__(self, **kwargs):
                calls.append(("open", kwargs))
                self.online = False
            def __enter__(self): opened.set(); return self
            def __exit__(self, *_): opened.clear(); calls.append("close")
            def get_info(self):
                if not self.online:
                    raise TimeoutError("identity replies suspended until session starts")
                calls.append("info")
                return {"firmware": "V1.3"}
            def go_online(self):
                calls.append("online")
                self.online = True
            def get_gain(self): calls.append("gain"); return {}
            def get_amp_mode(self): calls.append("mode"); return "DUAL"
            def meter_heartbeat(self, rate): calls.append(("heartbeat", rate))
            def poll(self, timeout_s):
                time.sleep(.01)
                sample.set()
                yield {"addr": "/meter", "typetags": "ffff", "args": [.1, .2, .3, .4]}
        stream = MeterStream(threading.Lock(), enabled=True, selector=lambda: {"path": "test", "serial": "test"}, client=Amp)
        try:
            self.assertEqual(stream.snapshot()["status"], "idle")
            self.assertEqual(calls, [])  # Cached observation/startup does not open hardware.
            stream.snapshot(touch=True)
            self.assertTrue(sample.wait(2))
            deadline = time.monotonic() + 2
            while stream.snapshot()["status"] != "live" and time.monotonic() < deadline:
                time.sleep(.01)
            state = stream.snapshot()
            self.assertEqual(state["levels"]["output_b"], .4)
            self.assertIsNone(state["clip"])
            self.assertIsNone(state["limit"])
            self.assertEqual(calls[1:6], ["online", "info", "online", "gain", "mode"])
            with stream.exclusive():
                self.assertFalse(opened.is_set())
                self.assertEqual(stream.snapshot()["status"], "paused")
                self.assertIsNone(stream.snapshot()["levels"])
                # Nested concurrent transaction protection does not unpause early.
                self.assertTrue(stream._pause.is_set())
            self.assertFalse(stream._pause.is_set())
            self.assertTrue(all(c in ("info", "online", "gain", "mode", "close") or isinstance(c, tuple) for c in calls))
        finally:
            stream.close()
        self.assertFalse(opened.is_set())

    def test_stale_readings_cleared_disabled_stream_never_starts(self):
        stream = MeterStream(threading.Lock())
        self.assertEqual(stream.snapshot(touch=True)["status"], "disabled")
        self.assertIsNone(stream._thread)
        stream._state.update(status="live", levels=dict.fromkeys(KEYS, .1))
        stream._sample_at = time.monotonic() - 3
        self.assertEqual(stream.snapshot()["status"], "stale")
        self.assertIsNone(stream.snapshot()["levels"])

    def test_availability_without_meters_expires_and_lease_closes(self):
        calls = []
        class Amp:
            def __init__(self, **kwargs): calls.append("open")
            def __enter__(self): return self
            def __exit__(self, *_): calls.append("close")
            def get_info(self): calls.append("info"); return {"firmware": "V1.3"}
            def go_online(self): calls.append("online")
            def get_gain(self): calls.append("gain"); return {}
            def get_amp_mode(self): calls.append("mode"); return "DUAL"
            def poll(self, timeout_s): time.sleep(.01); return []
        stream = MeterStream(threading.Lock(), selector=lambda: {"path": "test", "serial": "test"}, client=Amp, identity_interval=.04)
        try:
            self.assertFalse(stream.availability()["available"])
            self.assertIsNone(stream._thread)
            stream.availability(touch=True)
            deadline = time.monotonic() + 2
            while not stream.availability()["available"] and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(stream.availability()["available"])
            self.assertEqual(stream.availability()["identity"]["serial"], "test")
            self.assertIsNone(stream.snapshot()["levels"])
            # Disable refresh briefly to prove confirmations cannot live forever.
            with stream.exclusive():
                stream._confirmed_at = time.monotonic() - 13
                self.assertFalse(stream.availability()["available"])
                self.assertEqual(stream.availability()["status"], "expired")
            with stream._guard:
                stream._availability_lease_until = time.monotonic() - 1
            deadline = time.monotonic() + 2
            while stream.availability()["status"] != "idle" and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertIn("close", calls)
            self.assertEqual(stream.availability()["status"], "idle")
            self.assertFalse(stream.availability()["available"])
        finally:
            stream.close()
        self.assertTrue(all(c in ("open", "close", "info", "online", "gain", "mode") for c in calls))

    def test_missing_meters_do_not_hide_responsive_amp_but_identity_failure_does(self):
        fail = threading.Event()
        class Amp:
            def __init__(self, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def get_info(self):
                if fail.is_set(): raise OSError("USB disconnected")
                return {"firmware": "V1.3"}
            def go_online(self): pass
            def get_gain(self): return {}
            def get_amp_mode(self): return "DUAL"
            def meter_heartbeat(self, rate): pass
            def poll(self, timeout_s): time.sleep(.01); return []
        stream = MeterStream(threading.Lock(), enabled=True, selector=lambda: {"path": "test"}, client=Amp, identity_interval=.04)
        try:
            stream.snapshot(touch=True)
            stream.availability(touch=True)
            deadline = time.monotonic() + 4
            while stream.snapshot()["status"] != "stale" and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(stream.snapshot()["status"], "stale")
            self.assertIsNone(stream.snapshot()["levels"])
            self.assertTrue(stream.availability()["available"])
            fail.set()
            deadline = time.monotonic() + 2
            while stream.availability()["available"] and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertFalse(stream.availability()["available"])
            self.assertEqual(stream.availability()["status"], "unavailable")
        finally:
            stream.close()

    def test_unopenable_device_is_unavailable_without_any_confirmation(self):
        def denied(): raise PermissionError("USB access denied")
        stream = MeterStream(threading.Lock(), selector=denied)
        try:
            stream.availability(touch=True)
            deadline = time.monotonic() + 1
            while stream.availability()["status"] == "unknown" and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertFalse(stream.availability()["available"])
            self.assertEqual(stream.availability()["status"], "unavailable")
        finally:
            stream.close()


if __name__ == "__main__":
    unittest.main()
