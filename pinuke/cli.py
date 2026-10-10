"""PiNuke command line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .device import opencheck, probe, readback, scan, status
from .server import serve


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pi-hosted NU6000DSP control")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("scan", help="list matching USB devices without opening one")
    commands.add_parser("opencheck", help="open and close the enumerated HID path without sending reports")
    commands.add_parser("probe", help="open the amp and request identity only")
    commands.add_parser("status", help="check the info/online/gain/mode handshake with partial diagnostics")
    read = commands.add_parser("read", help="read live DSP state and save it as JSON")
    read.add_argument("output", type=Path)
    web = commands.add_parser("serve", help="serve PiNuke (editing requires --enable-edits)")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8765)
    web.add_argument("--public-origin", help="browser origin behind HTTPS proxy, e.g. https://amp.example")
    web.add_argument("--enable-edits", action="store_true", help="enable explicit, verified channel DSP edits")
    web.add_argument("--audit-dir", type=Path, help="directory for pre-change and outcome JSON records")
    web.add_argument("--enable-meters", action="store_true", help="enable viewer-leased live meter monitoring")
    web.add_argument("--meter-calibration", type=Path, help="verified amp-specific meter calibration JSON")
    args = parser.parse_args(argv)

    try:
        if args.command == "scan":
            print(json.dumps(scan(), indent=2))
        elif args.command == "opencheck":
            print(json.dumps(opencheck(), indent=2))
        elif args.command == "probe":
            print(json.dumps(probe(), indent=2))
        elif args.command == "status":
            result = status()
            print(json.dumps(result, indent=2))
            return 0 if result["complete"] else 1
        elif args.command == "read":
            state = readback()
            output = args.output.expanduser()
            if output.exists():
                raise FileExistsError(f"Refusing to overwrite {output}")
            output.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
            print(f"Saved live DSP readback to {output}")
        elif args.command == "serve":
            serve(args.host, args.port, public_origin=args.public_origin, enable_edits=args.enable_edits,
                  audit_dir=args.audit_dir, enable_meters=args.enable_meters, meter_calibration=args.meter_calibration)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"PiNuke: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
