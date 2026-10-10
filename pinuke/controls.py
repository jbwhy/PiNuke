"""Allowlisted channel DSP edits with preflight, audit and verified readback.

Addresses/types and generous input bounds come from the pinned upstream client.
Bounds are application validation, not measured NU6000DSP hardware limits.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import device


def numeric(label, low, high):
    return {"label": label, "min": low, "max": high}


def choices(label, values):
    return {"label": label, "choices": values}


FREQ = numeric("Frequency (Hz)", 1, 20000)
GAIN = numeric("Gain (dB)", -24, 24)
Q = numeric("Q", .01, 20)
TIME = numeric("Time (ms)", 0, 2000)
XOVER = ["OFF"] + [f"{family}{slope}" for family in ("BUT", "BES", "LR") for slope in (6, 12, 18, 24, 48)]
SPECS = {
    "high_pass": {"label": "High pass", "fields": {"type": choices("Filter", XOVER), "freq": FREQ}},
    "low_pass": {"label": "Low pass", "fields": {"type": choices("Filter", XOVER), "freq": FREQ}},
    "gain_db": {"label": "Output gain", "fields": {"gain_db": GAIN}},
    "delay": {"label": "Delay & phase", "fields": {"time_ms": numeric("Delay (ms)", 0, 1000), "phase_deg": choices("Phase (degrees)", [0, 180])}},
    "limiter": {"label": "Peak limiter", "fields": {"threshold_vp": numeric("Threshold (V peak)", 0, 200), "release_ms": {**TIME, "label": "Release (ms)"}, "hold_ms": {**TIME, "label": "Hold (ms)"}}},
    "peq": {"label": "Parametric EQ", "bands": 8, "fields": {"type": choices("Filter", ["OFF", "PEQ", "LS6", "LS12", "HS6", "HS12"]), "freq": FREQ, "gain": GAIN, "q": Q}},
    "deq_filter": {"label": "Dynamic EQ filter", "bands": 2, "fields": {"type": choices("Filter", ["OFF", "BP", "LP6", "LP12", "HP6", "HP12"]), "freq": FREQ, "q": Q}},
    "deq_compressor": {"label": "Dynamic EQ dynamics", "bands": 2, "fields": {"gain": GAIN, "threshold": numeric("Threshold (dB)", -60, 0), "ratio": numeric("Ratio", 1, 20)}},
    "deq_timing": {"label": "Dynamic EQ timing", "bands": 2, "fields": {"attack": {**TIME, "label": "Attack (ms)"}, "release": {**TIME, "label": "Release (ms)"}}},
}


class EditValidationError(ValueError):
    pass


def validate_changes(changes):
    if not isinstance(changes, list) or not 1 <= len(changes) <= 44:
        raise EditValidationError("Provide between 1 and 44 changed DSP groups")
    seen = set()
    for change in changes:
        if not isinstance(change, dict):
            raise EditValidationError("Each change must be an object")
        block = change.get("block")
        if not isinstance(block, str) or block not in SPECS:
            raise EditValidationError("Unknown DSP control")
        spec = SPECS[block]
        keys = {"channel", "block", "value"} | ({"band"} if "bands" in spec else set())
        if set(change) != keys or type(change["channel"]) is not int or change["channel"] not in (1, 2):
            raise EditValidationError("Invalid channel or control fields")
        band = change.get("band")
        if "bands" in spec and (type(band) is not int or not 1 <= band <= spec["bands"]):
            raise EditValidationError("Invalid DSP band")
        key = (change["channel"], block, band)
        if key in seen:
            raise EditValidationError("A DSP group cannot occur twice")
        seen.add(key)
        value = change["value"]
        if not isinstance(value, dict) or set(value) != set(spec["fields"]):
            raise EditValidationError(f"Incomplete {spec['label']} values")
        for field, rule in spec["fields"].items():
            item = value[field]
            if "choices" in rule:
                if type(item) not in (str, int) or item not in rule["choices"]:
                    raise EditValidationError(f"Invalid {rule['label']}")
            elif type(item) not in (int, float) or not math.isfinite(item) or not rule["min"] <= item <= rule["max"]:
                raise EditValidationError(f"{rule['label']} must be between {rule['min']} and {rule['max']}")
    return copy.deepcopy(changes)


def dsp_state(snapshot):
    # Captured time and changing bus/path names do not represent DSP changes.
    return {"serial": snapshot["usb"].get("serial"), "product": snapshot["usb"].get("product"),
            "info": snapshot["info"], "mode": snapshot["mode"], "gain": snapshot["gain"], "channels": snapshot["channels"]}


def revision(snapshot):
    return hashlib.sha256(json.dumps(dsp_state(snapshot), sort_keys=True, allow_nan=False).encode()).hexdigest()


def equivalent(expected, actual):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and expected.keys() == actual.keys() and all(equivalent(v, actual[k]) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(expected) == len(actual) and all(equivalent(a, b) for a, b in zip(expected, actual))
    if type(expected) in (int, float) and type(actual) in (int, float):
        return math.isfinite(actual) and math.isclose(expected, actual, rel_tol=2e-6, abs_tol=1e-4)
    return expected == actual


def group_value(snapshot, change):
    ch = snapshot["channels"][str(change["channel"])]
    block = change["block"]
    if block in ("high_pass", "low_pass"):
        return ch["crossover"][block]
    if block == "gain_db":
        return {"gain_db": ch["crossover"][block]}
    if block == "peq":
        return ch[block][change["band"] - 1]
    if block.startswith("deq_"):
        part = {"deq_filter": "filter", "deq_compressor": "compressor", "deq_timing": "timing"}[block]
        return ch["dynamic_eq"][change["band"] - 1][part]
    return ch[block]


def put_value(snapshot, change):
    if change["block"] == "gain_db":
        snapshot["channels"][str(change["channel"])]["crossover"]["gain_db"] = change["value"]["gain_db"]
    else:
        target = group_value(snapshot, change)
        target.clear()
        target.update(change["value"])


def set_and_get(amp, change):
    ch, block, val = change["channel"], change["block"], change["value"]
    args = [val[key] for key in SPECS[block]["fields"]]
    suffix = {"high_pass": "xover_hp", "low_pass": "xover_lp", "gain_db": "xover_gain",
              "deq_filter": "deq_filt", "deq_compressor": "deq_comp", "deq_timing": "deq_time"}.get(block, block)
    prefix = [ch] + ([change["band"]] if "band" in change else [])
    getattr(amp, f"set_{suffix}")(*prefix, *args)
    value = getattr(amp, f"get_{suffix}")(*prefix)
    return {"gain_db": value} if block == "gain_db" else value


def _save_audit(path, record):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix(".tmp")
    try:
        with temp.open("x", encoding="utf-8") as file:
            os.chmod(temp, 0o600)
            json.dump(record, file, indent=2, allow_nan=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def apply_changes(before, changes, audit_dir=None):
    """Never retry writes or auto-restore. Failures can have partially applied DSP."""
    changes = validate_changes(changes)  # Before opening hardware.
    usb = device.require_amp()
    if not usb.get("path"):
        raise device.DeviceSelectionError("hidapi returned no HID path for the iNuke")
    audit_dir = Path(audit_dir) if audit_dir else Path.home() / ".local/state/pinuke/changes"
    result = {"complete": False, "snapshot": None, "attempted": [], "verified": [], "error": None}
    with device.INukeClient(path=usb["path"]) as amp:
        current = device._read_connected(amp, usb)
        result["snapshot"] = current
        if not before["usb"].get("serial") or not equivalent(dsp_state(before), dsp_state(current)):
            result["error"] = "Amplifier identity or settings changed since your read. Review the fresh readback before applying again. No DSP change was sent."
            return result
        changes = [c for c in changes if not equivalent(group_value(current, c), c["value"])]
        if not changes:
            result["complete"] = True
            return result
        record = {"started_at": datetime.now(timezone.utc).isoformat(), "before": current, "requested": changes, "outcome": "pending"}
        path = audit_dir / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex}.json"
        _save_audit(path, record)  # Must succeed before any setter.
        expected = copy.deepcopy(current)
        try:
            for change in changes:
                identity = {key: value for key, value in change.items() if key != "value"}
                result["attempted"].append(identity)
                observed = set_and_get(amp, change)
                if not equivalent(change["value"], observed):
                    raise RuntimeError(f"Channel {change['channel']} {SPECS[change['block']]['label']} readback differs from the requested values")
                result["verified"].append(identity)
                put_value(expected, change)
            result["snapshot"] = device._read_connected(amp, usb)
            if not equivalent(dsp_state(expected), dsp_state(result["snapshot"])):
                raise RuntimeError("Full readback includes differences beyond the requested changes. Review the amplifier state.")
            result["complete"] = True
        except Exception as exc:
            result["error"] = f"Apply stopped: {exc}. Some changes may already be on the amp; no automatic retry or restore was attempted."
            result["snapshot"] = None
            try:
                result["snapshot"] = device._read_connected(amp, usb)
            except Exception as read_error:
                result["error"] += f" Fresh readback also failed: {read_error}"
        record.update(outcome="verified" if result["complete"] else "incomplete", finished_at=datetime.now(timezone.utc).isoformat(), result=result)
        try:
            _save_audit(path, record)
        except OSError as exc:
            result["complete"] = False
            result["error"] = f"Changes were attempted, but saving the final change record failed: {exc}. Read the amp before continuing."
    return result
