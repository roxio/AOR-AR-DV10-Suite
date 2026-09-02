"""In-process fake DV10 for development and tests without real hardware.

This is intentionally a *behavioural* stand-in, not a byte-exact clone of the
firmware: it understands the command mnemonics from the official AOR command
list and gives plausible responses (echoing writes, returning stored state on
reads) so the protocol layer, CLI, and GUI/web panel can all be built and
exercised end-to-end before hardware is available. It should be treated as a
convenience, not a source of protocol truth.
"""

from __future__ import annotations

import re
from collections import deque
from typing import Deque, Optional

from .base import Transport

_CRLF_VARIANTS = (b"\r\n", b"\r", b"\n")

# Mirrors aor_dv10.device._VFO_MODE_WRITE_CODES (kept independent to avoid
# a transport->device import) - commands whose writes are rejected outside
# VFO mode, confirmed against real hardware. Deliberately NOT including
# "MD" (never independently confirmed) or "VF" (confirmed to itself be the
# way *into* VFO mode - gating it on already being in VFO mode would be
# backwards).
_VFO_MODE_CODES = {"RF", "AC", "SQ", "AT", "RG", "ST", "SH"}

# Numeric RE result codes used to simulate the "RE 1" (result-code
# prefixing) behaviour confirmed against real hardware - see
# aor_dv10.protocol.codec.RESULT_CODES.
_RESULT_CODE_FOR_KIND = {
    "cannot_set": 30,  # e.g. a VFO-mode-gated write while browsing memory
    "format": 40,  # e.g. VF given something other than a VFO letter
    "range": 50,
    "not_supported": 60,  # e.g. AG (read or write) - confirmed real DV10 behaviour
}

_VFO_LETTERS = {"A", "B", "Z"}

# Mirrors aor_dv10.device.DIGITAL_MODES / ANALOG_MODES keys (kept
# independent to avoid a transport->device import) - used to validate MD
# writes the same way the real firmware does, see _handle() below.
_DIGITAL_MODE_CODES = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "F"}
_ANALOG_MODE_CODES = {"0", "1", "2", "3", "4", "5", "6"}


