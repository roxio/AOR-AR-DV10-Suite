
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
)

from ..adif import parse_adif, write_adif
from ..memory import (
    MemoryBank,
    MemoryChannel,
    backup_from_json,
    backup_to_json,
    parse_backup_csv,
    parse_chirp_csv,
    parse_generic_freq_csv,
    write_backup_csv,
    write_chirp_csv,
)
from .panels import Panel, _label
from .widgets import section_label


def load_memory_file(path: str) -> tuple[list[MemoryBank], list[MemoryChannel], str]:
    text = Path(path).read_text(encoding="utf-8-sig")
    suffix = Path(path).suffix.lower()
    if suffix in (".adi", ".adif"):
        banks, channels = parse_adif(text)
        return banks, channels, "ADIF"
    if suffix == ".json":
        banks, channels = backup_from_json(text)
        return banks, channels, "JSON"
    attempts = (
        (parse_backup_csv, "backup CSV"),
        (parse_chirp_csv, "CHIRP CSV"),
        (parse_generic_freq_csv, "frequency CSV"),
    )
    for parser, name in attempts:
        try:
            banks, channels = parser(text)
        except (ValueError, IndexError):
            continue
        if any(not channel.is_empty for channel in channels):
            return banks, channels, name
    raise ValueError(f"could not parse a memory file: {path}")


