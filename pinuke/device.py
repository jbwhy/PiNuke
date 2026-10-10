"""Read the NU6000DSP DSP configuration.

The bundled protocol module is adapted from Ryan Mathewson's MIT-licensed
inuke-oscd client. HID GETs are transmitted with SET_REPORT, and /online
changes communication session state; neither writes a DSP parameter.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from ._inuke_protocol import INukeClient, PID, VID


class DeviceSelectionError(RuntimeError):
    """A unique NU6000DSP is unavailable."""


def scan() -> list[dict[str, Any]]:
    try:
        import hid
    except ImportError as exc:
        raise RuntimeError("hidapi is not installed; install PiNuke in a virtual environment") from exc

    return [
        {
            "path": os.fsdecode(item.get("path") or b""),
            "product": item.get("product_string") or "",
            "manufacturer": item.get("manufacturer_string") or "",
            "serial": item.get("serial_number") or "",
            "vendor_id": item.get("vendor_id"),
            "product_id": item.get("product_id"),
        }
        for item in hid.enumerate(VID, PID)
    ]


def require_amp() -> dict[str, Any]:
    matches = scan()
    if len(matches) != 1:
        raise DeviceSelectionError(
            f"Expected one iNuke USB device (1397:1101); found {len(matches)}. "
            "Connect the NU6000DSP directly to the Pi."
        )
    amp = matches[0]
    if amp["product"] and amp["product"] != "NU6000DSP":
        raise DeviceSelectionError(
            f"Found {amp['product']}, not NU6000DSP. PiNuke will not query this device."
        )
    return amp


def opencheck() -> dict[str, Any]:
    """Open and close the enumerated HID path without sending a report."""
    usb = require_amp()
    path = usb.get("path")
    if not path:
        raise DeviceSelectionError("hidapi returned no HID path for the iNuke")
    with INukeClient(path=path):
        pass
    return {"source": "live-nu6000dsp-usb", "usb": usb, "opened": True}


def probe() -> dict[str, Any]:
    """Open the amp and request identity only, without reading DSP parameters."""
    usb = require_amp()
    path = usb.get("path")
    if not path:
        raise DeviceSelectionError("hidapi returned no HID path for the iNuke")
    with INukeClient(path=path) as amp:
        amp.go_online()
        info = amp.get_info()
    return {"source": "live-nu6000dsp-usb", "usb": usb, "info": info}


def _status_steps(amp):
    """Prime identity replies, then retain the captured vendor handshake.

    Live testing rejected merely moving /online: info replied but gain did not.
    The vendor sequence includes /online after info. Keep that step and add one
    documented communication-start trigger before info, without timeout retries.
    This sequence passed bounded live checks on NU6000DSP firmware V1.3.
    """
    def session_identity():
        amp.go_online()
        return amp.get_info()

    return (
        ("info", session_identity),
        ("online", amp.go_online),
        ("gain", amp.get_gain),
        ("ampmode", amp.get_amp_mode),
    )


def status() -> dict[str, Any]:
    """Check the four handshake steps, retaining completed responses on failure."""
    usb = require_amp()
    path = usb.get("path")
    if not path:
        raise DeviceSelectionError("hidapi returned no HID path for the iNuke")
    result = {"source": "live-nu6000dsp-usb", "usb": usb, "complete": False, "responses": {}}
    with INukeClient(path=path) as amp:
        for key, request in _status_steps(amp):
            try:
                value = request()
            except Exception as exc:
                result.update(failed_request=f"/{key}", error_type=type(exc).__name__, error=str(exc))
                return result
            result["responses"][key] = "sent" if key == "online" else value
    result["complete"] = True
    return result


def readback() -> dict[str, Any]:
    """Return a full, live DSP snapshot or raise; never return placeholder values."""
    usb = require_amp()
    path = usb.get("path")
    if not path:
        raise DeviceSelectionError("hidapi returned no HID path for the iNuke")
    with INukeClient(path=path) as amp:
        return _read_connected(amp, usb)


def _read_connected(amp, usb) -> dict[str, Any]:
    header = {key: request() for key, request in _status_steps(amp)}
    info = header["info"]
    gain = header["gain"]
    mode = header["ampmode"]
    channels: dict[str, Any] = {}
    for channel in (1, 2):
        channels[str(channel)] = {
            "peq": [amp.get_peq(channel, band) for band in range(1, 9)],
            "crossover": {
                "high_pass": amp.get_xover_hp(channel),
                "low_pass": amp.get_xover_lp(channel),
                "gain_db": amp.get_xover_gain(channel),
            },
            "dynamic_eq": [
                {
                    "filter": amp.get_deq_filt(channel, band),
                    "compressor": amp.get_deq_comp(channel, band),
                    "timing": amp.get_deq_time(channel, band),
                }
                for band in (1, 2)
            ],
            "delay": amp.get_delay(channel),
            "limiter": amp.get_limiter(channel),
        }
    return {
        "source": "live-nu6000dsp-usb",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "usb": usb,
        "info": info,
        "mode": mode,
        "gain": gain,
        "channels": channels,
    }
