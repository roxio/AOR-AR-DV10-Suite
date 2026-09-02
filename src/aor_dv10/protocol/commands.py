"""AR-DV10 / AR-DV1 command mnemonic registry.

Sourced from AOR's official "AR-DV10 AND AR-DV1 COMMAND LIST SUMMARY"
(aorja.com/support/manuals/AR-DV10_AND_AR-DV1_COMMAND_LIST_SUMMARY.pdf).
That document lists every mnemonic, a short description, and whether it is
Read-only, Write-only, or Read/Write - but *not* the byte-level value
encoding for each field (digit widths, units, enumerations). Where the
encoding is documented elsewhere or inferable with reasonable confidence
(frequency in Hz, on/off as "0"/"1", etc.) it's noted in ``notes``; otherwise
treat the value as an opaque string until confirmed against real hardware or
the full manual.

This table intentionally covers the *entire* published command set (not just
the handful with typed helpers on :class:`aor_dv10.device.DV10Device`), so
the CLI's ``raw`` command and tab-completion have full coverage from day one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Access(Enum):
    READ = "R"
    WRITE = "W"
    READ_WRITE = "RW"


@dataclass(frozen=True)
class Command:
    code: str
    description: str
    access: Access
    notes: str = ""


def _c(code: str, description: str, access: str, notes: str = "") -> Command:
    return Command(code=code, description=description, access=Access(access), notes=notes)


# code -> Command
COMMANDS: dict[str, Command] = {
    cmd.code: cmd
    for cmd in [
        _c("AC", "AGC", "RW", "AR-DV3 spec: 0=Fast, 1=Mid, 2=Slow, 3=RF-G - a 4-state speed selector, not on/off. DV3 spec says only valid in AM (other modes -> result code 30), but a real DV10 test (AC 0 / AC 1, in VFO mode) succeeded while apparently in FM mode - so either the AM-only restriction does not apply to DV10, or the mode at test time differed from what MD reported. Unconfirmed."),
        _c("AG", "Audio gain (volume)", "RW", "AR-DV3 spec: 00-99 (00=mute, 99=max). Confirmed on real DV10 with RE 1 (result-code prefixing) enabled: a bare read ('AG' with no argument) returns result code 60 (PC_RESULT_NONE / command does not exist) - so this firmware genuinely does not support reading AG in this form, resolving the earlier bare-'?' mystery."),
        _c("AN", "Earphone antenna ON/OFF (FM 64-108MHz)", "RW"),
        _c("AS", "Auto store", "RW", "Standalone auto-store on/off, also reachable as SG's own AS sub-field (search-side scan groups only - MG/memory-side has no AS field at all). Spec: This command may be used alone. See aor_dv10.device.DV10Device.get_auto_store()/set_auto_store()."),
        _c("AT", "Attenuator ON/OFF", "RW", "3-state selector (0=ATT OFF, 1=ATT ON, 2=10dB ATT). Labels follow a real DV10's effect (1 engages the ~10dB signal attenuator) per user report; the AR-DV3 spec's 'AMP ON/AMP OFF' wording doesn't match real behaviour. Wire values unchanged; 2 (10dB) is DV3-only."),
        _c("AV", "VolATT", "RW", "AR-DV10 operating manual (5.2): 00 (max)-15 (most attenuated), default 05 - caps how loud the physical (analog, non-remote) volume knob can go. Very likely the actual remotely-controllable volume on this receiver, given AG is confirmed non-functional - see device.get_volume_limit()."),
        _c("BK", "Bank link", "RW", "Standalone bank-link list (2-digit-per-bank, no separator; bb=99 disables all links), also reachable as the BK sub-field embedded in SG/MG. Spec: This command may be used alone. See aor_dv10.device.DV10Device.get_bank_link()/set_bank_link()."),
        _c("BP", "Beep", "RW", "Wire format/range corrected against the AR-DV1 wire spec: single digit 0-7, default 2 (0=Min/OFF, 7=Max) - not the two-digit 00-15/default-05 this project originally assumed from the AR-DV10 operating manual's MENU-CONFIG listing. Which document this actual firmware follows is unconfirmed; see aor_dv10.device.DV10Device.get_beep_level()/set_beep_level()."),
        _c("CC", "DMR color code", "RW", "AR-DV10 operating manual (10.7): 00 (decode all) to 16."),
        _c("CI", "Tone squelch ON/OFF", "RW", "NOT a plain boolean, despite the command summary's name - confirmed against real DV10 hardware to be a 3-value SQL TYPE selector: 0=OFF, 1=CTCSS (inferred by elimination, not independently read back), 2=Reverse Tone (confirmed - read back with the front panel showing 'REV.T'). DCS is a separate, independent toggle (see DI), not one of CI's values. See aor_dv10.device.TONE_SQUELCH_TYPES/get_squelch_tone_type()."),
        _c("CM", "DMR mute-by-color-code ON/OFF", "RW", "When on, only CC color code is decoded."),
        _c("CN", "Tone squelch frequency", "RW", "Confirmed against the AR-DV1 wire spec: CNnn is INDEX-based (nn=01-52, a 1-based index into device.CTCSS_TONES_HZ) or 99=search - NOT the literal decimal Hz value this project originally guessed. Also used for REVERSE TONE (same table, inverted squelch logic). See aor_dv10.device.DV10Device.get_tone_squelch_freq()/set_tone_squelch_freq()."),
        _c("CT", "Function", "RW"),
        _c("DA", "Digital amp (sound gain)", "RW", "AR-DV10 manual addendum (since v.1812C): 01.00 (normal) to 15.94 (loudest). Only useful if max volume with VOL ATT=00 is still insufficient."),
        _c("DC", "D-CR 15 bit descramble code", "RW", "AR-DV10 operating manual (10.7, DCR ENC C): 00001-32767, or 00000 for no scramble code."),
        _c("DI", "DCS ON/OFF", "RW", "Confirmed against real DV10 hardware: DI=1 with the front panel's SQL TYPE menu showing 'DCS' (CI reads its OFF value, '0', at the same time - DCS is independent of CI, not one of its values). Enables DCS squelch (see DS for the code). Manual 10.5.2. 0/1 boolean encoding confirmed for the DCS-active case; the OFF case (DI=0) not separately verified but presumed symmetric."),
        _c("DJ", "Digital data output", "RW"),
        _c("DK", "Acquire digital data", "R"),
        _c("DL", "Delay time", "RW", "Standalone DLnnn (000-099, 0.1 sec increments; 100 means unlimited). Distinct from the DL sub-field inside the SG/MG scan-group composites - see aor_dv10.device.DV10Device.get_delay_time_ds()/set_delay_time_ds()."),
        _c("DS", "DCS code", "RW", "AR-DV10 operating manual (10.5.2): one of 106 standard DCS codes (see device.DCS_CODES) or SRCH (auto-detect)."),
        _c("DT", "System clock", "RW", "AR-DV10 operating manual (11.1): YY-MM-DD HH:MM on the front panel; wire digit format unconfirmed, see device.get_clock()/set_clock()."),
        _c("EX", "End remote control", "W"),
        _c("FD", "Frequency scope: fast-speed scan data", "R", "Single-line, concatenated 3-digit dBm chunks (same chunking convention as LM's own S-meter reading: dbm equals negative int(chunk)). CAVEAT: documented as requiring \"scope mode\" (result code 30 otherwise) - no command or front-panel procedure to enter that mode was found anywhere in any reference document, including the full operating manual. May be unreachable in practice. See aor_dv10.device.DV10Device.read_scope_data_fast()."),
        _c("FR", "Free time", "RW", "Standalone FRnn (00-60 seconds; 00 means OFF). Distinct from the FR sub-field inside the SG/MG scan-group composites - see aor_dv10.device.DV10Device.get_free_time_s()/set_free_time_s()."),
        _c("GL", "Frequency scope: normal-speed scan data", "R", "21-continuing multi-line read (same shape as SD DIR/PR/MA/VI), one line per scan point shaped \"Ffffff.fffffLkkc\". NOTE: the spec's own syntax gives a 2-digit level field, narrower than the 3-digit convention used by LM/FD - implemented literally as specified but unconfirmed against real hardware. Same \"scope mode\" caveat as FD - see aor_dv10.device.DV10Device.read_scope_data_normal()."),
        _c("IF", "IF bandwidth", "RW", "Per-mode bandwidth selector - see aor_dv10.device.IF_BANDWIDTH_HZ (keyed by named demod type: FM/AM/SAH/SAL/USB/LSB/CW, not this project's usual 2-char mode codes). Kept as a raw string, not int(): the spec's own syntax documents the response shape as \"IFn, IFnn\" - potentially 2 digits, even though every documented value only needs 1. See DV10Device.get_if_bandwidth()/set_if_bandwidth()."),
        _c("KL", "Key backlight color", "RW", "KLn (0-7) - see aor_dv10.device.KEY_BACKLIGHT_COLORS. Note: the spec's own literal label for n=3 is \"MAGENDA\", not \"MAGENTA\" - confirmed as a genuine spec typo (not a pdftotext artifact) via both the rendered PDF image and the raw text layer, the same two-method cross-check as the \"SYSYEM\" backup-kind typo. See DV10Device.get_key_backlight_color()/set_key_backlight_color()."),
        _c("LB", "LCD backlight", "RW", "AR-DV10 operating manual (11.2): OFF (default)/CONT (always on)/AUTO (on for 5s after activity). Digit encoding unconfirmed - see device.BACKLIGHT_MODES."),
        _c("LC", "Frequency data output", "RW"),
        _c("LD", "LCD dimmer", "RW"),
        _c("LM", "S-meter reading", "R", "LMvvvq - vvv = signal level as -vvv dB, q = squelch state. The q mapping was corrected against the AR-DV1 wire spec's own LM entry: 0=closed, 1=noise/level squelch open, 2=tone/DCS/reverse squelch open, 3=detecting digital mode - the previous AR-DV3-spec-sourced guess (1=open, 2=open by CTCSS/DCR/VoiceSQ, 3=open by LevelSQ/NoiseSQ) grouped the squelch types wrong and mislabelled state 3 entirely. vvv still matches real DV10 readings like 1001/1011/1081 decoding to about -100..-108 dB. See device.SQUELCH_STATES."),
        _c("LN", "LCD contrast", "RW", "Range/default corrected against the AR-DV1 wire spec: 00 (lightest) - 63 (darkest), default 25 - not 00-40/default 30 per the AR-DV10 operating manual (11.2). Which document this actual firmware follows is unconfirmed; wire FORMAT (2-digit) is unchanged."),
        _c("LQ", "Level squelch", "RW", "AR-DV3 spec: LQnn, 00-99, sets the level-squelch threshold - this is the actual squelch *level* most users mean by squelch, as distinct from SQ (squelch mode selector) and NQ (noise squelch)."),
        _c("LS", "Auto-notch", "RW"),
        _c("LT", "S-meter data output", "RW"),
        _c("LU", "LCD direction", "RW"),
        _c("MA", "Read memory channel / bank-form multi-line read", "R", "Implemented per the AR-DV1 wire spec: MAbbcc reads one channel (bank+channel, 2 digits each); MAbb (bank digits only) triggers a bank-form dump of all 50 channels in that bank as consecutive response lines, reliably distinguishable only when RE is on - see aor_dv10.device.DV10Device.read_memory_bank(), which temporarily forces RE on for the duration of the read. See also aor_dv10.device.DV10Device.read_memory_channel()."),
        _c("MB", "Delete memory bank", "W", "MBbb deletes bank bb and all channels registered in it. See aor_dv10.device.DV10Device.delete_memory_bank()."),
        _c("MD", "Decoding mode", "RW", "AR-DV3 spec: 3 chars 'dan' (or 2 'da'): d=currently-receiving digital mode (read-only info), a=digital mode to set (0=Auto,1=D-STAR,2=YAESU,3=ALINCO,4=D-CR,5=P25,6=dPMR,7=DMR,8=TETRA T-DM,9=TETRA T-TC,F=digital off), n=analog mode (0=FM,1=AM,2=SAH,3=SAL,4=USB,5=LSB,6=CW; omit n to force a=F). Matches '0F0' observed on real DV10 (plain FM, digital off)."),
        _c("MDB", "MD output with busy flag information", "R"),
        _c("MG", "Scan group (memory-side)", "RW", "MGgg [DLmm] [FRpp] [BKbbb...] - like SG but for memory-bank scanning, and with NO auto-store (AS) sub-field at all (unlike SG). The bare-group READ direction is UNCONFIRMED - unlike SG's own result-code text, which explicitly says Setting / Reading completed, MG's says only Set completed. See aor_dv10.device.DV10Device.write_memory_scan_group()/read_memory_scan_group()."),
        _c("MM", "Last channel memory registration", "W", "Confirmed from the AR-DV1 wire spec to be two-phase: an immediate 21 (registration started) followed by 20 (registration completed) once it actually finishes - the one command in this project's set with more than one response line per request. See aor_dv10.device.DV10Device.register_last_channel() and aor_dv10.protocol.codec.CommandChannel.read_pending()."),
        _c("MP", "Pass channel", "RW", "NOT YET implemented as a standalone command in this project - the MX composite write can already set a channel pass flag via its own MP sub-field, see aor_dv10.device.DV10Device.write_memory_channel(). Standalone MP get/set is not yet implemented."),
        _c("MQ", "Delete memory channel", "W", "MQbbcc deletes (unregisters) channel cc in bank bb. See aor_dv10.device.DV10Device.delete_memory_channel()."),
        _c("MR", "Tune to memory channel", "W", "MRbbcc tunes the receiver to the given registered channel (bank+channel, 2 digits each) - a live jump-to-memory action, not a data read despite the command name. See aor_dv10.device.DV10Device.tune_memory_channel()."),
        _c("MS", "Memory scan", "W"),
        _c("MW", "Read/write memory bank settings", "RW", "MWbb reads or writes the channel-count, protect-flag and tag fields of a memory bank (composite, space-separated sub-fields per the AR-DV1 spec). The read direction is unconfirmed against real hardware - no explicit To read: line was found for MW in the spec - and returns documented defaults for a never-written bank. See aor_dv10.device.DV10Device.write_memory_bank() and get_memory_bank_info()."),
        _c("MYSRCHBK", "Output search bank backup file content", "R"),
        _c("MYSRCHGRP", "Output search group backup file content", "R"),
        _c("MYMEMCH", "Output memory channel backup file content", "R"),
        _c("MYMEMBK", "Output memory bank backup file content", "R"),
        _c("MYSCANGRP", "Output scan group backup file content", "R"),
        _c("MYSYSTEM", "Output all receiver settings backup file content", "R"),
        _c("MX", "Write memory channel (composite multi-field)", "W", "Implemented per the AR-DV1 wire spec: MXbbcc followed by space-separated optional sub-fields (MP=pass flag, RF=frequency, ST=step, SH=step-adjust, MD=mode, PT=write-protect, TT=tag). Safety-critical note: the MD sub-field embedded within an MX write is sent as a 2-character 'da' value, NOT the 3-character 'dan' shape standalone MD was confirmed to need (see aor_dv10.device._mode_write_value()) - see the docstring on aor_dv10.device.DV10Device.write_memory_channel() for why this is intentional (a different, still-unconfirmed sub-field, not something to 'fix' to match set_mode()) and must not be conflated with it. Omitted fields keep their previous value except MP/PT, which reset to 0 when omitted."),
        _c("MZ", "Write backup file info", "W"),
        _c("NC", "NXDN RAN code", "RW", "AR-DV10 operating manual (10.7): 00 (decode all) to 63."),
        _c("NM", "NXDN mute-by-RAN-code ON/OFF", "RW", "When on, only NC RAN code is decoded."),
        _c("NQ", "Noise squelch", "RW", "AR-DV3 spec: NQnn, 00-39, sets the noise-squelch threshold used when SQ (squelch mode) is set to 1=Noise - a sibling of LQ (level squelch, used when SQ=2=Level)."),
        _c("NR", "Noise reduction", "RW"),
        _c("OF", "Offset receive", "RW", "Corrected against the AR-DV1 wire spec: OFsnn - nn=00-39 is the offset slot (00=disabled/0Hz, 01-19=user, 20-39=presets, matching this project's prior understanding) but s (a leading +/- direction sign, omittable only when nn=00) is a field this project had entirely missed - it was never previously sent at all. See aor_dv10.device.DV10Device.get_offset_slot()/set_offset_slot()."),
        _c("OL", "Offset frequency", "RW", "Reworked against the AR-DV1 wire spec: OLnn RFffff.fffff - a COMBINED slot-number+frequency write (nn=00-39), unsigned (direction comes from OF's own sign field, not from this value), and reads also require the slot number (OLnn<CR>, never a bare OL<CR>) - this project's original bare-read/signed-value model was wrong on every count. Also global (not per-VFO/bank/channel) per the spec's own remark. See aor_dv10.device.DV10Device.get_offset_freq()/set_offset_freq()."),
        _c("OT", "DMR slot selection", "RW", "AR-DV10 manual addendum (from 1509F): 1+2 / 2+1 / 1 / 2."),
        _c("OX", "Monitor offset", "RW"),
        _c("PC", "APCO P25 NAC code", "RW", "AR-DV10 operating manual (10.7): 3 hex digits, 000 (decode all) to FFF."),
        _c("PD", "Delete pass frequencies", "W", "Bare PD deletes every VFO-search pass frequency; PDbb (or PD%% for every bank) deletes a whole bank's list; PDbbnn deletes one specific entry by index. See aor_dv10.device.DV10Device.delete_pass_frequencies()."),
        _c("PM", "APCO P25 mute-by-NAC-code ON/OFF", "RW", "When on, only PC NAC code is decoded."),
        _c("PO", "Priority receive ON/OFF", "RW", "AR-DV10 operating manual chapter 8."),
        _c("PP", "Priority receive channel", "RW", "Corrected against the AR-DV1 wire spec: PPbbcc - bank and channel run together with NO separator (this project's original \"bb-cc\" hyphenated guess, modelled after the manual's own display notation, would have been rejected by real hardware). See aor_dv10.device.DV10Device.get_priority_channel()/set_priority_channel()."),
        _c("PR", "List pass frequencies", "R", "PR (VFO search) or PRbb (a specific search bank) lists all 50 pass-frequency slots as a multi-line response, terminated by result code 20 with continuation lines flagged 21 - the same shape this project already handles for MA's bank form, reliably distinguishable only when RE is on. See aor_dv10.device.DV10Device.list_pass_frequencies()."),
        _c("PT", "Write protect", "RW", "Possibly the MENU-CONFIG page-2 auto-store-on-shutdown PROTECT flag (manual 11.2 item 7) rather than a per-memory-channel protect bit - see device.get_write_protect()."),
        _c("PW", "Mark a pass frequency", "W", "4 shapes - bare PW (mark current receive frequency for VFO search), PWffff.ffff (mark a specific frequency for VFO search), PWbb (mark current frequency in program-search bank bb), PWbbffff.ffff (mark a specific frequency in bank bb) - bb may be %% for every search bank. See aor_dv10.device.DV10Device.mark_pass_frequency()."),
        _c("QP", "Power off, disconnect", "W"),
        _c("RE", "Result code", "RW", "AR-DV3 spec: REn (0/1) toggles whether responses are PREFIXED with a numeric result code (10=unrelated message, 20=OK, +1=more lines follow, 30=cannot set due to current conditions, 40=format error, 50=out of range, 60=command does not exist). Confirmed on real DV10: 'raw RE 1' succeeds (its own write ack carries value '20', i.e. PC_RESULT_OK) and subsequent rejections do come back as '<code>?' instead of a bare '?' - see aor_dv10.protocol.codec.RESULT_CODES."),
        _c("RF", "Receive frequency", "RW", "decimal MHz. Read: CODE + 4 zero-padded integer digits + . + 5 decimal digits, e.g. 0145.50000 - confirmed on real DV10 hardware. AR-DV3 spec (presumed same family) describes writes more flexibly, decimal point required, width not fixed, range 0.1-3000.0 MHz - but on real DV10 the actual blocker for writes turned out to be VFO mode, not the digit format."),
        _c("RG", "Manual gain", "RW", "Range/default corrected against the AR-DV1 wire spec: 000 (min) - 110 (max), default 099 - not 000-255 per the AR-DV10 operating manual (10.2). Which document this actual firmware follows is unconfirmed; wire FORMAT (3-digit) is unchanged. Only takes effect when AGC (AC) is set to 3=RF-G."),
        _c("RN", "Serial number", "R", "CORRECTED access from the summary table's own R/W to R-only - the detailed \"AR-DV1 SERIAL NUMBER\" section documents only \"To read: RN<CR>\" / \"Response: RN0952zzzz\", no write syntax and none of the format/range-error result codes every genuinely-writable command here does list. Same summary-table-vs-detail-page precedent as SE's own access correction. See also SN's entry below - investigated and deliberately left raw-only. See DV10Device.get_serial_number()."),
        _c("RS", "Reset", "W", "AR-DV10 operating manual (11.2): 4=SYSTEM RESET (keeps memory), 5=FULL RESET (erases everything). DESTRUCTIVE; argument encoding unconfirmed."),
        _c("RT", "Receiver status output", "RW"),
        _c("RX", "Receiver status", "R"),
        _c("SB", "Communication speed (baud)", "RW"),
        _c("SC", "Voice descrambler frequencies", "R", "AR-DV10 operating manual (10.6): descrambler carrier frequency, 2000-7000Hz."),
        _c("SD DIR", "SD card: file directory", "R", "Bare SD DIR, one line per file (21-continuing, same shape as PR/MA/VI), plus a trailing nnnFILE(S) count line. Two documented per-file line shapes depending on extension: WAV files get a recorded duration, everything else gets a byte size. See aor_dv10.device.DV10Device.sd_dir()."),
        _c("SD INF", "SD card: card information", "R", "Free/total capacity plus an approximate free-recording-hours figure. See aor_dv10.device.DV10Device.sd_info()."),
        _c("SD LGR", "SD card: log info ON/OFF", "RW", "Deliberately left raw-only: the AR-DV1 command summary explicitly marks this \"No function\" for this receiver, with no detailed page anywhere in the full command reference (unlike every other SD command) - confirmed via the summary PDF table itself, not just the abbreviated one."),
        _c("SD MMR", "SD card: file restore", "W", "SD MMR<name> - restores a prior sd_backup(); name is documented as an arbitrary \"original file name\", not the same 5-token enum SD MMW uses for its kind argument. See aor_dv10.device.DV10Device.sd_restore()."),
        _c("SD MMW", "SD card: file backup", "W", "SD MMW<kind> - kind is one of SRCHBK/SRCHGRP/MEMCH/SCANGRP/SYSYEM (sic - the spec's own literal token for All is misspelled, confirmed via both the rendered PDF image and pdftotext's raw text layer independently). This is the mechanism behind AOR's serial-backup feature. See aor_dv10.device.DV10Device.sd_backup()."),
        _c("SD PLY", "SD card: playback", "W", "SD PLY<name> to start, SD PLY/ to stop (the spec's documented stop convention). See aor_dv10.device.DV10Device.sd_play()/sd_play_stop()."),
        _c("SD PST", "SD card: record/playback status", "R", "Bare digit 0-4 - see aor_dv10.device.SD_CARD_STATUS and DV10Device.sd_status()."),
        _c("SD REC", "SD card: recording", "W", "Bare SD REC to start (auto-generated file name - the spec gives no way to choose one), SD REC/ to stop (the spec's documented stop convention). See aor_dv10.device.DV10Device.sd_record_start()/sd_record_stop()."),
        _c("SD RSQ", "SD card: squelch skip", "RW", "Bare read, SD RSQn write (n: 0=no skip, 1=skip [default]) - a simple single-digit RW command, fully documented in the same spec section, so typed alongside the rest rather than left raw. See aor_dv10.device.DV10Device.get_sd_squelch_skip()/set_sd_squelch_skip()."),
        _c("SD TYP", "SD card: recording file type selection", "RW", "Deliberately left raw-only: the AR-DV1 command summary explicitly marks this \"No function\" for this receiver, with no detailed page anywhere in the full command reference (unlike every other SD command) - confirmed via the summary PDF table itself, not just the abbreviated one."),
        _c("SE", "Search bank setting", "W", "SEbb [SLffff.ffff] [SUffff.ffff] [STggg.gg] [SHhhh.hh] [MDdan] [PTa] [TTttt] - a program-search scan range (write-only; use SR to read it back). Access corrected from the placeholder R to W - it is SR, a separate mnemonic, that reads a search bank back, not a bare SE. Note: the AR-DV1 spec PDF's own SE table has a corrupted To-read/Response cell (a verbatim copy-paste of the unrelated SD DIR table) - see aor_dv10.device.DV10Device.write_search_bank() for the full account."),
        _c("SG", "Scan group (search-side)", "RW", "SGgg [DLmm] [FRpp] [ASn] [BKbbb...] - delay time, free time, auto-store and bank-link list for a search-side scan group. Result-code text explicitly confirms both directions ('Setting / Reading completed'), unlike MG's. See aor_dv10.device.DV10Device.write_search_scan_group()/read_search_scan_group()."),
        _c("SH", "Frequency step adjust", "RW", "AR-DV10 operating manual (5.9): fine sub-step offset, 0Hz up to half the ST step, in increments as fine as 0.05kHz."),
        _c("SI", "Voice descramble ON/OFF", "RW", "AR-DV10 operating manual (10.6): analog voice-inversion descrambler (V.SCR), FM-only, IF bandwidth 6/15kHz. Not available on US-market units."),
        _c("SL", "Search bank lower limit", "RW", "Bare SL reads, SLffff.ffff writes - a SESSION-ONLY value per the spec's own Remarks (effective until SS is sent, receive mode changes, or power off; fold it into a bank via SE to persist it). ffff.ffff is 4 decimal digits (100Hz resolution), narrower than RF/OL's 5-digit (10Hz). See aor_dv10.device.DV10Device.get_search_lower_limit()/set_search_lower_limit()."),
        _c("SN", "Output serial number", "R", "Deliberately left raw-only: unlike every other command in the AR-DV1 command summary table (even the \"No function\" ones), SN's own row has no page-number cross-reference into the detailed command list at all - and no PDF among every reference document available to this project (the full command list, both summary PDFs, the AR8200/AR-DV3/GSSI command lists, the manual addendum, the command-list-additions document, the full operating manual) contains a dedicated SN section anywhere. Cross-checked against RN (see that entry's own note) on the theory the two might be duplicates or related - they are not obviously so; SN appears to be an orphaned placeholder in the summary table with nothing backing it."),
        _c("SP", "Sleep timer", "RW", "Marked \"No function\" for DV10 in the official command summary; kept for completeness."),
        _c("SQ", "Select squelch (squelch level)", "RW", "AR-DV3 spec: 0=Auto, 1=Noise, 2=Level - selects the squelch *mode*, not a level, despite the summary's 'squelch level' description. The actual threshold is LQ (level squelch, 00-99) or NQ (noise squelch, 00-39)."),
        _c("SR", "Read search bank", "R", "SRbb reads back a search bank written via SE. Unlike MA (memory channels), an unregistered bank is a real ERROR here (result code 30, Bank unregistered per the spec's own text) rather than a placeholder success response - see aor_dv10.device.DV10Device.read_search_bank()'s docstring. Response field layout is inferred by analogy with SE's own write layout (SR's spec entry doesn't show one), same as MA mirrors MX."),
        _c("SS", "Execute program search", "W", "SSbb starts a program search over bank bb's configured range. Raises result code 30 if the bank isn't registered. See aor_dv10.device.DV10Device.execute_search()."),
        _c("ST", "Frequency step", "RW", "AR-DV10 operating manual (5.8): many presets from 10Hz to 500kHz (8.33k/9k/10k/12.5k/15k/20k/25k/30k/50k confirmed visible on one menu page, more on others). Confirmed against real hardware: wire format is STggg.gg, kHz-decimal (same shape as SH) - a bare integer Hz write is rejected with result code 40."),
        _c("SU", "Search bank upper limit", "RW", "Bare SU reads, SUffff.ffff writes - same session-only caveat as SL. Note: the AR-DV1 spec PDF's own SU entry text literally describes its parameter as low limit frequency (an apparent copy-paste from the SL entry above it) - treated as a documentation typo, see aor_dv10.device.DV10Device.get_search_upper_limit()'s docstring for why. See also set_search_upper_limit()."),
        _c("SX", "Delete search bank", "W", "SXbb deletes search bank bb. DESTRUCTIVE. Raises result code 30 if the bank isn't registered. See aor_dv10.device.DV10Device.delete_search_bank()."),
        _c("TI", "Priority receive interval", "RW", "AR-DV10 operating manual chapter 8: 1-99 seconds."),
        _c("TR", "Alarm/recording timer", "RW", "TRn XEe [TYy] [RPm] [RMrrr....] [TSttt....] [TEttt....] [WEx....] [AGvv] - modelled as a SINGLE unnumbered timer (bare read TR<CR> has no index; the spec never gives n a range). The AR-DV1 spec PDF's own syntax cell for TR is internally inconsistent - it omits the XE sub-field entirely and writes the literal 'TR1' instead of 'TRn' - recoverable only from the same entry's Remarks/Default prose ('TRnXE0', 'Default: TRn XE0 TY0 RMVFA TS01010000 TE01010000'). TY's value is never defined anywhere in the spec (every other field gets a letter-meaning line, this one doesn't) - passed through as an opaque int. See aor_dv10.timer's module docstring for the full account, and aor_dv10.device.DV10Device.write_recording_timer()/read_recording_timer()."),
        _c("TS", "T-TC mode slot number", "RW"),
        _c("VE", "VFO search setting", "RW", "VE DLmm FRpp ASn - the (single, receiver-wide, not per-VFO or per-group) delay/free-time/auto-store configuration used by VS. Access corrected from the placeholder R to RW - the AR-DV1 spec's own summary table lists it R/W, and the command's own entry has no To-read row because a bare VE<CR> read is the same shape as every other RW command here. See aor_dv10.device.DV10Device.read_vfo_search_settings()/write_vfo_search_settings()."),
        _c("VF", "VFO receive", "W", "CONFIRMED on real DV10: 'raw VF A' succeeds (bare 'VF' ack, no value) - this is the software command to enter VFO mode (see DV10Device.enter_vfo_mode()). Also confirmed: 'raw VF 1' (a digit, an old guess) fails with result code 40 under RE 1 - VF wants a letter, not 0/1. Extended with the AR-DV1 spec's full atomic form - VFt RFffff.fffff STggg.gg SHhhh.hh MDdan: enter_vfo_mode() takes optional frequency_hz/step_hz/step_adjust_hz/mode keywords built into the same write, while a bare enter_vfo_mode(vfo) call still sends the exact real-hardware-confirmed bare form unchanged. Not yet confirmed whether the embedded RF/ST/SH/MD fields work the same as the bare form did, or whether VF A works from memory-channel mode specifically."),
        _c("VI", "VFO information", "R", "Bare VI reads all three VFOs (A/B/Z) in one 3-line multi-response (result code 21-continuing, like PR/MA). The AR-DV1 spec PDF's own VI table has a corrupted second column - a verbatim copy-paste of the VE entry directly above it - so the real response shape had to be reconstructed from the table's Details prose instead, which spells out each response line directly. See aor_dv10.device.DV10Device.read_vfo_info() (a third instance of this exact PDF corruption pattern, alongside SE's and TR's)."),
        _c("VQ", "Voice squelch", "RW"),
        _c("VR", "Firmware version", "R"),
        _c("VS", "VFO search", "W", "Bare VS activates VFO search using VFO-A/VFO-B's current range and VE's delay/free-time/auto-store settings. See aor_dv10.device.DV10Device.execute_vfo_search()."),
        _c("WI", "Receiver model output", "R", "Message-only response confirmed on real DV10: 'AOR AR-DV10', with no 'WI' code echo - matches the AR-DV3 spec's equivalent pattern exactly."),
        _c("ZI", "Receiver ID", "RW"),
        _c("ZJ", "Move to previous frequency/bank/channel", "W"),
        _c("ZK", "Move to next frequency/bank/channel", "W"),
        _c("ZP", "Power ON, connect", "W", "Message-only response confirmed on real DV10: 'AOR AR-DV10' (matches AR-DV3 spec pattern 'AOR AR-DV3'), no code echo."),
        _c("ZS", "Power save ON/OFF", "RW"),
        _c("ZT", "Power save silent time", "RW"),
    ]
}