class MemoryPanel(Panel):
    def __init__(self, window):
        super().__init__(window, "Memory channels & live memory", collapsed=True)
        self.banks: list[MemoryBank] = []
        self.channels: list[MemoryChannel] = []
        self._rows: list[MemoryChannel] = []

        actions = QHBoxLayout()
        import_btn = QPushButton("Import CSV / JSON / CHIRP / ADIF")
        import_btn.setObjectName("Accent")
        import_btn.clicked.connect(self.on_import)
        export_btn = QPushButton("Export...")
        export_btn.clicked.connect(self.on_export)
        label_btn = QPushButton("Auto-label blanks")
        label_btn.clicked.connect(self.on_autolabel)
        actions.addWidget(import_btn)
        actions.addWidget(export_btn)
        actions.addWidget(label_btn)
        actions.addStretch(1)
        self.add_layout(actions)

        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("filter by name")
        self.search.textChanged.connect(self.rebuild)
        self.bank_filter = QSpinBox()
        self.bank_filter.setRange(-1, 39)
        self.bank_filter.setValue(-1)
        self.bank_filter.setSpecialValueText("all banks")
        self.bank_filter.valueChanged.connect(self.rebuild)
        filters.addWidget(self.search, 1)
        filters.addWidget(_label("Bank"))
        filters.addWidget(self.bank_filter)
        self.add_layout(filters)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Channel", "MHz", "Mode", "Name"])
        self.table.setMinimumHeight(220)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.doubleClicked.connect(lambda _: self.on_tune())
        self.add(self.table)

        tune = QHBoxLayout()
        tune_btn = QPushButton("Tune to selected")
        tune_btn.setObjectName("Accent")
        tune_btn.clicked.connect(self.on_tune)
        tune.addWidget(tune_btn)
        tune.addStretch(1)
        self.add_layout(tune)

        self.info = _label("no memory database loaded")
        self.add(self.info)

        self.add(section_label("Live receiver"))
        live = QHBoxLayout()
        self.live_bank = QSpinBox()
        self.live_bank.setRange(0, 39)
        export_live = QPushButton("Export live bank CSV")
        export_live.clicked.connect(self.on_live_export)
        diff = QPushButton("Diff vs live")
        diff.clicked.connect(self.on_live_diff)
        live.addWidget(_label("Bank"))
        live.addWidget(self.live_bank)
        live.addWidget(export_live)
        live.addWidget(diff)
        live.addStretch(1)
        self.add_layout(live)

        self.live_output = QPlainTextEdit()
        self.live_output.setReadOnly(True)
        self.live_output.setMinimumHeight(90)
        self.add(self.live_output)

    def on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import memory", "", "Memory files (*.csv *.json *.adi *.adif);;All files (*)"
        )
        if not path:
            return
        try:
            self.banks, self.channels, fmt = load_memory_file(path)
        except (ValueError, OSError) as exc:
            self.info.setText(f"import error: {exc}")
            return
        programmed = sum(1 for channel in self.channels if not channel.is_empty)
        self.info.setText(f"loaded {len(self.banks)} banks / {len(self.channels)} slots ({programmed}) - {fmt}")
        self.rebuild()

    def on_export(self) -> None:
        if not self.channels:
            self.info.setText("nothing to export")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export memory", "", "Backup CSV (*.csv);;JSON (*.json);;CHIRP CSV (*.csv);;ADIF (*.adi)"
        )
        if not path:
            return
        suffix = Path(path).suffix.lower()
        try:
            if suffix == ".json":
                text = backup_to_json(self.banks, self.channels)
            elif suffix in (".adi", ".adif"):
                text = write_adif(self.channels)
            elif "chirp" in Path(path).stem.lower():
                text = write_chirp_csv(self.channels)
            else:
                text = write_backup_csv(self.banks, self.channels)
            Path(path).write_text(text, encoding="utf-8")
        except (ValueError, OSError) as exc:
            self.info.setText(f"export error: {exc}")
            return
        self.info.setText(f"wrote {path}")

    def rebuild(self) -> None:
        needle = self.search.text().strip().lower()
        bank = self.bank_filter.value()
        rows = [
            channel
            for channel in self.channels
            if not channel.is_empty
            and (bank < 0 or channel.bank == bank)
            and (not needle or needle in channel.name.lower())
        ]
        self._rows = rows
        self.table.setRowCount(len(rows))
        for row, channel in enumerate(rows):
            values = [
                channel.bank_channel,
                f"{channel.frequency_hz / 1_000_000:.5f}",
                channel.mode or "",
                channel.name.strip(),
            ]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(value))

    def on_tune(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._rows):
            return
        channel = self._rows[row]

        def do_tune() -> None:
            self.device.enter_vfo_mode("A")
            self.device.set_frequency_hz(channel.frequency_hz)
            if channel.step_hz:
                self.device.set_frequency_step_hz(channel.step_hz)
            if channel.mode and len(channel.mode) == 3:
                self.device.set_mode(channel.mode[1:3])

        self.run(do_tune)
        self.info.setText(f"tuned to {channel.bank_channel} {channel.frequency_hz / 1_000_000:.5f} MHz")

    def on_autolabel(self) -> None:
        labeled = 0
        for channel in self.channels:
            if channel.is_empty or channel.name.strip():
                continue
            mode = (channel.mode or "").strip()
            channel.name = f"{mode} {channel.frequency_hz / 1_000_000:.5f}".strip()[:12]
            labeled += 1
        self.rebuild()
        self.info.setText(f"auto-labelled {labeled} channels")

    def on_live_export(self) -> None:
        bank = self.live_bank.value()
        slots = self.call(lambda: self.device.read_memory_bank(bank))
        if slots is None:
            self.live_output.setPlainText("live read failed")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export live bank", f"ardv10_bank{bank:02d}_live.csv", "CSV (*.csv)"
        )
        if not path:
            return
        lines = ["Bank,Channel,Frequency,MHz,Mode,Tag,Protect,Pass"]
        for slot in slots:
            freq = "" if slot.frequency_hz is None else f"{slot.frequency_hz / 1_000_000:.5f}"
            lines.append(
                f"{bank:02d},{slot.channel:02d},{freq},{slot.mode or ''},{slot.tag.strip()},"
                f"{int(slot.write_protect)},{int(slot.pass_channel)}"
            )
        try:
            Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as exc:
            self.live_output.setPlainText(f"write error: {exc}")
            return
        self.live_output.setPlainText(f"exported {len(slots)} slots to {path}")

    def on_live_diff(self) -> None:
        bank = self.live_bank.value()
        slots = self.call(lambda: self.device.read_memory_bank(bank))
        if slots is None:
            self.live_output.setPlainText("live read failed")
            return
        backup = {
            channel.channel: channel
            for channel in self.channels
            if channel.bank == bank
        }
        differences = []
        compared = 0
        for slot in slots:
            channel = backup.get(slot.channel)
            if channel is None:
                continue
            compared += 1
            live_freq = slot.frequency_hz
            backup_freq = channel.frequency_hz if not channel.is_empty else None
            if live_freq != backup_freq:
                differences.append(f"{bank:02d}-{slot.channel:02d} freq: {backup_freq} vs {live_freq}")
                continue
            if (slot.mode or "") != (channel.mode or ""):
                differences.append(f"{bank:02d}-{slot.channel:02d} mode: {channel.mode} vs {slot.mode}")
            if slot.tag.strip() != channel.name.strip():
                differences.append(f"{bank:02d}-{slot.channel:02d} name: {channel.name!r} vs {slot.tag!r}")
            if slot.write_protect != channel.protect:
                differences.append(f"{bank:02d}-{slot.channel:02d} protect: {channel.protect} vs {slot.write_protect}")
            if slot.pass_channel != channel.pass_flag:
                differences.append(f"{bank:02d}-{slot.channel:02d} pass: {channel.pass_flag} vs {slot.pass_channel}")
        header = f"bank {bank:02d}: {compared} compared, {len(differences)} differences"
        self.live_output.setPlainText("\n".join([header, *differences]))


