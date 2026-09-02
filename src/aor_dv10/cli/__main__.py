"""Entry point for the `dv10-cli` console script (also runnable as
`python -m aor_dv10.cli`).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys

from rich.console import Console

from ..device import DV10Device
from ..protocol.codec import DV10Error
from ..protocol.commands import COMMANDS
from ..transport.base import TransportError
from .repl import Repl


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dv10-cli",
        description="Yaesu-panel-style interactive command line for the AOR AR-DV10.",
    )
    p.add_argument(
        "--port",
        help="Explicit serial device (e.g. COM7 or /dev/ttyACM0). "
        "Omit to auto-detect by USB VID/PID.",
    )
    p.add_argument(
        "--baud", type=int, default=115200, help="Serial baud rate (default: 115200)"
    )
    p.add_argument(
        "--simulator",
        action="store_true",
        help="Talk to the in-process simulated DV10 instead of real hardware.",
    )
    p.add_argument(
        "--run",
        action="append",
        default=[],
        metavar="COMMAND",
        help="Run one CLI command non-interactively and exit (repeatable). "
        'E.g. --run "f 145.5" --run status',
    )
    p.add_argument(
        "--web",
        action="store_true",
        help="Also start the web panel in this same process, sharing this CLI's "
        "device connection instead of opening a second one (needs the 'zeroconf'-free "
        "parts of the [web] extra: pip install -e '.[web]'). One command, one connection, "
        "both interfaces.",
    )
    p.add_argument(
        "--web-host",
        default=None,
        help="Web panel bind address (default: 127.0.0.1, or 0.0.0.0 automatically if "
        "--mdns is given). Only meaningful with --web.",
    )
    p.add_argument(
        "--web-port", type=int, default=8000, help="Web panel HTTP port (default 8000)"
    )
    p.add_argument(
        "--mdns",
        action="store_true",
        help="Advertise the web panel on the LAN via mDNS as http://<--mdns-name>.local:<port>/ "
        "(needs the 'zeroconf' package, included in the [web] extra). Implies --web. SECURITY: "
        "this exposes control of the receiver, including power on/off, to anyone on your LAN "
        "with no authentication - only use it on a network you trust.",
    )
    p.add_argument(
        "--mdns-name",
        default="aordv10",
        help='mDNS hostname label to advertise as (default: "aordv10"). Only meaningful with --mdns.',
    )
    p.add_argument(
        "--export-commands",
        choices=("json", "csv"),
        default=None,
        metavar="FORMAT",
        help="Dump the full command mnemonic registry "
        "(aor_dv10.protocol.commands.COMMANDS - every code/description/"
        "access/notes this project knows about, not just the ones with a "
        "typed device.py helper) as FORMAT to stdout, then exit "
        "immediately - no device connection made or needed. Useful for "
        "cross-checking against a future AOR manual revision without "
        "hand-diffing PDFs again. E.g. dv10-cli --export-commands json > "
        "commands.json",
    )
    p.add_argument(
        "--debug",
        nargs="?",
        const="",
        default=None,
        metavar="LOGFILE",
        help="Trace every raw TX/RX line from startup (dimmed in the console) - the same as "
        "typing 'debug on' as the first REPL command. Optionally pass a file path to also "
        "append the trace there as it happens, e.g. --debug session.log - handy for pasting "
        "exact communication back when something on real hardware doesn't behave as expected.",
    )
    return p


def export_commands(fmt: str, out) -> None:
    """Write aor_dv10.protocol.commands.COMMANDS to ``out`` (a text-mode
    file-like object, e.g. sys.stdout) as ``fmt`` ("json" or "csv").
    Pure static data, sorted by code for a stable
    diff-friendly order - no device connection is made or needed."""
    rows = [
        {
            "code": cmd.code,
            "description": cmd.description,
            "access": cmd.access.value,
            "notes": cmd.notes,
        }
        for cmd in sorted(COMMANDS.values(), key=lambda c: c.code)
    ]
    if fmt == "json":
        json.dump(rows, out, indent=2, ensure_ascii=False)
        out.write("\n")
    elif fmt == "csv":
        writer = csv.DictWriter(out, fieldnames=["code", "description", "access", "notes"])
        writer.writeheader()
        writer.writerows(rows)
    else:
        raise ValueError(f"unknown --export-commands format: {fmt!r}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.export_commands:
        # Deliberately before Console()/device connection: this is a pure
        # data dump meant to be piped/redirected (e.g. into a .json file),
        # so nothing else should touch stdout on this path, and no serial
        # port or simulator needs to exist for it to work.
        export_commands(args.export_commands, sys.stdout)
        return 0

    console = Console()

    device = DV10Device.open_simulator() if args.simulator else DV10Device.open_serial(
        port=args.port, baudrate=args.baud
    )

    try:
        device.connect()
    except TransportError as exc:
        console.print(f"[red]Could not connect:[/red] {exc}")
        if not args.simulator:
            console.print(
                "[dim]Tip: pass --simulator to try the CLI without hardware, "
                "or --port to specify the DV10's COM port explicitly.[/dim]"
            )
        return 1

    web_panel = None
    if args.web or args.mdns:
        # --mdns implies --web: advertising a panel that isn't running
        # wouldn't do anything useful.
        try:
            from ..web import server as webserver
        except ImportError as exc:
            console.print(
                f"[red]--web/--mdns needs the web extra, which isn't installed:[/red] {exc}\n"
                "[dim]Run: pip install -e \".[web]\"[/dim]"
            )
            device.disconnect()
            return 1
        try:
            web_panel = webserver.start_in_thread(
                device,
                host=args.web_host,
                port=args.web_port,
                mdns=args.mdns,
                mdns_name=args.mdns_name,
            )
        except ImportError as exc:
            # e.g. --mdns without the "zeroconf" package - start_in_thread()
            # raises rather than printing (see its docstring), so the CLI
            # decides how to present it, consistently with the case above.
            console.print(f"[red]Could not start the web panel:[/red] {exc}")
            device.disconnect()
            return 1
        console.print(f"[cyan]Web panel:[/cyan] {web_panel.url}")
        if web_panel.mdns_url:
            console.print(f"[cyan]         also on the LAN as:[/cyan] {web_panel.mdns_url}")
        console.print(
            "[dim](sharing this session's device connection - commands from either "
            "interface affect the same receiver)[/dim]\n"
        )

    repl = Repl(device, console)
    if args.debug is not None:
        repl.enable_debug(args.debug or None)
        msg = "Tracing ON from startup (dim lines are raw TX/RX)"
        if args.debug:
            msg += f" - also logging to {args.debug}"
        console.print(f"[dim]{msg}[/dim]")
    try:
        if args.run:
            # Same error handling as the interactive REPL's run() loop
            # (see Repl.run() in repl.py): a DV10Error/ValueError from one
            # --run command shouldn't abort the rest of the batch with an
            # unhandled traceback - print it and move on to the next one.
            for cmd in args.run:
                console.print(f"[dim]DV10> {cmd}[/dim]")
                try:
                    repl.dispatch(cmd)
                except DV10Error as exc:
                    console.print(f"[red]Device error:[/red] {exc}")
                except ValueError as exc:
                    console.print(f"[red]{exc}[/red]")
        else:
            repl.run()
    finally:
        repl.disable_debug()
        if web_panel is not None:
            web_panel.stop()
        device.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
