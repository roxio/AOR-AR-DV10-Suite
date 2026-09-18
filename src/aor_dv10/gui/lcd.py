
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..device_types import (
    AGC_SPEEDS,
    ANALOG_MODES,
    ATTENUATOR_STATES,
    DIGITAL_MODES,
    TONE_SQUELCH_TYPES,
)
from .panels import Panel, _label
from .widgets import Chip, LedPill, Segmented, SmeterBar


def _reverse(table: dict[str, str]) -> dict[str, str]:
    return {value: key for key, value in table.items()}


class LcdPanel(Panel):
    def __init__(self, window):
        super().__init__(window, "Display")
        self.setObjectName("LcdScreen")
        self.header.setVisible(False)
        self._active_vfo = "A"
        self._tick = 0
        self._large = True
        self._peak: int | None = None
        self._analog_gated = False
        self._analog_names = _reverse(ANALOG_MODES)
        self._digital_names = _reverse(DIGITAL_MODES)
        self._digital = "F"
        self._analog = "0"

        freq_zone = QVBoxLayout()
        freq_zone.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(12)

        vfo_block = QVBoxLayout()
        vfo_block.setSpacing(3)
        self.vfo_label = QLabel("VFO-A")
        self.vfo_label.setObjectName("VfoLabel")
        self.mode_tag = QLabel("--")
        self.mode_tag.setObjectName("ModeTag")
        vfo_block.addWidget(self.vfo_label)
        vfo_block.addWidget(self.mode_tag)
        vfo_block.addStretch(1)
        top.addLayout(vfo_block)

        self.freq = QLabel("---.------")
        self.freq.setObjectName("Freq")
        self.freq.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._freq_glow = QGraphicsDropShadowEffect(self.freq)
        self._freq_glow.setBlurRadius(24)
        self._freq_glow.setOffset(0, 0)
        self._freq_glow.setColor(QColor(self.window.theme_color("accent")))
        self.freq.setGraphicsEffect(self._freq_glow)
        top.addWidget(self.freq, 1)

        sub = QVBoxLayout()
        sub.setSpacing(2)
        self._sub_labels: dict[str, QLabel] = {}
        for letter in ("A", "B", "Z"):
            line = QLabel(f"VFO-{letter}   ---.------")
            line.setObjectName("VfoSub")
            line.setAlignment(Qt.AlignRight)
            self._sub_labels[letter] = line
            sub.addWidget(line)
        top.addLayout(sub)
        freq_zone.addLayout(top)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        self.chip_rx = self._mini_chip("receiving")
        self.chip_dig = self._mini_chip("digital")
        self.chip_an = self._mini_chip("analog")
        chips.addStretch(1)
        for chip in (self.chip_rx, self.chip_dig, self.chip_an):
            chips.addWidget(chip)
        chips.addStretch(1)
        freq_zone.addLayout(chips)
        self.body_layout.addLayout(freq_zone)
        self.body_layout.addWidget(self._divider())

        meter_zone = QVBoxLayout()
        meter_zone.setSpacing(4)
        cap = QHBoxLayout()
        caption = _label("S-METER", "LcdCaption")
        self.smeter_value = _label("--", "SmeterValue")
        self.rx_status = _label("RX", "RxStatus")
        cap.addWidget(caption)
        cap.addStretch(1)
        cap.addWidget(self.smeter_value)
        cap.addWidget(self.rx_status)
        meter_zone.addLayout(cap)

        self.bar = SmeterBar()
        self.window.register_smeter(self.bar)
        meter_zone.addWidget(self.bar)

        ticks = QHBoxLayout()
        for text in ("S1", "S3", "S5", "S7", "S9", "+20", "+40", "+60dB"):
            tick = _label(text, "MeterTick")
            tick.setAlignment(Qt.AlignCenter)
            ticks.addWidget(tick, 1)
        meter_zone.addLayout(ticks)

        bottom = QHBoxLayout()
        self.smeter_db = _label("--- dB", "Muted")
        self.status_info = _label("", "Muted")
        self.peak = QPushButton("-- dB")
        self.peak.setObjectName("LinkBtn")
        self.peak.setToolTip("Reset peak")
        self.peak.clicked.connect(self.reset_peak)
        self.sql = LedPill("SQL --", "off")
        bottom.addWidget(self.smeter_db)
        bottom.addStretch(1)
        bottom.addWidget(self.status_info)
        bottom.addStretch(1)
        bottom.addWidget(self.peak)
        bottom.addWidget(self.sql)
        meter_zone.addLayout(bottom)
        self.body_layout.addLayout(meter_zone)
        self.body_layout.addWidget(self._divider())

        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        self.chip_att = Chip("Attenuator")
        self.chip_att.clicked.connect(self.cycle_att)
        self.chip_agc = Chip("AGC speed")
        self.chip_agc.clicked.connect(self.cycle_agc)
        self.chip_sql = Chip("Squelch type (CI)")
        self.chip_sql.clicked.connect(self.cycle_sql)
        self.chip_bw = Chip("Bandwidth (IF)", with_bar=True)
        self.chip_bw.clicked.connect(self.cycle_bw)
        for chip in (self.chip_att, self.chip_agc, self.chip_sql, self.chip_bw):
            status_row.addWidget(chip, 1)
        self.body_layout.addLayout(status_row)
        self.body_layout.addWidget(self._divider())

        matrix_row = QHBoxLayout()
        matrix_row.setSpacing(10)
        digital_block = QVBoxLayout()
        digital_block.setSpacing(4)
        digital_block.addWidget(_label("Digital", "LcdCaption"))
        digital_labels = {"8": "T-DM", "9": "T-TC"}
        self.digital = Segmented(
            [(code, digital_labels.get(code, name))
             for code, name in DIGITAL_MODES.items() if code != "F"],
            columns=5,
            style="MatrixBtn",
        )
        self.digital.changed.connect(self.on_digital)
        digital_block.addWidget(self.digital)
        digital_block.addStretch(1)
        matrix_row.addLayout(digital_block, 1)

        analog_block = QVBoxLayout()
        analog_block.setSpacing(4)
        analog_block.addWidget(_label("Analog", "LcdCaption"))
        self.analog = Segmented(
            [(code, name) for code, name in ANALOG_MODES.items()],
            columns=7,
            style="MatrixBtn",
        )
        self.analog.changed.connect(self.on_analog)
        analog_block.addWidget(self.analog)
        footer = QHBoxLayout()
        footer.setSpacing(6)
        digital_off = QPushButton("Digital off")
        digital_off.setObjectName("SmallBtn")
        digital_off.clicked.connect(lambda: self.on_digital("F"))
        set_mode = QPushButton("Set Mode")
        set_mode.setObjectName("Accent")
        set_mode.clicked.connect(self.on_set_mode)
        footer.addWidget(digital_off)
        footer.addWidget(set_mode)
        footer.addStretch(1)
        analog_block.addLayout(footer)
        analog_block.addStretch(1)
        matrix_row.addLayout(analog_block, 1)
        self.body_layout.addLayout(matrix_row)

    def _mini_chip(self, key: str) -> QLabel:
        chip = QLabel(f"{key} --")
        chip.setObjectName("ModeChip")
        return chip

    def _divider(self) -> QWidget:
        line = QWidget()
        line.setObjectName("LcdDivider")
        line.setFixedHeight(1)
        return line

    def on_digital(self, code: str) -> None:
        self._digital = code
        self._send_mode()

    def on_analog(self, code: str) -> None:
        self._analog = code
        self._send_mode()

    def on_set_mode(self) -> None:
        self._send_mode()

    def _send_mode(self) -> None:
        code = f"{self._digital}{self._analog}"
        self.run(lambda: self.device.set_mode(code))

    def _cycle(self, table: dict[str, str], current, setter) -> None:
        keys = list(table)
        try:
            index = keys.index(str(current))
        except ValueError:
            index = -1
        nxt = keys[(index + 1) % len(keys)]
        self.run(lambda: setter(nxt))

    def cycle_att(self) -> None:
        self._cycle(ATTENUATOR_STATES, self.call(self.device.get_attenuator_state), self.device.set_attenuator_state)

    def cycle_agc(self) -> None:
        self._cycle(AGC_SPEEDS, self.call(self.device.get_agc_speed), self.device.set_agc_speed)

    def cycle_sql(self) -> None:
        self._cycle(TONE_SQUELCH_TYPES, self.call(self.device.get_squelch_tone_type), self.device.set_squelch_tone_type)

    def cycle_bw(self) -> None:
        options = self.call(self.device.get_if_bandwidth_options_hz) or {}
        order = list(options.items())
        if not order:
            return
        current = self.call(self.device.get_if_bandwidth)
        digits = [digit for digit, _ in order]
        try:
            index = digits.index(str(current))
        except ValueError:
            index = -1
        digit = digits[(index + 1) % len(digits)]
        self.run(lambda: self.device.set_if_bandwidth(digit))

    def toggle_large(self) -> None:
        self._large = not self._large
        status = self.call(self.device.status)
        if status is not None:
            self.refresh(status)

    def refresh(self, status) -> None:
        self._tick += 1
        if status.frequency_hz is not None:
            value = f"{status.frequency_hz / 1_000_000:,.6f}"
        else:
            value = "---.------"
        muted = self.window.theme_color("muted")
        self._freq_glow.setColor(QColor(self.window.theme_color("accent")))
        size = 52 if self._large else 40
        self.freq.setText(
            f'<span style="font-size:{size}px;font-weight:700">{value}</span>'
            f'<span style="font-size:13px;color:{muted}"> MHz</span>'
        )
        info = status.mode_info
        if info is not None:
            self.mode_tag.setText(
                (info.analog_select or info.digital_select or "--").upper()
            )
            self.chip_rx.setText(f"receiving  {info.receiving_digital or '--'}")
            self.chip_dig.setText(f"digital  {info.digital_select or '--'}")
            self.chip_an.setText(f"analog  {info.analog_select or '--'}")
            if info.digital_select and info.digital_select in self._digital_names:
                self._digital = self._digital_names[info.digital_select]
                self.digital.set_current(self._digital)
            if info.analog_select and info.analog_select in self._analog_names:
                self._analog = self._analog_names[info.analog_select]
                self.analog.set_current(self._analog)
        self.vfo_label.setText(f"VFO-{self._active_vfo}")

        reading = status.smeter_reading
        dbm = reading.dbm if reading else None
        open_ = reading.squelch_open if reading else None
        self.bar.set_reading(dbm, open_)
        self.smeter_value.setText(self._s_unit(dbm))
        self.smeter_db.setText("--- dB" if dbm is None else f"{dbm} dB")
        if dbm is not None:
            self._peak = dbm if self._peak is None else max(self._peak, dbm)
        self.peak.setText("-- dB" if self._peak is None else f"{self._peak} dB")
        self.rx_status.setText("RX • BUSY" if open_ else "RX")
        self.rx_status.setProperty("busy", "true" if open_ else "false")
        self.rx_status.style().unpolish(self.rx_status)
        self.rx_status.style().polish(self.rx_status)
        if open_ is None:
            self.sql.setText("SQL --")
            self.sql.set_state("off")
        elif open_:
            self.sql.setText("SQL open")
            self.sql.set_state("amber")
        else:
            self.sql.setText("SQL closed")
            self.sql.set_state("off")
        self.status_info.setText("fresh" if self.device.connected else "unknown")

        att = ATTENUATOR_STATES.get(status.attenuator_state, status.attenuator_state)
        self.chip_att.set_value(att or "--")
        agc = AGC_SPEEDS.get(status.agc_speed, status.agc_speed or "--")
        self.chip_agc.set_value(agc)
        sql_type = TONE_SQUELCH_TYPES.get(self.call(self.device.get_squelch_tone_type), "--")
        self.chip_sql.set_value(sql_type)
        bw = self.call(self.device.get_if_bandwidth_hz)
        self.chip_bw.set_value("--" if bw is None else self._fmt_hz(bw))
        options = self.call(self.device.get_if_bandwidth_options_hz) or {}
        digits = list(options)
        if digits:
            raw = self.call(self.device.get_if_bandwidth)
            try:
                index = digits.index(str(raw))
            except ValueError:
                index = -1
            self.chip_bw.set_indicator((index + 1) / len(digits))

        if not self._analog_gated:
            gated = self.call(self.device.analog_modes_without_distinction)
            if gated:
                for code in gated:
                    button = self.analog._buttons.get(code)
                    if button is not None:
                        button.setEnabled(False)
                self._analog_gated = True

        if self._tick % 4 == 0:
            self._refresh_vfos()

    def reset_peak(self) -> None:
        self._peak = None
        self.peak.setText("-- dB")

    @staticmethod
    def _fmt_hz(value: int) -> str:
        if value >= 1000:
            return f"{value / 1000:g} kHz"
        return f"{value} Hz"

    @staticmethod
    def _s_unit(dbm: int | None) -> str:
        if dbm is None:
            return "--"
        if dbm <= -73:
            unit = round((dbm + 121) / 6)
            return f"S{max(1, min(9, unit))}"
        return f"+{round(dbm + 73)} dB"

    def _refresh_vfos(self) -> None:
        infos = self.call(self.device.read_vfo_info)
        if not infos:
            return
        for info in infos:
            label = self._sub_labels.get(info.vfo)
            if label is None:
                continue
            freq = "--" if info.frequency_hz is None else f"{info.frequency_hz / 1_000_000:.5f}"
            label.setText(f"VFO-{info.vfo}   {freq}")
