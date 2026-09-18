
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
)

from ..selectscan import SelectScanList
from .panels import Panel, _label
from .widgets import Segmented, ToggleRow, section_label


class SearchScanPanel(Panel):
    def __init__(self, window):
        super().__init__(window, "Search banks / scan groups / pass", collapsed=True)
        self.add(section_label("Search bank (SE / SR / SS / SX)"))
        row = QHBoxLayout()
        self.sb_bank = QSpinBox()
        self.sb_bank.setRange(0, 39)
        read = QPushButton("Read")
        read.clicked.connect(self.on_read_search)
        write = QPushButton("Write")
        write.clicked.connect(self.on_write_search)
        run = QPushButton("Run (SS)")
        run.clicked.connect(lambda: self.run(lambda: self.device.execute_search(self.sb_bank.value())))
        delete = QPushButton("Delete (SX)")
        delete.setObjectName("Danger")
        delete.clicked.connect(lambda: self.run(lambda: self.device.delete_search_bank(self.sb_bank.value())))
        row.addWidget(_label("Bank"))
        row.addWidget(self.sb_bank)
        for button in (read, write, run, delete):
            row.addWidget(button)
        row.addStretch(1)
        self.add_layout(row)

        limits = QHBoxLayout()
        self.sb_lower = QLineEdit()
        self.sb_lower.setObjectName("Mono")
        self.sb_lower.setPlaceholderText("lower MHz")
        self.sb_upper = QLineEdit()
        self.sb_upper.setObjectName("Mono")
        self.sb_upper.setPlaceholderText("upper MHz")
        self.sb_step = QLineEdit()
        self.sb_step.setObjectName("Mono")
        self.sb_step.setPlaceholderText("step kHz")
        self.sb_mode = QLineEdit()
        self.sb_mode.setObjectName("Mono")
        self.sb_mode.setPlaceholderText("mode e.g. F0")
        self.sb_tag = QLineEdit()
        self.sb_tag.setPlaceholderText("tag")
        for widget in (self.sb_lower, self.sb_upper, self.sb_step, self.sb_mode, self.sb_tag):
            limits.addWidget(widget)
        limits.addStretch(1)
        self.add_layout(limits)

        self.add(section_label("Scan groups (SG / MG)"))
        grp = QHBoxLayout()
        self.sg_type = Segmented([("SG", "Search (SG)"), ("MG", "Memory (MG)")])
        self.sg_group = QSpinBox()
        self.sg_group.setRange(0, 9)
        read_g = QPushButton("Read")
        read_g.clicked.connect(self.on_read_group)
        write_g = QPushButton("Write")
        write_g.clicked.connect(self.on_write_group)
        grp.addWidget(self.sg_type)
        grp.addWidget(_label("Group"))
        grp.addWidget(self.sg_group)
        grp.addWidget(read_g)
        grp.addWidget(write_g)
        grp.addStretch(1)
        self.add_layout(grp)

        grp2 = QHBoxLayout()
        self.g_delay = QSpinBox()
        self.g_delay.setRange(0, 99)
        self.g_free = QSpinBox()
        self.g_free.setRange(0, 60)
        self.g_link = QLineEdit()
        self.g_link.setObjectName("Mono")
        self.g_link.setPlaceholderText("bank link e.g. 00 01 02")
        grp2.addWidget(_label("Delay ds"))
        grp2.addWidget(self.g_delay)
        grp2.addWidget(_label("Free s"))
        grp2.addWidget(self.g_free)
        grp2.addWidget(_label("Banks"))
        grp2.addWidget(self.g_link, 1)
        self.add_layout(grp2)

        self.autostore = ToggleRow("Auto-store on hits (AS)")
        self.autostore.changed.connect(lambda on: self.run(lambda: self.device.set_auto_store(on)))
        self.add(self.autostore)

        self.add(section_label("Pass frequencies (PW / PR / PD)"))
        pr = QHBoxLayout()
        self.pr_bank = QSpinBox()
        self.pr_bank.setRange(-1, 39)
        self.pr_bank.setValue(-1)
        self.pr_bank.setSpecialValueText("all banks")
        list_btn = QPushButton("List (PR)")
        list_btn.clicked.connect(self.on_list_pass)
        self.pr_freq = QLineEdit()
        self.pr_freq.setObjectName("Mono")
        self.pr_freq.setPlaceholderText("MHz")
        mark = QPushButton("Mark (PW)")
        mark.clicked.connect(self.on_mark_pass)
        delete_p = QPushButton("Delete all (PD)")
        delete_p.setObjectName("Danger")
        delete_p.clicked.connect(self.on_delete_pass)
        pr.addWidget(_label("Bank"))
        pr.addWidget(self.pr_bank)
        pr.addWidget(list_btn)
        pr.addWidget(self.pr_freq)
        pr.addWidget(mark)
        pr.addWidget(delete_p)
        pr.addStretch(1)
        self.add_layout(pr)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(110)
        self.add(self.output)

    def _fmt_mhz(self, text: str):
        text = text.strip()
        if not text:
            return None
        try:
            return round(float(text) * 1_000_000)
        except ValueError:
            return None

    def on_read_search(self) -> None:
        bank = self.sb_bank.value()
        info = self.call(lambda: self.device.read_search_bank(bank))
        if info is None:
            self.output.setPlainText("read failed")
            return
        lines = [f"bank {bank:02d} registered={info.registered} protect={info.write_protect} tag={info.tag!r}"]
        if info.lower_limit_hz is not None:
            lines.append(f"lower {info.lower_limit_hz / 1_000_000:.4f} MHz")
        if info.upper_limit_hz is not None:
            lines.append(f"upper {info.upper_limit_hz / 1_000_000:.4f} MHz")
        if info.step_hz:
            lines.append(f"step {info.step_hz / 1000:g} kHz")
        if info.mode:
            lines.append(f"mode {info.mode}")
        self.output.setPlainText("\n".join(lines))

    def on_write_search(self) -> None:
        bank = self.sb_bank.value()
        kwargs = {}
        lower = self._fmt_mhz(self.sb_lower.text())
        upper = self._fmt_mhz(self.sb_upper.text())
        if lower is not None:
            kwargs["lower_limit_hz"] = lower
        if upper is not None:
            kwargs["upper_limit_hz"] = upper
        step_text = self.sb_step.text().strip()
        if step_text:
            try:
                kwargs["step_hz"] = round(float(step_text) * 1000)
            except ValueError:
                pass
        if self.sb_mode.text().strip():
            kwargs["mode"] = self.sb_mode.text().strip()
        if self.sb_tag.text().strip():
            kwargs["tag"] = self.sb_tag.text().strip()
        self.run(lambda: self.device.write_search_bank(bank, **kwargs))
        self.output.setPlainText(f"wrote search bank {bank:02d}")

    def on_read_group(self) -> None:
        group = self.sg_group.value()
        if self.sg_type._group.checkedButton() is None:
            return
        search = self.sg_type._buttons["SG"].isChecked()
        getter = self.device.read_search_scan_group if search else self.device.read_memory_scan_group
        info = self.call(lambda: getter(group))
        if info is None:
            self.output.setPlainText("read failed")
            return
        self.g_delay.setValue(info.delay_ds or 0)
        self.g_free.setValue(info.free_time_s or 0)
        self.g_link.setText(" ".join(f"{b:02d}" for b in info.bank_link))
        kind = "SG" if search else "MG"
        extra = ""
        if info.auto_store is not None:
            extra = f" autostore={info.auto_store}"
        self.output.setPlainText(f"{kind} group {group:02d}: delay={info.delay_ds} free={info.free_time_s}{extra}")

    def on_write_group(self) -> None:
        group = self.sg_group.value()
        banks = []
        for token in self.g_link.text().split():
            if token.isdigit():
                banks.append(int(token))
        search = self.sg_type._buttons["SG"].isChecked()
        if search:
            self.run(
                lambda: self.device.write_search_scan_group(
                    group,
                    delay_ds=self.g_delay.value(),
                    free_time_s=self.g_free.value(),
                    auto_store=self.autostore.button.isChecked(),
                    bank_link=banks,
                )
            )
        else:
            self.run(
                lambda: self.device.write_memory_scan_group(
                    group,
                    delay_ds=self.g_delay.value(),
                    free_time_s=self.g_free.value(),
                    bank_link=banks,
                )
            )
        self.output.setPlainText(f"wrote {'SG' if search else 'MG'} group {group:02d}")

    def on_list_pass(self) -> None:
        bank = self.pr_bank.value()
        entries = self.call(lambda: self.device.list_pass_frequencies(None if bank < 0 else bank))
        if entries is None:
            self.output.setPlainText("list failed")
            return
        lines = []
        for entry in entries:
            freq = "--" if entry.frequency_hz is None else f"{entry.frequency_hz / 1_000_000:.5f}"
            bank_text = "" if entry.bank is None else f" bank {entry.bank:02d}"
            lines.append(f"#{entry.index}  {freq} MHz{bank_text}")
        self.output.setPlainText("\n".join(lines) or "(no pass frequencies)")

    def on_mark_pass(self) -> None:
        hz = self._fmt_mhz(self.pr_freq.text())
        if hz is None:
            self.output.setPlainText("enter a frequency in MHz")
            return
        bank = self.pr_bank.value()
        self.run(
            lambda: self.device.mark_pass_frequency(
                frequency_hz=hz, bank=None if bank < 0 else bank, all_banks=bank < 0
            )
        )
        self.output.setPlainText(f"marked {hz / 1_000_000:.5f} MHz")

    def on_delete_pass(self) -> None:
        bank = self.pr_bank.value()
        self.run(
            lambda: self.device.delete_pass_frequencies(
                bank=None if bank < 0 else bank, all_banks=bank < 0
            )
        )
        self.output.setPlainText("deleted pass frequencies")

    def refresh(self, status) -> None:
        self.autostore.set_checked(bool(self.call(self.device.get_auto_store, False)))


