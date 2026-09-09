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

# Mirrors aor_dv10.device._VFO_MODE_WRITE_CODES (kept independent to avoid a
# transport->device import): writes rejected outside VFO mode, confirmed
# against real hardware. Excludes "MD" (never confirmed) and "VF" (confirmed
# to be the way *into* VFO mode - gating it would be backwards).
_VFO_MODE_CODES = {"RF", "AC", "SQ", "AT", "RG", "ST", "SH"}

# RE ("RE 1" result-code prefixing) codes, confirmed against real hardware -
# see aor_dv10.protocol.codec.RESULT_CODES.
_RESULT_CODE_FOR_KIND = {
    "cannot_set": 30,  # e.g. a VFO-mode-gated write while browsing memory
    "format": 40,  # e.g. VF given something other than a VFO letter
    "range": 50,
    "not_supported": 60,  # e.g. AG (read or write) - confirmed real DV10 behaviour
}

_VFO_LETTERS = {"A", "B", "Z"}

# Mirrors aor_dv10.device.DIGITAL_MODES / ANALOG_MODES keys (kept independent
# to avoid a transport->device import) - validates MD writes as the firmware does.
_DIGITAL_MODE_CODES = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "F"}
_ANALOG_MODE_CODES = {"0", "1", "2", "3", "4", "5", "6"}


