
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from aor_dv10.device import DV10Device
from aor_dv10.gui import app as gui_app
from aor_dv10.gui import theme


@pytest.fixture
def window():
    device = DV10Device.open_simulator()
    device.connect()
    _ = QApplication.instance() or QApplication([])
    win = gui_app.MainWindow(device)
    yield win, device
    device.disconnect()


def test_window_builds_with_all_panels(window):
    win, _ = window
    assert len(win._panels) >= 15
    assert win.memory_panel is not None


def test_all_themes_apply_and_refresh(window):
    win, _ = window
    for name in theme.THEMES:
        win.apply_theme(name)
        win.refresh()
    win.apply_theme(theme.DEFAULT_THEME)
    assert win._theme_name == theme.DEFAULT_THEME


def test_refresh_updates_readout(window):
    win, _ = window
    win.refresh()
    lcd = next(p for p in win._panels if p.__class__.__name__ == "LcdPanel")
    assert "MHz" in lcd.freq.text()


def test_language_switch_translates_panel_titles(window):
    win, _ = window
    english = [panel.title_label.text() for panel in win._panels]
    win._set_language("pl")
    polish = [panel.title_label.text() for panel in win._panels]
    assert english != polish
    win._set_language("en")
    assert [panel.title_label.text() for panel in win._panels] == english


def test_error_log_records_errors(window):
    win, _ = window
    win.error_log.add_entry("boom")
    assert win.error_log.table.rowCount() == 1


def test_knob_drag_terminates_and_steps():
    from aor_dv10.gui.widgets import Knob

    _ = QApplication.instance() or QApplication([])
    knob = Knob()
    steps: list[int] = []
    knob.stepped.connect(steps.append)

    knob._apply_delta(25)
    assert len(steps) == 2
    assert sum(steps) == -2

    knob._apply_delta(-55)
    assert len(steps) == 7
    assert sum(steps) == 3


def test_knob_wheel_steps():
    from aor_dv10.gui.widgets import Knob

    _ = QApplication.instance() or QApplication([])
    knob = Knob()
    steps: list[int] = []
    knob.stepped.connect(steps.append)
    assert knob._accumulated == 0.0
    assert steps == []