class LiveMemoryPanel(Panel):
    def __init__(self, window):
        super().__init__(window, "Live memory bank editor", collapsed=True)
        self._bank = 0

        row = QHBoxLayout()
        self.bank = QSpinBox()
        self.bank.setRange(0, 39)
        load = QPushButton("Load bank")
        load.setObjectName("Accent")
        load.clicked.connect(self.on_load)
        row.addWidget(_label("Bank"))
        row.addWidget(self.bank)
        row.addWidget(load)
        row.addStretch(1)
        self.add_layout(row)

        self.table = QTableWidget(50, 5)
        self.table.setHorizontalHeaderLabels(["Ch", "MHz", "Mode", "Tag", "PT"])
        self.table.setMinimumHeight(240)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.add(self.table)

        actions = QHBoxLayout()
        save = QPushButton("Write selected row (MX)")
        save.clicked.connect(self.on_write_row)
        overwrite = QPushButton("Overwrite bank (MX)")
        overwrite.setObjectName("Danger")
        overwrite.clicked.connect(self.on_overwrite)
        actions.addWidget(save)
        actions.addWidget(overwrite)
        actions.addStretch(1)
        self.add_layout(actions)

        self.info = _label("not loaded")
        self.add(self.info)

    def on_load(self) -> None:
        bank = self.bank.value()
        slots = self.call(lambda: self.device.read_memory_bank(bank))
        if slots is None:
            self.info.setText("load failed")
            return
        self._bank = bank
        self.table.setRowCount(len(slots))
        for row, slot in enumerate(slots):
            self.table.setItem(row, 0, QTableWidgetItem(str(slot.channel)))
            self.table.item(row, 0).setFlags(Qt.ItemIsEnabled)
            freq = "" if slot.frequency_hz is None else f"{slot.frequency_hz / 1_000_000:.5f}"
            self.table.setItem(row, 1, QTableWidgetItem(freq))
            self.table.setItem(row, 2, QTableWidgetItem(slot.mode or ""))
            self.table.setItem(row, 3, QTableWidgetItem(slot.tag))
            self.table.setItem(row, 4, QTableWidgetItem("1" if slot.write_protect else "0"))
            self.table.item(row, 4).setFlags(Qt.ItemIsEnabled)
        programmed = sum(1 for slot in slots if slot.frequency_hz is not None)
        self.info.setText(f"bank {bank:02d}: {programmed} programmed slots")

    def _row_values(self, row: int):
        freq_item = self.table.item(row, 1)
        text = freq_item.text().strip() if freq_item else ""
        if not text:
            return None
        try:
            hz = round(float(text) * 1_000_000)
        except ValueError:
            return None
        mode_item = self.table.item(row, 2)
        tag_item = self.table.item(row, 3)
        return hz, (mode_item.text().strip() if mode_item else ""), (tag_item.text() if tag_item else "")

    def on_write_row(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        values = self._row_values(row)
        if values is None:
            self.info.setText("row has no frequency")
            return
        hz, mode, tag = values
        self.run(
            lambda: self.device.write_memory_channel(
                self._bank, row, frequency_hz=hz, mode=mode or None, tag=tag
            )
        )
        self.info.setText(f"wrote {self._bank:02d}-{row:02d}")

    def on_overwrite(self) -> None:
        bank = self._bank
        entries = []
        for row in range(self.table.rowCount()):
            values = self._row_values(row)
            if values is not None:
                entries.append((row, values))
        if not entries:
            self.info.setText("nothing to write")
            return

        def do_write() -> None:
            for row, (hz, mode, tag) in entries:
                self.device.write_memory_channel(bank, row, frequency_hz=hz, mode=mode or None, tag=tag)

        self.run(do_write)
        self.info.setText(f"overwrote {len(entries)} rows of bank {bank:02d}")
