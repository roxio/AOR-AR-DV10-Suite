"""Rendering of the Yaesu-style "front panel" status header shown in the CLI."""

from __future__ import annotations

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..device import AGC_SPEEDS, ATTENUATOR_STATES, SQUELCH_MODES, DV10Device, SMeterReading, Status

# S-meter dB range used purely for the width of the bar graph below - not a
# hardware limit, just a sane display floor. Confirmed via the AR-DV3 spec
# and real DV10 readings that LM's signal-level digits mean "-vvv dB", e.g.
# "1001" -> -100 dB, squelch open.
SMETER_FLOOR_DB = -120
SMETER_CEILING_DB = 0


def _smeter_bar(reading: SMeterReading | None, width: int = 20) -> Text:
    if reading is None or reading.dbm is None:
        return Text("[" + "·" * width + "] --- dB", style="dim")

    dbm = max(SMETER_FLOOR_DB, min(reading.dbm, SMETER_CEILING_DB))
    span = SMETER_CEILING_DB - SMETER_FLOOR_DB
    filled = round(((dbm - SMETER_FLOOR_DB) / span) * width)
    bar = "█" * filled + "·" * (width - filled)

    open_ = reading.squelch_open
    if open_ is True:
        state_style = "green"
        state_label = "open"
    elif open_ is False:
        state_style = "dim"
        state_label = "closed"
    else:
        state_style = "yellow"
        state_label = "?"

    text = Text(f"[{bar}] {reading.dbm:4d} dB  ", style=state_style)
    text.append(f"SQL {state_label}", style=state_style)
    return text


def render_status(device: DV10Device, status: Status) -> Panel:
    """Build a Rich renderable that looks like a compact radio front panel.

    Deliberately styled after the boxed, monospace, all-caps readouts on a
    Yaesu CAT control panel (frequency in big digits, mode/squelch/AGC as a
    row of small labelled fields, S-meter as a bar) rather than a literal
    clone of any one Yaesu model's layout.
    """
    freq_text = Text(justify="center", style="bold cyan")
    if status.frequency_hz is not None:
        mhz = status.frequency_hz / 1_000_000
        freq_text.append(f"{mhz:>13,.6f} MHz")
    else:
        freq_text.append("---.------ MHz", style="dim")

    if status.mode_info is not None:
        mode_label = status.mode_info.describe()
    else:
        mode_label = status.mode or "--"

    squelch_label = status.squelch or "--"
    if status.squelch in SQUELCH_MODES:
        squelch_label = f"{status.squelch} ({SQUELCH_MODES[status.squelch]})"

    agc_label = "ON" if status.agc_on else "OFF"
    agc_style = "green" if status.agc_on else "dim"
    if status.agc_speed in AGC_SPEEDS:
        agc_label = AGC_SPEEDS[status.agc_speed]
        agc_style = "green"

    att_label = status.attenuator_state or "--"
    if status.attenuator_state in ATTENUATOR_STATES:
        att_label = ATTENUATOR_STATES[status.attenuator_state]

    fields = Table.grid(padding=(0, 2))
    fields.add_column(justify="right", style="bold")
    fields.add_column()
    fields.add_row("MODE", Text(mode_label, style="yellow"))
    fields.add_row("SQL MODE", Text(squelch_label))
    fields.add_row("VOL", Text(status.volume or "--"))
    fields.add_row("AGC", Text(agc_label, style=agc_style))
    fields.add_row("ATT", Text(att_label))
    fields.add_row("S-METER", _smeter_bar(status.smeter_reading))

    body = Group(freq_text, Text(""), fields)
    return Panel(
        body,
        title="AOR AR-DV10",
        subtitle="connected" if device.connected else "disconnected",
        border_style="cyan",
    )


def print_status(console: Console, device: DV10Device) -> None:
    console.print(render_status(device, device.status()))
