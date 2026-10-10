import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from pinuke import device
from pinuke._inuke_protocol import DeviceTimeoutError, _open_real_transport, osc_decode, osc_encode
from pinuke.server import make_handler


class FakeAmp:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def go_online(self):
        self.calls.append("online")

    def get_info(self):
        self.calls.append("info")
        return {"amp_name": "Test", "firmware": "1.0", "unknown": 5}

    def get_amp_mode(self):
        self.calls.append("mode")
        return "STEREO"

    def get_gain(self):
        self.calls.append("gain")
        return {"gainA": 0.0, "gainB": 0.0, "muteA": 0, "muteB": 0}

    def get_peq(self, ch, band):
        self.calls.append(("peq", ch, band))
        return {"type": "OFF", "freq": 100.0, "gain": 0.0, "q": 1.0}

    def get_xover_hp(self, ch):
        self.calls.append(("hp", ch))
        return {"type": "OFF", "freq": 20.0}

    def get_xover_lp(self, ch):
        self.calls.append(("lp", ch))
        return {"type": "OFF", "freq": 20000.0}

    def get_xover_gain(self, ch):
        self.calls.append(("xover_gain", ch))
        return 0.0

    def get_deq_filt(self, ch, band):
        self.calls.append(("deq_filt", ch, band))
        return {"type": "OFF", "freq": 100.0, "q": 1.0}

    def get_deq_comp(self, ch, band):
        self.calls.append(("deq_comp", ch, band))
        return {"gain": 0.0, "threshold": -10.0, "ratio": 1.0}

    def get_deq_time(self, ch, band):
        self.calls.append(("deq_time", ch, band))
        return {"attack": 1.0, "release": 10.0}

    def get_delay(self, ch):
        self.calls.append(("delay", ch))
        return {"time_ms": 0.0, "phase_deg": 0}

    def get_limiter(self, ch):
        self.calls.append(("limiter", ch))
        return {"threshold_vp": 69.9, "release_ms": 100.0, "hold_ms": 50.0}