class SdTimerPanel(Panel):
    def __init__(self, window):
        super().__init__(window, "VFO search / recording / SD card", collapsed=True)
        self.add(section_label("SD card (SD ...)"))
        row = QHBoxLayout()
        for text, verb in (("Dir", "dir"), ("Info", "info"), ("Status", "status")):
            button = QPushButton(text)
            button.clicked.connect(lambda _=False, v=verb: self.on_sd(v))
            row.addWidget(button)
        rec = QPushButton("Rec start")
        rec.clicked.connect(lambda: self.on_sd("rec"))
        row.addWidget(rec)
        play = QPushButton("Play")
        play.clicked.connect(lambda: self.on_sd("play"))
        row.addWidget(play)
        row.addStretch(1)
        self.add_layout(row)

        self.rsq = ToggleRow("SD squelch skip (SD RSQ)")
        self.rsq.changed.connect(lambda on: self.run(lambda: self.device.set_sd_squelch_skip(on)))
        self.add(self.rsq)

        self.add(section_label("VFO search settings (VE)"))
        ve = QHBoxLayout()
        self.ve_delay = QSpinBox()
        self.ve_delay.setRange(0, 99)
        self.ve_free = QSpinBox()
        self.ve_free.setRange(0, 60)
        read_ve = QPushButton("Read")
        read_ve.clicked.connect(self.on_read_ve)
        write_ve = QPushButton("Write")
        write_ve.clicked.connect(
            lambda: self.run(
                lambda: self.device.write_vfo_search_settings(
                    delay_ds=self.ve_delay.value(), free_time_s=self.ve_free.value()
                )
            )
        )
        ve.addWidget(_label("Delay ds"))
        ve.addWidget(self.ve_delay)
        ve.addWidget(_label("Free s"))
        ve.addWidget(self.ve_free)
        ve.addWidget(read_ve)
        ve.addWidget(write_ve)
        ve.addStretch(1)
        self.add_layout(ve)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(110)
        self.add(self.output)

    def on_read_ve(self) -> None:
        settings = self.call(self.device.read_vfo_search_settings)
        if settings is None:
            self.output.setPlainText("read failed")
            return
        self.ve_delay.setValue(settings.delay_ds or 0)
        self.ve_free.setValue(settings.free_time_s or 0)
        self.output.setPlainText(f"VE delay={settings.delay_ds} free={settings.free_time_s}")

    def on_sd(self, verb: str) -> None:
        if verb == "dir":
            entries = self.call(lambda: self.device.sd_dir())
            if entries is None:
                self.output.setPlainText("SD dir failed")
                return
            lines = []
            for entry in entries:
                name = getattr(entry, "name", None) or str(entry)
                size = getattr(entry, "size", None)
                lines.append(f"{name}  {size if size is not None else ''}".rstrip())
            self.output.setPlainText("\n".join(lines) or "(empty)")
            return
        if verb == "info":
            info = self.call(self.device.sd_info)
            self.output.setPlainText(str(info))
            return
        if verb == "status":
            status = self.call(self.device.sd_status)
            self.output.setPlainText(str(status))
            return
        if verb == "rec":
            self.run(self.device.sd_record_start)
            self.output.setPlainText("recording started")
            return
        if verb == "play":
            self.output.setPlainText("use the raw console: raw SD PLY <name>")

    def refresh(self, status) -> None:
        self.rsq.set_checked(bool(self.call(self.device.get_sd_squelch_skip, False)))


