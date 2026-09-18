
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
)

from ..protocol import COMMANDS
from ..protocol.codec import DV10Error
from .panels import Panel, _label
from .widgets import ToggleRow, section_label


class CodesPanel(Panel):
    def __init__(self, window):
        super().__init__(window, "Digital codes / offset / priority", collapsed=True)

        self.add(section_label("DMR (CC / CM / OT)"))
        row = QHBoxLayout()
        self.dmr_cc = QSpinBox()
        self.dmr_cc.setRange(0, 16)
        self.dmr_cc.editingFinished.connect(
            lambda: self.run(lambda: self.device.set_dmr_color_code(self.dmr_cc.value()))
        )
        self.dmr_slot = QSpinBox()
        self.dmr_slot.setRange(0, 2)
        self.dmr_slot.editingFinished.connect(
            lambda: self.run(lambda: self.device.set_dmr_slot(self.dmr_slot.value()))
        )
        row.addWidget(_label("Color code"))
        row.addWidget(self.dmr_cc)
        row.addWidget(_label("Slot"))
        row.addWidget(self.dmr_slot)
        row.addStretch(1)
        self.add_layout(row)
        self.dmr_mute = ToggleRow("Mute by color code (CM)")
        self.dmr_mute.changed.connect(
            lambda on: self.run(lambda: self.device.set_dmr_mute_by_color_code(on))
        )
        self.add(self.dmr_mute)

        self.add(section_label("P25 (PC / PM)"))
        p25 = QHBoxLayout()
        self.p25_nac = QLineEdit()
        self.p25_nac.setObjectName("Mono")
        self.p25_nac.setMaxLength(3)
        p25_btn = QPushButton("Set")
        p25_btn.clicked.connect(lambda: self.run(lambda: self.device.set_p25_nac(self.p25_nac.text())))
        p25.addWidget(_label("NAC (hex)"))
        p25.addWidget(self.p25_nac)
        p25.addWidget(p25_btn)
        p25.addStretch(1)
        self.add_layout(p25)
        self.p25_mute = ToggleRow("Mute by NAC (PM)")
        self.p25_mute.changed.connect(lambda on: self.run(lambda: self.device.set_p25_mute_by_nac(on)))
        self.add(self.p25_mute)

        self.add(section_label("NXDN (NC / NM)"))
        nxdn = QHBoxLayout()
        self.nxdn_ran = QSpinBox()
        self.nxdn_ran.setRange(0, 63)
        self.nxdn_ran.editingFinished.connect(
            lambda: self.run(lambda: self.device.set_nxdn_ran(self.nxdn_ran.value()))
        )
        nxdn.addWidget(_label("RAN"))
        nxdn.addWidget(self.nxdn_ran)
        nxdn.addStretch(1)
        self.add_layout(nxdn)
        self.nxdn_mute = ToggleRow("Mute by RAN (NM)")
        self.nxdn_mute.changed.connect(lambda on: self.run(lambda: self.device.set_nxdn_mute_by_ran(on)))
        self.add(self.nxdn_mute)

        self.add(section_label("D-CR descramble (DC)"))
        dcr = QHBoxLayout()
        self.dcr = QSpinBox()
        self.dcr.setRange(0, 32767)
        self.dcr.editingFinished.connect(
            lambda: self.run(lambda: self.device.set_dcr_descramble_code(self.dcr.value()))
        )
        dcr.addWidget(self.dcr)
        dcr.addStretch(1)
        self.add_layout(dcr)

        self.descr = ToggleRow("Analog voice descrambler (SI)")
        self.descr.changed.connect(lambda on: self.run(lambda: self.device.set_voice_descrambler_enabled(on)))
        self.add(self.descr)

        self.add(section_label("Offset (OF / OL)"))
        off = QHBoxLayout()
        self.off_slot = QSpinBox()
        self.off_slot.setRange(0, 39)
        self.off_slot.editingFinished.connect(
            lambda: self.run(lambda: self.device.set_offset_slot(self.off_slot.value()))
        )
        self.off_freq = QLineEdit()
        self.off_freq.setObjectName("Mono")
        off_btn = QPushButton("Set freq")
        off_btn.clicked.connect(self.on_offset_freq)
        off.addWidget(_label("Slot"))
        off.addWidget(self.off_slot)
        off.addWidget(_label("MHz"))
        off.addWidget(self.off_freq)
        off.addWidget(off_btn)
        off.addStretch(1)
        self.add_layout(off)

        self.add(section_label("Priority (PO / PP / TI)"))
        self.prio = ToggleRow("Priority monitoring (PO)")
        self.prio.changed.connect(lambda on: self.run(lambda: self.device.set_priority_enabled(on)))
        self.add(self.prio)
        prio = QHBoxLayout()
        self.prio_chan = QLineEdit()
        self.prio_chan.setObjectName("Mono")
        self.prio_chan.setPlaceholderText("bank-ch, e.g. 00-05")
        prio_btn = QPushButton("Set channel")
        prio_btn.clicked.connect(self.on_priority_channel)
        self.prio_interval = QSpinBox()
        self.prio_interval.setRange(1, 99)
        self.prio_interval.editingFinished.connect(
            lambda: self.run(lambda: self.device.set_priority_interval(self.prio_interval.value()))
        )
        prio.addWidget(self.prio_chan)
        prio.addWidget(prio_btn)
        prio.addWidget(_label("Interval s"))
        prio.addWidget(self.prio_interval)
        prio.addStretch(1)
        self.add_layout(prio)

    def on_offset_freq(self) -> None:
        text = self.off_freq.text().strip()
        if not text:
            return
        try:
            hz = round(float(text) * 1_000_000)
        except ValueError:
            return
        slot = self.off_slot.value()
        self.run(lambda: self.device.set_offset_freq(slot, hz))

    def on_priority_channel(self) -> None:
        text = self.prio_chan.text().strip()
        if "-" not in text:
            return
        bank, _, channel = text.partition("-")
        try:
            self.run(lambda: self.device.set_priority_channel(int(bank), int(channel)))
        except ValueError:
            return

    def refresh(self, status) -> None:
        for spin, getter in (
            (self.dmr_cc, self.device.get_dmr_color_code),
            (self.dmr_slot, self.device.get_dmr_slot),
            (self.nxdn_ran, self.device.get_nxdn_ran),
            (self.dcr, self.device.get_dcr_descramble_code),
            (self.off_slot, self.device.get_offset_slot),
            (self.prio_interval, self.device.get_priority_interval),
        ):
            value = self.call(getter)
            if isinstance(value, int) and not spin.hasFocus():
                spin.setValue(value)
        self.dmr_mute.set_checked(bool(self.call(self.device.get_dmr_mute_by_color_code, False)))
        self.nxdn_mute.set_checked(bool(self.call(self.device.get_nxdn_mute_by_ran, False)))
        self.descr.set_checked(bool(self.call(self.device.get_voice_descrambler_enabled, False)))
        self.prio.set_checked(bool(self.call(self.device.get_priority_enabled, False)))
        nac = self.call(self.device.get_p25_nac)
        if nac is not None and not self.p25_nac.hasFocus():
            self.p25_nac.setText(str(nac))


