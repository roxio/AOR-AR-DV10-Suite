
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..device import DV10Device
from ..protocol.codec import DV10Error
from ..transport.base import TransportError
from . import i18n, theme, widgets
from .lcd import LcdPanel
from .panels import (
    LevelsPanel,
    OptionsPanel,
    SquelchPanel,
    TuningPanel,
)
from .panels2 import CodesPanel, ConsolePanel, TelemetryPanel
from .panels3 import LiveMemoryPanel, MemoryPanel
from .panels4 import SdTimerPanel, SearchScanPanel, SelectScanPanel, SignalLogPanel
from .panels5 import AutomationPanel, ScopePanel
from .panels6 import ErrorLogPanel, SettingsPanel, TimerPanel, VfoPanel
from .widgets import Card, LedDot, Rocker, Segmented, SmeterBar

BACKLIGHT_SHORT = {"0": "Off", "1": "Cont", "2": "Auto"}


class _Header(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("Header")
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(2, 4, 2, 10)
        self.grid.setHorizontalSpacing(4)
        self.grid.setVerticalSpacing(6)
        self.options_box: QWidget | None = None
        self._stacked: bool | None = None

    def place(self, stacked: bool) -> None:
        if self.options_box is None:
            return
        self.grid.removeWidget(self.options_box)
        if stacked:
            self.grid.addWidget(self.options_box, 1, 0, 1, 8)
            self.grid.setColumnStretch(3, 0)
        else:
            self.grid.addWidget(self.options_box, 0, 3, Qt.AlignCenter)
            self.grid.setColumnStretch(3, 1)

    def resizeEvent(self, event) -> None:
        stacked = self.width() < 1024
        if stacked != self._stacked:
            self._stacked = stacked
            self.place(stacked)
        super().resizeEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, device: DV10Device):
        super().__init__()
        self.device = device
        self._theme_name = theme.DEFAULT_THEME
        self._theme_choice = theme.DEFAULT_THEME
        self._panels: list = []
        self._smeters: list[SmeterBar] = []
        self._sparks: list = []
        self.memory_panel = None
        self.error_log = None
        self.lcd_panel = None

        self.setWindowTitle("AOR AR-DV10 Control")
        self.resize(1100, 820)
        self.setMinimumSize(760, 560)

        central = QWidget()
        central.setObjectName("Page")
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(0)

        chassis = QFrame()
        chassis.setObjectName("Chassis")
        shadow = QGraphicsDropShadowEffect(chassis)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 150))
        chassis.setGraphicsEffect(shadow)
        outer.addWidget(chassis)

        root = QVBoxLayout(chassis)
        root.setContentsMargins(18, 14, 18, 18)
        root.setSpacing(12)

        root.addWidget(self._build_header())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        page = QWidget()
        page.setObjectName("Page")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(10)
        created: dict = {}
        for factory in (
            LcdPanel,
            TuningPanel,
            SquelchPanel,
            LevelsPanel,
            OptionsPanel,
            CodesPanel,
            MemoryPanel,
            LiveMemoryPanel,
            VfoPanel,
            SdTimerPanel,
            TimerPanel,
            SearchScanPanel,
            ScopePanel,
            SelectScanPanel,
            SettingsPanel,
            SignalLogPanel,
            AutomationPanel,
            ConsolePanel,
            TelemetryPanel,
            ErrorLogPanel,
        ):
            panel = factory(self)
            panel.header.setChecked(True)
            self._panels.append(panel)
            created[factory] = panel

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(14)
        self.lcd_panel = created[LcdPanel]
        top.addWidget(self.lcd_panel, 60)
        top.addWidget(created[TuningPanel], 40)
        page_layout.addLayout(top)

        groups = (
            ("More: Squelch / Levels / Codes / Offset · Priority",
             (SquelchPanel, LevelsPanel, OptionsPanel, CodesPanel)),
            ("Memory Channels & Live Memory",
             (MemoryPanel, LiveMemoryPanel)),
            ("VFO · Search · Recording · SD Card",
             (VfoPanel, SdTimerPanel, TimerPanel)),
            ("Search Banks · Scan Groups · Pass Frequencies",
             (SearchScanPanel,)),
            ("Spectrum Scope · Select-Scan · Additional Settings",
             (ScopePanel, SelectScanPanel, SettingsPanel)),
            ("Favorites · Signal log · Alerts · Snapshots · Automation · Presets",
             (SignalLogPanel, AutomationPanel)),
            ("Raw console & Command queue",
             (ConsolePanel, TelemetryPanel, ErrorLogPanel)),
        )
        for title, factories in groups:
            group = Card(title, collapsed=True)
            grid = QHBoxLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(10)
            columns = [QVBoxLayout(), QVBoxLayout()]
            for column in columns:
                column.setSpacing(10)
            for index, factory in enumerate(factories):
                columns[index % 2].addWidget(created[factory])
            for column in columns:
                column.addStretch(1)
                grid.addLayout(column, 1)
            group.add_layout(grid)
            page_layout.addWidget(group)
        page_layout.addStretch(1)

        scroll.setWidget(page)
        root.addWidget(scroll, 1)

        self.memory_panel = next(
            (panel for panel in self._panels if isinstance(panel, MemoryPanel)), None
        )
        self.error_log = next(
            (panel for panel in self._panels if isinstance(panel, ErrorLogPanel)), None
        )

        self.signal_log = next(
            (panel for panel in self._panels if isinstance(panel, SignalLogPanel)), None
        )
        self._last_open = False

        self.status_line = QLabel("ready")
        self.status_line.setObjectName("Muted")
        root.addWidget(self.status_line)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1500)
        i18n.retranslate(self)
        self.refresh()

    def _build_header(self) -> QFrame:
        header = _Header()
        grid = header.grid

        self.conn_led = LedDot()
        grid.addWidget(self.conn_led, 0, 0)

        nameplate = QWidget()
        nameplate.setObjectName("Nameplate")
        np = QHBoxLayout(nameplate)
        np.setContentsMargins(0, 0, 0, 0)
        np.setSpacing(4)
        aor = QLabel("AOR")
        aor.setObjectName("NameplateAor")
        model = QLabel("AR-DV10")
        model.setObjectName("NameplateModel")
        np.addWidget(aor)
        np.addWidget(model)
        grid.addWidget(nameplate, 0, 1)

        self.id_label = QLabel("")
        self.id_label.setObjectName("NameplateFw")
        grid.addWidget(self.id_label, 0, 2)

        options = QWidget()
        options.setObjectName("TopbarOptions")
        opt = QHBoxLayout(options)
        opt.setContentsMargins(0, 0, 0, 0)
        opt.setSpacing(8)

        self.beep_toggle = Rocker(mini=True)
        self.beep_toggle.toggled.connect(lambda on: self.run(lambda: self.device.set_beep(on)))
        opt.addWidget(self._topbar_group(self.beep_toggle, "Beep"))

        self.re_toggle = Rocker(mini=True)
        self.re_toggle.toggled.connect(
            lambda on: self.run(lambda: self.device.set_result_code_prefixing(on))
        )
        opt.addWidget(self._topbar_group(self.re_toggle, "RE"))

        self.bp_slider = QSlider(Qt.Horizontal)
        self.bp_slider.setRange(0, 7)
        self.bp_slider.setFixedWidth(48)
        self.bp_slider.sliderReleased.connect(
            lambda: self.run(lambda: self.device.set_beep_level(self.bp_slider.value()))
        )
        self.bp_box = self._topbar_slider("BP", self.bp_slider)
        opt.addWidget(self.bp_box)

        self.ln_slider = QSlider(Qt.Horizontal)
        self.ln_slider.setRange(0, 63)
        self.ln_slider.setFixedWidth(48)
        self.ln_slider.sliderReleased.connect(
            lambda: self.run(lambda: self.device.set_lcd_contrast(self.ln_slider.value()))
        )
        self.ln_box = self._topbar_slider("LN", self.ln_slider)
        opt.addWidget(self.ln_box)

        bl_group = QWidget()
        bl_group.setObjectName("TopbarGroup")
        bl_layout = QHBoxLayout(bl_group)
        bl_layout.setContentsMargins(0, 0, 0, 0)
        bl_layout.setSpacing(4)
        bl_label = QLabel("BL")
        bl_label.setObjectName("TopbarLabel")
        self.bl_select = QComboBox()
        self.bl_select.setObjectName("TopbarSelect")
        for code, name in BACKLIGHT_SHORT.items():
            self.bl_select.addItem(name, code)
        self.bl_select.currentIndexChanged.connect(
            lambda: self.run(lambda: self.device.set_backlight_mode(self.bl_select.currentData()))
        )
        bl_layout.addWidget(bl_label)
        bl_layout.addWidget(self.bl_select)
        opt.addWidget(bl_group)

        on_btn = QPushButton("ON")
        on_btn.setObjectName("PowerOn")
        on_btn.clicked.connect(lambda: self.run(self.device.power_on))
        off_btn = QPushButton("OFF")
        off_btn.setObjectName("PowerOff")
        off_btn.clicked.connect(lambda: self.run(self.device.power_off))
        opt.addWidget(on_btn)
        opt.addWidget(off_btn)
        opt.addStretch(1)
        header.options_box = options

        self.lang_switch = Segmented(
            [(code, code.upper()) for code, _ in i18n.languages()], style="TopbarSwitch"
        )
        self.lang_switch.set_current(i18n.language())
        self.lang_switch.changed.connect(self._set_language)
        grid.addWidget(self.lang_switch, 0, 4)

        theme_buttons = (
            ("light", "☀", "Light"),
            ("dark", "☾", "Dark"),
            ("amber", "A", "Amber"),
            ("green", "G", "Green"),
            ("auto", "◐", "Auto (day/night)"),
        )
        self.theme_switch = Segmented(
            [(name, symbol) for name, symbol, _ in theme_buttons], style="TopbarSwitch"
        )
        for name, _symbol, tip in theme_buttons:
            self.theme_switch._buttons[name].setToolTip(tip)
        self.theme_switch._buttons["auto"].setCheckable(True)
        self.theme_switch.set_current(self._theme_choice)
        self.theme_switch.changed.connect(self.apply_theme)
        grid.addWidget(self.theme_switch, 0, 5)

        kiosk = QPushButton("⛶")
        kiosk.setObjectName("TopbarSwitch")
        kiosk.setToolTip("Toggle fullscreen / kiosk mode")
        kiosk.clicked.connect(self._toggle_kiosk)
        grid.addWidget(kiosk, 0, 6)

        clock_btn = QPushButton("⏰")
        clock_btn.setObjectName("TopbarSwitch")
        clock_btn.setToolTip("Set the receiver clock to this computer's time (DT)")
        clock_btn.clicked.connect(self._sync_clock)
        grid.addWidget(clock_btn, 0, 7)

        zoom = QPushButton("▿")
        zoom.setObjectName("TopbarSwitch")
        zoom.setToolTip("Toggle large LCD")
        zoom.clicked.connect(self._toggle_lcd_zoom)
        grid.addWidget(zoom, 0, 8)

        grid.setColumnStretch(3, 1)
        header.place(False)
        return header

    def _toggle_kiosk(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _toggle_lcd_zoom(self) -> None:
        if self.lcd_panel is not None:
            self.lcd_panel.toggle_large()

    def _topbar_group(self, widget: QWidget, label: str) -> QWidget:
        box = QWidget()
        box.setObjectName("TopbarGroup")
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        text = QLabel(label)
        text.setObjectName("TopbarLabel")
        layout.addWidget(widget)
        layout.addWidget(text)
        return box

    def _topbar_slider(self, label: str, slider: QSlider) -> QWidget:
        box = QWidget()
        box.setObjectName("TopbarGroup")
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        text = QLabel(label)
        text.setObjectName("TopbarLabel")
        value = QLabel(str(slider.value()))
        value.setObjectName("ReadoutChip")
        slider.valueChanged.connect(lambda v: value.setText(str(v)))
        layout.addWidget(text)
        layout.addWidget(slider)
        layout.addWidget(value)
        box.value_label = value
        return box

    def _sync_clock(self) -> None:
        now = datetime.now()
        self.run(lambda: self.device.set_clock(now.year % 100, now.month, now.day, now.hour, now.minute))

    def _sync_topbar(self) -> None:
        bp = self.call(self.device.get_beep_level)
        if isinstance(bp, int):
            self.bp_slider.blockSignals(True)
            self.bp_slider.setValue(bp)
            self.bp_slider.blockSignals(False)
            self.bp_box.value_label.setText(str(bp))
        ln = self.call(self.device.get_lcd_contrast)
        if isinstance(ln, int):
            self.ln_slider.blockSignals(True)
            self.ln_slider.setValue(ln)
            self.ln_slider.blockSignals(False)
            self.ln_box.value_label.setText(str(ln))
        bl = self.call(self.device.get_backlight_mode)
        if bl is not None:
            index = self.bl_select.findData(str(bl).strip())
            if index >= 0:
                self.bl_select.blockSignals(True)
                self.bl_select.setCurrentIndex(index)
                self.bl_select.blockSignals(False)

    def _set_language(self, code: str) -> None:
        if not code:
            return
        i18n.set_language(code)
        i18n.retranslate(self)

    def apply_theme(self, name: str) -> None:
        self._theme_choice = name
        resolved = name
        if name == "auto":
            resolved = "light" if 6 <= datetime.now().hour < 18 else "dark"
        self._theme_name = resolved
        t = theme.THEMES[resolved]
        widgets.set_theme(t)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.build_qss(t))
        switch = getattr(self, "theme_switch", None)
        if switch is not None:
            switch.set_current(name)
        for meter in self._smeters:
            meter.set_theme(t)
        for spark in self._sparks:
            spark.set_theme(t)
        self.style().unpolish(self)
        self.style().polish(self)

    def make_smeter(self) -> SmeterBar:
        meter = SmeterBar()
        meter.set_theme(theme.THEMES[self._theme_name])
        self._smeters.append(meter)
        return meter

    def register_smeter(self, meter: SmeterBar) -> None:
        meter.set_theme(theme.THEMES[self._theme_name])
        self._smeters.append(meter)

    def register_spark(self, spark) -> None:
        spark.set_theme(theme.THEMES[self._theme_name])
        self._sparks.append(spark)

    def theme_color(self, name: str = "bad") -> str:
        t = theme.THEMES[self._theme_name]
        palette = {
            "bad": t.bad,
            "good": t.good,
            "amber": t.amber,
            "accent": t.accent,
            "muted": t.muted,
            "label": t.label_text,
        }
        return palette.get(name, t.text)

    def run(self, fn: Callable) -> object:
        try:
            return fn()
        except (DV10Error, TransportError, ValueError, IndexError) as exc:
            self.status_line.setText(f"error: {exc}")
            if self.error_log is not None:
                self.error_log.add_entry(str(exc))
            return None

    def call(self, fn: Callable, default=None):
        try:
            return fn()
        except (DV10Error, TransportError, ValueError, IndexError):
            return default

    def refresh(self) -> None:
        try:
            status = self.device.status()
        except (DV10Error, TransportError) as exc:
            self.conn_led.set_state(False)
            self.status_line.setText(f"error: {exc}")
            return
        connected = bool(self.device.connected)
        self.conn_led.set_state(connected)
        model = self.call(self.device.model)
        version = self.call(self.device.firmware_version)
        if model or version:
            self.id_label.setText(f"fw {version or '--'}")
            self.id_label.setToolTip(model or "")
        self._sync_topbar()
        for panel in self._panels:
            if not panel.body.isVisibleTo(self):
                continue
            try:
                panel.refresh(status)
            except (DV10Error, TransportError, ValueError, IndexError) as exc:
                self.status_line.setText(f"panel error: {exc}")
        self._note_signal(status)

    def _note_signal(self, status) -> None:
        reading = status.smeter_reading
        open_now = bool(reading.squelch_open) if reading is not None else False
        if open_now and not self._last_open and self.signal_log is not None:
            mode = status.mode_info.describe() if status.mode_info else (status.mode or "")
            self.signal_log.add_event(
                status.frequency_hz, reading.dbm if reading else None, mode
            )
        self._last_open = open_now


