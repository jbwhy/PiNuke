"""OSC encode/decode + typed HID client for the iNuke DSP USB protocol.

Adapted from Ryan Mathewson's inuke-oscd, commit
21cacc5d77c29e0d9ba5f261c6baa8d34cf169ac, under the MIT license.
See ../UPSTREAM_LICENSE and https://github.com/RyanMathewson/inuke-oscd .

See docs/PROTOCOL_NOTES.md for the full protocol writeup this implements:
  - Device: VID 0x1397, PID 0x1101 (vendor-defined HID)
  - Host->device: HID SET_REPORT control transfer, ReportID 0, 63-byte report
  - Device->host: HID Input report on endpoint 0x81, 63-byte report
  - Report payload: 1-byte length N, then N bytes of a binary OSC 1.0 message,
    then don't-care padding.
  - A "GET" is the bare address with an empty ("," only) type tag string;
    the device replies on the same address with real args.

`INukeClient` takes an optional `transport` for testing -- anything with
.write(bytes), .read(length, timeout_ms=...) -> bytes|None, and .close() --
and opens a real hidapi device.device() by default.
"""
from __future__ import annotations

import os
import struct
import time
from typing import Any, Callable, Iterable, Iterator, Optional

VID = 0x1397
PID = 0x1101
REPORT_LEN = 63
DEFAULT_TIMEOUT_S = 2.0

# Minimum gap enforced between any two outgoing messages (GET or SET). A
# burst of unpaced SETs (e.g. writing all 8 PEQ bands back-to-back) was
# observed to silently drop some writes on real hardware -- the device
# accepted the USB transfers but didn't apply every one. This wasn't
# something the existing GET-only sequential flows (naturally paced by
# round-trip latency) ever hit. The real safe minimum was not isolated
# precisely (later bursts happened against a device already in a degraded
# state from the first one), so this is a conservative guess, not a
# confirmed device spec -- see docs/PROTOCOL_NOTES.md.
MIN_SEND_INTERVAL_S = 0.075


class DeviceTimeoutError(TimeoutError):
    pass


class DeviceNotFoundError(RuntimeError):
    pass


def _pad4(b: bytes) -> bytes:
    pad = (4 - len(b) % 4) % 4
    if pad == 0:
        pad = 4  # OSC always NUL-terminates, even if already aligned
    return b + b"\x00" * pad


def osc_encode(address: str, typetags: str = "", args: Iterable[Any] = ()) -> bytes:
    out = _pad4(address.encode("ascii"))
    out += _pad4(("," + typetags).encode("ascii"))
    for t, a in zip(typetags, args):
        if t == "f":
            out += struct.pack(">f", a)
        elif t == "i":
            out += struct.pack(">i", int(a))
        elif t == "s":
            out += _pad4(str(a).encode("ascii"))
        else:
            raise ValueError(f"unsupported typetag {t!r}")
    return out


