"""Viewer-leased meter stream, serialized with all DSP transactions.

Only the established handshake, identity GETs and optional /meter heartbeats
are sent. No DSP setters. Availability does not depend on meter freshness.
Uncalibrated amplitudes are never presented as clipping or limiter activity.
"""
from __future__ import annotations

import copy
import json
import math
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import device

KEYS = ("input_a", "input_b", "output_a", "output_b")


def load_calibration(path):
    if not path:
        return None
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("verified") is not True:
        raise ValueError("Meter calibration must be explicitly verified")
    for key in ("serial", "firmware", "evidence"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ValueError(f"Meter calibration requires {key}")
    for key, names in (("reference_amplitude", KEYS), ("output_vp_per_amplitude", KEYS[2:])):
        values = value.get(key)
        if not isinstance(values, dict) or set(values) != set(names):
            raise ValueError(f"Invalid calibration {key}")
        if any(type(n) not in (int, float) or not math.isfinite(n) or n <= 0 for n in values.values()):
            raise ValueError("Calibration values must be finite and positive")
    return value


def meter_values(message):
    args = message.get("args")
    if message.get("addr") != "/meter" or message.get("typetags") != "ffff":
        return None
    if not isinstance(args, list) or len(args) != 4:
        return None
    if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in args):
        return None
    return dict(zip(KEYS, args))


class MeterStream:
    def __init__(self, device_lock, enabled=False, calibration=None, selector=None, client=None, identity_interval=5.0):
        self.device_lock = device_lock
        self.enabled = enabled
        self.calibration = calibration
        self.selector = selector or device.require_amp
        self.client = client or device.INukeClient
        self._guard = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._pause_count = 0
        self._lease_until = 0.0
        self._availability_lease_until = 0.0
        self._confirmed_at = 0.0
        self.identity_interval = identity_interval
        self._availability = {"available": False, "status": "unknown", "identity": None}
        self._sample_at = 0.0
        self._state = {"enabled": enabled, "status": "idle" if enabled else "disabled",
                       "levels": None, "captured_at": None, "identity": None,
                       "calibration": None, "error": None, "clip": None, "limit": None}
        self._thread = None

    def snapshot(self, touch=False):
        with self._guard:
            if touch and self.enabled:
                self._lease_until = time.monotonic() + 8
                self._start_locked()
            result = copy.deepcopy(self._state)
            age = time.monotonic() - self._sample_at if self._sample_at else None
        result["age_ms"] = round(age * 1000) if age is not None else None
        if result["status"] == "live" and (age is None or age > 2):
            result.update(status="stale", levels=None)
        return result

    def _start_locked(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="pinuke-meters", daemon=True)
            self._thread.start()
        self._wake.set()

    def availability(self, touch=False):
        """Actual identity responses, independent of meter freshness.

        Viewer discovery is read-only and leased even if meters are disabled.
        Cached observation never starts a session. A confirmation expires after
        12 seconds; expired, absent or inaccessible devices are not available.
        """
        with self._guard:
            if touch:
                self._availability_lease_until = time.monotonic() + 8
                self._start_locked()
            result = copy.deepcopy(self._availability)
            age = time.monotonic() - self._confirmed_at if self._confirmed_at else None
        result["age_ms"] = round(age * 1000) if age is not None else None
        if result["available"] and (age is None or age > 12):
            result.update(available=False, status="expired")
        return result

    def _confirm(self, usb, info):
        identity = {"serial": usb.get("serial"), "firmware": info["firmware"]}
        cal = self.calibration
        if cal and any(cal[key] != identity[key] for key in ("serial", "firmware")):
            cal = None
        with self._guard:
            self._confirmed_at = time.monotonic()
            self._availability.update(available=True, status="available", identity=identity)
            self._state.update(identity=identity, calibration=cal)

    def _unavailable(self, status):
        with self._guard:
            self._availability.update(available=False, status=status)

    def _update(self, **values):
        with self._guard:
            self._state.update(values)

    def _wanted(self):
        with self._guard:
            return time.monotonic() < max(self._lease_until, self._availability_lease_until)

    def _meter_wanted(self):
        with self._guard:
            return self.enabled and time.monotonic() < self._lease_until

    @contextmanager
    def exclusive(self):
        # Set before waiting for USB lock: the stream exits within one bounded poll.
        with self._guard:
            self._pause_count += 1
            self._pause.set()
        try:
            with self.device_lock:
                self._update(status="paused" if self.enabled else "disabled", levels=None)
                yield
        finally:
            with self._guard:
                self._pause_count -= 1
                if not self._pause_count:
                    self._pause.clear()
            self._wake.set()

    def close(self):
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=10)
        self._unavailable("closed")

    def _run(self):
        while not self._stop.is_set():
            if not self._wanted() or self._pause.is_set():
                if not self._wanted():
                    self._unavailable("idle")
                self._wake.wait(.25)
                self._wake.clear()
                continue
            try:
                with self.device_lock:
                    if self._pause.is_set() or not self._wanted():
                        continue
                    self._update(status="connecting", levels=None, error=None, calibration=None)
                    usb = self.selector()
                    if not usb.get("path"):
                        raise device.DeviceSelectionError("No HID path for the amplifier")
                    with self.client(path=usb["path"]) as amp:
                        header = {}
                        for key, request in device._status_steps(amp):
                            if self._pause.is_set() or self._stop.is_set():
                                break
                            header[key] = request()
                        if len(header) != 4:
                            continue
                        self._confirm(usb, header["info"])
                        next_identity = time.monotonic() + self.identity_interval
                        heartbeat = 0.0
                        last_sample = time.monotonic()
                        while self._wanted() and not self._pause.is_set() and not self._stop.is_set():
                            now = time.monotonic()
                            # /info proves the device is responsive even when
                            # its meter reports are missing or malformed.
                            if now >= next_identity:
                                info = amp.get_info()
                                # Preserve the vendor post-info session step on
                                # periodic checks too, then renew requested meters.
                                amp.go_online()
                                self._confirm(usb, info)
                                next_identity = time.monotonic() + self.identity_interval
                                heartbeat = 0.0
                            if self._meter_wanted() and now >= heartbeat:
                                amp.meter_heartbeat(10.0)
                                heartbeat = now + 5
                            for report in amp.poll(timeout_s=.2):
                                levels = meter_values(report)
                                if levels is None or not self._meter_wanted():
                                    continue
                                last_sample = time.monotonic()
                                with self._guard:
                                    self._sample_at = last_sample
                                    self._state.update(status="live", levels=levels, error=None,
                                                       captured_at=datetime.now(timezone.utc).isoformat())
                            if self._meter_wanted() and time.monotonic() - last_sample > 3:
                                self._update(status="stale", levels=None)
                            elif not self._meter_wanted():
                                self._update(status="idle" if self.enabled else "disabled", levels=None)
                    self._update(status="paused" if self._pause.is_set() else "idle", levels=None)
                    if not self._pause.is_set():
                        self._unavailable("idle")
            except Exception as exc:
                self._unavailable("unavailable")
                self._update(status="unavailable", levels=None, calibration=None, error=str(exc))
                # Read-only reconnect, bounded rate; never retry a setter.
                self._stop.wait(5)