def _load_fonts() -> None:
    from pathlib import Path

    from PySide6.QtGui import QFontDatabase

    folder = Path(__file__).with_name("fonts")
    if folder.is_dir():
        for path in folder.glob("*.ttf"):
            QFontDatabase.addApplicationFont(str(path))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AOR AR-DV10 GUI")
    parser.add_argument("--port", help="Explicit serial device; omit to auto-detect")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--simulator", action="store_true", help="Use the in-process simulator")
    parser.add_argument("--theme", default=theme.DEFAULT_THEME, choices=list(theme.THEMES))
    args = parser.parse_args(argv)

    device = (
        DV10Device.open_simulator()
        if args.simulator
        else DV10Device.open_serial(port=args.port, baudrate=args.baud)
    )
    try:
        device.connect()
    except (TransportError, OSError) as exc:
        print(f"Could not connect: {exc}")
        print("Tip: run with --simulator to use the GUI without hardware.")
        return 1

    app = QApplication(sys.argv)
    _load_fonts()
    font = QFont()
    font.setFamilies(["Inter", "Segoe UI", "Arial"])
    font.setPointSize(9)
    app.setFont(font)
    window = MainWindow(device)
    window.apply_theme(args.theme)
    window.show()
    ret = app.exec()
    device.disconnect()
    return ret


if __name__ == "__main__":
    raise SystemExit(main())