class SelectScanPanel(Panel):
    def __init__(self, window):
        super().__init__(window, "Select-scan", collapsed=True)
        self.entries = SelectScanList()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._queue: list[tuple[int, int]] = []

        row = QHBoxLayout()
        self.bank = QSpinBox()
        self.bank.setRange(0, 39)
        self.channel = QSpinBox()
        self.channel.setRange(0, 49)
        add = QPushButton("Add")
        add.clicked.connect(self.on_add)
        remove = QPushButton("Remove")
        remove.clicked.connect(self.on_remove)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.on_clear)
        row.addWidget(_label("Bank"))
        row.addWidget(self.bank)
        row.addWidget(_label("Ch"))
        row.addWidget(self.channel)
        for button in (add, remove, clear):
            row.addWidget(button)
        row.addStretch(1)
        self.add_layout(row)

        run_row = QHBoxLayout()
        self.dwell = QSpinBox()
        self.dwell.setRange(1, 60)
        self.dwell.setValue(2)
        self.cycles = QSpinBox()
        self.cycles.setRange(1, 999)
        self.cycles.setValue(1)
        self.run_button = QPushButton("Run")
        self.run_button.setObjectName("Accent")
        self.run_button.clicked.connect(self.on_run)
        stop = QPushButton("Stop")
        stop.clicked.connect(self.on_stop)
        run_row.addWidget(_label("Dwell s"))
        run_row.addWidget(self.dwell)
        run_row.addWidget(_label("Cycles"))
        run_row.addWidget(self.cycles)
        run_row.addWidget(self.run_button)
        run_row.addWidget(stop)
        run_row.addStretch(1)
        self.add_layout(run_row)

        self.info = _label("list: 0 entries")
        self.add(self.info)

    def on_add(self) -> None:
        try:
            self.entries.add(self.bank.value(), self.channel.value())
        except ValueError as exc:
            self.info.setText(str(exc))
            return
        self._update_info()

    def on_remove(self) -> None:
        self.entries.remove(self.bank.value(), self.channel.value())
        self._update_info()

    def on_clear(self) -> None:
        self.entries.clear()
        self._update_info()

    def _update_info(self) -> None:
        listing = ", ".join(f"{b:02d}-{c:02d}" for b, c in self.entries)
        self.info.setText(f"list: {len(self.entries)} entries  {listing}")

    def on_run(self) -> None:
        if not self.entries:
            self.info.setText("list is empty")
            return
        self._queue = list(self.entries) * self.cycles.value()
        self.run_button.setEnabled(False)
        self._timer.start(self.dwell.value() * 1000)
        self._tick()

    def on_stop(self) -> None:
        self._timer.stop()
        self._queue = []
        self.run_button.setEnabled(True)

    def _tick(self) -> None:
        if not self._queue:
            self.on_stop()
            self.info.setText("select-scan finished")
            return
        bank, channel = self._queue.pop(0)
        self.run(lambda: self.device.tune_memory_channel(bank, channel))
        self.info.setText(f"scanning {bank:02d}-{channel:02d} ({len(self._queue)} left)")