class SimulatorTransport(Transport):
    """A tiny state machine that answers DV10 commands over an in-memory queue."""

    def __init__(self) -> None:
        self._open = False
        self._inbox: Deque[bytes] = deque()
        # Confirmed against real hardware: tuning/level writes are rejected
        # while browsing a memory channel rather than in VFO mode. A test-only
        # knob (set sim.vfo_mode = False); a successful "VF <letter>" write
        # flips it back on, mirroring real "VF A".
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
            "SN": "SIMULATED0001",
            "RX": "1",
            # Manual-sourced defaults - plausible values so the GUI/CLI have
            # something to show, NOT confirmed against real hardware. ST uses
            # the confirmed kHz-decimal wire format (STggg.gg).
            "ST": "012.50",
            # Per the AR-DV1 spec, SH's default is "000.00" (kHz-decimal),
            # not a bare "0".
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
            # "OL" lives in self.offset_freqs, not here: per the AR-DV1 spec
            # its reads/writes always require an explicit slot number (OLnn).
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
            # SL/SU/AS/BK are spec-confirmed both-directions single-value
            # fields, so they need no special-casing in _handle(), unlike the
            # composite SE/SG/MG/PW/PR/PD commands.
            "SL": "0000.0000",  # search-range lower limit, session-only per the spec's own Remarks
            "SU": "0000.0000",  # search-range upper limit, session-only per the spec's own Remarks
            "AS": "0",  # standalone auto-store flag
            "BK": "99",  # standalone bank-link list ("99" = none linked)
            # KL/IF/DL/FR: same simple single-value category as SL/SU/AS/BK.
            # IF's "3" is FM's spec default; per-mode IF-bandwidth validation
            # (result code 30) is not modelled, values are just echoed back.
            "KL": "0",  # key backlight color, spec default OFF
            "IF": "3",  # IF bandwidth selector, spec default (FM: 15KHz)
            "DL": "020",  # standalone delay time (deciseconds), spec default
            "FR": "00",  # standalone free time (seconds), spec default OFF
            # Placeholder defaults so these round-trip at all - NOT confirmed
            # against real hardware. On/off ones default off ("0"); the rest to
            # an empty string, no format detail being available to guess from.
            "AN": "0",
            "CT": "",
            "DJ": "",
            "DK": "",
            "LC": "0",
            "LT": "0",
            "OX": "0",
            "TS": "",
            "VQ": "",
            "ZS": "0",
            "ZT": "",
            "RT": "0",
            "SB": "",
        }
        # Per-slot offset-frequency table (OL, keyed by 2-digit slot). Slot
        # "00" is fixed at 0Hz (offset off) and "20"-"39" are read-only factory
        # presets, matching the spec's "cannot be changed" note.
        self.offset_freqs = {f"{i:02d}": "0000.00000" for i in range(40)}
        # Live memory channels/banks (MX/MA/MR/MW/MB/MQ), keyed "bbcc"/"bb"
        # and present only once written: a never-written channel is genuinely
        # "not registered", so absence from this dict IS that state.
        self.memory_channels: dict = {}
        self.memory_banks: dict = {}
        # Search banks / scan groups / pass frequencies (SE/SR/SS/SX, SG/MG,
        # PW/PR/PD). SL/SU/AS/BK stay in self.state and use _handle()'s generic
        # fallback instead.
        # One RF/ST/SH/MD snapshot per VFO letter, independent of self.state's
        # own RF/ST/SH/MD (which track whichever VFO is CURRENTLY receiving).
        self.vfos: dict = {
            v: {"RF": "0145.50000", "ST": "012.50", "SH": "000.00", "MD": "0F0"}
            for v in _VFO_LETTERS
        }
        # VE: one receiver-wide (not per-VFO, not per-group) delay/free-time/
        # auto-store setting, used by VS.
        self.vfo_search_settings: dict = {"DL": "20", "FR": "00", "AS": "0"}
        # TR, the scheduled recording/alarm timer - see aor_dv10.timer's module
        # docstring for the spec-reconstruction caveats. Defaults match the
        # AR-DV1 spec's Default line (WE/AG have none stated, so start None).
        self.recording_timer: dict = {
            "XE": "0", "TY": "0", "RP": "0", "RM": "VFA",
            "TS": "01010000", "TE": "01010000", "WE": None, "AG": None,
        }
        self.search_banks: dict = {}  # "bb" -> {"SL","SU","ST","SH","MD","PT","TT"}
        self.scan_groups_search: dict = {}  # "gg" -> {"DL","FR","AS","BK"} (SG)
        self.scan_groups_memory: dict = {}  # "gg" -> {"DL","FR","BK"} (MG, no AS)
        self.pass_freqs_vfo: dict = {}  # "nn" (00-49) -> "ffff.ffff", sparse
        self.pass_freqs_bank: dict = {}  # "bb" -> {"nn": "ffff.ffff"}, sparse
        # SD card management. sd_files is keyed "NAME.EXT"; each entry sets
        # either "duration" (WAV) or "size", mirroring SD DIR's two line shapes.
        # sd_error_injection is a test-only one-shot seam: set it to a documented
        # error token (CARDBUSY/NOCARD/FAT12/NOFILE/CARDFULL) and the next SD
        # command returns that instead, then clears it. No real card state is
        # modelled, so this is how tests reach the documented error paths.
        self.sd_files: dict = {}
        self.sd_recording: Optional[str] = None
        self.sd_playing: Optional[str] = None
        self.sd_error_injection: Optional[str] = None
        # Frequency scope (FD/GL). Both only succeed "in scope mode" (result
        # code 30 otherwise), and NO command or front-panel procedure to enter
        # that mode was found in any reference document, the full operating
        # manual included. So this is a test-only manual toggle: False exercises
        # the documented error path, True returns deterministic fake scan data.
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
    # Framing confirmed against real hardware: no space between code and value
    # in either direction; errors are a bare "?", or "<numeric code>?" once
    # "RE 1" has been sent; and WI responds with just the value, no code echo,
    # replicated here so that path gets exercised too.
    #
    # Real-hardware finding: with RE on, EVERY response is prefixed, not just
    # errors ("20RF0145.50000" for a plain RF read - see codec's module
    # docstring). The same crash showed a successful write's ack body is EMPTY,
    # not a code echo. Hence _respond(): "<20 if RE is on><body, may be empty>".

    _ALL_CODES = (
        "EX", "ZP", "QP", "RF", "MD", "SQ", "AG", "AC", "AT", "RG", "LM",
        "LQ", "NQ", "BP", "VR", "WI", "RN", "SN", "RX", "RE", "VF",
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
        # SD card management. Multi-word candidates use the same startswith()
        # scan - safe because none is a prefix of another and there is no bare
        # "SD" command to collide with.
        "SD DIR", "SD INF", "SD PST", "SD REC", "SD PLY", "SD RSQ",
        "SD MMW", "SD MMR",
        # frequency scope. Bare 2-letter codes, unlike the "SD "-prefixed
        # family above.
        "FD", "GL",
        # Previously raw-console-only commands (RX already listed above).
        # _handle()'s generic state-dict fallback serves them, but only once
        # they are recognised here first.
        "AN", "CT", "DJ", "DK", "LC", "LT", "OX", "TS", "VQ", "ZS", "ZT", "RT", "SB",
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
            # Ack shape unconfirmed for these two; modelled consistently with
            # the "empty ack body" finding (see _respond()).
            yield self._respond("")
            return

        if code in ("ZJ", "ZK"):
            # "Move to previous/next" - no value, no-op ack; the real frequency
            # side effect is not simulated.
            yield self._respond("")
            return

        if code == "RS":
            # "Reset" - takes "0"/"1" (system/full); no-op ack here, no state
            # wipe. DESTRUCTIVE on real hardware.
            yield self._respond("")
            return

        if code == "AG":
            # Confirmed on real DV10 (via RE 1): reads AND writes both fail
            # with result code 60 - this firmware has no remote AG support.
            yield self._error("not_supported")
            return

        if code == "MD" and arg is not None:
            # Confirmed on real DV10: MD writes take a 3-character "dan" value,
            # the same shape MD reads back - not the 2-char form this project
            # sent for a long time (silently accepted, never applied). The
            # leading read-only "d" accepted an arbitrary digit in testing so it
            # is not validated; the digital/analog positions are, rejecting an
            # unknown code with result code 40.
            if len(arg) != 3:
                yield self._error("format")
                return
            digital_code, analog_code = arg[1].upper(), arg[2].upper()
            if digital_code not in _DIGITAL_MODE_CODES or analog_code not in _ANALOG_MODE_CODES:
                yield self._error("format")
                return
            # Best-effort: how real firmware settles the read-only "currently
            # receiving digital" field after a write is unconfirmed, so report
            # "no active digital decode" (Auto).
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
            # Confirmed on real DV10: bare "VF A" succeeds and is, as best
            # understood, how you get INTO VFO mode. The spec's optional
            # embedded RF/ST/SH/MD fields are UNCONFIRMED past that bare form.
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
            # Per the spec VF also makes this the actively-receiving VFO, so
            # mirror its snapshot into the live RF/ST/SH/MD state.
            live = self.vfos[letter]
            self.state["RF"] = live["RF"]
            self.state["ST"] = live["ST"]
            self.state["SH"] = live["SH"]
            self.state["MD"] = live["MD"]
            yield self._respond("")
            return

        if code == "VE":
            # VFO-search delay/free-time/auto-store: one receiver-wide setting
            # (no group number), unlike SG/MG.
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
            # All three VFOs (A/B/Z) in one 3-line 21-continuing response, the
            # same shape used for PR/MA. read_vfo_info() explains why this shape
            # had to be reconstructed from the spec's prose, its table cell
            # being corrupted.
            for i, letter in enumerate(("A", "B", "Z")):
                v = self.vfos[letter]
                body = f"VF{letter} RF{v['RF']} ST{v['ST']} SH{v['SH']} MD{v['MD']}"
                if self.state.get("RE") == "1":
                    yield ("20" if i == 2 else "21") + body
                else:
                    yield body
            return

        if code == "TR":
            # Scheduled recording/alarm timer. See aor_dv10.timer's module
            # docstring: the AR-DV1 spec PDF's TR entry is internally
            # inconsistent about which fields even exist.
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
            # Fast-speed scope scan - see scope_mode in __init__ for the
            # "no known way to enter scope mode" caveat.
            if not self.scope_mode:
                yield self._error("cannot_set")  # spec: 30 = Not in scope mode
                return
            chunks = "".join(self._fake_scope_bin_dbm(i, 3) for i in range(40))
            yield self._respond(f"FD{chunks}")
            return

        if code == "GL":
            # Normal-speed scope scan - 21-continuing multi-line shape, same
            # pattern as "SD DIR"/"VI"/"PR". See scope_mode in __init__ for the
            # "no known way to enter scope mode" caveat.
            if not self.scope_mode:
                yield self._error("cannot_set")  # spec: 30 = Not in scope mode
                return
            base_mhz_x1e5 = 11_800_000  # 118.00000 MHz, as integer 1e-5-MHz units
            lines = []
            for i in range(10):
                # Integer arithmetic throughout, split into 4-digit integer and
                # 5-digit fractional parts: avoids float-formatting edge cases
                # and guarantees the width _GL_LINE_RE expects.
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
            # Multi-line 21-continuing shape, same pattern as "VI"/"PR".
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
                # SD PST has no documented textual error tokens ("4" already
                # means "not found/unusable"), so an injected token just forces
                # status "4" rather than echoing text.
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
            # Two-phase response per the AR-DV1 wire spec: 21 (started) then
            # 20 (completed), both queued for the same "MM" request. Real timing
            # is unconfirmed; this just stands in for "fast enough that both are
            # ready". Two lines only when RE is on - with RE off, 20 and 21 are
            # indistinguishable empty acks and the spec's two-phase text is part
            # of the RE-on description, so there is no basis for claiming two.
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
            # omitted; MP/PT reset to 0 instead of carrying over.
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
            # Read memory channel(s). The bank form ("MAbb") is a full 50-line
            # response (one per slot, "- - -" where unregistered), 21-prefixed
            # except the last line (20) when RE is on. See
            # read_memory_bank()'s docstring for what is unconfirmed here.
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
            # Memory bank metadata (channel count/protect/tag). Bare "MWbb" is
            # modelled as read-or-create-with-defaults; there is no documented
            # read form to be sure about (see get_memory_bank_info()).
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
            # Per the spec: ST/SH/MD/TT keep their previous value when omitted,
            # PT resets to 0 - same shape as MX. SL/SU have no documented
            # fallback; kept anyway, there being no better option.
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
            # Read a search bank. Response shape is inferred, mirroring SE's
            # own write layout.
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
            # Search-side scan group. Bare "SGgg" is a read - the spec says
            # "Setting / Reading completed" for this one.
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
            # Memory-side scan group. Unlike SG, no AS sub-field, and the
            # bare-group read direction is UNCONFIRMED (the spec only says "Set
            # completed"); modelled read-or-create like MW for consistency.
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
            # Mark a pass frequency - 4 documented shapes: bare PW,
            # PWffff.ffff, PWbb, PWbbffff.ffff (bb may be "%%" = every bank).
            #
            # Disambiguated by EXACT LENGTH, never by peeking at a character:
            # bank = 2 chars, frequency = 9, bank+frequency = 11. Peeking at
            # position 2 mis-parsed a bare frequency ("0146.5200") as a bank
            # plus leftover, a frequency's first two digits being
            # indistinguishable from a bank number by content alone.
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
            # List pass frequencies: same 50-line, 21/20-terminated shape as
            # MA's bank form.
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
            # Delete pass frequencies - 3 documented shapes: bare PD,
            # PDbb/PD%%, PDbbnn.
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
            # Per the AR-DV1 wire spec: "OLnn RFffff.fffff" (combined
            # slot+frequency write); reads also require the slot number
            # (OLnn<CR>), never a bare OL<CR>.
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
            # Per the AR-DV1 wire spec: OFsnn - a leading +/- direction sign
            # (omittable only when the slot is 00) plus the slot number.
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
            # Per the AR-DV1 wire spec: CNnn is a 1-based CTCSS-table index
            # (01-52) or 99=search, NOT a literal Hz value.
            arg_s = arg.strip()
            if arg_s.isdigit() and len(arg_s) == 2 and (arg_s == "99" or 1 <= int(arg_s) <= 52):
                self.state["CN"] = arg_s
                yield self._respond("")
            else:
                yield self._error("format")
            return

        if code == "BP" and arg is not None:
            # Per the AR-DV1 wire spec: BPn is a single digit 0-7, not a
            # two-digit 00-15 value.
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
            # Confirmed on real DV10: rejected while browsing a memory channel.
            # Mapped to result code 30 as the closest fit in RESULT_CODES - that
            # specific mapping is this project's inference, not observed.
            yield self._error("cannot_set")
            return
        if code not in self.state and code not in {"RF", "MD", "SQ", "AG"}:
            yield self._error("not_supported")
            return
        self.state[code] = arg
        # Confirmed on real DV10: a successful write's ack body is EMPTY, not
        # an echo. This holds for "RE" itself: setting self.state["RE"] above
        # means _respond("") picks up the NEW state for this very ack, matching
        # the real "RE 1" -> "20" transcript with no special-casing.
        yield self._respond("")