def osc_decode(msg: bytes) -> Optional[dict]:
    if not msg or msg[0:1] != b"/":
        return None
    end = msg.find(b"\x00")
    if end == -1:
        return None
    addr = msg[:end].decode("ascii", "replace")

    pos = ((end + 4) // 4) * 4
    if pos >= len(msg) or msg[pos : pos + 1] != b",":
        return {"addr": addr, "typetags": None, "args": None}

    tend = msg.find(b"\x00", pos)
    typetags = msg[pos + 1 : tend].decode("ascii", "replace")
    pos = ((tend + 4) // 4) * 4

    args = []
    for t in typetags:
        if t in "fi":
            val = struct.unpack(">f" if t == "f" else ">i", msg[pos : pos + 4])[0]
            args.append(val)
            pos += 4
        elif t == "s":
            send = msg.find(b"\x00", pos)
            if send == -1:
                send = len(msg)
            args.append(msg[pos:send].decode("ascii", "replace"))
            pos = ((send + 4) // 4) * 4
        else:
            args.append(f"?{t}?")
    return {"addr": addr, "typetags": typetags, "args": args}


def _open_real_transport(path: Optional[str] = None):
    try:
        import hid
    except ImportError as err:
        raise RuntimeError(
            "the 'hidapi' package is required to talk to a real amp (pip install hidapi)"
        ) from err
    dev = hid.device()
    try:
        if path:
            dev.open_path(os.fsencode(path))
        else:
            dev.open(VID, PID)
    except OSError as err:
        target = f"HID path {path!r}" if path else f"VID={VID:#06x} PID={PID:#06x}"
        raise DeviceNotFoundError(f"could not open iNuke {target}: {err}") from err
    dev.set_nonblocking(True)
    return dev


class INukeClient:
    def __init__(
        self,
        transport=None,
        default_timeout_s: float = DEFAULT_TIMEOUT_S,
        min_send_interval_s: float = MIN_SEND_INTERVAL_S,
        path: Optional[str] = None,
    ):
        self._transport = transport if transport is not None else _open_real_transport(path)
        self._owns_transport = transport is None
        self.default_timeout_s = default_timeout_s
        self.min_send_interval_s = min_send_interval_s
        self._last_send_at = 0.0

    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> "INukeClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- raw framing ---
    def send(self, address: str, typetags: str = "", args: Iterable[Any] = ()) -> None:
        """Every send (from here or from get() below) is paced at least
        MIN_SEND_INTERVAL_S apart, so a burst of writes (e.g. all 8 PEQ
        bands) can't outrun what the device can reliably apply."""
        msg = osc_encode(address, typetags, args)
        if len(msg) > REPORT_LEN - 1:
            raise ValueError(f"message too long for one report ({len(msg)} bytes): {address}")
        report = bytes([len(msg)]) + msg
        report = report.ljust(REPORT_LEN, b"\x00")

        wait = self.min_send_interval_s - (time.time() - self._last_send_at)
        if wait > 0:
            time.sleep(wait)
        self._transport.write(b"\x00" + report)
        self._last_send_at = time.time()

    def poll(self, timeout_s: float = 1.0) -> Iterator[dict]:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            data = self._transport.read(REPORT_LEN, timeout_ms=100)
            if not data:
                continue
            data = bytes(data)
            n = data[0]
            decoded = osc_decode(data[1 : 1 + n])
            if decoded:
                yield decoded

    def get(
        self, address: str, typetags: str = "", args: Iterable[Any] = (), timeout_s: Optional[float] = None
    ) -> dict:
        if timeout_s is None:
            timeout_s = self.default_timeout_s
        self.send(address, typetags, args)
        for msg in self.poll(timeout_s):
            if msg["addr"] == address:
                return msg
        raise DeviceTimeoutError(f"no reply from {address} within {timeout_s}s")

    # --- session control ---
    def go_online(self) -> None:
        self.send("/online")

    def go_offline(self) -> None:
        self.send("/offline")

    def meter_heartbeat(self, rate_hz: float = 10.0) -> None:
        self.send("/meter", "f", [rate_hz])

    # --- device info / identity ---
    def get_info(self) -> dict:
        a = self.get("/info")["args"]
        return {"amp_name": a[0], "firmware": a[1], "unknown": a[2]}

    def set_amp_name(self, name: str) -> None:
        self.send("/ampname", "s", [name])

    # --- amp mode ---
    def get_amp_mode(self) -> str:
        return self.get("/ampmode")["args"][0]

    def set_amp_mode(self, mode: str) -> None:
        self.send("/ampmode", "s", [mode])

    def get_gain(self) -> dict:
        a = self.get("/gain")["args"]
        return {"gainA": a[0], "gainB": a[1], "muteA": a[2], "muteB": a[3]}

    # --- parametric EQ ---
    def get_peq(self, ch: int, band: int) -> dict:
        a = self.get(f"/channel/{ch}/peq/{band}")["args"]
        return {"type": a[0], "freq": a[1], "gain": a[2], "q": a[3]}

    def set_peq(self, ch: int, band: int, type_: str, freq: float, gain: float, q: float) -> None:
        self.send(f"/channel/{ch}/peq/{band}", "sfff", [type_, freq, gain, q])

    # --- crossover ---
    def get_xover_hp(self, ch: int) -> dict:
        a = self.get(f"/channel/{ch}/xover/hp")["args"]
        return {"type": a[0], "freq": a[1]}

    def set_xover_hp(self, ch: int, type_: str, freq: float) -> None:
        self.send(f"/channel/{ch}/xover/hp", "sf", [type_, freq])

    def get_xover_lp(self, ch: int) -> dict:
        a = self.get(f"/channel/{ch}/xover/lp")["args"]
        return {"type": a[0], "freq": a[1]}

    def set_xover_lp(self, ch: int, type_: str, freq: float) -> None:
        self.send(f"/channel/{ch}/xover/lp", "sf", [type_, freq])

    def get_xover_gain(self, ch: int) -> float:
        return self.get(f"/channel/{ch}/xover/gain")["args"][0]

    def set_xover_gain(self, ch: int, gain_db: float) -> None:
        self.send(f"/channel/{ch}/xover/gain", "f", [gain_db])

    # --- dynamic EQ ---
    def get_deq_comp(self, ch: int, band: int) -> dict:
        a = self.get(f"/channel/{ch}/deq/{band}/comp")["args"]
        return {"gain": a[0], "threshold": a[1], "ratio": a[2]}

    def set_deq_comp(self, ch: int, band: int, gain: float, threshold: float, ratio: float) -> None:
        self.send(f"/channel/{ch}/deq/{band}/comp", "fff", [gain, threshold, ratio])

    def get_deq_time(self, ch: int, band: int) -> dict:
        a = self.get(f"/channel/{ch}/deq/{band}/time")["args"]
        return {"attack": a[0], "release": a[1]}

    def set_deq_time(self, ch: int, band: int, attack: float, release: float) -> None:
        self.send(f"/channel/{ch}/deq/{band}/time", "ff", [attack, release])

    def get_deq_filt(self, ch: int, band: int) -> dict:
        a = self.get(f"/channel/{ch}/deq/{band}/filt")["args"]
        return {"type": a[0], "freq": a[1], "q": a[2]}

    def set_deq_filt(self, ch: int, band: int, type_: str, freq: float, q: float) -> None:
        self.send(f"/channel/{ch}/deq/{band}/filt", "sff", [type_, freq, q])

    # --- delay / limiter ---
    def get_delay(self, ch: int) -> dict:
        a = self.get(f"/channel/{ch}/delay")["args"]
        return {"time_ms": a[0], "phase_deg": a[1]}

    def set_delay(self, ch: int, time_ms: float, phase_deg: int) -> None:
        self.send(f"/channel/{ch}/delay", "fi", [time_ms, phase_deg])

    def get_limiter(self, ch: int) -> dict:
        a = self.get(f"/channel/{ch}/limiter")["args"]
        return {"threshold_vp": a[0], "release_ms": a[1], "hold_ms": a[2]}

    def set_limiter(self, ch: int, threshold_vp: float, release_ms: float, hold_ms: float) -> None:
        self.send(f"/channel/{ch}/limiter", "fff", [threshold_vp, release_ms, hold_ms])

    # --- presets ---
    def get_preset_name(self, slot: int) -> dict:
        a = self.get("/preset/name", "iis", [slot, 0, "DUMMY"])["args"]
        return {"slot": a[0], "mode_enum": a[1], "name": a[2]}

    def save_preset(self, slot: int, amp_mode_enum: int, name: str) -> None:
        self.send("/preset/save", "iis", [slot, amp_mode_enum, name])

    def load_preset(self, slot: int, name: str) -> None:
        self.send("/preset/load", "iis", [slot, 0, name])

    # --- full sweep (mirrors the vendor app's connect handshake) ---
    def full_sync(self, on_progress: Optional[Callable[[int, int, str], None]] = None) -> dict:
        steps: list[tuple[str, Callable[[], Any]]] = []
        steps.append(("info", self.get_info))
        steps.append(("online", self.go_online))
        steps.append(("gain", self.get_gain))
        steps.append(("ampmode", self.get_amp_mode))
        for ch in (1, 2):
            for b in range(1, 9):
                steps.append((f"peq{ch}.{b}", lambda ch=ch, b=b: self.get_peq(ch, b)))
            steps.append((f"xoverHp{ch}", lambda ch=ch: self.get_xover_hp(ch)))
            steps.append((f"xoverLp{ch}", lambda ch=ch: self.get_xover_lp(ch)))
            steps.append((f"xoverGain{ch}", lambda ch=ch: self.get_xover_gain(ch)))
            for b in (1, 2):
                steps.append((f"deqComp{ch}.{b}", lambda ch=ch, b=b: self.get_deq_comp(ch, b)))
                steps.append((f"deqTime{ch}.{b}", lambda ch=ch, b=b: self.get_deq_time(ch, b)))
                steps.append((f"deqFilt{ch}.{b}", lambda ch=ch, b=b: self.get_deq_filt(ch, b)))
            steps.append((f"delay{ch}", lambda ch=ch: self.get_delay(ch)))
            steps.append((f"limiter{ch}", lambda ch=ch: self.get_limiter(ch)))
        for slot in range(1, 21):
            steps.append((f"preset{slot}", lambda slot=slot: self.get_preset_name(slot)))

        results: dict[str, Any] = {}
        total = len(steps)
        for i, (key, fn) in enumerate(steps, 1):
            try:
                results[key] = fn()
            except Exception as err:  # noqa: BLE001 -- surfaced per-key, not fatal
                results[key] = {"error": str(err)}
            if on_progress:
                on_progress(i, total, key)
        return results