class SimulatorTransport(Transport):
    """A tiny state machine that answers DV10 commands over an in-memory queue."""

    def __init__(self) -> None:
        self._open = False
        self._inbox: Deque[bytes] = deque()
        # Confirmed against real hardware: writes to tuning/level parameters
        # are rejected while the receiver is browsing a memory channel
        # rather than in VFO mode. This is a Python-level knob (set sim.vfo_mode =
        # False) purely for exercising that behaviour in tests/demos; a
        # successful "VF <letter>" write (see _handle) flips it back on,
        # mirroring the newly-confirmed real "VF A" success.
        self.vfo_mode = True
        self.state = {
            "RF": "0145.50000",  # receive frequency, decimal MHz - confirmed against real hardware
            "MD": "0F0",  # mode/bandwidth code - confirmed against real hardware (meaning of the 3 chars still undecoded)
            "SQ": "0",  # squelch MODE selector (0=Auto,1=Noise,2=Level) - confirmed via AR-DV3 spec
            "AG": "020",
            "AC": "1",
            "AT": "0",
            "RG": "099",  # AR-DV1 spec range is 000-110, default 099
            "LM": "1001",  # S-meter: vvvq = -vvv dB (100) + squelch state (1=open) - confirmed format
            "LQ": "050",
            "NQ": "020",
            "RE": "0",
            "BP": "2",  # AR-DV1 spec is a single digit 0-7, default 2
            "VR": "1.00",
            "WI": "AR-DV10",
            "RN": "SIMULATED0001",
            "RX": "1",
            # Manual-sourced defaults, added alongside device.py's
            # manual-sourced expansion - plausible defaults so the GUI/CLI
            # have something to show, not values confirmed against real
            # hardware.
            # ST default in the confirmed kHz-decimal wire format
            # (STggg.gg) - see DV10Device.get_frequency_step_hz()/
            # set_frequency_step_hz(). 12.50 kHz == 12500 Hz, matching
            # this simulator's previous bare-integer default.
            "ST": "012.50",
            # SH default corrected: the AR-DV1 spec's own default for
            # the standalone SH command is "000.00" (kHz-decimal), not a
            # bare "0" - see
            # DV10Device.get_step_adjust_hz()/set_step_adjust_hz().
            "SH": "000.00",
            "CI": "0",
            "CN": "01",  # AR-DV1 spec is a 1-based CTCSS-table index, not a literal Hz string
            "DI": "0",
            "DS": "023",
            "CC": "00",
            "CM": "0",
            "OT": "1+2",
            "PC": "000",
            "PM": "0",
            "NC": "00",
            "NM": "0",
            "DC": "00000",
            "SI": "0",
            "SC": "2000",
            "OF": "00",  # slot 00 + omitted sign (offset reception off) - see set_offset_slot()
            # "OL" is not a flat state entry here, see self.offset_freqs
            # below - OL reads/writes always require an explicit slot
            # number (OLnn), per the AR-DV1 spec.
            "PO": "0",
            "PP": "0000",  # AR-DV1 spec is bbcc with no separator
            "TI": "05",
            "AV": "05",
            "DA": "01.00",
            "LN": "30",
            "LB": "0",
            "SP": "00",
            "DT": "2601010000",
            "ZI": "0000",
            "PT": "0",
            # SL/SU/AS/BK are all spec-confirmed both-directions
            # ("Setting / Reading completed") and simple single-value
            # fields, so they need no special-case handling in _handle()
            # below, unlike the composite SE/SG/MG/PW/PR/PD commands.
            "SL": "0000.0000",  # search-range lower limit, session-only per the spec's own Remarks
            "SU": "0000.0000",  # search-range upper limit, session-only per the spec's own Remarks
            "AS": "0",  # standalone auto-store flag
            "BK": "99",  # standalone bank-link list ("99" = none linked)
            # KL/IF/DL/FR are also simple single-value fields, same
            # "no special-case handling needed" category as SL/SU/AS/BK
            # above. IF's default ("3") is FM's own spec default
            # ("default: 3 FM") - the simulator doesn't model
            # per-mode IF-bandwidth validation (result code 30, "Invalid
            # decode mode"), just stores/echoes whatever was last written.
            "KL": "0",  # key backlight color, spec default OFF
            "IF": "3",  # IF bandwidth selector, spec default (FM: 15KHz)
            "DL": "020",  # standalone delay time (deciseconds), spec default
            "FR": "00",  # standalone free time (seconds), spec default OFF
        }
        # Per-slot offset-frequency table (OL, keyed by 2-digit slot) -
        # see the AR-DV1-spec-confirmed OL handling in _handle() below.
        # Slot "00" is fixed at 0Hz (offset reception off) and slots
        # "20"-"39" are modelled as read-only factory presets, matching
        # the spec's "cannot be changed" note.
        self.offset_freqs = {f"{i:02d}": "0000.00000" for i in range(40)}
        # Live memory channels/banks (MX/MA/MR/MW/MB/MQ) - keyed by
        # "bbcc"/"bb" strings, present only once written (unlike
        # offset_freqs above, which pre-populates all 40 slots - a memory
        # channel that's never been written is genuinely "not registered,"
        # not "registered with a zero value", so absence from this dict IS
        # that state - see _handle()'s MA/MW handling below.
        self.memory_channels: dict = {}
        self.memory_banks: dict = {}
        # Search banks / scan groups / pass frequencies (SE/SR/SS/SX/SL/SU,
        # SG/MG/AS/BK, PW/PR/PD) - see _handle()'s handling below. SL/SU/
        # AS/BK are simple enough (single value, spec-confirmed "may be
        # used alone") to just live in self.state and go through the
        # generic bare-read/write fallback at the bottom of _handle() - no
        # special casing needed for those four.
        # One RF/ST/SH/MD snapshot per VFO letter, independent of
        # self.state's own RF/ST/SH/MD (which track whichever VFO is
        # CURRENTLY receiving) - see the "VF" and "VI" _handle() cases
        # below. Defaults match self.state's own RF/ST/SH/MD defaults.
        self.vfos: dict = {
            v: {"RF": "0145.50000", "ST": "012.50", "SH": "000.00", "MD": "0F0"}
            for v in _VFO_LETTERS
        }
        # VE: a single, receiver-wide (not per-VFO, not per-group) delay/
        # free-time/auto-store setting used by VS - see the "VE"/"VS"
        # _handle() cases below.
        self.vfo_search_settings: dict = {"DL": "20", "FR": "00", "AS": "0"}
        # TR, the scheduled recording/alarm timer - see aor_dv10.timer's
        # module docstring for the significant
        # spec-reconstruction caveats. Defaults match the AR-DV1 spec's
        # own Default line exactly (WE/AG have no stated default, so
        # start unset/None here).
        self.recording_timer: dict = {
            "XE": "0", "TY": "0", "RP": "0", "RM": "VFA",
            "TS": "01010000", "TE": "01010000", "WE": None, "AG": None,
        }
        self.search_banks: dict = {}  # "bb" -> {"SL","SU","ST","SH","MD","PT","TT"}
        self.scan_groups_search: dict = {}  # "gg" -> {"DL","FR","AS","BK"} (SG)
        self.scan_groups_memory: dict = {}  # "gg" -> {"DL","FR","BK"} (MG, no AS)
        self.pass_freqs_vfo: dict = {}  # "nn" (00-49) -> "ffff.ffff", sparse
        self.pass_freqs_bank: dict = {}  # "bb" -> {"nn": "ffff.ffff"}, sparse
        # SD card management. sd_files is keyed by
        # "NAME.EXT" (upper-cased extension as-stored); each entry has
        # either "duration" (WAV) or "size" (everything else) set, mirroring
        # the two per-file line shapes SD DIR documents - see
        # aor_dv10.device.DV10Device.sd_dir()'s docstring. sd_error_injection
        # is a test-only, one-shot seam: set it to one of the documented SD
        # error tokens (CARDBUSY/NOCARD/FAT12/NOFILE/CARDFULL) and the next
        # SD DIR/INF/PST/REC/PLY/MMW/MMR command returns that token instead
        # of its normal behaviour, then clears it - there's no real "card
        # state" modelled here otherwise (no busy/full/wrong-format
        # simulation), so this is how tests exercise the documented error
        # paths without one.
        self.sd_files: dict = {}
        self.sd_recording: Optional[str] = None
        self.sd_playing: Optional[str] = None
        self.sd_error_injection: Optional[str] = None
        # Frequency scope (FD/GL). Both are
        # documented as only succeeding while the receiver is "in scope
        # mode" (result code 30, "Not in scope mode", otherwise) - and no
        # command or front-panel procedure to enter that mode was found in
        # any reference document, including the full operating manual (see
        # aor_dv10.device's "Frequency scope" section docstring). There is
        # no real scope-mode state machine to model here, so - mirroring
        # sd_error_injection's precedent - this is a test-only, manually-set
        # toggle: leave it False to exercise the documented "not in scope
        # mode" error path, or set it True to get cooked deterministic fake
        # scan data back instead.
        self.scope_mode: bool = False

    # -- Transport interface -------------------------------------------------

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False
        self._inbox.clear()

    @property
    def is_open(self) -> bool:
        return self._open

    def write_line(self, data: bytes) -> None:
        if not self._open:
            from .base import TransportError

            raise TransportError("Simulator transport is not open")
        line = data
        for term in _CRLF_VARIANTS:
            line = line.replace(term, b"")
        line = line.strip()
        if not line:
            return  # a bare [CR] resync ping - nothing to answer
        for reply in self._handle(line.decode("ascii", errors="replace")):
            self._inbox.append(reply.encode("ascii") + b"\r")

    def read_line(self, timeout: float) -> Optional[bytes]:
        if self._inbox:
            return self._inbox.popleft()
        return None

    # -- Fake firmware ---------------------------------------------------
    #
    # Framing confirmed against real hardware: no space between a
    # command's code and its value, in either direction; unsupported/error
    # responses are a bare "?" by default, or "<numeric code>?" once "RE 1"
    # has been sent (see _error() below); and at least one command (WI)
    # responds with just the value, no code echo - we replicate that one
    # deliberately so anything exercising the simulator also exercises that
    # code path.
    #
    # Real-hardware bug: with "RE" left on from an earlier session, a
    # crash on real hardware showed RE prefixes EVERY response, not just
    # error ones - e.g. a
    # plain "RF" read comes back "20RF0145.50000" (see
    # aor_dv10.protocol.codec's module docstring for the full story). That
    # crash also retroactively clarified that a successful write's ack body
    # is actually EMPTY (not a bare-code echo as first assumed - the two
    # were indistinguishable in CLI output with RE off, since
    # Response.code always shows the *sent* code regardless of what's
    # actually on the wire; RE's own "20"-only ack is what broke the tie).
    # _respond() below implements this: every successful response is
    # "<20 if RE is on><the plain RE-off body, which may be empty>".

    _ALL_CODES = (
        "EX", "ZP", "QP", "RF", "MD", "SQ", "AG", "AC", "AT", "RG", "LM",
        "LQ", "NQ", "BP", "VR", "WI", "RN", "RX", "RE", "VF",
        # Manual-sourced expansion - see aor_dv10.device's
        # manual-sourced tables for what's still wire-unconfirmed.
        "ST", "SH", "CI", "CN", "DI", "DS", "CC", "CM", "OT", "PC", "PM",
        "NC", "NM", "DC", "SI", "SC", "OF", "OL", "PO", "PP", "TI",
        "AV", "DA", "LN", "LB", "SP", "DT", "ZI", "PT", "RS", "ZJ", "ZK", "VI",
        "MM",
        "MX", "MA", "MR", "MW", "MB", "MQ",  # live memory channels/banks
        # search banks, scan groups, pass frequencies
        "SE", "SR", "SS", "SX", "SL", "SU", "SG", "MG", "AS", "BK", "PW", "PR", "PD",
        # smaller typed commands - simple single-value fields, handled
        # generically like the line above.
        "KL", "IF", "DL", "FR",
        # atomic VFO / VFO-search / VFO-info
        "VE", "VS",
        "TR",
        # SD card management. Multi-word candidates matched by the same
        # startswith() scan above - safe because none of them is a prefix
        # of another (they differ by the 3rd/6th character), and there's
        # no bare "SD" command to collide with in the first place.
        "SD DIR", "SD INF", "SD PST", "SD REC", "SD PLY", "SD RSQ",
        "SD MMW", "SD MMR",
        # frequency scope. Bare 2-letter codes, unlike the "SD "-prefixed
        # family above.
        "FD", "GL",
    )

    def _respond(self, body: str) -> str:
        """Wrap a normal (non-error) response body with the RE-confirmed
        numeric OK prefix ("20") when result-code prefixing is active - see
        the module-level note above (RE prefixes every response, not just
        errors). With RE off (default), returns body unchanged."""
        if self.state.get("RE") == "1":
            return f"20{body}"
        return body

    def _error(self, kind: str) -> str:
        """A rejection response: bare "?" by default, or "<code>?" once "RE
        1" is active - mirrors the real-hardware-confirmed RE result-code
        prefixing behaviour."""
        if self.state.get("RE") == "1":
            return f"{_RESULT_CODE_FOR_KIND[kind]}?"
        return "?"

    @staticmethod
    def _parse_fields(text: str, *, tag_field: str | None = None) -> dict:
        """Mirrors aor_dv10.device._parse_composite_fields() - split a
        space-separated "XXvalue XXvalue ..." composite request/response
        into {code: value}. Kept independent to avoid a
        transport->device import, same rationale as _VFO_MODE_CODES
        above.

        ``tag_field``: same
        "rest of the line" handling as the device-side function this
        mirrors - without it, an incoming MX/MW/SE write with a tag
        containing a space (e.g. "TT2M BAND") gets silently truncated to
        the first word right here, in the simulator's own state, before
        the client ever gets a chance to read it back - so the
        device.py-side fix alone isn't sufficient; both sides need it."""
        fields = {}
        for match in re.finditer(r"\S+", text):
            token = match.group()
            if len(token) > 2 and token[:2].isalpha():
                code = token[:2].upper()
                if tag_field and code == tag_field.upper():
                    fields[code] = text[match.start() + 2 :].strip()
                    break
                fields[code] = token[2:]
        return fields

    @staticmethod
    def _format_memory_record(bbcc: str, record: dict) -> str:
        return (
            f"{bbcc} MP{record['MP']} RF{record['RF']} ST{record['ST']} "
            f"SH{record['SH']} MD{record['MD']} PT{record['PT']} TT{record['TT']}"
        )

    @staticmethod
    def _fake_scope_bin_dbm(i: int, digits: int = 3) -> str:
        """A deterministic, reproducible fake dBm-ish value for fake
        scope-scan point ``i`` - not a claim about
        real RF levels, just a stable pattern so tests can assert on
        specific values. Zero-padded to ``digits`` characters (3 for FD's
        chunks, 2 for GL's narrower documented level field - see
        aor_dv10.device.ScopeLine's docstring re: that width
        discrepancy)."""
        value = (i * 17 + 30) % (10 ** digits - 10) + 5
        return f"{value:0{digits}d}"

    def _current_sd_timestamp(self) -> str:
        """Builds a spec-shaped "yyyy/mm/dd HH:MM:SS" SD-file timestamp
        from this simulator's fake DT clock state - a simulator-only
        convenience for making sd_dir() results look plausible, not a
        claim about how the real receiver derives SD file timestamps
        (unconfirmed)."""
        dt = self.state.get("DT", "0000000000")
        yy, mm, dd, hh, mn = dt[0:2], dt[2:4], dt[4:6], dt[6:8], dt[8:10]
        return f"20{yy}/{mm}/{dd} {hh}:{mn}:00"

    @staticmethod
    def _add_pass_freq(table: dict, freq: str) -> bool:
        """Fill the first empty slot (00-49) of a pass-frequency table
        with ``freq`` - False if all 50 are already taken (the spec's own
        documented per-list ceiling), see PW's _handle() case below."""
        for i in range(50):
            key = f"{i:02d}"
            if key not in table:
                table[key] = freq
                return True
        return False

    def _handle(self, line: str):
        code = None
        for candidate in self._ALL_CODES:
            if line.upper().startswith(candidate):
                code = candidate
                break
        if code is None:
            yield self._error("not_supported")
            return
        arg = line[len(code):] or None

        if code == "ZP":
            # Confirmed on real DV10: ZP is message-only, no code echo -
            # responds with "AOR <model>", same message-only pattern as WI.
            model = self.state.get("WI", "AR-DV10")
            yield self._respond(f"AOR {model}")
            return

        if code in ("EX", "QP"):
            # Ack shape not independently confirmed for these two
            # specifically, but modelled consistently with the corrected
            # "empty ack body" understanding below (see _respond()).
            yield self._respond("")
            return

        if code in ("ZJ", "ZK"):
            # "Move to previous/next frequency/bank/channel" - no value,
            # modelled as a no-op ack (real hardware's actual frequency
            # side effect isn't simulated).
            yield self._respond("")
            return

        if code == "RS":
            # "Reset" - takes a "0"/"1" (system/full) argument per
            # device.reset(); modelled as a no-op ack, no actual state
            # wipe (DESTRUCTIVE on real hardware).
            yield self._respond("")
            return

        if code == "AG":
            # Confirmed on real DV10 (via RE 1): not just the bare read -
            # writes fail with the same result code 60 (PC_RESULT_NONE)
            # too. This unit/firmware genuinely doesn't support AG at all
            # remotely.
            yield self._error("not_supported")
            return

        if code == "MD" and arg is not None:
            # Confirmed on real DV10: MD writes take a 3-character value
            # in the SAME "dan" shape MD itself reads back, not the
            # shorter 2-character form this project sent for a long time
            # (which the real device silently accepted without ever
            # applying it) - see aor_dv10.device._mode_write_value()/
            # set_mode(). The leading "d" position is read-only on the
            # read side and accepted an arbitrary digit in real-hardware
            # testing, so it isn't validated here either; the middle
            # "digital select" and trailing "analog select" positions are
            # validated the same way the old 2-char check used to (an
            # unrecognised code in either position rejected the same way
            # real hardware rejected "F1" as an invalid analog code):
            # result code 40.
            if len(arg) != 3:
                yield self._error("format")
                return
            digital_code, analog_code = arg[1].upper(), arg[2].upper()
            if digital_code not in _DIGITAL_MODE_CODES or analog_code not in _ANALOG_MODE_CODES:
                yield self._error("format")
                return
            # Best-effort approximation of the read-only "currently
            # receiving digital" field: not independently confirmed how the
            # real firmware settles this right after a write, so we just
            # report "no active digital decode" (Auto) - see
            # aor_dv10.device.ModeInfo.
            receiving_digital = "0"
            self.state["MD"] = f"{receiving_digital}{digital_code}{analog_code}"
            yield self._respond("")
            return

        if code == "VF":
            if arg is None:
                yield self._error("not_supported")
                return
            letter, _, rest = arg.strip().partition(" ")
            letter = letter.upper()
            if letter not in _VFO_LETTERS:
                # Confirmed on real DV10 (via RE 1): "VF 1" (a digit)
                # returns result code 40 (PC_RESULT_FORMAT_ERR).
                yield self._error("format")
                return
            # Confirmed on real DV10: "VF A" (bare, no other fields)
            # succeeds - and, per this project's best current
            # understanding, is how you get *into* VFO mode. Extended
            # with the spec's optional embedded RF/ST/SH/MD fields -
            # UNCONFIRMED against real hardware past the bare-letter
            # form, see DV10Device.enter_vfo_mode().
            self.vfo_mode = True
            if rest:
                fields = self._parse_fields(rest)
                prev = self.vfos[letter]
                self.vfos[letter] = {
                    "RF": fields.get("RF", prev["RF"]),
                    "ST": fields.get("ST", prev["ST"]),
                    "SH": fields.get("SH", prev["SH"]),
                    "MD": fields.get("MD", prev["MD"]),
                }
            # Per the spec, VF also makes this the actively-receiving VFO
            # - mirror its (possibly just-updated) snapshot into the
            # "live" RF/ST/SH/MD state every other command reads/writes.
            live = self.vfos[letter]
            self.state["RF"] = live["RF"]
            self.state["ST"] = live["ST"]
            self.state["SH"] = live["SH"]
            self.state["MD"] = live["MD"]
            yield self._respond("")
            return

        if code == "VE":
            # VFO-search delay/free-time/auto-store - a single
            # receiver-wide setting (no group number), unlike SG/MG - see
            # aor_dv10.device.DV10Device.read_vfo_search_settings()/
            # write_vfo_search_settings().
            arg_s = (arg or "").strip()
            if not arg_s:
                s = self.vfo_search_settings
                yield self._respond(f"DL{s['DL']} FR{s['FR']} AS{s['AS']}")
                return
            fields = self._parse_fields(arg_s)
            prev = self.vfo_search_settings
            self.vfo_search_settings = {
                "DL": fields.get("DL", prev["DL"]),
                "FR": fields.get("FR", prev["FR"]),
                "AS": fields.get("AS", prev["AS"]),
            }
            yield self._respond("")
            return

        if code == "VS":
            # Activate VFO search (bare command, no value, write-only) -
            # see aor_dv10.device.DV10Device.execute_vfo_search().
            yield self._respond("")
            return

        if code == "VI":
            # Read all three VFOs (A/B/Z) in one 3-line multi-response -
            # same 21-continuing shape this project already models for
            # PR/MA - see aor_dv10.device.DV10Device.read_vfo_info() for
            # why the request/response shape had to be reconstructed from
            # the AR-DV1 spec's prose rather than its own (corrupted)
            # table cell.
            for i, letter in enumerate(("A", "B", "Z")):
                v = self.vfos[letter]
                body = f"VF{letter} RF{v['RF']} ST{v['ST']} SH{v['SH']} MD{v['MD']}"
                if self.state.get("RE") == "1":
                    yield ("20" if i == 2 else "21") + body
                else:
                    yield body
            return

        if code == "TR":
            # Scheduled recording/alarm timer - see
            # aor_dv10.device.DV10Device.write_recording_timer()/
            # read_recording_timer() and aor_dv10.timer's module
            # docstring for the significant spec-reconstruction caveats
            # (the AR-DV1 spec PDF's own TR table entry is internally
            # inconsistent about which fields exist at all).
            arg_s = (arg or "").strip()
            if not arg_s:
                t = self.recording_timer
                parts = [f"XE{t['XE']}"]
                if t["TY"] is not None:
                    parts.append(f"TY{t['TY']}")
                parts.append(f"RP{t['RP']}")
                parts.append(f"RM{t['RM']}")
                parts.append(f"TS{t['TS']}")
                parts.append(f"TE{t['TE']}")
                if t["WE"] is not None:
                    parts.append(f"WE{t['WE']}")
                if t["AG"] is not None:
                    parts.append(f"AG{t['AG']}")
                yield self._respond(" ".join(parts))
                return
            fields = self._parse_fields(arg_s)
            if "XE" not in fields or fields["XE"] not in ("0", "1", "2"):
                yield self._error("format")
                return
            prev = self.recording_timer
            self.recording_timer = {
                "XE": fields["XE"],
                "TY": fields.get("TY", prev["TY"]),
                "RP": fields.get("RP", prev["RP"]),
                "RM": fields.get("RM", prev["RM"]),
                "TS": fields.get("TS", prev["TS"]),
                "TE": fields.get("TE", prev["TE"]),
                "WE": fields.get("WE", prev["WE"]),
                "AG": fields.get("AG", prev["AG"]),
            }
            yield self._respond("")
            return

        if code == "FD":
            # Fast-speed scope scan - see the scope_mode docstring in
            # __init__ above and aor_dv10.device's "Frequency scope"
            # section for the "no known way to enter scope mode" caveat.
            if not self.scope_mode:
                yield self._error("cannot_set")  # spec: 30 = Not in scope mode
                return
            chunks = "".join(self._fake_scope_bin_dbm(i, 3) for i in range(40))
            yield self._respond(f"FD{chunks}")
            return

        if code == "GL":
            # Normal-speed scope scan - 21-continuing multi-line shape,
            # same yield-with-continue-code pattern as "SD DIR"/"VI"/"PR"
            # below. See the scope_mode docstring in __init__ and
            # aor_dv10.device's "Frequency scope" section for the "no
            # known way to enter scope mode" caveat, and ScopeLine's
            # docstring for the 2-digit-level-width caveat.
            if not self.scope_mode:
                yield self._error("cannot_set")  # spec: 30 = Not in scope mode
                return
            base_mhz_x1e5 = 11_800_000  # 118.00000 MHz, as integer 1e-5-MHz units
            lines = []
            for i in range(10):
                # Integer arithmetic throughout, then split into a
                # zero-padded 4-digit integer part and 5-digit fractional
                # part - avoids float-formatting edge cases and guarantees
                # the 4-digit integer width _GL_LINE_RE expects.
                freq_x1e5 = base_mhz_x1e5 + i * 2_500  # 0.025 MHz steps
                int_part, frac_part = divmod(freq_x1e5, 100_000)
                level = self._fake_scope_bin_dbm(i, 2)
                squelch = i % 2
                lines.append(f"GLF{int_part:04d}.{frac_part:05d}L{level}{squelch}")
            for i, body in enumerate(lines):
                last = i == len(lines) - 1
                if self.state.get("RE") == "1":
                    yield ("20" if last else "21") + body
                else:
                    yield body
            return

        if code == "SD DIR":
            # Multi-line, 21-continuing shape - see
            # aor_dv10.device.DV10Device.sd_dir() and the "VI"/"PR" blocks
            # above for the same yield-with-continue-code pattern.
            if self.sd_error_injection:
                token, self.sd_error_injection = self.sd_error_injection, None
                yield self._respond(f"SD DIR {token}")
                return
            names = sorted(self.sd_files.keys())
            lines = []
            for name_ext in names:
                info = self.sd_files[name_ext]
                if info.get("duration") is not None:
                    lines.append(f"SD DIR {name_ext} {info['duration']} {info['timestamp']}")
                else:
                    lines.append(f"SD DIR {name_ext} {info.get('size', 0)} {info['timestamp']}")
            lines.append(f"SD DIR {len(names):03d}FILE(S)")
            for i, body in enumerate(lines):
                last = i == len(lines) - 1
                if self.state.get("RE") == "1":
                    yield ("20" if last else "21") + body
                else:
                    yield body
            return

        if code == "SD INF":
            if self.sd_error_injection:
                token, self.sd_error_injection = self.sd_error_injection, None
                yield self._respond(f"SD INF {token}")
                return
            yield self._respond("SD INF FREE: 967872KB ( 7.8H) TOTAL: 30517578KB")
            return

        if code == "SD PST":
            if self.sd_error_injection:
                # SD PST has no documented textual error tokens of its own -
                # "4" already covers "not found/unusable" as a status
                # value - so an injected token here just forces status "4"
                # rather than echoing the token as text.
                self.sd_error_injection = None
                yield self._respond("SD PST4")
                return
            if self.sd_recording is not None:
                digit = "1"
            elif self.sd_playing is not None:
                digit = "2"
            else:
                digit = "0"
            yield self._respond(f"SD PST{digit}")
            return

        if code == "SD REC":
            if self.sd_error_injection:
                token, self.sd_error_injection = self.sd_error_injection, None
                yield self._respond(f"SD REC {token}")
                return
            arg_s = (arg or "").strip()
            if arg_s == "/":
                if self.sd_recording is not None:
                    name_ext = self.sd_recording
                    self.sd_files[name_ext] = {
                        "duration": "00:00:05.0",
                        "timestamp": self._current_sd_timestamp(),
                    }
                    self.sd_recording = None
                # stopping when nothing is recording is treated as a benign
                # no-op - the spec doesn't document behaviour for that case.
                yield self._respond("")
                return
            if arg_s:
                yield self._error("format")
                return
            base = self.state.get("DT", "0000000000")[2:]  # mmddhhmm, 8 digits
            existing = {k.upper() for k in self.sd_files}
            name_ext = f"{base}.WAV"
            n = 1
            while name_ext.upper() in existing:
                n += 1
                name_ext = f"{base}_{n}.WAV"
            self.sd_recording = name_ext
            yield self._respond("")
            return

        if code == "SD PLY":
            if self.sd_error_injection:
                token, self.sd_error_injection = self.sd_error_injection, None
                yield self._respond(f"SD PLY {token}")
                return
            arg_s = (arg or "").strip()
            if arg_s == "/":
                self.sd_playing = None  # stopping when idle: benign no-op
                yield self._respond("")
                return
            if not arg_s:
                yield self._error("format")
                return
            name_u = arg_s.upper()
            found = None
            for k in self.sd_files:
                if k.upper() == name_u or k.split(".")[0].upper() == name_u:
                    found = k
                    break
            if found is None:
                yield self._respond("SD PLY NOFILE")
                return
            self.sd_playing = found
            yield self._respond("")
            return

        if code == "SD RSQ":
            arg_s = (arg or "").strip()
            if not arg_s:
                yield self._respond(f"SD RSQ{self.state.get('SD_RSQ', '1')}")
                return
            if arg_s not in ("0", "1"):
                yield self._error("range")
                return
            self.state["SD_RSQ"] = arg_s
            yield self._respond(f"SD RSQ{arg_s}")
            return

        if code == "SD MMW":
            if self.sd_error_injection:
                token, self.sd_error_injection = self.sd_error_injection, None
                yield self._respond(f"SD MMW {token}")
                return
            kind = (arg or "").strip().upper()
            name_ext = f"{kind}.DAT"
            self.sd_files[name_ext] = {
                "size": 1024,
                "timestamp": self._current_sd_timestamp(),
            }
            yield self._respond("")
            return

        if code == "SD MMR":
            if self.sd_error_injection:
                token, self.sd_error_injection = self.sd_error_injection, None
                yield self._respond(f"SD MMR {token}")
                return
            name_u = (arg or "").strip().upper()
            found = any(k.split(".")[0].upper() == name_u for k in self.sd_files)
            if not found:
                yield self._respond("SD MMR NOFILE")
                return
            yield self._respond("")
            return

        if code == "MM":
            # Two-phase response, confirmed against the AR-DV1
            # wire spec: 21 (registration started) then, once registration
            # finishes, 20 (registration completed) - modelled here as
            # both lines queued for the SAME "MM" request (this is a
            # behavioural stand-in for "registration is fast enough that
            # both lines are ready immediately", not a claim about real
            # timing, which is unconfirmed - see
            # aor_dv10.device.DV10Device.register_last_channel()). Only
            # modelled as two lines when RE is on: RE off can't
            # distinguish 20 from 21 at all (both are empty acks), and the
            # spec's own two-phase text is itself part of the RE-on result
            # -code description, so there's no documented basis for
            # claiming two lines still arrive with RE off - see
            # DV10Device.register_last_channel()'s docstring for how it
            # handles that case (no follow-up read attempted).
            if self.state.get("RE") == "1":
                yield "21"
                yield "20"
            else:
                yield ""
            return

        if code == "MX":
            # Program a memory channel - see
            # aor_dv10.device.DV10Device.write_memory_channel().
            if arg is None:
                yield self._error("format")
                return
            bbcc, _, rest = arg.strip().partition(" ")
            if not (bbcc.isdigit() and len(bbcc) == 4):
                yield self._error("format")
                return
            fields = self._parse_fields(rest, tag_field="TT")
            prev = self.memory_channels.get(bbcc, {
                "RF": self.state.get("RF", "0145.50000"),
                "ST": "012.50", "SH": "000.00", "MD": "0F0", "TT": "",
            })
            # Per the spec: RF/ST/SH/MD/TT keep their previous value when
            # omitted; MP/PT (unlike those) reset to 0 when omitted, they
            # do NOT carry over - see write_memory_channel()'s docstring.
            self.memory_channels[bbcc] = {
                "MP": fields.get("MP", "0"),
                "RF": fields.get("RF", prev["RF"]),
                "ST": fields.get("ST", prev["ST"]),
                "SH": fields.get("SH", prev["SH"]),
                "MD": fields.get("MD", prev["MD"]),
                "PT": fields.get("PT", "0"),
                "TT": fields.get("TT", prev["TT"]),
            }
            yield self._respond("")
            return

        if code == "MA":
            # Read memory channel(s) - see
            # aor_dv10.device.DV10Device.read_memory_channel()/
            # read_memory_bank(). The bank form ("MAbb") is modelled as a
            # full 50-line response (one per channel slot, registered or
            # not - matching the single-channel form's own "- - -"
            # placeholder for an unregistered slot), 21-prefixed except
            # the last line (20) when RE is on - the same multi-line shape
            # this project already models for MM, see
            # DV10Device.read_memory_bank()'s docstring for what's
            # unconfirmed about this.
            if arg is None:
                yield self._error("format")
                return
            arg = arg.strip()
            if arg.isdigit() and len(arg) == 2:
                bank = arg
                lines = []
                for c in range(50):
                    bbcc = f"{bank}{c:02d}"
                    record = self.memory_channels.get(bbcc)
                    if record is None:
                        lines.append(f"MA{bbcc} - - -")
                    else:
                        lines.append(f"MA{self._format_memory_record(bbcc, record)}")
                for i, body in enumerate(lines):
                    if self.state.get("RE") == "1":
                        yield ("20" if i == len(lines) - 1 else "21") + body
                    else:
                        yield body
                return
            if arg.isdigit() and len(arg) == 4:
                record = self.memory_channels.get(arg)
                if record is None:
                    yield self._respond(f"MA{arg} - - -")
                else:
                    yield self._respond(f"MA{self._format_memory_record(arg, record)}")
                return
            yield self._error("format")
            return

        if code == "MR":
            # Tune to (start receiving) a memory channel - see
            # aor_dv10.device.DV10Device.tune_memory_channel().
            if arg is None or not (arg.isdigit() and len(arg) == 4):
                yield self._error("format")
                return
            record = self.memory_channels.get(arg)
            if record is None:
                yield self._error("cannot_set")  # spec: 30 = channel not registered
                return
            self.state["RF"] = record["RF"]
            self.state["MD"] = record["MD"]
            self.vfo_mode = False  # now browsing a memory channel, not a VFO
            yield self._respond("")
            return

        if code == "MW":
            # Memory bank metadata (channel count/protect/tag) - see
            # aor_dv10.device.DV10Device.write_memory_bank()/
            # get_memory_bank_info(). Bare "MWbb" is modelled as
            # read-or-create-with-defaults (see get_memory_bank_info()'s
            # own "unconfirmed" docstring note - there's no documented
            # read form to be sure about).
            if arg is None:
                yield self._error("format")
                return
            bank, _, rest = arg.strip().partition(" ")
            if not (bank.isdigit() and len(bank) == 2):
                yield self._error("format")
                return
            if not rest:
                info = self.memory_banks.get(bank)
                if info is None:
                    info = {"MC": "50", "PT": "0", "TT": ""}
                    self.memory_banks[bank] = info
                yield self._respond(f"MW{bank} MC{info['MC']} PT{info['PT']} TT{info['TT']}")
                return
            fields = self._parse_fields(rest, tag_field="TT")
            prev = self.memory_banks.get(bank, {"MC": "50", "PT": "0", "TT": ""})
            self.memory_banks[bank] = {
                "MC": fields.get("MC", prev["MC"]),
                "PT": fields.get("PT", prev["PT"]),
                "TT": fields.get("TT", prev["TT"]),
            }
            yield self._respond("")
            return

        if code == "MB":
            # Delete a memory bank (and its channels/pass-channels) - see
            # aor_dv10.device.DV10Device.delete_memory_bank().
            if arg is None or not (arg.isdigit() and len(arg) == 2):
                yield self._error("format")
                return
            had_channels = [k for k in self.memory_channels if k.startswith(arg)]
            if arg not in self.memory_banks and not had_channels:
                yield self._error("cannot_set")  # spec: 30 = bank not registered
                return
            self.memory_banks.pop(arg, None)
            for k in had_channels:
                del self.memory_channels[k]
            yield self._respond("")
            return

        if code == "MQ":
            # Delete a single memory channel - see
            # aor_dv10.device.DV10Device.delete_memory_channel().
            if arg is None or not (arg.isdigit() and len(arg) == 4):
                yield self._error("format")
                return
            if arg not in self.memory_channels:
                yield self._error("cannot_set")  # spec: 30 = channel not registered
                return
            del self.memory_channels[arg]
            yield self._respond("")
            return

        if code == "SE":
            # Configure a search bank - see
            # aor_dv10.device.DV10Device.write_search_bank()/read_search_bank() (SR).
            if arg is None:
                yield self._error("format")
                return
            bank, _, rest = arg.strip().partition(" ")
            if not (bank.isdigit() and len(bank) == 2):
                yield self._error("format")
                return
            fields = self._parse_fields(rest, tag_field="TT")
            prev = self.search_banks.get(bank, {
                "SL": "0000.0000", "SU": "0000.0000",
                "ST": "012.50", "SH": "000.00", "MD": "0F0", "TT": "",
            })
            # Per the spec: ST/SH/MD/TT keep their previous value when
            # omitted, PT resets to 0 - same shape as MX. SL/SU have no
            # documented "previous value" fallback of their own; kept
            # here too (there's no better alternative for an omitted
            # limit on an existing bank).
            self.search_banks[bank] = {
                "SL": fields.get("SL", prev["SL"]),
                "SU": fields.get("SU", prev["SU"]),
                "ST": fields.get("ST", prev["ST"]),
                "SH": fields.get("SH", prev["SH"]),
                "MD": fields.get("MD", prev["MD"]),
                "PT": fields.get("PT", "0"),
                "TT": fields.get("TT", prev["TT"]),
            }
            yield self._respond("")
            return

        if code == "SR":
            # Read a search bank - see
            # aor_dv10.device.DV10Device.read_search_bank(). Response shape
            # is inferred (mirrors SE's own write layout) - see that
            # section's docstring in device.py for why.
            if arg is None or not (arg.isdigit() and len(arg) == 2):
                yield self._error("format")
                return
            record = self.search_banks.get(arg)
            if record is None:
                yield self._error("cannot_set")  # spec: 30 = bank unregistered
                return
            yield self._respond(
                f"SR{arg} SL{record['SL']} SU{record['SU']} ST{record['ST']} "
                f"SH{record['SH']} MD{record['MD']} PT{record['PT']} TT{record['TT']}"
            )
            return

        if code == "SS":
            # Execute a program search - see
            # aor_dv10.device.DV10Device.execute_search().
            if arg is None or not (arg.isdigit() and len(arg) == 2):
                yield self._error("format")
                return
            if arg not in self.search_banks:
                yield self._error("cannot_set")  # spec: 30 = bank unregistered
                return
            yield self._respond("")
            return

        if code == "SX":
            # Delete a search bank - see
            # aor_dv10.device.DV10Device.delete_search_bank().
            if arg is None or not (arg.isdigit() and len(arg) == 2):
                yield self._error("format")
                return
            if arg not in self.search_banks:
                yield self._error("cannot_set")  # spec: 30 = bank unregistered
                return
            del self.search_banks[arg]
            yield self._respond("")
            return

        if code == "SG":
            # Search-side scan group - see
            # aor_dv10.device.DV10Device.write_search_scan_group()/
            # read_search_scan_group(). Bare "SGgg" is a read (spec text
            # explicitly says "Setting / Reading completed" for this one).
            if arg is None:
                yield self._error("format")
                return
            group, _, rest = arg.strip().partition(" ")
            if not (group.isdigit() and len(group) == 2):
                yield self._error("format")
                return
            if not rest:
                info = self.scan_groups_search.setdefault(
                    group, {"DL": "20", "FR": "00", "AS": "0", "BK": "99"}
                )
                yield self._respond(
                    f"SG{group} DL{info['DL']} FR{info['FR']} AS{info['AS']} BK{info['BK']}"
                )
                return
            fields = self._parse_fields(rest)
            prev = self.scan_groups_search.get(group, {"DL": "20", "FR": "00", "AS": "0", "BK": "99"})
            self.scan_groups_search[group] = {
                "DL": fields.get("DL", prev["DL"]),
                "FR": fields.get("FR", prev["FR"]),
                "AS": fields.get("AS", prev["AS"]),
                "BK": fields.get("BK", prev["BK"]),
            }
            yield self._respond("")
            return

        if code == "MG":
            # Memory-side scan group - see
            # aor_dv10.device.DV10Device.write_memory_scan_group()/
            # read_memory_scan_group(). Unlike SG, no AS sub-field, and
            # the bare-group read direction is UNCONFIRMED (the spec's own
            # result-code text for MG only says "Set completed" - see
            # read_memory_scan_group()'s docstring) - modelled the same
            # read-or-create-with-defaults way as MW for consistency.
            if arg is None:
                yield self._error("format")
                return
            group, _, rest = arg.strip().partition(" ")
            if not (group.isdigit() and len(group) == 2):
                yield self._error("format")
                return
            if not rest:
                info = self.scan_groups_memory.setdefault(
                    group, {"DL": "20", "FR": "00", "BK": "99"}
                )
                yield self._respond(f"MG{group} DL{info['DL']} FR{info['FR']} BK{info['BK']}")
                return
            fields = self._parse_fields(rest)
            prev = self.scan_groups_memory.get(group, {"DL": "20", "FR": "00", "BK": "99"})
            self.scan_groups_memory[group] = {
                "DL": fields.get("DL", prev["DL"]),
                "FR": fields.get("FR", prev["FR"]),
                "BK": fields.get("BK", prev["BK"]),
            }
            yield self._respond("")
            return

        if code == "PW":
            # Mark a pass frequency - see
            # aor_dv10.device.DV10Device.mark_pass_frequency() for the 4
            # documented shapes this mirrors: bare PW, PWffff.ffff, PWbb,
            # PWbbffff.ffff (bb may be "%%" for "every search bank").
            #
            # Disambiguated by EXACT LENGTH, not by peeking at one
            # character: a bank token is always exactly 2 digits (or
            # "%%"), a bare frequency is always exactly 9 chars
            # ("ffff.ffff"), and a bank+frequency is always exactly
            # 2+9=11 chars - a length-only check that first tried
            # "peek at position 2" mis-parsed a bare 9-char frequency
            # (e.g. "0146.5200") as a 2-digit bank token followed by a
            # 7-char leftover, since a frequency's own first two digits
            # are indistinguishable from a bank number by content alone.
            # Caught via a live smoke test (raw "PW0146.52000" fed through
            # DV10Device.mark_pass_frequency(frequency_hz=...) came back
            # "?" instead of an ack) - fixed by matching on length instead.
            arg_s = (arg or "").strip()
            if not arg_s:
                ok = self._add_pass_freq(self.pass_freqs_vfo, self.state.get("RF", "0145.50000"))
                yield self._respond("") if ok else self._error("cannot_set")
                return
            if arg_s == "%%":
                bank_part, freq_part = "%%", ""
            elif len(arg_s) == 2 and arg_s.isdigit():
                bank_part, freq_part = arg_s, ""
            elif len(arg_s) == 9 and arg_s[4:5] == ".":
                bank_part, freq_part = "", arg_s
            elif arg_s.startswith("%%") and len(arg_s) == 11 and arg_s[6:7] == ".":
                bank_part, freq_part = "%%", arg_s[2:]
            elif len(arg_s) == 11 and arg_s[:2].isdigit() and arg_s[6:7] == ".":
                bank_part, freq_part = arg_s[:2], arg_s[2:]
            else:
                yield self._error("format")
                return
            if not bank_part:
                ok = self._add_pass_freq(self.pass_freqs_vfo, freq_part)
                yield self._respond("") if ok else self._error("cannot_set")
                return
            banks = list(self.search_banks) if bank_part == "%%" else [bank_part]
            freq = freq_part or self.state.get("RF", "0145.50000")
            all_ok = True
            for b in banks:
                table = self.pass_freqs_bank.setdefault(b, {})
                all_ok = self._add_pass_freq(table, freq) and all_ok
            yield self._respond("") if all_ok else self._error("cannot_set")
            return

        if code == "PR":
            # List pass frequencies - see
            # aor_dv10.device.DV10Device.list_pass_frequencies(). Same
            # 50-line, 21/20-result-code-terminated shape this project
            # already models for MA's bank form.
            arg_s = (arg or "").strip()
            if arg_s and not (arg_s.isdigit() and len(arg_s) == 2):
                yield self._error("format")
                return
            if arg_s:
                table = self.pass_freqs_bank.get(arg_s, {})
                prefix = f"PR{arg_s}"
            else:
                table = self.pass_freqs_vfo
                prefix = "PR"
            lines = []
            for i in range(50):
                key = f"{i:02d}"
                freq = table.get(key)
                if freq is None:
                    lines.append(f"{prefix}{key} - - -")
                else:
                    lines.append(f"{prefix}{key}{freq}")
            for i, body in enumerate(lines):
                if self.state.get("RE") == "1":
                    yield ("20" if i == len(lines) - 1 else "21") + body
                else:
                    yield body
            return

        if code == "PD":
            # Delete pass frequencies - see
            # aor_dv10.device.DV10Device.delete_pass_frequencies() for the
            # 3 documented shapes this mirrors: bare PD, PDbb/PD%%, PDbbnn.
            arg_s = (arg or "").strip()
            if not arg_s:
                self.pass_freqs_vfo.clear()
                yield self._respond("")
                return
            if arg_s == "%%":
                for b in list(self.pass_freqs_bank):
                    self.pass_freqs_bank[b] = {}
                yield self._respond("")
                return
            if len(arg_s) == 2 and arg_s.isdigit():
                if arg_s not in self.pass_freqs_bank and arg_s not in self.search_banks:
                    yield self._error("cannot_set")
                    return
                self.pass_freqs_bank[arg_s] = {}
                yield self._respond("")
                return
            if len(arg_s) == 4 and arg_s.isdigit():
                bank, idx = arg_s[:2], arg_s[2:]
                table = self.pass_freqs_bank.get(bank)
                if table is None or idx not in table:
                    yield self._error("cannot_set")
                    return
                del table[idx]
                yield self._respond("")
                return
            yield self._error("format")
            return

        if code == "OL":
            # Reworked against the AR-DV1 wire spec: OLnn
            # RFffff.fffff (combined slot+frequency write; reads also
            # require the slot number, OLnn<CR> - never a bare OL<CR>) -
            # see aor_dv10.device.DV10Device.get_offset_freq()/
            # set_offset_freq().
            if arg is None:
                yield self._error("format")
                return
            arg_up = arg.strip().upper()
            if " " in arg_up:
                nn_part, _, rf_part = arg_up.partition(" ")
                if not (nn_part.isdigit() and len(nn_part) == 2 and rf_part.startswith("RF")):
                    yield self._error("format")
                    return
                if nn_part not in self.offset_freqs:
                    yield self._error("range")
                    return
                if int(nn_part) >= 20:
                    # Factory presets (20-39): the spec says these "cannot
                    # be changed".
                    yield self._error("cannot_set")
                    return
                self.offset_freqs[nn_part] = rf_part[2:]
                yield self._respond("")
                return
            nn_part = arg_up
            if not (nn_part.isdigit() and len(nn_part) == 2):
                yield self._error("format")
                return
            freq = self.offset_freqs.get(nn_part)
            if freq is None:
                yield self._error("range")
                return
            yield self._respond(f"OL{nn_part} RF{freq}")
            return

        if code == "OF" and arg is not None:
            # Corrected against the AR-DV1 wire spec: OFsnn - a leading
            # +/- direction sign (omittable only when the slot is 00)
            # alongside the slot
            # number this project already modelled - see
            # aor_dv10.device.DV10Device.set_offset_slot().
            arg_up = arg.strip().upper()
            if arg_up[:1] in ("+", "-"):
                sign, nn = arg_up[0], arg_up[1:]
            else:
                sign, nn = "", arg_up
            if not (nn.isdigit() and len(nn) == 2):
                yield self._error("format")
                return
            if nn == "00":
                sign = ""
            elif not sign:
                yield self._error("format")  # sign is required for any non-zero slot
                return
            self.state["OF"] = f"{sign}{nn}"
            yield self._respond("")
            return

        if code == "PP" and arg is not None:
            # Corrected against the AR-DV1 wire spec: PPbbcc, no
            # separator - see aor_dv10.device.DV10Device.set_priority_channel().
            arg_s = arg.strip()
            if not (arg_s.isdigit() and len(arg_s) == 4):
                yield self._error("format")
                return
            self.state["PP"] = arg_s
            yield self._respond("")
            return

        if code == "CN" and arg is not None:
            # Corrected against the AR-DV1 wire spec: CNnn is a 1-based
            # CTCSS-table index (01-52) or 99=search, not a literal Hz
            # value - see
            # aor_dv10.device.DV10Device.set_tone_squelch_freq().
            arg_s = arg.strip()
            if arg_s.isdigit() and len(arg_s) == 2 and (arg_s == "99" or 1 <= int(arg_s) <= 52):
                self.state["CN"] = arg_s
                yield self._respond("")
            else:
                yield self._error("format")
            return

        if code == "BP" and arg is not None:
            # Corrected against the AR-DV1 wire spec: BPn is a single
            # digit 0-7, not a two-digit 00-15 value - see
            # aor_dv10.device.DV10Device.set_beep_level().
            arg_s = arg.strip()
            if arg_s.isdigit() and len(arg_s) == 1 and 0 <= int(arg_s) <= 7:
                self.state["BP"] = arg_s
                yield self._respond("")
            else:
                yield self._error("format")
            return

        if arg is None:
            # read
            value = self.state.get(code)
            if value is None:
                yield self._error("not_supported")
            elif code == "WI":
                yield self._respond(value)  # real hardware omits the "WI" prefix on this one
            else:
                yield self._respond(f"{code}{value}")
            return

        # write
        if not self.vfo_mode and code in _VFO_MODE_CODES:
            # Confirmed on real DV10: rejected while browsing a memory
            # channel. Modelled as "cannot set given current conditions"
            # (result code 30), which is the closest fit in RESULT_CODES,
            # though this specific mapping is this project's own inference
            # rather than something seen on real hardware with RE on.
            yield self._error("cannot_set")
            return
        if code not in self.state and code not in {"RF", "MD", "SQ", "AG"}:
            yield self._error("not_supported")
            return
        self.state[code] = arg
        # Confirmed on real DV10: a successful write's ack body is EMPTY
        # (not an echo of the code or the argument) - see the module-level
        # note above. This applies uniformly, including to "RE" itself:
        # setting self.state["RE"] just above means _respond("") already
        # picks up the *new* RE state for this very ack, exactly matching
        # the real "RE 1" -> "20" (prefix + empty body) transcript, with no
        # special-casing needed.
        yield self._respond("")
