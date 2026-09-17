
from __future__ import annotations

import re
from collections import deque
from typing import Deque, Optional

from .base import Transport
from ..protocol.parsing import parse_composite_fields

_CRLF_VARIANTS = (b"\r\n", b"\r", b"\n")

_VFO_MODE_CODES = {"RF", "AC", "SQ", "AT", "RG", "ST", "SH"}

_RESULT_CODE_FOR_KIND = {
    "cannot_set": 30,
    "format": 40,
    "range": 50,
    "not_supported": 60,
}

_VFO_LETTERS = {"A", "B", "Z"}

_DIGITAL_MODE_CODES = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "F"}
_ANALOG_MODE_CODES = {"0", "1", "2", "3", "4", "5", "6"}


class SimulatorTransport(Transport):

    def __init__(self) -> None:
        self._open = False
        self._inbox: Deque[bytes] = deque()
        self.vfo_mode = True
        self.state = {
            "RF": "0145.50000",
            "MD": "0F0",
            "SQ": "0",
            "AG": "020",
            "AC": "1",
            "AT": "0",
            "RG": "099",
            "LM": "1001",
            "LQ": "050",
            "NQ": "020",
            "RE": "0",
            "BP": "2",
            "VR": "1.00",
            "WI": "AR-DV10",
            "RN": "SIMULATED0001",
            "SN": "SIMULATED0001",
            "RX": "1",
            "ST": "012.50",
            "SH": "000.00",
            "CI": "0",
            "CN": "01",
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
            "OF": "00",
            "PO": "0",
            "PP": "0000",
            "TI": "05",
            "AV": "05",
            "DA": "01.00",
            "LN": "30",
            "LB": "0",
            "SP": "00",
            "DT": "2601010000",
            "ZI": "0000",
            "PT": "0",
            "SL": "0000.0000",
            "SU": "0000.0000",
            "AS": "0",
            "BK": "99",
            "KL": "0",
            "IF": "3",
            "DL": "020",
            "FR": "00",
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
        self.offset_freqs = {f"{i:02d}": "0000.00000" for i in range(40)}
        self.memory_channels: dict = {}
        self.memory_banks: dict = {}
        self.vfos: dict = {
            v: {"RF": "0145.50000", "ST": "012.50", "SH": "000.00", "MD": "0F0"}
            for v in _VFO_LETTERS
        }
        self.vfo_search_settings: dict = {"DL": "20", "FR": "00", "AS": "0"}
        self.recording_timer: dict = {
            "XE": "0", "TY": "0", "RP": "0", "RM": "VFA",
            "TS": "01010000", "TE": "01010000", "WE": None, "AG": None,
        }
        self.search_banks: dict = {}
        self.scan_groups_search: dict = {}
        self.scan_groups_memory: dict = {}
        self.pass_freqs_vfo: dict = {}
        self.pass_freqs_bank: dict = {}
        self.sd_files: dict = {}
        self.sd_recording: Optional[str] = None
        self.sd_playing: Optional[str] = None
        self.sd_error_injection: Optional[str] = None
        self.scope_mode: bool = False


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
            return
        for reply in self._handle(line.decode("ascii", errors="replace")):
            self._inbox.append(reply.encode("ascii") + b"\r")

    def read_line(self, timeout: float) -> Optional[bytes]:
        if self._inbox:
            return self._inbox.popleft()
        return None


    _ALL_CODES = (
        "EX", "ZP", "QP", "RF", "MD", "SQ", "AG", "AC", "AT", "RG", "LM",
        "LQ", "NQ", "BP", "VR", "WI", "RN", "SN", "RX", "RE", "VF",
        "ST", "SH", "CI", "CN", "DI", "DS", "CC", "CM", "OT", "PC", "PM",
        "NC", "NM", "DC", "SI", "SC", "OF", "OL", "PO", "PP", "TI",
        "AV", "DA", "LN", "LB", "SP", "DT", "ZI", "PT", "RS", "ZJ", "ZK", "VI",
        "MM",
        "MX", "MA", "MR", "MW", "MB", "MQ",
        "SE", "SR", "SS", "SX", "SL", "SU", "SG", "MG", "AS", "BK", "PW", "PR", "PD",
        "KL", "IF", "DL", "FR",
        "VE", "VS",
        "TR",
        "SD DIR", "SD INF", "SD PST", "SD REC", "SD PLY", "SD RSQ",
        "SD MMW", "SD MMR",
        "FD", "GL",
        "AN", "CT", "DJ", "DK", "LC", "LT", "OX", "TS", "VQ", "ZS", "ZT", "RT", "SB",
    )

    def _respond(self, body: str) -> str:
        if self.state.get("RE") == "1":
            return f"20{body}"
        return body

    def _error(self, kind: str) -> str:
        if self.state.get("RE") == "1":
            return f"{_RESULT_CODE_FOR_KIND[kind]}?"
        return "?"

    @staticmethod
    def _parse_fields(text: str, *, tag_field: str | None = None) -> dict:
        return parse_composite_fields(text, tag_field=tag_field)

    @staticmethod
    def _format_memory_record(bbcc: str, record: dict) -> str:
        return (
            f"{bbcc} MP{record['MP']} RF{record['RF']} ST{record['ST']} "
            f"SH{record['SH']} MD{record['MD']} PT{record['PT']} TT{record['TT']}"
        )

    @staticmethod
    def _fake_scope_bin_dbm(i: int, digits: int = 3) -> str:
        value = (i * 17 + 30) % (10 ** digits - 10) + 5
        return f"{value:0{digits}d}"

    def _current_sd_timestamp(self) -> str:
        dt = self.state.get("DT", "0000000000")
        yy, mm, dd, hh, mn = dt[0:2], dt[2:4], dt[4:6], dt[6:8], dt[8:10]
        return f"20{yy}/{mm}/{dd} {hh}:{mn}:00"

    @staticmethod
    def _add_pass_freq(table: dict, freq: str) -> bool:
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
            model = self.state.get("WI", "AR-DV10")
            yield self._respond(f"AOR {model}")
            return

        if code in ("EX", "QP"):
            yield self._respond("")
            return

        if code in ("ZJ", "ZK"):
            yield self._respond("")
            return

        if code == "RS":
            yield self._respond("")
            return

        if code == "AG":
            yield self._error("not_supported")
            return

        if code == "MD" and arg is not None:
            if len(arg) != 3:
                yield self._error("format")
                return
            digital_code, analog_code = arg[1].upper(), arg[2].upper()
            if digital_code not in _DIGITAL_MODE_CODES or analog_code not in _ANALOG_MODE_CODES:
                yield self._error("format")
                return
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
                yield self._error("format")
                return
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
            live = self.vfos[letter]
            self.state["RF"] = live["RF"]
            self.state["ST"] = live["ST"]
            self.state["SH"] = live["SH"]
            self.state["MD"] = live["MD"]
            yield self._respond("")
            return

        if code == "VE":
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
            yield self._respond("")
            return

        if code == "VI":
            for i, letter in enumerate(("A", "B", "Z")):
                v = self.vfos[letter]
                body = f"VF{letter} RF{v['RF']} ST{v['ST']} SH{v['SH']} MD{v['MD']}"
                if self.state.get("RE") == "1":
                    yield ("20" if i == 2 else "21") + body
                else:
                    yield body
            return

        if code == "TR":
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
            if not self.scope_mode:
                yield self._error("cannot_set")
                return
            chunks = "".join(self._fake_scope_bin_dbm(i, 3) for i in range(40))
            yield self._respond(f"FD{chunks}")
            return

        if code == "GL":
            if not self.scope_mode:
                yield self._error("cannot_set")
                return
            base_mhz_x1e5 = 11_800_000
            lines = []
            for i in range(10):
                freq_x1e5 = base_mhz_x1e5 + i * 2_500
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
                yield self._respond("")
                return
            if arg_s:
                yield self._error("format")
                return
            base = self.state.get("DT", "0000000000")[2:]
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
                self.sd_playing = None
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
            if self.state.get("RE") == "1":
                yield "21"
                yield "20"
            else:
                yield ""
            return

        if code == "MX":
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
            if arg is None or not (arg.isdigit() and len(arg) == 4):
                yield self._error("format")
                return
            record = self.memory_channels.get(arg)
            if record is None:
                yield self._error("cannot_set")
                return
            self.state["RF"] = record["RF"]
            self.state["MD"] = record["MD"]
            self.vfo_mode = False
            yield self._respond("")
            return

        if code == "MW":
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
            if arg is None or not (arg.isdigit() and len(arg) == 2):
                yield self._error("format")
                return
            had_channels = [k for k in self.memory_channels if k.startswith(arg)]
            if arg not in self.memory_banks and not had_channels:
                yield self._error("cannot_set")
                return
            self.memory_banks.pop(arg, None)
            for k in had_channels:
                del self.memory_channels[k]
            yield self._respond("")
            return

        if code == "MQ":
            if arg is None or not (arg.isdigit() and len(arg) == 4):
                yield self._error("format")
                return
            if arg not in self.memory_channels:
                yield self._error("cannot_set")
                return
            del self.memory_channels[arg]
            yield self._respond("")
            return

        if code == "SE":
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
            if arg is None or not (arg.isdigit() and len(arg) == 2):
                yield self._error("format")
                return
            record = self.search_banks.get(arg)
            if record is None:
                yield self._error("cannot_set")
                return
            yield self._respond(
                f"SR{arg} SL{record['SL']} SU{record['SU']} ST{record['ST']} "
                f"SH{record['SH']} MD{record['MD']} PT{record['PT']} TT{record['TT']}"
            )
            return

        if code == "SS":
            if arg is None or not (arg.isdigit() and len(arg) == 2):
                yield self._error("format")
                return
            if arg not in self.search_banks:
                yield self._error("cannot_set")
                return
            yield self._respond("")
            return

        if code == "SX":
            if arg is None or not (arg.isdigit() and len(arg) == 2):
                yield self._error("format")
                return
            if arg not in self.search_banks:
                yield self._error("cannot_set")
                return
            del self.search_banks[arg]
            yield self._respond("")
            return

        if code == "SG":
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
                yield self._error("format")
                return
            self.state["OF"] = f"{sign}{nn}"
            yield self._respond("")
            return

        if code == "PP" and arg is not None:
            arg_s = arg.strip()
            if not (arg_s.isdigit() and len(arg_s) == 4):
                yield self._error("format")
                return
            self.state["PP"] = arg_s
            yield self._respond("")
            return

        if code == "CN" and arg is not None:
            arg_s = arg.strip()
            if arg_s.isdigit() and len(arg_s) == 2 and (arg_s == "99" or 1 <= int(arg_s) <= 52):
                self.state["CN"] = arg_s
                yield self._respond("")
            else:
                yield self._error("format")
            return

        if code == "BP" and arg is not None:
            arg_s = arg.strip()
            if arg_s.isdigit() and len(arg_s) == 1 and 0 <= int(arg_s) <= 7:
                self.state["BP"] = arg_s
                yield self._respond("")
            else:
                yield self._error("format")
            return

        if arg is None:
            value = self.state.get(code)
            if value is None:
                yield self._error("not_supported")
            elif code == "WI":
                yield self._respond(value)
            else:
                yield self._respond(f"{code}{value}")
            return

        if not self.vfo_mode and code in _VFO_MODE_CODES:
            yield self._error("cannot_set")
            return
        if code not in self.state and code not in {"RF", "MD", "SQ", "AG"}:
            yield self._error("not_supported")
            return
        self.state[code] = arg
        yield self._respond("")
