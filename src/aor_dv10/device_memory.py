
from __future__ import annotations

from typing import List, Optional

from .constants import CHANNELS_PER_BANK, TAG_WIDTH
from .device_types import (
    DIGITAL_MODES,
    MemoryBankInfo,
    MemoryChannelInfo,
    PassFrequencyEntry,
    ScanGroupInfo,
    SearchBankInfo,
    _format_bank_link,
    _format_rf_freq_mhz,
    _format_search_freq_mhz,
    _mode_write_value,
    _parse_bank_link,
    _parse_composite_fields,
    _validate_mode_pair,
)
from .protocol.codec import DV10ResyncNeeded


class MemoryMixin:

    def _parse_memory_channel_response(
        self, bank: int, channel: int, text: str
    ) -> "MemoryChannelInfo":
        fields = _parse_composite_fields(text.strip(), tag_field="TT")
        if not fields:
            return MemoryChannelInfo(bank=bank, channel=channel, registered=False)
        freq_raw = fields.get("RF")
        step_raw = fields.get("ST")
        stepadj_raw = fields.get("SH")
        return MemoryChannelInfo(
            bank=bank,
            channel=channel,
            registered=True,
            pass_channel=fields.get("MP") == "1",
            frequency_hz=round(float(freq_raw) * 1_000_000) if freq_raw else None,
            step_hz=round(float(step_raw) * 1000) if step_raw else None,
            step_adjust_hz=round(float(stepadj_raw) * 1000) if stepadj_raw else None,
            mode=fields.get("MD"),
            write_protect=fields.get("PT") == "1",
            tag=fields.get("TT", "").strip(),
        )

    def write_memory_channel(
        self,
        bank: int,
        channel: int,
        *,
        frequency_hz: Optional[int] = None,
        step_hz: Optional[int] = None,
        step_adjust_hz: Optional[int] = None,
        mode: Optional[str] = None,
        pass_channel: bool = False,
        write_protect: bool = False,
        tag: Optional[str] = None,
    ) -> None:
        parts = ["MP1" if pass_channel else "MP0"]
        if frequency_hz is not None:
            parts.append(f"RF{float(frequency_hz) / 1_000_000:010.5f}")
        if step_hz is not None:
            parts.append(f"ST{float(step_hz) / 1000:06.2f}")
        if step_adjust_hz is not None:
            parts.append(f"SH{float(step_adjust_hz) / 1000:06.2f}")
        if mode is not None:
            m = str(mode).strip().upper()
            if len(m) == 2:
                m = _mode_write_value(m)
            elif len(m) != 3:
                raise ValueError(
                    f'mode must be "<digital><analog>" 2 chars (e.g. "F0") '
                    f'or a 3-char dan value (e.g. "0F0") - got {m!r}'
                )
            parts.append(f"MD{m}")
        parts.append("PT1" if write_protect else "PT0")
        if tag is not None:
            parts.append(f"TT{tag.strip()[:TAG_WIDTH]}")
        value = f"{int(bank):02d}{int(channel):02d}"
        if parts:
            value += " " + " ".join(parts)
        self._chan.write("MX", value)

    def read_memory_channel(self, bank: int, channel: int) -> MemoryChannelInfo:
        bank, channel = int(bank), int(channel)
        resp = self._chan.read(f"MA{bank:02d}{channel:02d}")
        return self._parse_memory_channel_response(bank, channel, resp.value or "")

    def read_memory_bank(self, bank: int, timeout: float = 5.0) -> List[MemoryChannelInfo]:
        bank = int(bank)
        bank_str = f"{bank:02d}"
        with self._forced_re():
            first = self._chan.send(f"MA{bank_str}")
            responses = [first]
            while responses[-1].result_code == 21:
                nxt = self._chan.read_pending(timeout=timeout)
                if nxt is None:
                    raise DV10ResyncNeeded(
                        f"MA{bank_str} reported more lines were coming (21) but "
                        f"none arrived within {timeout}s"
                    )
                responses.append(nxt)

        channels: List[MemoryChannelInfo] = []
        for resp in responses:
            text = (resp.raw or "").strip()
            if resp.result_code is not None:
                prefix = str(resp.result_code)
                if text.startswith(prefix):
                    text = text[len(prefix):]
            up = text.upper()
            if up.startswith(("MA", "MX")):
                text, up = text[2:], up[2:]
            if up.startswith(bank_str):
                text = text[2:]
            text = text.strip()
            channel_str, _, rest = text.partition(" ")
            if not (channel_str.isdigit() and len(channel_str) == 2):
                continue
            channels.append(self._parse_memory_channel_response(bank, int(channel_str), rest))
        slots = [MemoryChannelInfo(bank=bank, channel=i, registered=False) for i in range(CHANNELS_PER_BANK)]
        for c in channels:
            if 0 <= c.channel < 50:
                slots[c.channel] = c
        return slots

    def tune_memory_channel(self, bank: int, channel: int) -> None:
        self._chan.write("MR", f"{int(bank):02d}{int(channel):02d}")

    def write_memory_bank(
        self,
        bank: int,
        *,
        channel_count: Optional[int] = None,
        protect: Optional[bool] = None,
        tag: Optional[str] = None,
    ) -> None:
        parts = []
        if channel_count is not None:
            parts.append(f"MC{int(channel_count):02d}")
        if protect is not None:
            parts.append(f"PT{1 if protect else 0}")
        if tag is not None:
            parts.append(f"TT{tag.strip()[:TAG_WIDTH]}")
        value = f"{int(bank):02d}"
        if parts:
            value += " " + " ".join(parts)
        self._chan.write("MW", value)

    def get_memory_bank_info(self, bank: int) -> MemoryBankInfo:
        bank = int(bank)
        bank_str = f"{bank:02d}"
        resp = self._chan.read(f"MW{bank_str}")
        text = (resp.value or "").strip()
        up = text.upper()
        if up.startswith("MW"):
            text, up = text[2:], up[2:]
        if up.startswith(bank_str):
            text = text[2:]
        fields = _parse_composite_fields(text.strip(), tag_field="TT")
        count_raw = fields.get("MC")
        return MemoryBankInfo(
            bank=bank,
            channel_count=int(count_raw) if count_raw and count_raw.isdigit() else None,
            protect=fields.get("PT") == "1",
            tag=fields.get("TT", "").strip(),
        )

    def delete_memory_bank(self, bank: int) -> None:
        self._chan.write("MB", f"{int(bank):02d}")

    def delete_memory_channel(self, bank: int, channel: int) -> None:
        self._chan.write("MQ", f"{int(bank):02d}{int(channel):02d}")


    def _parse_search_bank_response(self, bank: int, text: str) -> "SearchBankInfo":
        fields = _parse_composite_fields(text.strip(), tag_field="TT")
        if not fields:
            return SearchBankInfo(bank=bank, registered=False)
        lower_raw = fields.get("SL")
        upper_raw = fields.get("SU")
        step_raw = fields.get("ST")
        stepadj_raw = fields.get("SH")
        return SearchBankInfo(
            bank=bank,
            registered=True,
            lower_limit_hz=round(float(lower_raw) * 1_000_000) if lower_raw else None,
            upper_limit_hz=round(float(upper_raw) * 1_000_000) if upper_raw else None,
            step_hz=round(float(step_raw) * 1000) if step_raw else None,
            step_adjust_hz=round(float(stepadj_raw) * 1000) if stepadj_raw else None,
            mode=fields.get("MD"),
            write_protect=fields.get("PT") == "1",
            tag=fields.get("TT", "").strip(),
        )

    def write_search_bank(
        self,
        bank: int,
        *,
        lower_limit_hz: Optional[int] = None,
        upper_limit_hz: Optional[int] = None,
        step_hz: Optional[int] = None,
        step_adjust_hz: Optional[int] = None,
        mode: Optional[str] = None,
        write_protect: bool = False,
        tag: Optional[str] = None,
    ) -> None:
        parts = []
        if lower_limit_hz is not None:
            parts.append(f"SL{_format_search_freq_mhz(lower_limit_hz)}")
        if upper_limit_hz is not None:
            parts.append(f"SU{_format_search_freq_mhz(upper_limit_hz)}")
        if step_hz is not None:
            parts.append(f"ST{float(step_hz) / 1000:06.2f}")
        if step_adjust_hz is not None:
            parts.append(f"SH{float(step_adjust_hz) / 1000:06.2f}")
        if mode is not None:
            m = str(mode).strip().upper()
            if len(m) not in (2, 3):
                raise ValueError(
                    f'mode must be 2 chars (natural, e.g. "F0") or 3 chars '
                    f'(dan, e.g. "000") - got {m!r}'
                )
            parts.append(f"MD{m}")
        if write_protect:
            parts.append("PT1")
        if tag is not None:
            parts.append(f"TT{tag.strip()[:TAG_WIDTH]}")
        value = f"{int(bank):02d}"
        if parts:
            value += " " + " ".join(parts)
        self._chan.write("SE", value)

    def read_search_bank(self, bank: int) -> SearchBankInfo:
        bank = int(bank)
        resp = self._chan.read(f"SR{bank:02d}")
        return self._parse_search_bank_response(bank, resp.value or "")

    def execute_search(self, bank: int) -> None:
        self._chan.write("SS", f"{int(bank):02d}")

    def delete_search_bank(self, bank: int) -> None:
        self._chan.write("SX", f"{int(bank):02d}")

    def get_search_lower_limit(self) -> Optional[int]:
        resp = self._chan.read("SL")
        raw = (resp.value or "").strip()
        return round(float(raw) * 1_000_000) if raw else None

    def set_search_lower_limit(self, frequency_hz: int) -> None:
        self._chan.write("SL", _format_search_freq_mhz(frequency_hz))

    def get_search_upper_limit(self) -> Optional[int]:
        resp = self._chan.read("SU")
        raw = (resp.value or "").strip()
        return round(float(raw) * 1_000_000) if raw else None

    def set_search_upper_limit(self, frequency_hz: int) -> None:
        self._chan.write("SU", _format_search_freq_mhz(frequency_hz))


    def _parse_scan_group_response(
        self, group: int, text: str, *, has_auto_store: bool
    ) -> "ScanGroupInfo":
        fields = _parse_composite_fields(text.strip())
        delay_raw = fields.get("DL")
        free_raw = fields.get("FR")
        return ScanGroupInfo(
            group=group,
            delay_ds=int(delay_raw) if delay_raw and delay_raw.isdigit() else None,
            free_time_s=int(free_raw) if free_raw and free_raw.isdigit() else None,
            auto_store=(fields.get("AS") == "1") if has_auto_store and "AS" in fields else None,
            bank_link=tuple(_parse_bank_link(fields.get("BK", ""))),
        )

    def write_search_scan_group(
        self,
        group: int,
        *,
        delay_ds: Optional[int] = None,
        free_time_s: Optional[int] = None,
        auto_store: Optional[bool] = None,
        bank_link: Optional[List[int]] = None,
    ) -> None:
        parts = []
        if delay_ds is not None:
            parts.append(f"DL{int(delay_ds):02d}")
        if free_time_s is not None:
            parts.append(f"FR{int(free_time_s):02d}")
        if auto_store is not None:
            parts.append(f"AS{1 if auto_store else 0}")
        if bank_link is not None:
            parts.append(f"BK{_format_bank_link(bank_link)}")
        value = f"{int(group):02d}"
        if parts:
            value += " " + " ".join(parts)
        self._chan.write("SG", value)

    def read_search_scan_group(self, group: int) -> ScanGroupInfo:
        group = int(group)
        resp = self._chan.read(f"SG{group:02d}")
        return self._parse_scan_group_response(group, resp.value or "", has_auto_store=True)

    def write_memory_scan_group(
        self,
        group: int,
        *,
        delay_ds: Optional[int] = None,
        free_time_s: Optional[int] = None,
        bank_link: Optional[List[int]] = None,
    ) -> None:
        parts = []
        if delay_ds is not None:
            parts.append(f"DL{int(delay_ds):02d}")
        if free_time_s is not None:
            parts.append(f"FR{int(free_time_s):02d}")
        if bank_link is not None:
            parts.append(f"BK{_format_bank_link(bank_link)}")
        value = f"{int(group):02d}"
        if parts:
            value += " " + " ".join(parts)
        self._chan.write("MG", value)

    def read_memory_scan_group(self, group: int) -> ScanGroupInfo:
        group = int(group)
        resp = self._chan.read(f"MG{group:02d}")
        return self._parse_scan_group_response(group, resp.value or "", has_auto_store=False)

    def get_auto_store(self) -> bool:
        resp = self._chan.read("AS")
        return (resp.value or "").strip() == "1"

    def set_auto_store(self, enabled: bool) -> None:
        self._chan.write("AS", "1" if enabled else "0")

    def get_bank_link(self) -> List[int]:
        resp = self._chan.read("BK")
        return _parse_bank_link((resp.value or "").strip())

    def set_bank_link(self, banks: Optional[List[int]]) -> None:
        self._chan.write("BK", _format_bank_link(banks))


    def mark_pass_frequency(
        self,
        *,
        frequency_hz: Optional[int] = None,
        bank: Optional[int] = None,
        all_banks: bool = False,
    ) -> None:
        if all_banks and bank is not None:
            raise ValueError("pass bank=<n> and all_banks=True together - use one or the other")
        bank_token = "%%" if all_banks else (f"{int(bank):02d}" if bank is not None else None)
        freq_token = None if frequency_hz is None else _format_search_freq_mhz(frequency_hz)
        if bank_token is None and freq_token is None:
            self._chan.send("PW", retry=False)
        else:
            self._chan.write("PW", (bank_token or "") + (freq_token or ""))

    def list_pass_frequencies(
        self, bank: Optional[int] = None, timeout: float = 5.0
    ) -> List[PassFrequencyEntry]:
        bank_i = None if bank is None else int(bank)
        code = "PR" if bank_i is None else f"PR{bank_i:02d}"
        with self._forced_re():
            first = self._chan.send(code)
            responses = [first]
            while responses[-1].result_code == 21:
                nxt = self._chan.read_pending(timeout=timeout)
                if nxt is None:
                    raise DV10ResyncNeeded(
                        f"{code} reported more lines were coming (21) but none "
                        f"arrived within {timeout}s"
                    )
                responses.append(nxt)

        entries: List[PassFrequencyEntry] = []
        for resp in responses:
            text = (resp.value or "").strip()
            up = text.upper()
            if up.startswith("PR"):
                text, up = text[2:], up[2:]
            if bank_i is not None:
                bank_str = f"{bank_i:02d}"
                if up.startswith(bank_str):
                    text = text[2:]
            index_str, rest = text[:2], text[2:].strip()
            if not (index_str.isdigit() and len(index_str) == 2):
                continue
            if rest in ("", "-", "- -", "- - -", "---"):
                freq_hz = None
            else:
                try:
                    freq_hz = round(float(rest) * 1_000_000)
                except ValueError:
                    freq_hz = None
            entries.append(
                PassFrequencyEntry(index=int(index_str), frequency_hz=freq_hz, bank=bank_i)
            )
        return entries

    def delete_pass_frequencies(
        self,
        *,
        bank: Optional[int] = None,
        index: Optional[int] = None,
        all_banks: bool = False,
    ) -> None:
        if all_banks and bank is not None:
            raise ValueError("pass bank=<n> and all_banks=True together - use one or the other")
        if index is not None and bank is None and not all_banks:
            raise ValueError(
                "PD has no form to delete a single VFO-search pass frequency by "
                "index alone - only the whole VFO-search list (bare PD)"
            )
        if index is not None and all_banks:
            raise ValueError(
                "PD has no form combining the %% (all banks) wildcard with a "
                "specific pass-frequency index - only PDbbnn (one bank, one index)"
            )
        if bank is None and not all_banks:
            self._chan.send("PD", retry=False)
            return
        bank_token = "%%" if all_banks else f"{int(bank):02d}"
        if index is None:
            self._chan.write("PD", bank_token)
        else:
            self._chan.write("PD", f"{bank_token}{int(index):02d}")

