"""Interactive REPL: a Yaesu-CAT-flavoured command line for the DV10.

Short, terse verbs (f/m/sq/vol/agc/...) in the spirit of typing commands into
a Yaesu radio's CAT terminal, plus a live status panel you can redraw with
`s`, and a `raw` escape hatch that gives access to every command in
aor_dv10.protocol.commands.COMMANDS even before it has a typed helper.
"""

from __future__ import annotations

import shlex
import time

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from rich.console import Console

from ..device import (
    BACKLIGHT_MODES,
    DV10Device,
    KEY_BACKLIGHT_COLORS,
    SD_CARD_STATUS,
    TONE_SQUELCH_TYPES,
)
from ..timer import (
    RecordingTimer,
    format_once_time,
    format_weekly_time,
    receive_mode_memory_channel,
    receive_mode_memory_scan,
    receive_mode_search_bank,
    receive_mode_vfo,
    receive_mode_vfo_search,
)
from ..memory import MemoryChannel, parse_backup_csv, write_backup_csv
from ..selectscan import SelectScanList, run_select_scan
from ..protocol.codec import DV10Error
from ..protocol.commands import COMMANDS
from .panel import print_status

HELP = """\
Commands:
  s, status              Show the panel (frequency / mode / squelch / volume / S-meter / AGC)
  f [MHZ]                Show or set frequency in MHz, e.g. "f 145.500000"
                          (needs VFO mode)
  m [MODE]                Show or set raw MD mode code, e.g. "m F0" (FM, digital off) -
                          see aor_dv10.device.DIGITAL_MODES / ANALOG_MODES
  sq [0|1|2]              Show or set squelch MODE (0=Auto,1=Noise,2=Level) - NOT a level,
                          despite the name; see 'lq'/'nq' below for the actual thresholds
  lq [LEVEL]              Show or set level-squelch threshold (00-99), used when sq=2
  nq [LEVEL]              Show or set noise-squelch threshold (00-39), used when sq=1
  vol [LEVEL]              Show or set volume (audio gain) - confirmed unsupported
                          (error 60) on at least one real DV10 unit
  agc on|off               Legacy on/off AGC (maps to AC speed Mid/Fast) - see 'agcspd'
  agcspd [0-3]             Show or set AGC speed directly (0=Fast,1=Mid,2=Slow,3=RF-G)
  beep on|off               Enable/disable the DV10's key beep
  att on|off               Legacy on/off attenuator (on->ATT ON, off->ATT OFF) - see 'attst'
  attst [0-2]              Show or set attenuator state directly (0=ATT OFF,1=ATT ON,2=10dB ATT)
  re on|off                Toggle numeric result-code prefixing on responses - CONFIRMED working on real DV10
  vfo [A|B|Z] [mhz] [mode]  Select a VFO (default A) - CONFIRMED on real DV10 to be the way into VFO mode,
                          needed before f/sq/att/agcspd/etc. writes will succeed. Optionally set
                          frequency/mode atomically in the same VF write - see "vi" below
  vi                       VI: show all three VFOs (A/B/Z) at once - frequency/step/step-adjust/mode
  vs                       VS: start a VFO search using VFO-A/VFO-B's current range and "ve"'s settings
  ve [delay_ds] [free_s] [autostore 0|1]
                          VE: show or set the VFO-search delay/free-time/auto-store settings used by "vs"
  raw CODE [VALUE]          Send a raw command, e.g. "raw LM" or "raw AT 1"
  describe CODE             Show what a raw command code does
  step [HZ]                Show or set the tuning step, e.g. "step 12500"
  tone on|off               Enable/disable CTCSS tone squelch
  tonefreq [VALUE]          Show or set the CTCSS tone, e.g. "tonefreq 100.0"
  dcs on|off                Enable/disable DCS squelch
  dcscode [VALUE]           Show or set the DCS code, e.g. "dcscode 023"
  offset [SLOT [+|-]]       Show or set the offset slot + direction (00=off, 01-19=user, 20-39=preset)
  offsetfreq [SLOT [MHZ]]   Show or set slot SLOT's offset frequency (unsigned; direction is "offset"'s)
  prio on|off                Enable/disable priority-channel monitoring
  priochan [BANK CH]        PP: show or set the priority channel
  priointerval [1-99]       TI: show or set the priority-check interval (seconds)
  dmrcc [00-16]              CC: show or set the DMR color code
  dmrcm on|off               CM: enable/disable DMR mute-by-color-code
  dmrslot [VALUE]            OT: show or set the DMR slot selection
  p25nac [000-FFF]           PC: show or set the APCO P25 NAC code
  p25pm on|off                PM: enable/disable P25 mute-by-NAC
  nxdnran [00-63]            NC: show or set the NXDN RAN code
  nxdnnm on|off               NM: enable/disable NXDN mute-by-RAN
  dcrcode [00000-32767]      DC: show or set the DCR (DMR mode) descramble code
  descr on|off                SI: enable/disable the analog voice descrambler (V.SCR)
  beeplvl [0-7]               BP: show or set the key-beep volume level
  vollimit [00-15]           AV: show or set the "VOL ATT" ceiling the physical volume knob
                          can reach - very likely the real remote volume control, since AG
                          (audio gain) is confirmed non-functional
  digain [01.00-15.94]      DA: show or set extra digital-mode audio gain (for when max
                          volume with vollimit=00 still isn't loud enough)
  mgain [000-110]            RG: show or set manual (non-AGC) gain
  contrast [00-63]           LN: show or set LCD contrast
  movenext                    Move to the next memory channel/bank (front-panel Up equivalent)
  moveprev                    Move to the previous memory channel/bank (front-panel Down equivalent)
  stepadj [HZ]               SH: show or set the frequency-step adjust value
  backlight [0|1|2]         LB: show or set LCD backlight mode (0=OFF,1=CONTINUOUS,2=AUTO) -
                          see aor_dv10.device.BACKLIGHT_MODES
  klcolor [0-7]              KL: show or set KEY backlight color (0=OFF,1=BLUE,2=RED,3=MAGENDA
                          [sic - spec's own typo],4=GREEN,5=CYAN,6=YELLOW,7=ORANGE) - distinct
                          from "backlight" (LB) above, despite the similar name
  ifbw [VALUE]               IF: show or set the IF bandwidth selector by its raw digit -
                          meaning depends on the current mode, see aor_dv10.device.IF_BANDWIDTH_HZ
  bw [HZ]                    IF bandwidth by Hz value instead of raw digit, e.g. "bw 15000" -
                          choices depend on the current analog mode (FM/AM/USB/...); "bw" alone
                          shows the current value and the choices valid right now
  delay [DECISECONDS]       DL: show or set the standalone delay time (000-099, 0.1s ticks;
                          100=unlimited) - distinct from the DL inside "scan swrite"/"mwrite"
  freetime [SECONDS]        FR: show or set the standalone free time (00-60s; 0=OFF) -
                          distinct from the FR inside "scan swrite"/"mwrite"
  serial                     RN: show the AR-DV1 serial number (read-only - the spec's
                          detailed section documents only a read, despite the command
                          summary table listing it as R/W)
  sqltype [0-2]               CI: show or set the tone-squelch type - 0=OFF, 1=CTCSS,
                          2=Reverse Tone (confirmed against real hardware - see
                          aor_dv10.device.TONE_SQUELCH_TYPES). DCS is separate - see "dcs" -
                          not one of this selector's values
  id                          WI/VR: show detected receiver model, firmware, and normalized
                          family (DV10/DV1/unknown) - the family gates model-specific UI
                          quirks like SAH/SAL not being distinct on the DV10, see
                          aor_dv10.device.ANALOG_MODES_WITHOUT_DISTINCTION_BY_FAMILY
  regchan                   MM: register the current VFO/channel as "last channel memory"
                          (write-only; DESTRUCTIVE-ish - see DV10Device.register_last_channel())
  power on|off               ZP (connect/power on) / QP (disconnect/power off)
  timer                     TR: show the scheduled recording/alarm timer's current configuration
  timer off                 TR: deactivate the timer (XE0) - other fields are left as they were
  timer set <target> <once|weekly> <start> <end> [alarm|recording] [days] [volume]
                          TR: configure the timer. <target> is "vfo:A"/"vfo:B"/"vfo:Z", "vs"
                          (VFO search), "bank:<n>" (program search), "ch:<bank>-<ch>" (memory
                          channel), or "scan:<n>" (memory scan). <start>/<end> are raw MMDDhhmm
                          (once) or hhmm (weekly) tokens. [days] is a comma list for weekly
                          schedules (sun,mon,tue,wed,thu,fri,sat) or "-" for none. See
                          aor_dv10.timer's module docstring for real caveats before relying on this -
                          the AR-DV1 spec's own TR entry is internally inconsistent and several
                          fields (notably the timer TYPE and the weekday-mask width) are unconfirmed.
  sd dir                    SD DIR: list files on the SD card
  sd info                   SD INF: card capacity summary (free/total, approx. free hours)
  sd status                 SD PST: record/playback status
  sd rec start|stop         SD REC / SD REC/: start/stop recording (auto name). Stop is AR-DV1/DV3-only and refused on the DV10.
  sd play <name>|stop       SD PLY<name> / SD PLY/: start/stop playback
  sd rsq [on|off]            SD RSQ: show or set squelch-skip during playback
  sd backup <kind>          SD MMW<kind>: back up receiver settings - kind is one of SRCHBK/
                          SRCHGRP/MEMCH/SCANGRP/SYSYEM (sic - see aor_dv10.device.SD_BACKUP_KIND_*)
  sd restore <name>         SD MMR<name>: restore a prior "sd backup" (usually the same kind token)
  mem load <path>          Load an "AR-DV10 Connect" memory-bank backup CSV export
  mem find <text>          Search loaded channel names (case-insensitive substring)
  mem list [bank]          List programmed channels, optionally filtered to one bank (00-39)
  mem goto <bank>-<ch>     Tune to a loaded channel via f/m/step (VFO mode, not a live
                          memory-channel read)
  mem export <path>        Write the loaded (and possibly since-edited) database back to CSV
  rmem read <bank> <ch>     MA: query the receiver's own stored record for a live memory channel
  rmem readbank <bank>      MA (bank form): dump every channel slot in a bank (50 lines)
  rmem write <bank> <ch> <MHZ> [mode] [tag]
                          MX: program a live memory channel (DESTRUCTIVE - overwrites the slot)
  rmem tune <bank> <ch>     MR: actually start receiving a live memory channel
  rmem delete <bank> <ch>   MQ: delete a single live memory channel (DESTRUCTIVE)
  rmem bank <bank>          MW: read a live memory bank's metadata (channel count/protect/tag)
  rmem bankset <bank> [count] [protect] [tag]
                          MW: configure a live memory bank's metadata
  rmem bankdel <bank>       MB: delete a live memory bank and everything in it (DESTRUCTIVE)
  rmem find <text> [bank]   Search live channel tags for a substring (case-insensitive) - like
                          "mem find" but reads the receiver's own MA records instead of a
                          loaded CSV. With no bank, loops over all 40 banks (00-39) - slow
                          (up to 40 sequential MA-bank reads over serial); give a bank to
                          narrow it down when you know roughly where to look.
  scope fast                 FD: one-shot fast-speed scope scan, printed as a text sparkline.
                          CAVEAT: documented as requiring "scope mode" first, and no known
                          command/procedure enters it - see aor_dv10.device's "Frequency
                          scope" section. Likely to fail with result code 30 on real hardware.
  scope normal               GL: one-shot normal-speed scope scan (frequency + level per line).
                          Same "scope mode" caveat as "scope fast".
  select add <bank> <ch>    Add a channel to the client-side select-scan list (session-only,
                          not saved to the receiver - see aor_dv10.selectscan)
  select remove <bank> <ch>  Remove a channel from the select-scan list
  select list                Show the current select-scan list
  select clear                Empty the select-scan list
  select run [cycles] [dwell_s]
                          Scan the list via MR (tune_memory_channel), pausing dwell_s
                          (default 2.0) between channels; runs forever unless cycles is
                          given, or until Ctrl-C
  debug on [logfile]       Start tracing every raw TX/RX line (byte-exact); optionally also
                          append it to logfile as it happens
  debug off                Stop live tracing (recent history is kept either way)
  debug last [N]           Show the last N traced TX/RX lines (default 20) - works even if
                          "debug on" was never used, since tracing is always recorded
  debug save <path>        Write all recorded trace lines to a file
  help, ?                  Show this help
  search write <bank> [lo_mhz] [hi_mhz] [step_hz] [step_adj_hz] [mode] [protect 0|1] [tag...]
                          SE: configure a program-search bank (all fields after <bank> optional,
                          and only settable in order - trailing ones may be omitted, not skipped)
  search read <bank>       SR: read back a program-search bank
  search run <bank>        SS: start a program search over a bank's configured range
  search delete <bank>     SX: delete a program-search bank (DESTRUCTIVE)
  search lolimit [mhz]     SL: show or set the search range's lower limit (SESSION-only, see docs)
  search hilimit [mhz]     SU: show or set the search range's upper limit (SESSION-only, see docs)
  scan sread <group>        SG: read a search-side scan group's delay/free-time/auto-store/bank-link
  scan swrite <group> [delay_ds] [free_s] [autostore 0|1] [bank...|clear]
                          SG: configure a search-side scan group ("clear" as the bank list
                          explicitly disables all links - see DV10Device.write_search_scan_group())
  scan mread <group>        MG: read a memory-side scan group (no auto-store field, unlike SG)
  scan mwrite <group> [delay_ds] [free_s] [bank...|clear]
                          MG: configure a memory-side scan group
  scan autostore [on|off]   AS: show or set the standalone auto-store flag
  scan banklink [bank...|clear]
                          BK: show or set the standalone bank-link list ("clear" disables all)
  pass mark [mhz]           PW: mark current (or given) frequency as a VFO-search pass frequency
  pass mark bank <bank> [mhz]
                          PW: mark current (or given) frequency as a pass frequency in <bank>
  pass mark allbanks <mhz>  PW: mark <mhz> as a pass frequency in every program-search bank
  pass list [bank]          PR: list the 50 pass-frequency slots for VFO search or a bank
  pass delete               PD: delete every VFO-search pass frequency (DESTRUCTIVE)
  pass delete bank <bank> [index]
                          PD: delete one bank's whole pass-frequency list, or one entry by index
  pass delete allbanks      PD: delete every bank's pass-frequency list (DESTRUCTIVE)
  quit, exit                 Disconnect and leave

Many more settings (DMR/P25/NXDN/D-CR selective codes, priority
channel/interval, SD card, backups, ...) don't have a short verb yet - use
"raw CODE [VALUE]" and "describe CODE" for those; see
aor_dv10.protocol.commands.COMMANDS for the full mnemonic list.
"""