class ProtocolTests(unittest.TestCase):
    def test_scan_keeps_exact_hid_path(self):
        hid = MagicMock()
        hid.enumerate.return_value = [{"path": b"/dev/hidraw0", "vendor_id": 5015, "product_id": 4353}]
        with patch.dict("sys.modules", {"hid": hid}):
            result = device.scan()
        self.assertEqual(result[0]["path"], "/dev/hidraw0")

    def test_open_uses_enumerated_path(self):
        hid = MagicMock()
        with patch.dict("sys.modules", {"hid": hid}):
            _open_real_transport("/dev/hidraw0")
        hid.device.return_value.open_path.assert_called_once_with(b"/dev/hidraw0")
        hid.device.return_value.open.assert_not_called()

    def test_meter_request_matches_captured_wire_message(self):
        self.assertEqual(
            osc_encode("/meter", "f", [10.0]).hex(),
            "2f6d6574657200002c66000041200000",
        )
        self.assertEqual(osc_decode(osc_encode("/meter", "f", [10.0]))["args"], [10.0])

    def test_full_readback_has_no_dsp_setters(self):
        fake = FakeAmp()
        with patch.object(device, "require_amp", return_value={"product": "NU6000DSP", "path": "/dev/hidraw0"}), \
             patch.object(device, "INukeClient", return_value=fake):
            state = device.readback()
        self.assertEqual(state["source"], "live-nu6000dsp-usb")
        self.assertEqual(state["mode"], "STEREO")
        self.assertEqual(len(state["channels"]["1"]["peq"]), 8)
        self.assertEqual(len(state["channels"]["2"]["dynamic_eq"]), 2)
        self.assertEqual(fake.calls[:5], ["online", "info", "online", "gain", "mode"])
        self.assertEqual(sum(isinstance(call, tuple) and call[0] == "peq" for call in fake.calls), 16)

    def test_probe_requests_identity_only(self):
        fake = FakeAmp()
        with patch.object(device, "require_amp", return_value={"product": "", "path": "/dev/hidraw0"}), \
             patch.object(device, "INukeClient", return_value=fake):
            result = device.probe()
        self.assertEqual(result["info"]["amp_name"], "Test")
        self.assertEqual(fake.calls, ["online", "info"])

    def test_status_preserves_completed_responses_on_mode_timeout(self):
        fake = FakeAmp()

        def timeout():
            fake.calls.append("mode")
            raise DeviceTimeoutError("no reply from /ampmode within 2.0s")

        fake.get_amp_mode = timeout
        with patch.object(device, "require_amp", return_value={"product": "NU6000DSP", "path": "1-1.3:1.0"}), \
             patch.object(device, "INukeClient", return_value=fake):
            result = device.status()
        self.assertFalse(result["complete"])
        self.assertEqual(result["failed_request"], "/ampmode")
        self.assertEqual(result["error_type"], "DeviceTimeoutError")
        self.assertEqual(result["responses"]["info"]["amp_name"], "Test")
        self.assertEqual(result["responses"]["gain"]["gainA"], 0.0)
        self.assertEqual(fake.calls, ["online", "info", "online", "gain", "mode"])

    def test_each_reopened_read_primes_identity_and_preserves_vendor_sequence(self):
        class ReplySuspendedAmp(FakeAmp):
            def __enter__(self):
                self.online = False
                return self

            def go_online(self):
                super().go_online()
                self.online = True
                self.gain_ready = True

            def get_info(self):
                if not self.online:
                    raise DeviceTimeoutError("reply suspended until online")
                result = super().get_info()
                self.gain_ready = False
                return result

            def get_gain(self):
                if not self.gain_ready:
                    raise DeviceTimeoutError("fixture requires vendor post-info online")
                return super().get_gain()

        fake = ReplySuspendedAmp()
        with patch.object(device, "require_amp", return_value={"product": "NU6000DSP", "path": "test"}), \
             patch.object(device, "INukeClient", return_value=fake):
            first = device.readback()
            fake.calls.clear()
            second = device.readback()
        self.assertEqual(first["channels"], second["channels"])
        self.assertEqual(fake.calls[:5], ["online", "info", "online", "gain", "mode"])
        self.assertEqual(fake.calls.count("online"), 2)

    def test_identity_failure_is_not_retried_or_followed_by_dsp_reads(self):
        fake = FakeAmp()
        def fail():
            fake.calls.append("info")
            raise DeviceTimeoutError("no identity reply")
        fake.get_info = fail
        with patch.object(device, "require_amp", return_value={"product": "NU6000DSP", "path": "test"}), \
             patch.object(device, "INukeClient", return_value=fake):
            result = device.status()
        self.assertFalse(result["complete"])
        self.assertEqual(result["failed_request"], "/info")
        self.assertEqual(result["responses"], {})
        self.assertEqual(fake.calls, ["online", "info"])

    def test_opencheck_sends_no_reports(self):
        fake = FakeAmp()
        with patch.object(device, "require_amp", return_value={"product": "", "path": "/dev/hidraw0"}), \
             patch.object(device, "INukeClient", return_value=fake) as client:
            result = device.opencheck()
        self.assertTrue(result["opened"])
        client.assert_called_once_with(path="/dev/hidraw0")
        self.assertEqual(fake.calls, [])

    def test_wrong_model_is_rejected_before_open(self):
        with patch.object(device, "scan", return_value=[{"product": "NU3000DSP"}]):
            with self.assertRaises(device.DeviceSelectionError):
                device.require_amp()


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.reads = []

        def reader():
            self.reads.append(True)
            return {"source": "fake-live", "usb": {"product": "NU6000DSP", "serial": "test"}, "info": {}, "mode": "DUAL", "gain": {}, "channels": {}}

        handler = make_handler(reader=reader, scanner=lambda: [{"product": "NU6000DSP"}], public_origin="https://amp.example")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def fetch(self, path, method="GET", headers=None):
        with urlopen(Request(self.base + path, method=method, headers=headers or {}), timeout=3) as response:
            return json.load(response)

    def test_page_and_scan_do_not_open_hardware(self):
        self.assertEqual(self.fetch("/api/scan")["devices"][0]["product"], "NU6000DSP")
        self.assertIsNone(self.fetch("/api/state")["snapshot"])
        self.assertEqual(self.reads, [])

    def test_meter_stream_is_opt_in_and_cached_observation_does_not_open(self):
        self.assertEqual(self.fetch('/api/meters')['status'], 'disabled')
        self.assertEqual(self.fetch('/api/meter-state')['status'], 'disabled')
        self.assertFalse(self.fetch('/api/availability-state')['available'])
        self.assertIsNone(self.server.RequestHandlerClass.meters._thread)
        self.assertEqual(self.reads, [])
        with urlopen(self.base + '/graphs.js') as response:
            self.assertEqual(response.headers['X-Frame-Options'], 'SAMEORIGIN')
            self.assertEqual(response.headers['Content-Security-Policy'], "frame-ancestors 'self'")

    def test_readback_requires_explicit_post_and_arbitrary_write_endpoint_is_absent(self):
        result = self.fetch("/api/readback", method="POST")
        self.assertEqual(result["snapshot"]["source"], "fake-live")
        self.assertEqual(len(self.reads), 1)
        with self.assertRaises(HTTPError) as caught:
            self.fetch("/api/mode", method="POST")
        self.assertEqual(caught.exception.code, 404)

    def test_configured_https_origin_can_read_through_proxy(self):
        result = self.fetch("/api/readback", method="POST", headers={"Origin": "https://amp.example", "Host": "amp.example"})
        self.assertEqual(result["snapshot"]["source"], "fake-live")
        self.assertEqual(len(self.reads), 1)

    def test_foreign_origin_is_rejected_before_hardware_read(self):
        with self.assertRaises(HTTPError) as caught:
            self.fetch("/api/readback", method="POST", headers={"Origin": "https://elsewhere.example", "Host": "amp.example"})
        self.assertEqual(caught.exception.code, 403)
        self.assertEqual(self.reads, [])


if __name__ == "__main__":
    unittest.main()
