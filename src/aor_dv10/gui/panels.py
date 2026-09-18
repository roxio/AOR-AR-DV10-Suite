
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..device_types import (
    AGC_SPEEDS,
    ANALOG_MODES,
    ATTENUATOR_STATES,
    BACKLIGHT_MODES,
    CTCSS_TONES_HZ,
    DCS_CODES,
    DIGITAL_MODES,
    SQUELCH_MODES,
)
from .widgets import (
    Card,
    Knob,
    LedPill,
    Segmented,
    SliderRow,
    Sparkline,
    ToggleRow,
    section_label,
)


class Panel(Card):
    def __init__(self, window, title: str, collapsed: bool = False):
        super().__init__(title, collapsed)
        self.window = window
        self.device = window.device

    def run(self, fn: Callable) -> object:
        return self.window.run(fn)

    def call(self, fn: Callable, default=None):
        return self.window.call(fn, default)

    def refresh(self, status) -> None:
        return None


def _label(text: str, obj: str = "Muted") -> QLabel:
    label = QLabel(text)
    label.setObjectName(obj)
    label.setWordWrap(True)
    return label


def _compact(button: QPushButton) -> QPushButton:
    button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
    button.setMinimumWidth(0)
    return button


class TuningPanel(Panel):
    def __init__(self, window):
        super().__init__(window, "Tune")
        self.header.setVisible(False)
        self.add(section_label("Tune"))
        self._number = ""
        self._step_hz = 25_000
        self._active_vfo = "A"
        self._nudge_hz = 100
        self._history: list[int] = []
        self._hist_index = -1
        self._rf_value = 0
        self._af_value = 0
        self._hold_timers: list = []

        tune_area = QHBoxLayout()
        tune_area.setSpacing(16)
        self.knob = Knob(140)
        self.knob.stepped.connect(self.on_knob)
        tune_area.addWidget(self.knob, 0, Qt.AlignTop)

        side = QVBoxLayout()
        side.setSpacing(6)
        self.step_button = QPushButton("STEP --")
        self.step_button.setObjectName("SmallBtn")
        self.step_button.clicked.connect(self.on_cycle_step)
        side.addWidget(self.step_button)

        nudge = QHBoxLayout()
        nudge.setSpacing(6)
        self.nudge_minus = QPushButton("-")
        self.nudge_minus.setObjectName("SmallBtn")
        self.nudge_plus = QPushButton("+")
        self.nudge_plus.setObjectName("SmallBtn")
        self.nudge_label = _label("100 Hz", "NudgeLabel")
        self.nudge_label.setAlignment(Qt.AlignCenter)
        self.nudge_label.setMinimumWidth(54)
        self.nudge_step = QPushButton("STEP")
        self.nudge_step.setObjectName("SmallBtn")
        self.nudge_step.clicked.connect(self.on_cycle_nudge)
        self._install_hold(self.nudge_minus, -1)
        self._install_hold(self.nudge_plus, 1)
        nudge.addWidget(self.nudge_minus)
        nudge.addWidget(self.nudge_label)
        nudge.addWidget(self.nudge_step)
        nudge.addWidget(self.nudge_plus)
        nudge.addStretch(1)
        side.addLayout(nudge)

        skip = _compact(QPushButton("SKIP FREQ"))
        skip.setObjectName("FuncBtn")
        skip.clicked.connect(self.on_skip_freq)
        side.addWidget(skip)
        stop = _compact(QPushButton("STOP SEARCH"))
        stop.setObjectName("FuncBtn")
        stop.clicked.connect(self.on_stop_search)
        side.addWidget(stop)

        history = QHBoxLayout()
        history.setSpacing(6)
        back = _compact(QPushButton("◀ back"))
        back.setObjectName("SmallBtn")
        back.clicked.connect(self.on_hist_back)
        forward = _compact(QPushButton("forward ▶"))
        forward.setObjectName("SmallBtn")
        forward.clicked.connect(self.on_hist_forward)
        history.addWidget(back)
        history.addWidget(forward)
        side.addLayout(history)
        side.addStretch(1)
        tune_area.addLayout(side, 1)

        mini_widget = QWidget()
        mini = QHBoxLayout(mini_widget)
        mini.setContentsMargins(0, 0, 0, 0)
        mini.setSpacing(12)
        self.rf_knob = Knob(42)
        self.rf_knob.stepped.connect(self.on_rf_knob)
        self.af_knob = Knob(42)
        self.af_knob.stepped.connect(self.on_af_knob)
        for knob, text in ((self.rf_knob, "RF GAIN/SQL"), (self.af_knob, "AF GAIN")):
            block = QVBoxLayout()
            block.setSpacing(3)
            block.addWidget(knob, 0, Qt.AlignHCenter)
            label = _label(text, "MiniLabel")
            label.setAlignment(Qt.AlignHCenter)
            block.addWidget(label)
            mini.addLayout(block)
        mini.addStretch(1)
        mini_widget.setVisible(False)
        tune_area.addWidget(mini_widget, 0, Qt.AlignTop)
        self.add_layout(tune_area)

        columns = QHBoxLayout()
        columns.setSpacing(10)
        left = QVBoxLayout()
        left.setSpacing(6)
        step_grid = QGridLayout()
        step_grid.setHorizontalSpacing(6)
        step_grid.setVerticalSpacing(6)
        for index, (text, delta) in enumerate(
            (("-1 MHz", -1_000_000), ("+1 MHz", 1_000_000),
             ("-25 kHz", -25_000), ("+25 kHz", 25_000),
             ("-5 kHz", -5_000), ("+5 kHz", 5_000))
        ):
            button = QPushButton(text)
            button.setObjectName("StepBtn")
            button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            button.clicked.connect(lambda _=False, d=delta: self.on_step(d))
            step_grid.addWidget(button, index // 3, index % 3)
        left.addLayout(step_grid)

        self.vfo = Segmented([("A", "VFO A"), ("B", "VFO B"), ("Z", "VFO Z")], columns=3, style="SmallBtn")
        self.vfo.changed.connect(self.on_vfo)
        left.addWidget(self.vfo)

        move = QHBoxLayout()
        move.setSpacing(6)
        prev = _compact(QPushButton("« prev"))
        prev.setObjectName("SmallBtn")
        prev.clicked.connect(lambda: self.run(self.device.move_previous))
        nxt = _compact(QPushButton("next »"))
        nxt.setObjectName("SmallBtn")
        nxt.clicked.connect(lambda: self.run(self.device.move_next))
        move.addWidget(prev)
        move.addWidget(nxt)
        left.addLayout(move)
        left.addStretch(1)

        self.band_button = QPushButton("BAND")
        self.band_button.setObjectName("FuncBtn")
        self.band_button.clicked.connect(self.on_band)
        left.addWidget(self.band_button)
        columns.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(6)
        self.entry = QDoubleSpinBox()
        self.entry.setDecimals(6)
        self.entry.setRange(0.0, 6000.0)
        self.entry.setSingleStep(0.001)
        self.entry.setMinimumWidth(90)
        right.addWidget(self.entry)

        keypad = QGridLayout()
        keypad.setHorizontalSpacing(6)
        keypad.setVerticalSpacing(6)
        key_list = [("1", 0, 0), ("2", 0, 1), ("3", 0, 2),
                    ("4", 1, 0), ("5", 1, 1), ("6", 1, 2),
                    ("7", 2, 0), ("8", 2, 1), ("9", 2, 2),
                    ("CE", 3, 0), ("0", 3, 1), (".", 3, 2)]
        for text, row, col in key_list:
            button = QPushButton(text)
            button.setObjectName("KeypadBtn")
            button.clicked.connect(lambda _=False, t=text: self.on_key(t))
            keypad.addWidget(button, row, col)
        right.addLayout(keypad)

        ent = QPushButton("ENT")
        ent.setObjectName("Accent")
        ent.clicked.connect(self.on_enter)
        right.addWidget(ent)
        right.addStretch(1)
        columns.addLayout(right, 1)
        self.add_layout(columns)

    def on_cycle_step(self) -> None:
        steps = [100, 500, 1000, 2500, 5000, 10000, 12500, 25000, 50000, 100000]
        try:
            index = steps.index(self._step_hz)
        except ValueError:
            index = -1
        self._step_hz = steps[(index + 1) % len(steps)]
        self.run(lambda: self.device.set_frequency_step_hz(self._step_hz))
        self.step_button.setText(f"STEP {self._step_hz / 1000:g} kHz")

    def _install_hold(self, button: QPushButton, direction: int) -> None:
        timer = QTimer(self)
        timer.setInterval(140)
        timer.timeout.connect(lambda: self.on_nudge(direction))
        button.pressed.connect(lambda: (self.on_nudge(direction), timer.start()))
        button.released.connect(timer.stop)
        self._hold_timers.append(timer)

    def on_nudge(self, direction: int) -> None:
        current = self.call(lambda: self.device.get_frequency_hz())
        if current is None:
            return
        self.run(lambda: self.device.set_frequency_hz(current + direction * self._nudge_hz))

    def on_cycle_nudge(self) -> None:
        steps = [10, 100, 500, 1000, 2500, 5000, 12500, 25000]
        try:
            index = steps.index(self._nudge_hz)
        except ValueError:
            index = -1
        self._nudge_hz = steps[(index + 1) % len(steps)]
        self.nudge_label.setText(f"{self._nudge_hz} Hz" if self._nudge_hz < 1000 else f"{self._nudge_hz // 1000} kHz")

    def on_skip_freq(self) -> None:
        hz = self.call(lambda: self.device.get_frequency_hz())
        if hz is None:
            return
        self.run(lambda: self.device.mark_pass_frequency(frequency_hz=hz))

    def on_stop_search(self) -> None:
        self.run(lambda: self.device.enter_vfo_mode("A"))

    def on_hist_back(self) -> None:
        if self._hist_index > 0:
            self._hist_index -= 1
            self.run(lambda: self.device.set_frequency_hz(self._history[self._hist_index]))

    def on_hist_forward(self) -> None:
        if self._hist_index < len(self._history) - 1:
            self._hist_index += 1
            self.run(lambda: self.device.set_frequency_hz(self._history[self._hist_index]))

    def on_rf_knob(self, delta: int) -> None:
        self._rf_value = max(0, min(99, self._rf_value + delta))
        self.run(lambda: self.device.set_squelch_level(self._rf_value))

    def on_af_knob(self, delta: int) -> None:
        self._af_value = max(0, min(15, self._af_value + delta))
        self.run(lambda: self.device.set_volume_limit(self._af_value))

    def on_band(self) -> None:
        bands = (
            ("FM broadcast", 98_000_000), ("Airband", 124_000_000),
            ("2 m", 145_000_000), ("Marine", 156_800_000),
            ("70 cm", 435_000_000), ("PMR446", 446_006_250),
            ("DMR", 446_100_000), ("Weather", 162_550_000),
        )
        menu = QMenu(self)
        for name, hz in bands:
            menu.addAction(name, lambda h=hz: self.run(lambda: self.device.set_frequency_hz(h)))
        menu.exec(self.band_button.mapToGlobal(self.band_button.rect().bottomLeft()))

    def on_knob(self, steps: int) -> None:
        self.on_step(steps * self._step_hz)

    def on_vfo(self, vfo: str) -> None:
        self._active_vfo = vfo
        self.run(lambda: self.device.enter_vfo_mode(vfo))

    def on_key(self, key: str) -> None:
        if key in ("CLR", "CE"):
            self._number = ""
        elif key == ".":
            if "." not in self._number:
                self._number += "."
        else:
            self._number += key
        if self._number:
            try:
                self.entry.setValue(float(self._number))
            except ValueError:
                pass

    def on_enter(self) -> None:
        self.on_set()
        self._number = ""

    def on_set(self) -> None:
        hz = round(self.entry.value() * 1_000_000)
        self.run(lambda: self.device.set_frequency_hz(hz))

    def on_step(self, delta: int) -> None:
        current = self.call(lambda: self.device.get_frequency_hz())
        if current is None:
            return
        self.run(lambda: self.device.set_frequency_hz(current + delta))

    def refresh(self, status) -> None:
        if status.frequency_hz is not None and not self.entry.hasFocus():
            self.entry.setValue(status.frequency_hz / 1_000_000)
        step = self.call(self.device.get_frequency_step_hz)
        if isinstance(step, int) and step > 0:
            self._step_hz = step
        self.step_button.setText(f"STEP {self._step_hz / 1000:g} kHz")

        hz = status.frequency_hz
        if hz is not None and (not self._history or self._history[-1] != hz):
            if self._hist_index < len(self._history) - 1:
                del self._history[self._hist_index + 1:]
            self._history.append(hz)
            if len(self._history) > 50:
                self._history.pop(0)
            self._hist_index = len(self._history) - 1

        lq = self.call(self.device.get_squelch_level)
        if lq is not None:
            self._rf_value = int(lq)
        av = self.call(self.device.get_volume_limit)
        if av is not None:
            self._af_value = int(av)


class SmeterPanel(Panel):
    def __init__(self, window):
        super().__init__(window, "S-meter")
        self._history: list[int] = []
        self.bar = self.window.make_smeter()
        self.add(self.bar)

        self.spark = Sparkline()
        self.spark.setMinimumHeight(70)
        self.window.register_spark(self.spark)
        self.add(self.spark)

        row = QGridLayout()
        self.sql = LedPill("SQL", "off")
        row.addWidget(self.sql, 0, 0, 2, 1)
        self.mode = _label("mode --")
        self.mode.setWordWrap(True)
        self.vol = _label("vol --")
        self.agc = _label("agc --")
        self.att = _label("att --")
        row.addWidget(self.mode, 0, 1)
        row.addWidget(self.vol, 0, 2)
        row.addWidget(self.agc, 1, 1)
        row.addWidget(self.att, 1, 2)
        row.setColumnStretch(1, 1)
        row.setColumnStretch(2, 1)
        self.add_layout(row)

    def refresh(self, status) -> None:
        reading = status.smeter_reading
        dbm = reading.dbm if reading else None
        open_ = reading.squelch_open if reading else None
        self.bar.set_reading(dbm, open_)
        if dbm is not None:
            self._history.append(dbm)
            if len(self._history) > 120:
                self._history.pop(0)
            self.spark.set_values(self._history)
        if open_ is None:
            self.sql.setText("SQL ?")
            self.sql.set_state("off")
        elif open_:
            self.sql.setText("SQL OPEN")
            self.sql.set_state("good")
        else:
            self.sql.setText("SQL CLOSED")
            self.sql.set_state("off")
        mode_desc = status.mode_info.describe() if status.mode_info else (status.mode or "--")
        self.mode.setText(f"mode {mode_desc}")
        self.vol.setText(f"vol {status.volume if status.volume is not None else '--'}")
        agc = AGC_SPEEDS.get(status.agc_speed, status.agc_on)
        self.agc.setText(f"agc {agc if agc is not None else '--'}")
        att = ATTENUATOR_STATES.get(status.attenuator_state, status.attenuator_state)
        self.att.setText(f"att {att if att is not None else '--'}")


def _reverse(table: dict[str, str]) -> dict[str, str]:
    return {value: key for key, value in table.items()}


class ModePanel(Panel):
    def __init__(self, window):
        super().__init__(window, "Mode")
        self._analog_names = _reverse(ANALOG_MODES)
        self._digital_names = _reverse(DIGITAL_MODES)
        self._digital = "F"
        self._analog = "0"

        self.add(section_label("Analog"))
        self.analog = Segmented([(code, name) for code, name in ANALOG_MODES.items()], columns=4)
        self.analog.changed.connect(self.on_analog)
        self.add(self.analog)

        self.add(section_label("Digital"))
        self.digital = Segmented([(code, name) for code, name in DIGITAL_MODES.items()], columns=4)
        self.digital.changed.connect(self.on_digital)
        self.add(self.digital)

        self.current = _label("")
        self.add(self.current)

    def _send(self) -> None:
        code = f"{self._digital}{self._analog}"
        self.run(lambda: self.device.set_mode(code))

    def on_analog(self, code: str) -> None:
        self._analog = code
        self._send()

    def on_digital(self, code: str) -> None:
        self._digital = code
        self._send()

    def refresh(self, status) -> None:
        info = status.mode_info
        if info is None:
            return
        if info.analog_select and info.analog_select in self._analog_names:
            self._analog = self._analog_names[info.analog_select]
            self.analog.set_current(self._analog)
        if info.digital_select and info.digital_select in self._digital_names:
            self._digital = self._digital_names[info.digital_select]
            self.digital.set_current(self._digital)
        self.current.setText(f"current: {info.describe()}")


class SquelchPanel(Panel):
    def __init__(self, window):
        super().__init__(window, "Squelch")
        self.sq = Segmented([(code, name) for code, name in SQUELCH_MODES.items()])
        self.sq.changed.connect(lambda code: self.run(lambda: self.device.set_squelch_mode(code)))
        self.add(section_label("Mode (SQ)"))
        self.add(self.sq)

        self.add(section_label("Level (LQ 00-99)"))
        self.lq = SliderRow(0, 99)
        self.lq.changed.connect(lambda v: self.run(lambda: self.device.set_squelch_level(v)))
        self.add(self.lq)

        self.add(section_label("Noise (NQ 00-39)"))
        self.nq = SliderRow(0, 39)
        self.nq.changed.connect(lambda v: self.run(lambda: self.device.set_noise_squelch_level(v)))
        self.add(self.nq)

        self.tone = ToggleRow("CTCSS tone squelch (CI)")
        self.tone.changed.connect(lambda on: self.run(lambda: self.device.set_tone_squelch_enabled(on)))
        self.add(self.tone)

        self.tone_type = Segmented([("0", "OFF"), ("1", "CTCSS"), ("2", "Reverse")])
        self.tone_type.changed.connect(lambda c: self.run(lambda: self.device.set_squelch_tone_type(c)))
        self.add(self.tone_type)

        tone_row = QHBoxLayout()
        self.tone_freq = QComboBox()
        for value in ("OFF", "SRCH"):
            self.tone_freq.addItem(value, value)
        for tone in CTCSS_TONES_HZ:
            self.tone_freq.addItem(tone, tone)
        tone_set = QPushButton("Set tone")
        tone_set.clicked.connect(
            lambda: self.run(lambda: self.device.set_tone_squelch_freq(self.tone_freq.currentData()))
        )
        tone_row.addWidget(self.tone_freq, 1)
        tone_row.addWidget(tone_set)
        self.add_layout(tone_row)

        self.dcs = ToggleRow("DCS squelch (DI)")
        self.dcs.changed.connect(lambda on: self.run(lambda: self.device.set_dcs_enabled(on)))
        self.add(self.dcs)

        dcs_row = QHBoxLayout()
        self.dcs_code = QComboBox()
        for value in ("OFF", "SRCH"):
            self.dcs_code.addItem(value, value)
        for code in DCS_CODES:
            self.dcs_code.addItem(code, code)
        dcs_set = QPushButton("Set code")
        dcs_set.clicked.connect(
            lambda: self.run(lambda: self.device.set_dcs_code(self.dcs_code.currentData()))
        )
        dcs_row.addWidget(self.dcs_code, 1)
        dcs_row.addWidget(dcs_set)
        self.add_layout(dcs_row)

    def refresh(self, status) -> None:
        if status.squelch is not None:
            self.sq.set_current(status.squelch)
        lq = self.call(self.device.get_squelch_level)
        if lq is not None and not self.lq.slider.isSliderDown():
            self.lq.set_value(lq if isinstance(lq, int) else int(str(lq)))
        nq = self.call(self.device.get_noise_squelch_level)
        if nq is not None and not self.nq.slider.isSliderDown():
            self.nq.set_value(nq if isinstance(nq, int) else int(str(nq)))
        self.tone.set_checked(bool(self.call(self.device.get_tone_squelch_enabled, False)))
        self.dcs.set_checked(bool(self.call(self.device.get_dcs_enabled, False)))
        tone = self.call(self.device.get_tone_squelch_freq)
        if tone:
            index = self.tone_freq.findData(str(tone).strip())
            if index >= 0:
                self.tone_freq.setCurrentIndex(index)
        code = self.call(self.device.get_dcs_code)
        if code:
            index = self.dcs_code.findData(str(code).strip())
            if index >= 0:
                self.dcs_code.setCurrentIndex(index)


class LevelsPanel(Panel):
    def __init__(self, window):
        super().__init__(window, "Levels")
        self.add(section_label("AGC speed (AC)"))
        self.agc = Segmented([(code, name) for code, name in AGC_SPEEDS.items()])
        self.agc.changed.connect(lambda c: self.run(lambda: self.device.set_agc_speed(c)))
        self.add(self.agc)

        self.add(section_label("Attenuator (AT)"))
        self.att = Segmented([(code, name) for code, name in ATTENUATOR_STATES.items()])
        self.att.changed.connect(lambda c: self.run(lambda: self.device.set_attenuator_state(c)))
        self.add(self.att)

        self.add(section_label("Volume limit (AV)"))
        self.vol = SliderRow(0, 15)
        self.vol.changed.connect(lambda v: self.run(lambda: self.device.set_volume_limit(v)))
        self.add(self.vol)

        self.add(section_label("Digital gain (DA x0.01)"))
        self.dig = SliderRow(100, 1594)
        self.dig.changed.connect(lambda v: self.run(lambda: self.device.set_digital_gain(v / 100)))
        self.add(self.dig)

        self.add(section_label("Manual gain (RG)"))
        self.mgain = SliderRow(0, 110)
        self.mgain.changed.connect(lambda v: self.run(lambda: self.device.set_manual_gain(v)))
        self.add(self.mgain)

    def refresh(self, status) -> None:
        if status.agc_speed is not None:
            self.agc.set_current(status.agc_speed)
        if status.attenuator_state is not None:
            self.att.set_current(status.attenuator_state)
        for slider, getter in (
            (self.vol, self.device.get_volume_limit),
            (self.mgain, self.device.get_manual_gain),
        ):
            value = self.call(getter)
            if isinstance(value, int) and not slider.slider.isSliderDown():
                slider.set_value(value)


class OptionsPanel(Panel):
    def __init__(self, window):
        super().__init__(window, "Options & power")

        self.add(section_label("Beep level (BP 0-7)"))
        self.beep = SliderRow(0, 7)
        self.beep.changed.connect(lambda v: self.run(lambda: self.device.set_beep_level(v)))
        self.add(self.beep)

        self.add(section_label("LCD contrast (LN 0-63)"))
        self.contrast = SliderRow(0, 63)
        self.contrast.changed.connect(lambda v: self.run(lambda: self.device.set_lcd_contrast(v)))
        self.add(self.contrast)

        self.add(section_label("Backlight (LB)"))
        self.backlight = Segmented([(code, name) for code, name in BACKLIGHT_MODES.items()])
        self.backlight.changed.connect(lambda c: self.run(lambda: self.device.set_backlight_mode(c)))
        self.add(self.backlight)

        self.re = ToggleRow("Result-code prefixing (RE)")
        self.re.changed.connect(lambda on: self.run(lambda: self.device.set_result_code_prefixing(on)))
        self.add(self.re)

        self.writeprotect = ToggleRow("Write protect (PT)")
        self.writeprotect.changed.connect(lambda on: self.run(lambda: self.device.set_write_protect(on)))
        self.add(self.writeprotect)

        self.add(section_label("Receiver ID (ZI)"))
        row = QHBoxLayout()
        self.zi = QLineEdit()
        zi_btn = QPushButton("Set")
        zi_btn.clicked.connect(self.on_zi)
        row.addWidget(self.zi, 1)
        row.addWidget(zi_btn)
        self.add_layout(row)

        self.add(section_label("Power (ZP / QP)"))
        power = QHBoxLayout()
        on_btn = QPushButton("Power ON")
        on_btn.setObjectName("Accent")
        on_btn.clicked.connect(lambda: self.run(self.device.power_on))
        off_btn = QPushButton("Power OFF")
        off_btn.clicked.connect(lambda: self.run(self.device.power_off))
        power.addWidget(on_btn)
        power.addWidget(off_btn)
        power.addStretch(1)
        self.add_layout(power)

        self.add(section_label("Danger zone"))
        reset_row = QHBoxLayout()
        self.reset_button = QPushButton("Factory reset (RS)")
        self.reset_button.setObjectName("Danger")
        self.reset_button.clicked.connect(self.arm_reset)
        self._reset_armed = False
        reset_row.addWidget(self.reset_button)
        reset_row.addStretch(1)
        self.add_layout(reset_row)

    def on_zi(self) -> None:
        text = self.zi.text().strip()
        self.run(lambda: self.device.set_receiver_id(text))

    def arm_reset(self) -> None:
        if not self._reset_armed:
            self._reset_armed = True
            self.reset_button.setText("Click again to confirm reset")
            return
        self._reset_armed = False
        self.reset_button.setText("Factory reset (RS)")
        self.run(lambda: self.device.reset(False))

    def refresh(self, status) -> None:
        beep = self.call(self.device.get_beep_level)
        if isinstance(beep, int) and not self.beep.slider.isSliderDown():
            self.beep.set_value(beep)
        contrast = self.call(self.device.get_lcd_contrast)
        if isinstance(contrast, int) and not self.contrast.slider.isSliderDown():
            self.contrast.set_value(contrast)
        li = self.call(self.device.get_backlight_mode)
        if li is not None:
            self.backlight.set_current(str(li))
        zi = self.call(self.device.get_receiver_id)
        if isinstance(zi, str) and not self.zi.hasFocus():
            self.zi.setText(zi)
