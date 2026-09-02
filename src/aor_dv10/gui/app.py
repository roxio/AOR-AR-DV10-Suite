"""Minimal PySide6 GUI - phase 2 starting point.

Priority for this project was core protocol + CLI first (see README.md).
This GUI is a working but intentionally small skeleton: a
Yaesu-panel-styled readout plus the same handful of controls the CLI exposes,
built on the identical DV10Device API so nothing here has its own copy of
protocol logic. Extending it (memory channels, scan, search banks, digital
mode params, ...) is mostly a matter of adding more widgets that call more
DV10Device / device.raw(...) methods.

Run with:  pip install -e ".[gui]"  &&  python -m aor_dv10.gui.app [--simulator]
"""

from __future__ import annotations

import argparse
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..device import AGC_SPEEDS, ATTENUATOR_STATES, SQUELCH_MODES, DV10Device
from ..protocol.codec import DV10Error
from ..transport.base import TransportError


class MainWindow(QMainWindow):
    def __init__(self, device: DV10Device):
        super().__init__()
        self.device = device
        self.setWindowTitle("AOR AR-DV10 Control")
        self.setMinimumWidth(420)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # -- big frequency readout, Yaesu-panel style --------------------
        self.freq_label = QLabel("---.------ MHz")
        self.freq_label.setAlignment(Qt.AlignCenter)
        self.freq_label.setStyleSheet(
            "font-family: 'DejaVu Sans Mono', monospace; font-size: 32px; "
            "color: #00e5ff; background: #001018; padding: 12px; border: 2px solid #00e5ff;"
        )
        layout.addWidget(self.freq_label)

        # -- S-meter ------------------------------------------------------
        meter_box = QHBoxLayout()
        meter_box.addWidget(QLabel("S-METER"))
        self.smeter_bar = QProgressBar()
        # LM's confirmed format is "vvvq": vvv = signal level as -vvv dB,
        # q = squelch state digit - see aor_dv10.device.SMeterReading.
        # -120..0 dB is a sane display floor/ceiling, not
        # a hardware limit.
        self.smeter_bar.setRange(-120, 0)
        meter_box.addWidget(self.smeter_bar)
        layout.addLayout(meter_box)

        # -- controls -------------------------------------------------------
        controls = QGroupBox("Controls")
        grid = QGridLayout(controls)

        grid.addWidget(QLabel("Frequency (MHz)"), 0, 0)
        self.freq_input = QDoubleSpinBox()
        self.freq_input.setDecimals(6)
        self.freq_input.setRange(0, 6000)
        grid.addWidget(self.freq_input, 0, 1)
        set_freq_btn = QPushButton("Set")
        set_freq_btn.clicked.connect(self.on_set_frequency)
        grid.addWidget(set_freq_btn, 0, 2)

        # Confirmed against real DV10 hardware: "raw VF A"
        # succeeds and is very likely the software command to enter VFO
        # mode - the precondition for the frequency/squelch/AGC/attenuator
        # writes above to succeed at all instead of failing with "?".
        # Surfaced here as a button rather than
        # done automatically, since it hasn't been confirmed to be safe/a
        # no-op to call repeatedly or from every starting state.
        vfo_btn = QPushButton("Enter VFO A")
        vfo_btn.setToolTip(
            "Sends VF A - needed before Set (frequency/squelch/AGC/"
            "attenuator) will work if the receiver is browsing a memory "
            "channel."
        )
        vfo_btn.clicked.connect(self.on_enter_vfo)
        grid.addWidget(vfo_btn, 0, 3)

        grid.addWidget(QLabel("Mode"), 1, 0)
        self.mode_input = QLineEdit()
        grid.addWidget(self.mode_input, 1, 1)
        set_mode_btn = QPushButton("Set")
        set_mode_btn.clicked.connect(self.on_set_mode)
        grid.addWidget(set_mode_btn, 1, 2)

        # NOTE: AC (AGC) is actually a 4-state speed selector (Fast/Mid/
        # Slow/RF-G), confirmed via the AR-DV3 spec - see
        # aor_dv10.device.AGC_SPEEDS / get_agc_speed() / set_agc_speed().
        # This checkbox is a legacy on/off simplification (on -> Mid,
        # off -> Fast) kept for now; a proper 4-way selector is future work.
        self.agc_check = QCheckBox("AGC (legacy on/off)")
        self.agc_check.stateChanged.connect(self.on_toggle_agc)
        grid.addWidget(self.agc_check, 2, 0)

        self.beep_check = QCheckBox("Beep")
        self.beep_check.stateChanged.connect(self.on_toggle_beep)
        grid.addWidget(self.beep_check, 2, 1)

        # NOTE: AT is a 3-state selector (0=ATT OFF, 1=ATT ON, 2=10dB ATT) -
        # the labels follow a real DV10's effect (1 engages the ~10dB signal
        # attenuator), see aor_dv10.device.ATTENUATOR_STATES /
        # get_attenuator_state() / set_attenuator_state(). This checkbox is
        # a legacy on/off simplification (on -> ATT ON, off -> ATT OFF) that
        # can't reach the 10dB (DV3-only) state; a proper 3-way selector is
        # future work.
        self.att_check = QCheckBox("Attenuator (legacy on/off)")
        self.att_check.stateChanged.connect(self.on_toggle_att)
        grid.addWidget(self.att_check, 2, 2)

        # Confirmed against real DV10 hardware: toggling this
        # on ("raw RE 1") makes rejected commands come back with a decoded
        # numeric result code instead of a bare "?" - see
        # aor_dv10.protocol.codec.RESULT_CODES. Purely
        # a diagnostic aid; DV10Device already decodes the numeric-code
        # response either way once this is on.
        self.re_check = QCheckBox("Result codes (diagnostic)")
        self.re_check.stateChanged.connect(self.on_toggle_re)
        grid.addWidget(self.re_check, 2, 3)

        layout.addWidget(controls)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: gray;")
        layout.addWidget(self.status_label)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()

    def refresh(self) -> None:
        try:
            status = self.device.status()
        except DV10Error as exc:
            self.status_label.setText(f"error: {exc}")
            return
        if status.frequency_hz is not None:
            self.freq_label.setText(f"{status.frequency_hz / 1_000_000:>13,.6f} MHz")
        if status.smeter_reading is not None and status.smeter_reading.dbm is not None:
            self.smeter_bar.setValue(status.smeter_reading.dbm)
            self.smeter_bar.setFormat(
                f"{status.smeter_reading.dbm} dB - SQL "
                + ("open" if status.smeter_reading.squelch_open else "closed")
            )
        mode_desc = status.mode_info.describe() if status.mode_info else status.mode
        sql_desc = SQUELCH_MODES.get(status.squelch, status.squelch)
        agc_desc = AGC_SPEEDS.get(status.agc_speed, status.agc_speed or status.agc_on)
        att_desc = ATTENUATOR_STATES.get(status.attenuator_state, status.attenuator_state)
        self.status_label.setText(
            f"mode={mode_desc} sql_mode={sql_desc} vol={status.volume} "
            f"agc={agc_desc} att={att_desc}"
        )

    def _guard(self, fn):
        try:
            fn()
        except DV10Error as exc:
            QMessageBox.warning(self, "Device error", str(exc))

    def on_set_frequency(self) -> None:
        hz = round(self.freq_input.value() * 1_000_000)
        self._guard(lambda: self.device.set_frequency_hz(hz))

    def on_set_mode(self) -> None:
        mode = self.mode_input.text().strip()
        if mode:
            self._guard(lambda: self.device.set_mode(mode))

    def on_toggle_agc(self) -> None:
        self._guard(lambda: self.device.set_agc(self.agc_check.isChecked()))

    def on_toggle_beep(self) -> None:
        self._guard(lambda: self.device.set_beep(self.beep_check.isChecked()))

    def on_toggle_att(self) -> None:
        self._guard(lambda: self.device.set_attenuator(self.att_check.isChecked()))

    def on_enter_vfo(self) -> None:
        self._guard(lambda: self.device.enter_vfo_mode("A"))

    def on_toggle_re(self) -> None:
        self._guard(lambda: self.device.set_result_code_prefixing(self.re_check.isChecked()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AOR AR-DV10 GUI (phase 2 skeleton)")
    parser.add_argument("--port", help="Explicit serial device; omit to auto-detect")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--simulator", action="store_true", help="Use the in-process simulator")
    args = parser.parse_args(argv)

    device = (
        DV10Device.open_simulator()
        if args.simulator
        else DV10Device.open_serial(port=args.port, baudrate=args.baud)
    )
    try:
        device.connect()
    except TransportError as exc:
        print(f"Could not connect: {exc}")
        return 1

    app = QApplication(sys.argv)
    window = MainWindow(device)
    window.show()
    ret = app.exec()
    device.disconnect()
    return ret


if __name__ == "__main__":
    sys.exit(main())
