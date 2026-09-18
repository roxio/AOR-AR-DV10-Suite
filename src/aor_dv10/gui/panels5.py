
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QSpinBox

from ..memory import backup_from_json, backup_to_json
from .panels import Panel, _label
from .widgets import Segmented, Sparkline, section_label

BACKUP_DIR = Path("dv10_backups")


class ScopePanel(Panel):
    def __init__(self, window):
        super().__init__(window, "Spectrum scope", collapsed=True)
        row = QHBoxLayout()
        fast = QPushButton("Read fast (FD)")
        fast.setObjectName("Accent")
        fast.clicked.connect(lambda: self.on_read(True))
        normal = QPushButton("Read normal (GL)")
        normal.clicked.connect(lambda: self.on_read(False))
        row.addWidget(fast)
        row.addWidget(normal)
        row.addStretch(1)
        self.add_layout(row)

        self.spark = Sparkline()
        self.window.register_spark(self.spark)
        self.add(self.spark)

        self.info = _label("not read")
        self.add(self.info)

    def on_read(self, fast: bool) -> None:
        if fast:
            values = self.call(self.device.read_scope_data_fast)
        else:
            line = self.call(self.device.read_scope_data_normal)
            values = getattr(line, "levels_dbm", None) if line is not None else None
        if not values:
            self.info.setText("no scope data (receiver must be in scope mode)")
            return
        self.spark.set_values(list(values))
        self.info.setText(f"{len(values)} points, min {min(values)} dB / max {max(values)} dB")

    def refresh(self, status) -> None:
        return None


class AutomationPanel(Panel):
    def __init__(self, window):
        super().__init__(window, "Snapshots & automation", collapsed=True)
        self.add(section_label("Snapshots (dv10_backups)"))
        snap = QHBoxLayout()
        self.snapshot_list = QComboBox()
        create = QPushButton("Create")
        create.setObjectName("Accent")
        create.clicked.connect(self.on_create)
        restore = QPushButton("Restore")
        restore.clicked.connect(self.on_restore)
        delete = QPushButton("Delete")
        delete.setObjectName("Danger")
        delete.clicked.connect(self.on_delete)
        snap.addWidget(self.snapshot_list, 1)
        for button in (create, restore, delete):
            snap.addWidget(button)
        self.add_layout(snap)

        self.add(section_label("Interval jobs"))
        job = QHBoxLayout()
        self.action = Segmented([("backup", "Backup"), ("scan", "Scan")])
        self.interval = QSpinBox()
        self.interval.setRange(1, 3600)
        self.interval.setValue(300)
        self.bank = QSpinBox()
        self.bank.setRange(0, 39)
        self.job_button = QPushButton("Start")
        self.job_button.setObjectName("Accent")
        self.job_button.clicked.connect(self.on_toggle_job)
        job.addWidget(self.action)
        job.addWidget(_label("every s"))
        job.addWidget(self.interval)
        job.addWidget(_label("bank"))
        job.addWidget(self.bank)
        job.addWidget(self.job_button)
        job.addStretch(1)
        self.add_layout(job)

        self.job_info = _label("idle")
        self.add(self.job_info)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_tick)
        self.refresh_snapshots()

    def _memory(self):
        panel = getattr(self.window, "memory_panel", None)
        if panel is None or not panel.channels:
            return None
        return panel

    def refresh_snapshots(self) -> None:
        current = self.snapshot_list.currentText()
        self.snapshot_list.clear()
        if BACKUP_DIR.is_dir():
            for path in sorted(BACKUP_DIR.glob("*.json"), reverse=True):
                self.snapshot_list.addItem(path.name)
        index = self.snapshot_list.findText(current)
        if index >= 0:
            self.snapshot_list.setCurrentIndex(index)

    def on_create(self) -> None:
        panel = self._memory()
        if panel is None:
            self.job_info.setText("no memory database loaded")
            return
        BACKUP_DIR.mkdir(exist_ok=True)
        name = f"dv10_memory_{datetime.now():%Y%m%d-%H%M%S}.json"
        (BACKUP_DIR / name).write_text(backup_to_json(panel.banks, panel.channels), encoding="utf-8")
        self.refresh_snapshots()
        self.job_info.setText(f"created {name}")

    def on_restore(self) -> None:
        panel = self._memory()
        name = self.snapshot_list.currentText()
        path = BACKUP_DIR / name
        if not name or not path.is_file():
            self.job_info.setText("select a snapshot first")
            return
        try:
            banks, channels = backup_from_json(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            self.job_info.setText(f"restore error: {exc}")
            return
        if panel is not None:
            panel.banks, panel.channels = banks, channels
            panel.info.setText(f"restored {name}")
            panel.rebuild()
        self.job_info.setText(f"restored {name}")

    def on_delete(self) -> None:
        name = self.snapshot_list.currentText()
        path = BACKUP_DIR / name
        if name and path.is_file():
            path.unlink()
        self.refresh_snapshots()
        self.job_info.setText(f"deleted {name}")

    def on_toggle_job(self) -> None:
        if self.timer.isActive():
            self.timer.stop()
            self.job_button.setText("Start")
            self.job_info.setText("stopped")
            return
        self.timer.start(self.interval.value() * 1000)
        self.job_button.setText("Stop")
        self.job_info.setText(f"running every {self.interval.value()} s")

    def on_tick(self) -> None:
        backup = self.action._buttons["backup"].isChecked()
        if backup:
            self.on_create()
        else:
            self.run(lambda: self.device.execute_search(self.bank.value()))
            self.job_info.setText(f"ran scan bank {self.bank.value():02d}")

    def refresh(self, status) -> None:
        return None
