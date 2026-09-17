
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from .protocol.codec import DV10Error, DV10ProtocolError, DV10ResyncNeeded, Response


@dataclass
class SdCardFile:

    name: str
    extension: str
    timestamp: Optional[str] = None
    duration: Optional[str] = None
    size_bytes: Optional[int] = None


@dataclass
class SdCardInfo:

    free_kb: int
    free_hours: Optional[float]
    total_kb: int


SD_CARD_STATUS = {
    "0": "card present, no access",
    "1": "recording",
    "2": "playing back",
    "3": "processing (not recording or playing back)",
    "4": "SD card not found, can't be used, or another error",
}

SD_BACKUP_KIND_SEARCH_BANK = "SRCHBK"
SD_BACKUP_KIND_SEARCH_GROUP = "SRCHGRP"
SD_BACKUP_KIND_MEMORY_CHANNEL = "MEMCH"
SD_BACKUP_KIND_SCAN_GROUP = "SCANGRP"
SD_BACKUP_KIND_ALL = "SYSYEM"
_SD_BACKUP_KINDS = {
    SD_BACKUP_KIND_SEARCH_BANK,
    SD_BACKUP_KIND_SEARCH_GROUP,
    SD_BACKUP_KIND_MEMORY_CHANNEL,
    SD_BACKUP_KIND_SCAN_GROUP,
    SD_BACKUP_KIND_ALL,
}

_SD_ERROR_HINTS = {
    "CARDBUSY": "SD card busy",
    "NOCARD": "SD card not found",
    "FAT12": "SD card is formatted FAT12 and can't be used by this receiver",
    "NOFILE": "the specified file does not exist on the SD card",
    "CARDFULL": "SD card has no free space left",
}


def _check_sd_error(text: str) -> None:
    token = (text or "").strip().upper()
    hint = _SD_ERROR_HINTS.get(token)
    if hint is not None:
        raise DV10ProtocolError(token, text, hint=hint)


def _sd_value(resp: Response, prefix: str) -> str:
    text = (resp.value or "").strip()
    if text.upper().startswith(prefix.upper()):
        text = text[len(prefix):].strip()
    _check_sd_error(text)
    return text


class SdMixin:

    def _sd_action(self, code: str, value: Optional[str] = None) -> str:
        with self._forced_re():
            resp = self._chan.send(code, value)
        return _sd_value(resp, code)

    def sd_dir(self, timeout: float = 5.0) -> List[SdCardFile]:
        with self._forced_re():
            first = self._chan.send("SD DIR")
            responses = [first]
            while responses[-1].result_code == 21:
                nxt = self._chan.read_pending(timeout=timeout)
                if nxt is None:
                    raise DV10ResyncNeeded(
                        f"SD DIR reported more lines were coming (21) but none "
                        f"arrived within {timeout}s"
                    )
                responses.append(nxt)

        files: List[SdCardFile] = []
        for resp in responses:
            text = _sd_value(resp, "SD DIR")
            if re.match(r"^\d+FILE\(S\)$", text, re.IGNORECASE):
                continue
            parts = text.split()
            if len(parts) != 4:
                continue
            name_ext, second, date_s, time_s = parts
            name, dot, ext = name_ext.rpartition(".")
            if not dot:
                name, ext = name_ext, ""
            entry = SdCardFile(name=name, extension=ext, timestamp=f"{date_s} {time_s}")
            if ext.upper() == "WAV":
                entry.duration = second
            else:
                try:
                    entry.size_bytes = int(second)
                except ValueError:
                    pass
            files.append(entry)
        return files

    def sd_info(self) -> SdCardInfo:
        resp = self._chan.read("SD INF")
        text = _sd_value(resp, "SD INF")
        m = re.match(
            r"FREE:\s*(\d+)\s*KB\s*\(\s*([\d.]+)\s*H\s*\)\s*TOTAL:\s*(\d+)\s*KB",
            text,
            re.IGNORECASE,
        )
        if not m:
            raise DV10Error(f"unrecognised SD INF response: {text!r}")
        return SdCardInfo(
            free_kb=int(m.group(1)),
            free_hours=float(m.group(2)),
            total_kb=int(m.group(3)),
        )

    def sd_status(self) -> str:
        resp = self._chan.read("SD PST")
        text = (resp.value or "").strip()
        if text.upper().startswith("SD PST"):
            text = text[len("SD PST"):].strip()
        return text

    def sd_record_start(self) -> None:
        self._sd_action("SD REC")

    def sd_record_stop(self) -> None:
        self._sd_action("SD REC", "/")

    def sd_play(self, name: str) -> None:
        self._sd_action("SD PLY", name)

    def sd_play_stop(self) -> None:
        self._sd_action("SD PLY", "/")

    def sd_backup(self, kind: str) -> None:
        kind_u = kind.strip().upper()
        if kind_u not in _SD_BACKUP_KINDS:
            raise ValueError(
                f"unknown SD backup kind {kind!r} - expected one of "
                f"{', '.join(sorted(_SD_BACKUP_KINDS))}"
            )
        self._sd_action("SD MMW", kind_u)

    def sd_restore(self, name: str) -> None:
        self._sd_action("SD MMR", name.strip())

    def get_sd_squelch_skip(self) -> str:
        resp = self._chan.read("SD RSQ")
        text = (resp.value or "").strip()
        if text.upper().startswith("SD RSQ"):
            text = text[len("SD RSQ"):].strip()
        return text

    def set_sd_squelch_skip(self, skip: bool) -> None:
        self._chan.write("SD RSQ", "1" if skip else "0")