class SignalLogPanel(Panel):
    def __init__(self, window):
        super().__init__(window, "Signal log", collapsed=True)
        row = QHBoxLayout()
        clear = QPushButton("Clear log")
        clear.clicked.connect(self.clear)
        row.addWidget(clear)
        self.threshold_on = ToggleRow("Threshold alerts")
        self.threshold = QSpinBox()
        self.threshold.setRange(-120, 0)
        self.threshold.setValue(-80)
        row.addWidget(self.threshold_on)
        row.addWidget(_label("dBm >="))
        row.addWidget(self.threshold)
        row.addStretch(1)
        self.count = _label("0 events")
        row.addWidget(self.count)
        self.add_layout(row)

        self._tray = QSystemTrayIcon(self) if QSystemTrayIcon.isSystemTrayAvailable() else None
        if self._tray is not None:
            self._tray.show()

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Time", "MHz", "dB", "Mode"])
        self.table.setMinimumHeight(200)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.add(self.table)

    def clear(self) -> None:
        self.table.setRowCount(0)
        self.count.setText("0 events")

    def add_event(self, frequency_hz, dbm, mode) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        freq = "--" if frequency_hz is None else f"{frequency_hz / 1_000_000:.5f}"
        alert = (
            self.threshold_on.button.isChecked()
            and dbm is not None
            and dbm >= self.threshold.value()
        )
        self.table.insertRow(0)
        for col, value in enumerate((stamp, freq, "--" if dbm is None else str(dbm), mode or "")):
            item = QTableWidgetItem(value)
            item.setFlags(Qt.ItemIsEnabled)
            if alert:
                item.setForeground(QColor(self.window.theme_color("bad")))
            self.table.setItem(0, col, item)
        self.count.setText(f"{self.table.rowCount()} events")
        if alert and self._tray is not None:
            self._tray.showMessage(
                "AR-DV10 signal alert",
                f"{freq} MHz  {dbm} dB  {mode or ''}".strip(),
            )