_VERBS = [
    "s", "status", "f", "m", "sq", "lq", "nq", "vol", "agc", "agcspd",
    "beep", "att", "attst", "re", "vfo", "raw", "describe", "power", "help",
    "quit", "exit",
    "step", "tone", "tonefreq", "dcs", "dcscode", "offset", "offsetfreq", "prio",
    "mem", "rmem", "debug", "regchan", "search", "scan", "pass",
    "vi", "vs", "ve", "timer", "sd", "scope", "select",
    "backlight", "klcolor", "ifbw", "bw", "delay", "freetime", "serial",
    "id", "sqltype", "priochan", "priointerval", "dmrcc", "dmrcm", "dmrslot",
    "p25nac", "p25pm", "nxdnran", "nxdnnm", "dcrcode", "descr",
    "beeplvl", "vollimit", "digain", "mgain", "contrast",
    "movenext", "moveprev", "stepadj",
]


def _on_off(token: str) -> bool:
    token = token.strip().lower()
    if token in ("on", "1", "true"):
        return True
    if token in ("off", "0", "false"):
        return False
    raise ValueError(f"expected on/off, got {token!r}")


class Repl:
    def __init__(self, device: DV10Device, console: Console | None = None):
        self.device = device
        self.console = console or Console()
        completer = WordCompleter(_VERBS + list(COMMANDS.keys()), ignore_case=True)
        self.session = PromptSession("DV10> ", completer=completer)
        # "mem load"-ed backup CSV, if any - see the "mem" verb and
        # aor_dv10.memory. File-format only, never touches the live
        # MX/MA memory-channel wire commands.
        self.memory_banks: list = []
        self.memory_channels: list[MemoryChannel] = []
        # Client-side select-scan list - session-only,
        # never persisted or written to the receiver. See the "select"
        # verb and aor_dv10.selectscan.
        self.select_scan_list = SelectScanList()
        # Open log file for "debug on <path>"/--debug <path>, if any - see
        # the "debug" verb and enable_debug()/disable_debug() below.
        self._trace_file = None

    def run(self) -> None:
        print_status(self.console, self.device)
        self.console.print("Type 'help' for commands.\n")
        try:
            while True:
                try:
                    line = self.session.prompt()
                except (EOFError, KeyboardInterrupt):
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    if not self.dispatch(line):
                        break
                except DV10Error as exc:
                    self.console.print(f"[red]Device error:[/red] {exc}")
                except ValueError as exc:
                    self.console.print(f"[red]{exc}[/red]")
        finally:
            self.disable_debug()

    def dispatch(self, line: str) -> bool:
        """Returns False to request exit."""
        parts = shlex.split(line)
        verb, args = parts[0].lower(), parts[1:]

        if verb in ("quit", "exit"):
            return False
        if verb in ("help", "?"):
            self.console.print(HELP)
        elif verb in ("s", "status"):
            print_status(self.console, self.device)
        elif verb == "f":
            if args:
                hz = round(float(args[0]) * 1_000_000)
                self.device.set_frequency_hz(hz)
            self.console.print(f"{self.device.get_frequency_hz() / 1_000_000:.6f} MHz")
        elif verb == "m":
            if args:
                self.device.set_mode(args[0])
            self.console.print(self.device.get_mode())
        elif verb == "sq":
            if args:
                self.device.set_squelch(args[0])
            self.console.print(self.device.get_squelch())
        elif verb == "vol":
            if args:
                self.device.set_volume(args[0])
            self.console.print(self.device.get_volume())
        elif verb == "agc":
            if not args:
                raise ValueError("usage: agc on|off")
            self.device.set_agc(_on_off(args[0]))
        elif verb == "beep":
            if not args:
                raise ValueError("usage: beep on|off")
            self.device.set_beep(_on_off(args[0]))
        elif verb == "att":
            if not args:
                raise ValueError("usage: att on|off")
            self.device.set_attenuator(_on_off(args[0]))
        elif verb == "lq":
            if args:
                self.device.set_squelch_level(args[0])
            self.console.print(self.device.get_squelch_level())
        elif verb == "nq":
            if args:
                self.device.set_noise_squelch_level(args[0])
            self.console.print(self.device.get_noise_squelch_level())
        elif verb == "agcspd":
            if args:
                self.device.set_agc_speed(args[0])
            self.console.print(self.device.get_agc_speed())
        elif verb == "attst":
            if args:
                self.device.set_attenuator_state(args[0])
            self.console.print(self.device.get_attenuator_state())
        elif verb == "re":
            if not args:
                raise ValueError("usage: re on|off")
            self.device.set_result_code_prefixing(_on_off(args[0]))
        elif verb == "vfo":
            # "vfo [A|B|Z] [mhz] [mode]". The VF command's *embedded*
            # RF/ST/SH/MD fields (the atomic "VFt RF... MD..." form) are a
            # silent no-op on real DV10 - confirmed by testing: "vfo A
            # 145.500000 F0" only switches to VFO-A and leaves the
            # frequency unchanged (matches the unconfirmed-inference warning
            # in enter_vfo_mode()). So a frequency/mode here is applied with
            # the STANDALONE, separately-confirmed RF and MD writes after
            # first entering the chosen VFO - the same
            # enter_vfo_mode()+set_frequency_hz() sequence the web server
            # and CLI use for mem-tune/mem-goto.
            vfo = (args[0] if args else "A").strip().upper()
            if vfo not in ("A", "B", "Z"):
                raise ValueError(f'vfo must be "A", "B", or "Z"')
            self.device.enter_vfo_mode(vfo)  # bare VFt: select/enter the VFO
            if len(args) > 1:
                hz = round(float(args[1]) * 1_000_000)
                self.device.set_frequency_hz(hz)
            if len(args) > 2:
                self.device.set_mode(args[2])
            self.console.print(f"VFO {vfo}")
        elif verb == "vi":
            for v in self.device.read_vfo_info():
                freq = f"{v.frequency_hz / 1_000_000:.5f} MHz" if v.frequency_hz is not None else "?"
                self.console.print(
                    f"VFO-{v.vfo}  {freq}  step={v.step_hz}  stepadj={v.step_adjust_hz}  mode={v.mode}"
                )
        elif verb == "vs":
            self.device.execute_vfo_search()
            self.console.print("VFO search started")
        elif verb == "ve":
            if args:
                delay_ds = int(args[0]) if len(args) > 0 else None
                free_s = int(args[1]) if len(args) > 1 else None
                auto_store = _on_off(args[2]) if len(args) > 2 else None
                self.device.write_vfo_search_settings(
                    delay_ds=delay_ds, free_time_s=free_s, auto_store=auto_store
                )
            s = self.device.read_vfo_search_settings()
            self.console.print(
                f"delay={s.delay_ds} free={s.free_time_s} autostore={s.auto_store}"
            )
        elif verb == "timer":
            self._dispatch_timer(args)
        elif verb == "sd":
            self._dispatch_sd(args)
        elif verb == "scope":
            self._dispatch_scope(args)
        elif verb == "select":
            self._dispatch_select(args)
        elif verb == "power":
            if not args or args[0].lower() not in ("on", "off"):
                raise ValueError("usage: power on|off")
            resp = self.device.power_on() if args[0].lower() == "on" else self.device.power_off()
            self.console.print(f"{resp.code} {resp.value or ''}".strip())
        elif verb == "raw":
            if not args:
                raise ValueError("usage: raw CODE [VALUE]")
            code, value = args[0], (args[1] if len(args) > 1 else None)
            resp = self.device.raw(code, value)
            self.console.print(f"{resp.code} {resp.value or ''}".strip())
        elif verb == "describe":
            if not args:
                raise ValueError("usage: describe CODE")
            self.console.print(self.device.describe(args[0]))
        elif verb == "step":
            if args:
                self.device.set_frequency_step_hz(int(float(args[0])))
            self.console.print(self.device.get_frequency_step_hz())
        elif verb == "tone":
            if not args:
                raise ValueError("usage: tone on|off")
            self.device.set_tone_squelch_enabled(_on_off(args[0]))
        elif verb == "tonefreq":
            if args:
                self.device.set_tone_squelch_freq(args[0])
            self.console.print(self.device.get_tone_squelch_freq())
        elif verb == "dcs":
            if not args:
                raise ValueError("usage: dcs on|off")
            self.device.set_dcs_enabled(_on_off(args[0]))
        elif verb == "dcscode":
            if args:
                self.device.set_dcs_code(args[0])
            self.console.print(self.device.get_dcs_code())
        elif verb == "offset":
            # OF takes an explicit direction sign too - "offset <slot
            # 00-39> [+|-]" (default "+") - see
            # DV10Device.set_offset_slot().
            if args:
                direction = args[1] if len(args) > 1 else "+"
                self.device.set_offset_slot(int(args[0]), direction)
            self.console.print(self.device.get_offset_slot())
        elif verb == "offsetfreq":
            # OL always needs an explicit slot
            # number, for both reads and writes - "offsetfreq <slot 00-39>
            # [freq_mhz]" - see DV10Device.get_offset_freq()/
            # set_offset_freq(). With no args at all, falls back to
            # whatever slot OF currently has active.
            if len(args) >= 2:
                self.device.set_offset_freq(int(args[0]), float(args[1]))
            if args:
                slot = int(args[0])
            else:
                raw_of = self.device.get_offset_slot()
                digits = "".join(ch for ch in raw_of if ch.isdigit())
                slot = int(digits) if digits else 0
            self.console.print(self.device.get_offset_freq(slot))
        elif verb == "regchan":
            # MM: register the currently-tuned VFO/bank/channel as the
            # receiver's "last channel memory" - see
            # DV10Device.register_last_channel() for the
            # AR-DV1-spec two-phase-response handling this relies on.
            code = self.device.register_last_channel()
            self.console.print(f"registration result code: {code}")
        elif verb == "prio":
            if not args:
                raise ValueError("usage: prio on|off")
            self.device.set_priority_enabled(_on_off(args[0]))
        elif verb == "priochan":
            if len(args) >= 2:
                self.device.set_priority_channel(int(args[0]), int(args[1]))
            self.console.print(self.device.get_priority_channel())
        elif verb == "priointerval":
            if args:
                self.device.set_priority_interval(int(args[0]))
            self.console.print(self.device.get_priority_interval())
        elif verb == "dmrcc":
            if args:
                self.device.set_dmr_color_code(int(args[0]))
            self.console.print(self.device.get_dmr_color_code())
        elif verb == "dmrcm":
            if not args:
                raise ValueError("usage: dmrcm on|off")
            self.device.set_dmr_mute_by_color_code(_on_off(args[0]))
        elif verb == "dmrslot":
            if args:
                self.device.set_dmr_slot(args[0])
            self.console.print(self.device.get_dmr_slot())
        elif verb == "p25nac":
            if args:
                self.device.set_p25_nac(args[0])
            self.console.print(self.device.get_p25_nac())
        elif verb == "p25pm":
            if not args:
                raise ValueError("usage: p25pm on|off")
            self.device.set_p25_mute_by_nac(_on_off(args[0]))
        elif verb == "nxdnran":
            if args:
                self.device.set_nxdn_ran(int(args[0]))
            self.console.print(self.device.get_nxdn_ran())
        elif verb == "nxdnnm":
            if not args:
                raise ValueError("usage: nxdnnm on|off")
            self.device.set_nxdn_mute_by_ran(_on_off(args[0]))
        elif verb == "dcrcode":
            if args:
                self.device.set_dcr_descramble_code(int(args[0]))
            self.console.print(self.device.get_dcr_descramble_code())
        elif verb == "descr":
            if not args:
                raise ValueError("usage: descr on|off")
            self.device.set_voice_descrambler_enabled(_on_off(args[0]))
        elif verb == "beeplvl":
            if args:
                self.device.set_beep_level(int(args[0]))
            self.console.print(self.device.get_beep_level())
        elif verb == "vollimit":
            if args:
                self.device.set_volume_limit(int(args[0]))
            self.console.print(self.device.get_volume_limit())
        elif verb == "digain":
            if args:
                self.device.set_digital_gain(float(args[0]))
            self.console.print(self.device.get_digital_gain())
        elif verb == "mgain":
            if args:
                self.device.set_manual_gain(int(args[0]))
            self.console.print(self.device.get_manual_gain())
        elif verb == "contrast":
            if args:
                self.device.set_lcd_contrast(int(args[0]))
            self.console.print(self.device.get_lcd_contrast())
        elif verb == "movenext":
            self.device.move_next()
        elif verb == "moveprev":
            self.device.move_previous()
        elif verb == "stepadj":
            if args:
                self.device.set_step_adjust_hz(int(float(args[0])))
            self.console.print(self.device.get_step_adjust_hz())
        elif verb == "backlight":
            # LB (LCD backlight mode) - NOT to be confused with "klcolor"
            # (KL, key backlight color) just below; see this section's
            # comment near the HELP text above for why these two got
            # separated out under different verb names.
            if args:
                self.device.set_backlight_mode(args[0])
            mode = self.device.get_backlight_mode()
            self.console.print(f"{mode} ({BACKLIGHT_MODES.get(mode, 'unknown')})")
        elif verb == "klcolor":
            if args:
                self.device.set_key_backlight_color(int(args[0]))
            n = self.device.get_key_backlight_color()
            self.console.print(f"{n} ({KEY_BACKLIGHT_COLORS.get(n, 'unknown')})")
        elif verb == "ifbw":
            if args:
                self.device.set_if_bandwidth(args[0])
            self.console.print(self.device.get_if_bandwidth())
        elif verb == "bw":
            if args:
                self.device.set_if_bandwidth_hz(int(args[0]))
            hz = self.device.get_if_bandwidth_hz()
            options = sorted(self.device.get_if_bandwidth_options_hz().values())
            if options:
                choices = ", ".join(str(v) for v in options)
            else:
                # Empty options has two different causes - see
                # get_if_bandwidth_options_hz()'s docstring - worth
                # telling apart here rather than one generic "none known"
                # for both.
                digital = self.device.get_mode_info().digital_select
                if digital and digital != "Digital off":
                    choices = f"none - auto-selected by the receiver while digital ({digital}) is active"
                else:
                    choices = "none known for the current mode"
            self.console.print(f"{hz if hz is not None else '?'} Hz (choices: {choices})")
        elif verb == "delay":
            if args:
                self.device.set_delay_time_ds(int(args[0]))
            self.console.print(self.device.get_delay_time_ds())
        elif verb == "freetime":
            if args:
                self.device.set_free_time_s(int(args[0]))
            self.console.print(self.device.get_free_time_s())
        elif verb == "serial":
            self.console.print(self.device.get_serial_number())
        elif verb == "id":
            model = self.device.model()
            firmware = self.device.firmware_version()
            family = self.device.device_family()
            self.console.print(
                f"{model or '?'} (firmware {firmware or '?'}, family={family or 'unknown'})"
            )
        elif verb == "sqltype":
            if args:
                self.device.set_squelch_tone_type(args[0])
            value = self.device.get_squelch_tone_type()
            label = TONE_SQUELCH_TYPES.get(value, "unknown")
            self.console.print(f"{value} ({label})")
        elif verb == "mem":
            self._dispatch_mem(args)
        elif verb == "rmem":
            self._dispatch_rmem(args)
        elif verb == "search":
            self._dispatch_search(args)
        elif verb == "scan":
            self._dispatch_scan(args)
        elif verb == "pass":
            self._dispatch_pass(args)
        elif verb == "debug":
            self._dispatch_debug(args)
        else:
            self.console.print(f"[red]Unknown command:[/red] {verb!r} (try 'help')")
        return True

    def enable_debug(self, path: str | None = None) -> None:
        """Start live protocol tracing - every raw TX/RX line, printed
        dimmed to the console as it happens, and (if ``path`` is given)
        also appended to that file so nothing is lost even if the
        terminal scrollback isn't enough to copy from later. Safe to call
        again while already on (e.g. --debug at startup, then "debug on
        <path>" later to also start logging to a file) - it just replaces
        the file, if any. Trace lines are recorded regardless of this
        being called at all - see "debug last"/DV10Device.trace_lines()."""
        if self._trace_file is not None:
            try:
                self._trace_file.close()
            except Exception:
                pass
            self._trace_file = None
        if path:
            self._trace_file = open(path, "a", encoding="utf-8")
            self._trace_file.write(
                f"\n--- trace session started {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n"
            )
            self._trace_file.flush()
        self.device.set_trace_sink(self._trace_line)

    def disable_debug(self) -> None:
        """Stop live tracing (recorded history is kept regardless - see
        "debug last"). Safe to call even if tracing was never on."""
        self.device.set_trace_sink(None)
        if self._trace_file is not None:
            try:
                self._trace_file.close()
            except Exception:
                pass
            self._trace_file = None

    def _trace_line(self, line: str) -> None:
        self.console.print(f"[dim]{line}[/dim]")
        if self._trace_file is not None:
            try:
                self._trace_file.write(line + "\n")
                self._trace_file.flush()
            except Exception:
                pass

    def _dispatch_rmem(self, args: list[str]) -> None:
        """Handles the "rmem ..." (receiver live memory) verb family - the
        real MX/MA/MR/MW/MB/MQ wire commands, talking directly to whatever
        is actually programmed into the receiver right now. Deliberately
        separate from "mem ..." (the AR-DV10 Connect backup CSV workflow,
        see aor_dv10.memory) - see aor_dv10.device.MemoryChannelInfo's
        docstring for why the two field layouts aren't interchangeable."""
        if not args:
            raise ValueError(
                "usage: rmem read <bank> <ch> | rmem readbank <bank> | "
                "rmem write <bank> <ch> <freq_mhz> [mode] [tag...] | "
                "rmem tune <bank> <ch> | rmem delete <bank> <ch> | "
                "rmem bank <bank> | rmem bankset <bank> [count] [protect 0|1] [tag...] | "
                "rmem bankdel <bank>"
            )
        sub, rest = args[0].lower(), args[1:]

        def _print_channel(c):
            if not c.registered:
                self.console.print(f"{c.bank:02d}-{c.channel:02d}  (not registered)")
                return
            freq = f"{c.frequency_hz / 1_000_000:.5f} MHz" if c.frequency_hz is not None else "?"
            self.console.print(
                f"{c.bank:02d}-{c.channel:02d}  {freq}  mode={c.mode}  "
                f"pass={c.pass_channel} protect={c.write_protect}  {c.tag!r}"
            )

        if sub == "read":
            if len(rest) < 2:
                raise ValueError("usage: rmem read <bank> <ch>")
            _print_channel(self.device.read_memory_channel(int(rest[0]), int(rest[1])))
        elif sub == "readbank":
            if not rest:
                raise ValueError("usage: rmem readbank <bank>")
            channels = self.device.read_memory_bank(int(rest[0]))
            registered = [c for c in channels if c.registered]
            for c in registered:
                _print_channel(c)
            self.console.print(f"({len(registered)} registered of {len(channels)} slots)")
        elif sub == "write":
            if len(rest) < 3:
                raise ValueError("usage: rmem write <bank> <ch> <freq_mhz> [mode] [tag...]")
            bank, ch = int(rest[0]), int(rest[1])
            freq_hz = round(float(rest[2]) * 1_000_000)
            mode = rest[3] if len(rest) > 3 else None
            tag = " ".join(rest[4:]) if len(rest) > 4 else None
            self.device.write_memory_channel(bank, ch, frequency_hz=freq_hz, mode=mode, tag=tag)
            self.console.print(f"wrote {bank:02d}-{ch:02d}")
        elif sub == "tune":
            if len(rest) < 2:
                raise ValueError("usage: rmem tune <bank> <ch>")
            self.device.tune_memory_channel(int(rest[0]), int(rest[1]))
            self.console.print("ok")
        elif sub == "delete":
            if len(rest) < 2:
                raise ValueError("usage: rmem delete <bank> <ch>")
            self.device.delete_memory_channel(int(rest[0]), int(rest[1]))
            self.console.print("deleted")
        elif sub == "bank":
            if not rest:
                raise ValueError("usage: rmem bank <bank>")
            info = self.device.get_memory_bank_info(int(rest[0]))
            self.console.print(
                f"bank {info.bank:02d}: channels={info.channel_count} "
                f"protect={info.protect} tag={info.tag!r}"
            )
        elif sub == "bankset":
            if not rest:
                raise ValueError("usage: rmem bankset <bank> [count] [protect 0|1] [tag...]")
            bank = int(rest[0])
            count = int(rest[1]) if len(rest) > 1 else None
            protect = _on_off(rest[2]) if len(rest) > 2 else None
            tag = " ".join(rest[3:]) if len(rest) > 3 else None
            self.device.write_memory_bank(bank, channel_count=count, protect=protect, tag=tag)
            self.console.print(f"bank {bank:02d} set")
        elif sub == "bankdel":
            if not rest:
                raise ValueError("usage: rmem bankdel <bank>")
            self.device.delete_memory_bank(int(rest[0]))
            self.console.print("bank deleted")
        elif sub == "find":
            # Task 14, item 39: "extend [mem find] to live-read data once
            # #10 lands" - #10 (read_memory_bank()) landed in an earlier
            # task, so this is that extension. Deliberately kept separate
            # from "mem find" (which searches a loaded CSV's .name field)
            # rather than merged into it, mirroring the project's existing
            # mem/rmem split (see this method's own docstring) - the two
            # commands read genuinely different data sources with
            # different field layouts (MemoryChannelInfo.tag here vs.
            # MemoryChannel.name there).
            if not rest:
                raise ValueError("usage: rmem find <text> [bank]")
            needle = rest[0].strip().lower()
            banks = [int(rest[1])] if len(rest) > 1 else list(range(40))
            hits = []
            for bank in banks:
                for c in self.device.read_memory_bank(bank):
                    if c.registered and needle in c.tag.strip().lower():
                        hits.append(c)
            if not hits:
                self.console.print("(no matches)")
            for c in hits[:50]:
                freq = f"{c.frequency_hz / 1_000_000:.5f} MHz" if c.frequency_hz is not None else "?"
                self.console.print(f"{c.bank:02d}-{c.channel:02d}  {freq}  mode={c.mode}  {c.tag!r}")
            if len(hits) > 50:
                self.console.print(f"... and {len(hits) - 50} more")
        else:
            raise ValueError(f"unknown 'rmem' subcommand: {sub!r}")

    def _dispatch_search(self, args: list[str]) -> None:
        """Handles the "search ..." verb family - program-search banks
        (SE/SR/SS/SX) and the session-only SL/SU range shortcuts - see
        aor_dv10.device.DV10Device's "search banks" section."""
        if not args:
            raise ValueError(
                "usage: search write <bank> [lo_mhz] [hi_mhz] [step_hz] [step_adj_hz] "
                "[mode] [protect 0|1] [tag...] | search read <bank> | search run <bank> | "
                "search delete <bank> | search lolimit [mhz] | search hilimit [mhz]"
            )
        sub, rest = args[0].lower(), args[1:]

        def _print_bank(info):
            lo = f"{info.lower_limit_hz / 1_000_000:.4f}" if info.lower_limit_hz is not None else "?"
            hi = f"{info.upper_limit_hz / 1_000_000:.4f}" if info.upper_limit_hz is not None else "?"
            self.console.print(
                f"bank {info.bank:02d}: {lo}-{hi} MHz  step={info.step_hz}  "
                f"stepadj={info.step_adjust_hz}  mode={info.mode}  "
                f"protect={info.write_protect}  {info.tag!r}"
            )

        if sub == "write":
            if not rest:
                raise ValueError(
                    "usage: search write <bank> [lo_mhz] [hi_mhz] [step_hz] [step_adj_hz] "
                    "[mode] [protect 0|1] [tag...]"
                )
            bank = int(rest[0])
            lo = round(float(rest[1]) * 1_000_000) if len(rest) > 1 else None
            hi = round(float(rest[2]) * 1_000_000) if len(rest) > 2 else None
            step_hz = int(float(rest[3])) if len(rest) > 3 else None
            step_adj_hz = int(float(rest[4])) if len(rest) > 4 else None
            mode = rest[5] if len(rest) > 5 else None
            protect = _on_off(rest[6]) if len(rest) > 6 else False
            tag = " ".join(rest[7:]) if len(rest) > 7 else None
            self.device.write_search_bank(
                bank,
                lower_limit_hz=lo,
                upper_limit_hz=hi,
                step_hz=step_hz,
                step_adjust_hz=step_adj_hz,
                mode=mode,
                write_protect=protect,
                tag=tag,
            )
            self.console.print(f"search bank {bank:02d} set")
        elif sub == "read":
            if not rest:
                raise ValueError("usage: search read <bank>")
            _print_bank(self.device.read_search_bank(int(rest[0])))
        elif sub == "run":
            if not rest:
                raise ValueError("usage: search run <bank>")
            self.device.execute_search(int(rest[0]))
            self.console.print("search started")
        elif sub == "delete":
            if not rest:
                raise ValueError("usage: search delete <bank>")
            self.device.delete_search_bank(int(rest[0]))
            self.console.print("search bank deleted")
        elif sub == "lolimit":
            if rest:
                self.device.set_search_lower_limit(round(float(rest[0]) * 1_000_000))
            hz = self.device.get_search_lower_limit()
            self.console.print(f"{hz / 1_000_000:.4f} MHz" if hz is not None else "?")
        elif sub == "hilimit":
            if rest:
                self.device.set_search_upper_limit(round(float(rest[0]) * 1_000_000))
            hz = self.device.get_search_upper_limit()
            self.console.print(f"{hz / 1_000_000:.4f} MHz" if hz is not None else "?")
        else:
            raise ValueError(f"unknown 'search' subcommand: {sub!r}")

    @staticmethod
    def _parse_bank_link_tokens(tokens: list[str]):
        """Shared by "scan swrite/mwrite/banklink": trailing bank-number
        tokens, or the single literal "clear" to send an explicit empty
        list (BK's "99" disable-all shorthand) - see
        DV10Device.write_search_scan_group()'s docstring for why this is
        NOT the same thing as omitting the bank_link argument entirely
        (which this helper is simply never asked to produce - the caller
        passes None itself when there are no tokens at all)."""
        if tokens == ["clear"]:
            return []
        return [int(t) for t in tokens]

    def _dispatch_scan(self, args: list[str]) -> None:
        """Handles the "scan ..." verb family - search-side (SG) and
        memory-side (MG) scan groups, plus their shared standalone AS
        (auto-store) and BK (bank-link) sub-commands - see
        aor_dv10.device.DV10Device's "scan groups" section."""
        if not args:
            raise ValueError(
                "usage: scan sread <group> | "
                "scan swrite <group> [delay_ds] [free_s] [autostore 0|1] [bank...|clear] | "
                "scan mread <group> | "
                "scan mwrite <group> [delay_ds] [free_s] [bank...|clear] | "
                "scan autostore [on|off] | scan banklink [bank...|clear]"
            )
        sub, rest = args[0].lower(), args[1:]

        def _print_group(info, *, kind: str) -> None:
            self.console.print(
                f"{kind} group {info.group:02d}: delay={info.delay_ds} free={info.free_time_s} "
                f"autostore={info.auto_store} banks={list(info.bank_link)}"
            )

        if sub == "sread":
            if not rest:
                raise ValueError("usage: scan sread <group>")
            _print_group(self.device.read_search_scan_group(int(rest[0])), kind="search")
        elif sub == "swrite":
            if not rest:
                raise ValueError(
                    "usage: scan swrite <group> [delay_ds] [free_s] [autostore 0|1] [bank...|clear]"
                )
            group = int(rest[0])
            delay_ds = int(rest[1]) if len(rest) > 1 else None
            free_s = int(rest[2]) if len(rest) > 2 else None
            auto_store = _on_off(rest[3]) if len(rest) > 3 else None
            bank_link = self._parse_bank_link_tokens(rest[4:]) if len(rest) > 4 else None
            self.device.write_search_scan_group(
                group, delay_ds=delay_ds, free_time_s=free_s,
                auto_store=auto_store, bank_link=bank_link,
            )
            self.console.print(f"search scan group {group:02d} set")
        elif sub == "mread":
            if not rest:
                raise ValueError("usage: scan mread <group>")
            _print_group(self.device.read_memory_scan_group(int(rest[0])), kind="memory")
        elif sub == "mwrite":
            if not rest:
                raise ValueError("usage: scan mwrite <group> [delay_ds] [free_s] [bank...|clear]")
            group = int(rest[0])
            delay_ds = int(rest[1]) if len(rest) > 1 else None
            free_s = int(rest[2]) if len(rest) > 2 else None
            bank_link = self._parse_bank_link_tokens(rest[3:]) if len(rest) > 3 else None
            self.device.write_memory_scan_group(
                group, delay_ds=delay_ds, free_time_s=free_s, bank_link=bank_link,
            )
            self.console.print(f"memory scan group {group:02d} set")
        elif sub == "autostore":
            if rest:
                self.device.set_auto_store(_on_off(rest[0]))
            self.console.print("on" if self.device.get_auto_store() else "off")
        elif sub == "banklink":
            if rest:
                self.device.set_bank_link(self._parse_bank_link_tokens(rest))
            self.console.print(self.device.get_bank_link())
        else:
            raise ValueError(f"unknown 'scan' subcommand: {sub!r}")

    def _dispatch_pass(self, args: list[str]) -> None:
        """Handles the "pass ..." verb family - pass frequencies (PW mark
        / PR list / PD delete), the list of frequencies VFO search or a
        program search should skip past instead of stopping on - see
        aor_dv10.device.DV10Device's "pass frequencies" section."""
        if not args:
            raise ValueError(
                "usage: pass mark [mhz] | pass mark bank <bank> [mhz] | "
                "pass mark allbanks <mhz> | pass list [bank] | pass delete | "
                "pass delete bank <bank> [index] | pass delete allbanks"
            )
        sub, rest = args[0].lower(), args[1:]

        if sub == "mark":
            if rest and rest[0].lower() == "bank":
                if len(rest) < 2:
                    raise ValueError("usage: pass mark bank <bank> [mhz]")
                bank = int(rest[1])
                freq = round(float(rest[2]) * 1_000_000) if len(rest) > 2 else None
                self.device.mark_pass_frequency(frequency_hz=freq, bank=bank)
            elif rest and rest[0].lower() == "allbanks":
                if len(rest) < 2:
                    raise ValueError("usage: pass mark allbanks <mhz>")
                freq = round(float(rest[1]) * 1_000_000)
                self.device.mark_pass_frequency(frequency_hz=freq, all_banks=True)
            elif rest:
                freq = round(float(rest[0]) * 1_000_000)
                self.device.mark_pass_frequency(frequency_hz=freq)
            else:
                self.device.mark_pass_frequency()
            self.console.print("marked")
        elif sub == "list":
            bank = int(rest[0]) if rest else None
            entries = self.device.list_pass_frequencies(bank=bank)
            used = [e for e in entries if e.frequency_hz is not None]
            for e in used:
                self.console.print(f"{e.index:02d}: {e.frequency_hz / 1_000_000:.4f} MHz")
            self.console.print(f"({len(used)} of {len(entries)} slots used)")
        elif sub == "delete":
            if rest and rest[0].lower() == "bank":
                if len(rest) < 2:
                    raise ValueError("usage: pass delete bank <bank> [index]")
                bank = int(rest[1])
                index = int(rest[2]) if len(rest) > 2 else None
                self.device.delete_pass_frequencies(bank=bank, index=index)
            elif rest and rest[0].lower() == "allbanks":
                self.device.delete_pass_frequencies(all_banks=True)
            elif not rest:
                self.device.delete_pass_frequencies()
            else:
                raise ValueError(
                    "usage: pass delete | pass delete bank <bank> [index] | pass delete allbanks"
                )
            self.console.print("deleted")
        else:
            raise ValueError(f"unknown 'pass' subcommand: {sub!r}")

    _WEEKDAY_BITS = {
        "sun": 1, "mon": 2, "tue": 4, "wed": 8, "thu": 16, "fri": 32, "sat": 64,
    }

    def _dispatch_timer(self, args: list[str]) -> None:
        """Handles the "timer ..." verb family - TR, the scheduled
        recording/alarm timer - see aor_dv10.timer's module docstring
        for the significant spec-reconstruction caveats (the AR-DV1 spec
        PDF's own TR table entry is internally inconsistent) before
        relying on this for anything real. A friendlier "Schedule" panel
        (CLI or web) is left for later - this is deliberately the
        raw-fields version, not a polished one."""
        def _print_timer(t: RecordingTimer) -> None:
            self.console.print(
                f"action={t.action} type={t.timer_type} repeat={t.repeat} "
                f"mode={t.receive_mode} start={t.start} end={t.end} "
                f"weekdays={list(t.weekdays)} volume={t.alarm_volume}"
            )

        if not args:
            _print_timer(self.device.read_recording_timer())
            return
        sub, rest = args[0].lower(), args[1:]

        if sub == "off":
            self.device.write_recording_timer(RecordingTimer(action="off"))
            self.console.print("timer deactivated")
            return
        if sub == "set":
            if len(rest) < 4:
                raise ValueError(
                    "usage: timer set <target> <once|weekly> <start> <end> "
                    "[alarm|recording] [days] [volume]"
                )
            target, repeat, start, end = rest[0], rest[1], rest[2], rest[3]
            action = rest[4] if len(rest) > 4 else "recording"
            days_arg = rest[5] if len(rest) > 5 else None
            volume = int(rest[6]) if len(rest) > 6 else None

            if target == "vs":
                receive_mode = receive_mode_vfo_search()
            elif target.startswith("vfo:"):
                receive_mode = receive_mode_vfo(target.split(":", 1)[1])
            elif target.startswith("bank:"):
                receive_mode = receive_mode_search_bank(int(target.split(":", 1)[1]))
            elif target.startswith("scan:"):
                receive_mode = receive_mode_memory_scan(int(target.split(":", 1)[1]))
            elif target.startswith("ch:"):
                bank_s, _, ch_s = target.split(":", 1)[1].partition("-")
                receive_mode = receive_mode_memory_channel(int(bank_s), int(ch_s))
            else:
                raise ValueError(
                    f'unknown target {target!r} - expected "vfo:A", "vs", "bank:<n>", '
                    f'"ch:<bank>-<ch>", or "scan:<n>"'
                )

            if repeat not in ("once", "weekly"):
                raise ValueError('repeat must be "once" or "weekly"')
            weekdays: tuple = ()
            if days_arg and days_arg != "-":
                try:
                    weekdays = tuple(self._WEEKDAY_BITS[d.strip().lower()] for d in days_arg.split(","))
                except KeyError as exc:
                    raise ValueError(f"unknown weekday {exc.args[0]!r} - use sun,mon,tue,wed,thu,fri,sat")

            self.device.write_recording_timer(
                RecordingTimer(
                    action=action,
                    repeat=repeat,
                    receive_mode=receive_mode,
                    start=start,
                    end=end,
                    weekdays=weekdays,
                    alarm_volume=volume,
                )
            )
            _print_timer(self.device.read_recording_timer())
            return
        if sub in ("show", "status"):
            _print_timer(self.device.read_recording_timer())
            return
        raise ValueError(f"unknown 'timer' subcommand: {sub!r}")

    def _dispatch_sd(self, args: list[str]) -> None:
        """Handles the "sd ..." verb family - SD card management:
        SD DIR/INF/PST/REC/PLY/RSQ/MMW/MMR. See
        src/aor_dv10/device.py's "SD card management" section for the
        underlying API and its caveats (notably the misspelled SYSYEM
        backup token, and the deliberately-raw-only SD LGR/SD TYP, which
        the spec itself marks "No function" on this receiver)."""
        if not args:
            raise ValueError(
                "usage: sd dir|info|status|rec|play|rsq|backup|restore ..."
            )
        sub, rest = args[0].lower(), args[1:]

        if sub == "dir":
            files = self.device.sd_dir()
            if not files:
                self.console.print("(no files)")
                return
            for f in files:
                detail = (
                    f"duration={f.duration}"
                    if f.duration is not None
                    else f"size={f.size_bytes}"
                )
                ext = f".{f.extension}" if f.extension else ""
                self.console.print(f"{f.name}{ext}  {detail}  {f.timestamp}")
            return

        if sub == "info":
            info = self.device.sd_info()
            self.console.print(
                f"free={info.free_kb}KB (~{info.free_hours}h)  total={info.total_kb}KB"
            )
            return

        if sub == "status":
            digit = self.device.sd_status()
            self.console.print(f"{digit} - {SD_CARD_STATUS.get(digit, 'unknown')}")
            return

        if sub == "rec":
            if not rest or rest[0].lower() not in ("start", "stop"):
                raise ValueError("usage: sd rec start|stop")
            if rest[0].lower() == "start":
                self.device.sd_record_start()
                self.console.print("recording started")
            else:
                # AR-DV1's documented remote stop (SD REC /) is not
                # supported on the AR-DV10 - sending it wedges the radio
                # (recording there stops with the front-panel ● key only).
                # Deny instead of poking a command the device can't handle.
                if self.device.device_family() == "DV10":
                    raise ValueError(
                        "sd rec stop is not supported on the AR-DV10 - "
                        "stop recording with the receiver's front-panel ● (record) key"
                    )
                self.device.sd_record_stop()
                self.console.print("recording stopped")
            return

        if sub == "play":
            if not rest:
                raise ValueError("usage: sd play <name>|stop")
            if rest[0].lower() == "stop":
                self.device.sd_play_stop()
                self.console.print("playback stopped")
            else:
                self.device.sd_play(rest[0])
                self.console.print(f"playing {rest[0]}")
            return

        if sub == "rsq":
            if not rest:
                skip = self.device.get_sd_squelch_skip()
                self.console.print(f"squelch skip: {'on' if skip == '1' else 'off'}")
                return
            if rest[0].lower() not in ("on", "off"):
                raise ValueError("usage: sd rsq [on|off]")
            self.device.set_sd_squelch_skip(rest[0].lower() == "on")
            self.console.print(f"squelch skip set to {rest[0].lower()}")
            return

        if sub == "backup":
            if not rest:
                raise ValueError(
                    "usage: sd backup <kind> - one of SRCHBK/SRCHGRP/MEMCH/SCANGRP/SYSYEM"
                )
            self.device.sd_backup(rest[0])
            self.console.print(f"backed up {rest[0]}")
            return

        if sub == "restore":
            if not rest:
                raise ValueError("usage: sd restore <name>")
            self.device.sd_restore(rest[0])
            self.console.print(f"restored {rest[0]}")
            return

        raise ValueError(f"unknown 'sd' subcommand: {sub!r}")

    def _dispatch_scope(self, args: list[str]) -> None:
        """Handles the "scope ..." verb family - FD/GL frequency scope,
        printed as a text sparkline. See
        aor_dv10.device.DV10Device's "Frequency scope" section for the
        significant caveat this whole area carries: no known way to enter
        the "scope mode" both commands document as a precondition, found
        anywhere in any AR-DV10/AR-DV1 reference document (including the
        full operating manual) - expect a DV10ProtocolError (result code
        30) on real hardware unless/until that turns out to be wrong."""
        if not args or args[0].lower() not in ("fast", "normal"):
            raise ValueError("usage: scope fast|normal")
        sub = args[0].lower()

        # Coarse, dependency-free sparkline: 8 levels, no external charting
        # library - good enough for a terminal-only quick look.
        ramp = " .:-=+*#%@"

        def _spark(values: list) -> str:
            if not values:
                return "(no data)"
            lo, hi = min(values), max(values)
            if hi == lo:
                return ramp[-1] * len(values)
            span = hi - lo
            out = []
            for v in values:
                idx = round((v - lo) / span * (len(ramp) - 1))
                out.append(ramp[idx])
            return "".join(out)

        if sub == "fast":
            dbm_values = self.device.read_scope_data_fast()
            self.console.print(_spark(dbm_values))
            if dbm_values:
                self.console.print(
                    f"{len(dbm_values)} points, {min(dbm_values)}..{max(dbm_values)} dBm"
                )
            return

        lines = self.device.read_scope_data_normal()
        if not lines:
            self.console.print("(no data)")
            return
        levels = [int(line.level_raw) for line in lines]
        self.console.print(_spark(levels))
        lo_mhz = lines[0].frequency_hz / 1_000_000
        hi_mhz = lines[-1].frequency_hz / 1_000_000
        self.console.print(f"{len(lines)} points, {lo_mhz:.5f}-{hi_mhz:.5f} MHz")

    def _dispatch_select(self, args: list[str]) -> None:
        """Handles the "select ..." verb family - a purely client-side,
        AR8200-inspired select-scan list. See
        aor_dv10.selectscan's module docstring: nothing in
        the AR-DV1 spec documents an equivalent wire-level feature, so
        this loops tune_memory_channel() (MR) over a session-only list
        rather than talking to any dedicated select-scan command."""
        if not args:
            raise ValueError(
                "usage: select add <bank> <ch> | select remove <bank> <ch> | "
                "select list | select clear | select run [cycles] [dwell_s]"
            )
        sub, rest = args[0].lower(), args[1:]

        if sub == "add":
            if len(rest) < 2:
                raise ValueError("usage: select add <bank> <ch>")
            self.select_scan_list.add(int(rest[0]), int(rest[1]))
            self.console.print(f"added {int(rest[0]):02d}-{int(rest[1]):02d} "
                                f"({len(self.select_scan_list)} in list)")
            return

        if sub == "remove":
            if len(rest) < 2:
                raise ValueError("usage: select remove <bank> <ch>")
            removed = self.select_scan_list.remove(int(rest[0]), int(rest[1]))
            self.console.print("removed" if removed else "(not in list)")
            return

        if sub == "list":
            if not self.select_scan_list.entries:
                self.console.print("(empty)")
                return
            for bank, channel in self.select_scan_list:
                self.console.print(f"{bank:02d}-{channel:02d}")
            return

        if sub == "clear":
            self.select_scan_list.clear()
            self.console.print("cleared")
            return

        if sub == "run":
            cycles = int(rest[0]) if len(rest) > 0 and rest[0].lower() != "none" else None
            dwell_s = float(rest[1]) if len(rest) > 1 else 2.0
            entries = list(self.select_scan_list.entries)
            try:
                for bank, channel in run_select_scan(
                    self.device.tune_memory_channel, entries, dwell_s=dwell_s, cycles=cycles
                ):
                    self.console.print(f"-> {bank:02d}-{channel:02d}")
            except KeyboardInterrupt:
                self.console.print("(stopped)")
            return

        raise ValueError(f"unknown 'select' subcommand: {sub!r}")

    def _dispatch_debug(self, args: list[str]) -> None:
        """Protocol tracing: every raw TX/RX line to/from the
        device, byte-exact via repr() - so a stray space, an unexpected
        CR/LF, or a non-ASCII byte a real unit sends back is visible
        rather than silently stripped or decoded away. The point is
        pasting exact, unambiguous communication back for diagnosis:
        "debug on" to watch it live, "debug last [N]" to pull recent
        history at any time (works even without "debug on" - see
        DV10Device.trace_lines()), "debug save <path>" to dump it all to
        a file that's easy to attach or paste from."""
        if not args:
            raise ValueError(
                "usage: debug on [logfile] | debug off | debug last [N] | debug save <path>"
            )
        sub, rest = args[0].lower(), args[1:]

        if sub == "on":
            self.enable_debug(rest[0] if rest else None)
            msg = "Tracing ON (dim lines below are raw TX/RX)"
            if rest:
                msg += f" - also logging to {rest[0]}"
            self.console.print(f"[green]{msg}[/green]")
        elif sub == "off":
            self.disable_debug()
            self.console.print("[green]Tracing OFF[/green] (recent history still available via 'debug last')")
        elif sub == "last":
            n = int(rest[0]) if rest else 20
            lines = self.device.trace_lines(n)
            if not lines:
                self.console.print("(no trace recorded yet)")
            for line in lines:
                self.console.print(line)
        elif sub == "save":
            if not rest:
                raise ValueError("usage: debug save <path>")
            count = self.device.save_trace(rest[0])
            self.console.print(f"Wrote {count} trace lines to {rest[0]}")
        else:
            raise ValueError(f"unknown 'debug' subcommand: {sub!r}")

    def _dispatch_mem(self, args: list[str]) -> None:
        """Handles the "mem ..." verb family - loading/searching/exporting
        an "AR-DV10 Connect" memory-bank backup CSV, and tuning to a
        loaded channel by replaying its frequency/mode/step through the
        already-confirmed f/m/step writes. Deliberately separate from
        "rmem ..." (the live MX/MA/MR/MW/MB/MQ wire commands - see
        _dispatch_rmem()) - see aor_dv10.memory's module
        docstring and aor_dv10.device.MemoryChannelInfo's docstring for
        why the two field layouts aren't interchangeable."""
        if not args:
            raise ValueError(
                "usage: mem load <path> | mem find <text> | mem list [bank] | "
                "mem goto <bank>-<ch> | mem export <path>"
            )
        sub, rest = args[0].lower(), args[1:]

        if sub == "load":
            if not rest:
                raise ValueError("usage: mem load <path>")
            path = rest[0]
            with open(path, "rb") as f:
                text = f.read().decode("utf-8-sig")
            self.memory_banks, self.memory_channels = parse_backup_csv(text)
            programmed = sum(1 for c in self.memory_channels if not c.is_empty)
            self.console.print(
                f"Loaded {len(self.memory_banks)} banks / {len(self.memory_channels)} "
                f"channel slots ({programmed} programmed) from {path}"
            )
        elif sub == "find":
            self._require_memory_loaded()
            if not rest:
                raise ValueError("usage: mem find <text>")
            needle = " ".join(rest).strip().lower()
            hits = [
                c for c in self.memory_channels
                if not c.is_empty and needle in c.name.strip().lower()
            ]
            if not hits:
                self.console.print("(no matches)")
            for c in hits[:50]:
                self.console.print(
                    f"{c.bank_channel}  {c.frequency_mhz:9.5f} MHz  {c.mode}  {c.name.strip()}"
                )
            if len(hits) > 50:
                self.console.print(f"... and {len(hits) - 50} more")
        elif sub == "list":
            self._require_memory_loaded()
            bank_filter = int(rest[0]) if rest else None
            rows = [
                c for c in self.memory_channels
                if not c.is_empty and (bank_filter is None or c.bank == bank_filter)
            ]
            for c in rows[:100]:
                self.console.print(
                    f"{c.bank_channel}  {c.frequency_mhz:9.5f} MHz  {c.mode}  {c.name.strip()}"
                )
            if len(rows) > 100:
                self.console.print(f"... and {len(rows) - 100} more (use 'mem find' to narrow)")
            elif not rows:
                self.console.print("(no programmed channels)" if bank_filter is None else
                                    f"(no programmed channels in bank {bank_filter:02d})")
        elif sub == "goto":
            self._require_memory_loaded()
            if not rest:
                raise ValueError("usage: mem goto <bank>-<ch>")
            bank_str, _, ch_str = rest[0].partition("-")
            try:
                bank, channel = int(bank_str), int(ch_str)
            except ValueError:
                raise ValueError(f'expected "<bank>-<ch>", e.g. "00-05", got {rest[0]!r}')
            match = next(
                (c for c in self.memory_channels if c.bank == bank and c.channel == channel),
                None,
            )
            if match is None:
                raise ValueError(f"no such channel: {bank:02d}-{channel:02d}")
            if match.is_empty:
                raise ValueError(f"channel {match.bank_channel} is unprogrammed")
            self.device.enter_vfo_mode("A")
            self.device.set_frequency_hz(match.frequency_hz)
            if match.step_hz:
                self.device.set_frequency_step_hz(match.step_hz)
            if match.mode and len(match.mode) == 3:
                # CSV mode is "<receiving><digital-select><analog-select>";
                # set_mode() wants "<digital-select><analog-select>" - see
                # MemoryChannel.describe_mode() and DV10Device.set_mode().
                self.device.set_mode(match.mode[1:3])
            self.console.print(
                f"Tuned to {match.bank_channel} ({match.name.strip() or 'unnamed'}): "
                f"{match.frequency_mhz:.5f} MHz"
            )
        elif sub == "export":
            self._require_memory_loaded()
            if not rest:
                raise ValueError("usage: mem export <path>")
            path = rest[0]
            out = write_backup_csv(self.memory_banks, self.memory_channels)
            with open(path, "wb") as f:
                f.write(out.encode("utf-8"))
            self.console.print(f"Wrote {len(self.memory_channels)} channel slots to {path}")
        else:
            raise ValueError(f"unknown 'mem' subcommand: {sub!r}")

    def _require_memory_loaded(self) -> None:
        if not self.memory_channels:
            raise ValueError("no memory database loaded - use 'mem load <path>' first")