class TelemetryPanel(Panel):
    FIELDS = (
        ("Serial (SN)", "serial_number"),
        ("Receiver ID", "get_receiver_id"),
        ("Clock", "get_clock"),
        ("IF bandwidth", "get_if_bandwidth"),
        ("Delay (ds)", "get_delay_time_ds"),
        ("Free time (s)", "get_free_time_s"),
        ("Earphone antenna", "get_earphone_antenna"),
        ("Monitor offset", "get_monitor_offset"),
        ("Voice squelch", "get_voice_squelch"),
        ("Power save", "get_power_save"),
        ("Power-save time", "get_power_save_silent_time"),
        ("Freq data out", "get_freq_data_output"),
        ("S-meter data out", "get_smeter_data_output"),
        ("Receiver status", "get_receiver_status"),
    )

    def __init__(self, window):
        super().__init__(window, "Telemetry", collapsed=True)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        self._values = {}
        for row, (label, attr) in enumerate(self.FIELDS):
            grid.addWidget(_label(label), row // 2, (row % 2) * 2)
            value = _label("--")
            value.setObjectName("ReadoutMeta")
            self._values[attr] = value
            grid.addWidget(value, row // 2, (row % 2) * 2 + 1)
        self.add_layout(grid)

    def refresh(self, status) -> None:
        for _, attr in self.FIELDS:
            getter = getattr(self.device, attr, None)
            if getter is None:
                continue
            value = self.call(getter)
            self._values[attr].setText("--" if value is None else str(value))


class ConsolePanel(Panel):
    def __init__(self, window):
        super().__init__(window, "Raw console", collapsed=True)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(180)
        self.add(self.output)

        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setObjectName("Mono")
        self.input.setPlaceholderText("raw CODE [VALUE]   |   describe CODE   |   help")
        self.input.returnPressed.connect(self.on_submit)
        send = QPushButton("Send")
        send.setObjectName("Accent")
        send.clicked.connect(self.on_submit)
        queue_add = QPushButton("Add to queue")
        queue_add.clicked.connect(self.on_queue_add)
        row.addWidget(self.input, 1)
        row.addWidget(send)
        row.addWidget(queue_add)
        self.add_layout(row)

        trace_row = QHBoxLayout()
        self.trace = ToggleRow("Live protocol trace")
        self.trace.changed.connect(self.on_trace_toggle)
        show = QPushButton("Show last 50")
        show.clicked.connect(self.on_show_trace)
        save = QPushButton("Save trace...")
        save.clicked.connect(self.on_save_trace)
        trace_row.addWidget(self.trace)
        trace_row.addWidget(show)
        trace_row.addWidget(save)
        trace_row.addStretch(1)
        self.add_layout(trace_row)

        self.add(section_label("Command queue"))
        self.queue = QTableWidget(0, 2)
        self.queue.setHorizontalHeaderLabels(["Command", "Status"])
        self.queue.setEditTriggers(QTableWidget.NoEditTriggers)
        self.queue.setAlternatingRowColors(True)
        self.queue.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.queue.setMinimumHeight(110)
        self.add(self.queue)

        qrow = QHBoxLayout()
        run = QPushButton("Run queue")
        run.setObjectName("Accent")
        run.clicked.connect(self.on_queue_run)
        clear = QPushButton("Clear queue")
        clear.clicked.connect(self.on_queue_clear)
        qrow.addWidget(run)
        qrow.addWidget(clear)
        qrow.addStretch(1)
        self.add_layout(qrow)

        self._history: list[str] = []
        self._history_pos = 0
        self._queue: list[tuple[int, str]] = []
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._run_next_queued)
        self.input.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.input and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key_Up and self._history:
                self._history_pos = max(0, self._history_pos - 1)
                self.input.setText(self._history[self._history_pos])
                return True
            if event.key() == Qt.Key_Down and self._history:
                self._history_pos = min(len(self._history), self._history_pos + 1)
                self.input.setText(
                    self._history[self._history_pos] if self._history_pos < len(self._history) else ""
                )
                return True
        return super().eventFilter(obj, event)

    def print_line(self, text: str) -> None:
        self.output.appendPlainText(text)

    def _execute(self, line: str) -> str:
        parts = line.split()
        verb = parts[0].lower()
        if verb in ("help", "?"):
            return f"{len(COMMANDS)} command codes. Use 'describe CODE' or 'raw CODE [VALUE]'."
        if verb == "describe" and len(parts) >= 2:
            try:
                return self.device.describe(parts[1])
            except (DV10Error, ValueError) as exc:
                return f"error: {exc}"
        if verb == "debug" and parts[1:2] == ["last"]:
            count = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 20
            return "\n".join(str(entry) for entry in self.device.trace_lines(count))
        code = parts[0].upper()
        value = " ".join(parts[1:]) if len(parts) > 1 else None
        try:
            result = self.device.raw(code, value)
            text = getattr(result, "value", result)
            return text if text not in (None, "") else "(ok)"
        except (DV10Error, ValueError) as exc:
            return f"error: {exc}"

    def on_submit(self) -> None:
        line = self.input.text().strip()
        if not line:
            return
        self.input.clear()
        self._history.append(line)
        self._history_pos = len(self._history)
        self.print_line(f"DV10> {line}")
        self.print_line(self._execute(line))

    def on_trace_toggle(self, enabled: bool) -> None:
        self.device.set_trace_sink(self.print_line if enabled else None)

    def on_show_trace(self) -> None:
        for entry in self.device.trace_lines(50):
            self.print_line(str(entry))

    def on_save_trace(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save trace", "trace.log", "Log files (*.log);;All files (*)")
        if not path:
            return
        count = self.device.save_trace(path)
        self.print_line(f"saved {count} trace lines to {path}")

    def on_queue_add(self) -> None:
        line = self.input.text().strip()
        if not line:
            return
        self.input.clear()
        row = self.queue.rowCount()
        self.queue.insertRow(row)
        for col, value in enumerate((line, "queued")):
            item = QTableWidgetItem(value)
            item.setFlags(Qt.ItemIsEnabled)
            self.queue.setItem(row, col, item)

    def on_queue_clear(self) -> None:
        self._timer.stop()
        self._queue.clear()
        self.queue.setRowCount(0)

    def on_queue_run(self) -> None:
        if self._timer.isActive():
            return
        self._queue = [
            (row, self.queue.item(row, 0).text())
            for row in range(self.queue.rowCount())
            if self.queue.item(row, 1).text() == "queued"
        ]
        if not self._queue:
            return
        self._timer.start(50)

    def _run_next_queued(self) -> None:
        if not self._queue:
            self._timer.stop()
            return
        row, line = self._queue.pop(0)
        self.print_line(f"DV10> {line}")
        output = self._execute(line)
        self.print_line(output)
        status = "error" if output.startswith("error:") else "done"
        item = self.queue.item(row, 1)
        if item is not None:
            item.setText(status)
