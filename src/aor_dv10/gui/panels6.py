
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
)

from ..device_types import KEY_BACKLIGHT_COLORS
from ..timer import RecordingTimer
from .panels import Panel, _label
from .widgets import Segmented, section_label

WEEKDAYS = (
    ("mon", "Mon", 2),
    ("tue", "Tue", 4),
    ("wed", "Wed", 8),
    ("thu", "Thu", 16),
    ("fri", "Fri", 32),
    ("sat", "Sat", 64),
    ("sun", "Sun", 1),
)


class VfoPanel(Panel):
    def __init__(self, window):
        super().__init__(window, "VFO compare & templates", collapsed=True)
        self.settings = QSettings("aor-dv10-suite", "gui")

        read = QPushButton("Read VFOs (VI)")
        read.setObjectName("Accent")
        read.clicked.connect(self.on_read)
        self.add(read)

        self.table = QTableWidget(3, 4)
        self.table.setHorizontalHeaderLabels(["VFO", "MHz", "Mode", "Step kHz"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setMinimumHeight(120)
        self.add(self.table)
        self._vfo_rows: list[dict] = []

        self.add(section_label("Templates"))
        row = QHBoxLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("template name")
        save = QPushButton("Save from selected VFO")
        save.clicked.connect(self.on_save)
        row.addWidget(self.name, 1)
        row.addWidget(save)
        self.add_layout(row)

        row2 = QHBoxLayout()
        self.template = QComboBox()
        apply = QPushButton("Apply to its VFO")
        apply.setObjectName("Accent")
        apply.clicked.connect(self.on_apply)
        delete = QPushButton("Delete")
        delete.setObjectName("Danger")
        delete.clicked.connect(self.on_delete)
        row2.addWidget(self.template, 1)
        row2.addWidget(apply)
        row2.addWidget(delete)
        self.add_layout(row2)

        self.info = _label("not read")
        self.add(self.info)
        self._reload_templates()

    def on_read(self) -> None:
        infos = self.call(self.device.read_vfo_info)
        if not infos:
            self.info.setText("no VFO data")
            return
        self.table.setRowCount(len(infos))
        self._vfo_rows = []
        for row, info in enumerate(infos):
            freq = "" if info.frequency_hz is None else f"{info.frequency_hz / 1_000_000:.5f}"
            step = "" if not info.step_hz else f"{info.step_hz / 1000:g}"
            values = [info.vfo, freq, info.mode or "", step]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.table.setItem(row, col, item)
            self._vfo_rows.append(
                {"vfo": info.vfo, "frequency_hz": info.frequency_hz, "mode": info.mode}
            )
        self.info.setText(f"read {len(infos)} VFOs")

    def _reload_templates(self) -> None:
        self.template.clear()
        self.template.addItems(sorted(self._templates().keys()))

    def _templates(self) -> dict:
        raw = self.settings.value("vfo_templates", {})
        return dict(raw) if isinstance(raw, dict) else {}

    def _store(self, data: dict) -> None:
        self.settings.setValue("vfo_templates", data)

    def on_save(self) -> None:
        name = self.name.text().strip()
        row = self.table.currentRow()
        if not name or row < 0 or row >= len(self._vfo_rows):
            self.info.setText("enter a name and select a VFO row")
            return
        data = self._templates()
        data[name] = self._vfo_rows[row]
        self._store(data)
        self._reload_templates()
        self.info.setText(f"saved template {name!r}")

    def on_apply(self) -> None:
        name = self.template.currentText()
        data = self._templates()
        if not name or name not in data:
            return
        entry = data[name]
        vfo = entry.get("vfo", "A")
        freq = entry.get("frequency_hz")
        mode = entry.get("mode")
        mode_pair = mode[1:3] if isinstance(mode, str) and len(mode) >= 3 else None
        self.run(
            lambda: self.device.enter_vfo_mode(
                vfo, frequency_hz=freq, mode=mode_pair
            )
        )
        self.info.setText(f"applied {name!r} to VFO {vfo}")

    def on_delete(self) -> None:
        name = self.template.currentText()
        data = self._templates()
        if name in data:
            del data[name]
            self._store(data)
            self._reload_templates()
            self.info.setText(f"deleted {name!r}")


class SettingsPanel(Panel):
    def __init__(self, window):
        super().__init__(window, "Additional settings", collapsed=True)

        self.add(section_label("IF bandwidth"))
        row = QHBoxLayout()
        self.if_combo = QComboBox()
        if_btn = QPushButton("Set")
        if_btn.clicked.connect(self.on_if)
        row.addWidget(self.if_combo, 1)
        row.addWidget(if_btn)
        self.add_layout(row)

        self.add(section_label("Move / clock"))
        row2 = QHBoxLayout()
        prev = QPushButton("Move prev (ZJ)")
        prev.clicked.connect(lambda: self.run(self.device.move_previous))
        nxt = QPushButton("Move next (ZK)")
        nxt.clicked.connect(lambda: self.run(self.device.move_next))
        clock_btn = QPushButton("Set clock to now")
        clock_btn.clicked.connect(self.on_clock_now)
        row2.addWidget(prev)
        row2.addWidget(nxt)
        row2.addWidget(clock_btn)
        row2.addStretch(1)
        self.add_layout(row2)

        self.add(section_label("Key backlight (KL)"))
        row3 = QHBoxLayout()
        self.kl = QComboBox()
        for code, name in KEY_BACKLIGHT_COLORS.items():
            self.kl.addItem(name, code)
        kl_btn = QPushButton("Set")
        kl_btn.clicked.connect(lambda: self.run(lambda: self.device.set_key_backlight_color(self.kl.currentData())))
        row3.addWidget(self.kl, 1)
        row3.addWidget(kl_btn)
        self.add_layout(row3)

        self.add(section_label("Delay / free time"))
        row4 = QHBoxLayout()
        self.delay = QSpinBox()
        self.delay.setRange(0, 100)
        self.free = QSpinBox()
        self.free.setRange(0, 60)
        df_btn = QPushButton("Set")
        df_btn.clicked.connect(self.on_delay_free)
        row4.addWidget(_label("Delay ds"))
        row4.addWidget(self.delay)
        row4.addWidget(_label("Free s"))
        row4.addWidget(self.free)
        row4.addWidget(df_btn)
        row4.addStretch(1)
        self.add_layout(row4)

        self.add(section_label("Sleep timer (SP)"))
        row5 = QHBoxLayout()
        self.sleep = QLineEdit()
        self.sleep.setObjectName("Mono")
        sleep_btn = QPushButton("Set")
        sleep_btn.clicked.connect(lambda: self.run(lambda: self.device.set_sleep_timer(self.sleep.text())))
        row5.addWidget(self.sleep, 1)
        row5.addWidget(sleep_btn)
        self.add_layout(row5)

        self.add(section_label("Comm speed (SB)"))
        row6 = QHBoxLayout()
        self.sb = QLineEdit()
        self.sb.setObjectName("Mono")
        self.sb_button = QPushButton("Set (armed)")
        self.sb_button.setObjectName("Danger")
        self.sb_button.clicked.connect(self.on_comm_speed)
        self._sb_armed = False
        row6.addWidget(self.sb, 1)
        row6.addWidget(self.sb_button)
        self.add_layout(row6)

        self.info = _label("")
        self.add(self.info)

    def on_if(self) -> None:
        hz = self.if_combo.currentData()
        if hz is None:
            return
        self.run(lambda: self.device.set_if_bandwidth_hz(hz))
        self.info.setText(f"IF set to {hz} Hz")

    def on_clock_now(self) -> None:
        now = datetime.now()
        self.run(lambda: self.device.set_clock(now.year % 100, now.month, now.day, now.hour, now.minute))
        self.info.setText(f"clock set to {now:%Y-%m-%d %H:%M}")

    def on_delay_free(self) -> None:
        self.run(lambda: self.device.set_delay_time_ds(self.delay.value()))
        self.run(lambda: self.device.set_free_time_s(self.free.value()))
        self.info.setText("delay/free time set")

    def on_comm_speed(self) -> None:
        if not self._sb_armed:
            self._sb_armed = True
            self.sb_button.setText("Click again to confirm")
            return
        self._sb_armed = False
        self.sb_button.setText("Set (armed)")
        self.run(lambda: self.device.set_comm_speed(self.sb.text()))
        self.info.setText("comm speed set")

    def refresh(self, status) -> None:
        options = self.call(self.device.get_if_bandwidth_options_hz) or {}
        wanted = [(hz, f"{hz} Hz") for hz in options.values()]
        current = self.if_combo.currentData()
        self.if_combo.clear()
        for hz, label in sorted(wanted):
            self.if_combo.addItem(label, hz)
        index = self.if_combo.findData(current)
        if index >= 0:
            self.if_combo.setCurrentIndex(index)
        kl = self.call(self.device.get_key_backlight_color)
        if kl is not None:
            idx = self.kl.findData(str(kl).strip())
            if idx >= 0:
                self.kl.setCurrentIndex(idx)
        for spin, getter, limit in (
            (self.delay, self.device.get_delay_time_ds, 100),
            (self.free, self.device.get_free_time_s, 60),
        ):
            value = self.call(getter)
            if isinstance(value, int) and not spin.hasFocus():
                spin.setValue(min(max(value, 0), limit))


class TimerPanel(Panel):
    def __init__(self, window):
        super().__init__(window, "Recording timer (TR)", collapsed=True)
        row = QHBoxLayout()
        self.action = Segmented([("off", "Off"), ("alarm", "Alarm"), ("recording", "Recording")])
        self.repeat = Segmented([("once", "Once"), ("weekly", "Weekly")])
        read = QPushButton("Read")
        read.clicked.connect(self.on_read)
        write = QPushButton("Write")
        write.setObjectName("Accent")
        write.clicked.connect(self.on_write)
        row.addWidget(self.action)
        row.addWidget(self.repeat)
        row.addWidget(read)
        row.addWidget(write)
        row.addStretch(1)
        self.add_layout(row)

        grid = QGridLayout()
        self.start = QLineEdit()
        self.start.setObjectName("Mono")
        self.start.setPlaceholderText("MMDDHHMM or HHMM")
        self.end = QLineEdit()
        self.end.setObjectName("Mono")
        self.end.setPlaceholderText("MMDDHHMM or HHMM")
        self.receive = QLineEdit()
        self.receive.setObjectName("Mono")
        self.receive.setPlaceholderText("receive mode e.g. VFA / VS / SS00")
        self.volume = QSpinBox()
        self.volume.setRange(0, 99)
        grid.addWidget(_label("Start"), 0, 0)
        grid.addWidget(self.start, 0, 1)
        grid.addWidget(_label("End"), 1, 0)
        grid.addWidget(self.end, 1, 1)
        grid.addWidget(_label("Receive"), 2, 0)
        grid.addWidget(self.receive, 2, 1)
        grid.addWidget(_label("Alarm volume"), 3, 0)
        grid.addWidget(self.volume, 3, 1)
        self.add_layout(grid)

        days = QHBoxLayout()
        self._days: dict[str, QCheckBox] = {}
        for key, label, _bit in WEEKDAYS:
            box = QCheckBox(label)
            self._days[key] = box
            days.addWidget(box)
        days.addStretch(1)
        self.add_layout(days)

        self.info = _label("not read")
        self.add(self.info)

    def _build(self) -> RecordingTimer:
        days = tuple(bit for key, _label_text, bit in WEEKDAYS if self._days[key].isChecked())
        return RecordingTimer(
            action=self._selected(self.action, ("off", "alarm", "recording")),
            repeat=self._selected(self.repeat, ("once", "weekly")),
            receive_mode=self.receive.text().strip() or None,
            start=self.start.text().strip() or None,
            end=self.end.text().strip() or None,
            weekdays=days,
            alarm_volume=self.volume.value() or None,
        )

    def _selected(self, segmented: Segmented, values) -> str:
        for value in values:
            if segmented._buttons[value].isChecked():
                return value
        return values[0]

    def on_read(self) -> None:
        timer = self.call(self.device.read_recording_timer)
        if timer is None:
            self.info.setText("read failed")
            return
        self.action.set_current(timer.action)
        if timer.repeat:
            self.repeat.set_current(timer.repeat)
        self.start.setText(timer.start or "")
        self.end.setText(timer.end or "")
        self.receive.setText(timer.receive_mode or "")
        if timer.alarm_volume is not None:
            self.volume.setValue(timer.alarm_volume)
        for key, _label_text, bit in WEEKDAYS:
            self._days[key].setChecked(bit in timer.weekdays)
        self.info.setText(f"action={timer.action} repeat={timer.repeat} start={timer.start} end={timer.end}")

    def on_write(self) -> None:
        timer = self._build()
        self.run(lambda: self.device.write_recording_timer(timer))
        self.info.setText("timer written")


class ErrorLogPanel(Panel):
    def __init__(self, window):
        super().__init__(window, "Error log", collapsed=True)
        row = QHBoxLayout()
        clear = QPushButton("Clear log")
        clear.clicked.connect(self.clear)
        row.addWidget(clear)
        reconnect = QPushButton("Reconnect")
        reconnect.clicked.connect(lambda: self.run(self.device.reconnect))
        row.addWidget(reconnect)
        row.addStretch(1)
        self.count = _label("0 entries")
        row.addWidget(self.count)
        self.add_layout(row)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Time", "Message"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setMinimumHeight(150)
        self.add(self.table)

    def clear(self) -> None:
        self.table.setRowCount(0)
        self.count.setText("0 entries")

    def add_entry(self, message: str) -> None:
        self.table.insertRow(0)
        for col, value in enumerate((datetime.now().strftime("%H:%M:%S"), message)):
            item = QTableWidgetItem(value)
            item.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(0, col, item)
        self.count.setText(f"{self.table.rowCount()} entries")
