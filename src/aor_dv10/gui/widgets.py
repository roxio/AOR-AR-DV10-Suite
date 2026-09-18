
from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

_THEME = None


def set_theme(theme) -> None:
    global _THEME
    _THEME = theme


def current_theme():
    return _THEME


class Card(QFrame):
    def __init__(self, title: str, collapsed: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 10)
        outer.setSpacing(8)

        self._title = title
        self.header = QPushButton()
        self.header.setObjectName("CardHeader")
        self.header.setCheckable(True)
        self.header.setChecked(not collapsed)
        self.header.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout(self.header)
        row.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("CardTitle")
        self.title_label.setProperty("i18nUpper", True)
        self.arrow_label = QLabel()
        self.arrow_label.setObjectName("CardArrow")
        row.addWidget(self.title_label)
        row.addStretch(1)
        row.addWidget(self.arrow_label)
        self.header.toggled.connect(self._on_toggle)
        outer.addWidget(self.header)

        self.body = QWidget()
        self.body.setObjectName("CardBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(8)
        outer.addWidget(self.body)

        self._on_toggle(self.header.isChecked())

    def _on_toggle(self, expanded: bool) -> None:
        self.body.setVisible(expanded)
        self.arrow_label.setText("\u25be" if expanded else "\u25b8")
        self.setProperty("collapsed", "false" if expanded else "true")
        self.style().unpolish(self)
        self.style().polish(self)

    def add(self, widget: QWidget) -> None:
        self.body_layout.addWidget(widget)

    def add_layout(self, layout) -> None:
        self.body_layout.addLayout(layout)

    def row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.body_layout.addLayout(row)
        return row


def section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("SectionLabel")
    label.setProperty("i18nUpper", True)
    return label


class Lcd(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Lcd")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

    def add(self, widget: QWidget) -> None:
        self.layout().addWidget(widget)

    def add_layout(self, layout) -> None:
        self.layout().addLayout(layout)


class LedPill(QLabel):
    def __init__(self, text: str = "", state: str = "off", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setObjectName("LedPill")
        self.setAlignment(Qt.AlignCenter)
        self.set_state(state)

    def set_state(self, state: str) -> None:
        self.setProperty("state", state)
        self.style().unpolish(self)
        self.style().polish(self)


class BigReadout(QLabel):
    def __init__(self, placeholder: str = "---.------ MHz", parent: QWidget | None = None):
        super().__init__(placeholder, parent)
        self.setObjectName("BigReadout")
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)


class Segmented(QWidget):
    changed = Signal(str)

    def __init__(
        self,
        options: Iterable[tuple[str, str]],
        exclusive: bool = True,
        columns: int = 0,
        parent: QWidget | None = None,
        style: str = "MatrixBtn",
    ):
        super().__init__(parent)
        self.setObjectName("Segmented")
        self._columns = columns
        if columns:
            grid = QGridLayout(self)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(4)
            grid.setVerticalSpacing(4)
            layout = grid
        else:
            row = QHBoxLayout(self)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            layout = row
        self._group = QButtonGroup(self)
        self._group.setExclusive(exclusive)
        self._buttons: dict[str, QPushButton] = {}
        for index, (value, text) in enumerate(options):
            button = QPushButton(text)
            button.setObjectName(style)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            if style == "MatrixBtn":
                button.setMinimumWidth(34)
            elif style == "TopbarSwitch":
                button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            else:
                button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            button.clicked.connect(lambda _=False, v=value: self._emit(v))
            self._group.addButton(button)
            self._buttons[value] = button
            if columns:
                layout.addWidget(button, index // columns, index % columns)
            else:
                layout.addWidget(button)
        if not columns:
            layout.addStretch(1)

    def _emit(self, value: str) -> None:
        self.changed.emit(value)

    def set_enabled(self, value: bool) -> None:
        for button in self._buttons.values():
            button.setEnabled(value)

    def set_current(self, value: str, block: bool = True) -> None:
        button = self._buttons.get(value)
        if button is None:
            for key, candidate in self._buttons.items():
                if key.lower() == str(value).lower():
                    button = candidate
                    break
        if button is None:
            return
        was = self.blockSignals(True)
        previous = self._group.exclusive()
        self._group.setExclusive(True)
        button.setChecked(True)
        self._group.setExclusive(previous)
        self.blockSignals(was)


class ToggleRow(QWidget):
    changed = Signal(bool)

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.label = QLabel(text)
        self.label.setObjectName("Muted")
        self.button = Rocker()
        self.button.toggled.connect(self.changed.emit)
        row.addWidget(self.label, 1)
        row.addWidget(self.button, 0, Qt.AlignRight)

    def set_checked(self, value: bool) -> None:
        self.button.setChecked(bool(value), emit=False)


class Chip(QPushButton):
    def __init__(self, label: str, with_bar: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Chip")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(0)
        self.label = QLabel(label)
        self.label.setObjectName("ChipLabel")
        self.value = QLabel("--")
        self.value.setObjectName("ChipValue")
        for widget in (self.label, self.value):
            widget.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.label)
        layout.addWidget(self.value)
        self.bar = None
        if with_bar:
            from PySide6.QtWidgets import QProgressBar

            self.bar = QProgressBar()
            self.bar.setObjectName("ChipBar")
            self.bar.setRange(0, 100)
            self.bar.setTextVisible(False)
            self.bar.setFixedHeight(4)
            self.bar.setAttribute(Qt.WA_TransparentForMouseEvents)
            layout.addWidget(self.bar)

    def set_value(self, text: str) -> None:
        self.value.setText(text)

    def set_indicator(self, fraction: float) -> None:
        if self.bar is not None:
            self.bar.setValue(int(max(0.0, min(1.0, fraction)) * 100))


class LedDot(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(10, 10)
        self._on = False
        self._color: str | None = None

    def set_state(self, on: bool, color: str | None = None) -> None:
        self._on = bool(on)
        self._color = color
        self.update()

    def paintEvent(self, event) -> None:
        t = current_theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        if self._on:
            p.setBrush(QColor(self._color or (t.good if t else "#35d07f")))
        else:
            p.setBrush(QColor(t.led_idle if t else "#43474f"))
        p.drawEllipse(1, 1, self.width() - 2, self.height() - 2)
        p.end()


class Rocker(QWidget):
    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent: QWidget | None = None, mini: bool = False):
        super().__init__(parent)
        size = (26, 15) if mini else (36, 20)
        self.setFixedSize(*size)
        self.setCursor(Qt.PointingHandCursor)
        self._checked = bool(checked)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, value: bool, emit: bool = True) -> None:
        value = bool(value)
        if value != self._checked:
            self._checked = value
            self.update()
            if emit:
                self.toggled.emit(value)

    def mousePressEvent(self, event) -> None:
        self.setChecked(not self._checked)

    def paintEvent(self, event) -> None:
        t = current_theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        if self._checked:
            track = QColor(t.accent if t else "#3fc6ff")
        else:
            track = QColor(t.surface3 if t else "#26282d")
        p.setBrush(track)
        p.drawRoundedRect(QRect(0, 0, self.width(), self.height()), self.height() / 2, self.height() / 2)
        diameter = self.height() - 4
        x = self.width() - diameter - 2 if self._checked else 2
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRect(x, 2, diameter, diameter))
        p.end()


class Knob(QWidget):
    stepped = Signal(int)

    def __init__(self, size: int = 96, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setCursor(Qt.OpenHandCursor)
        self._angle = 0.0
        self._last_y: float | None = None
        self._accumulated = 0.0

    def wheelEvent(self, event) -> None:
        steps = event.angleDelta().y() / 120
        if steps:
            event.accept()
            self._angle = (self._angle + steps * 15) % 360
            self.update()
            self.stepped.emit(int(steps))

    def mousePressEvent(self, event) -> None:
        self._last_y = event.position().y()
        self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:
        if self._last_y is None:
            return
        dy = event.position().y() - self._last_y
        self._last_y = event.position().y()
        self._apply_delta(dy)

    def _apply_delta(self, dy: float) -> None:
        self._angle = (self._angle + dy) % 360
        self._accumulated += dy
        while abs(self._accumulated) >= 10:
            if self._accumulated > 0:
                self._accumulated -= 10
                step = -1
            else:
                self._accumulated += 10
                step = 1
            self.stepped.emit(step)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        self._last_y = None
        self.setCursor(Qt.OpenHandCursor)

    def paintEvent(self, event) -> None:
        t = current_theme()
        accent = QColor(t.accent if t else "#3fc6ff")
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height())
        rect = QRect(3, 3, side - 6, side - 6)

        outer = QLinearGradient(0, rect.top(), 0, rect.bottom())
        outer.setColorAt(0.0, QColor("#3a3d42"))
        outer.setColorAt(1.0, QColor("#101113"))
        p.setPen(QPen(QColor("#050505"), 1))
        p.setBrush(outer)
        p.drawEllipse(rect)

        for i in range(24):
            p.save()
            p.translate(rect.center())
            p.rotate(i * 15)
            p.setPen(QPen(QColor("#2a2d31") if i % 2 else QColor("#4a4e55"), 1))
            p.drawLine(0, -rect.height() // 2 + 2, 0, -rect.height() // 2 + 6)
            p.restore()

        face = rect.adjusted(12, 12, -12, -12)
        grad = QRadialGradient(face.center().x() - 6, face.center().y() - 6, face.width())
        grad.setColorAt(0.0, QColor("#4a4e55"))
        grad.setColorAt(1.0, QColor("#0e0f11"))
        p.setPen(QPen(QColor("#000000"), 1))
        p.setBrush(grad)
        p.drawEllipse(face)

        p.save()
        p.translate(rect.center())
        p.rotate(self._angle)
        p.setPen(QPen(accent, 3, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(0, -rect.height() // 2 + 7, 0, -face.height() // 2 + 2)
        p.restore()
        p.end()


class SliderRow(QWidget):
    changed = Signal(int)

    def __init__(self, minimum: int, maximum: int, parent: QWidget | None = None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.value_label = QLabel("--")
        self.value_label.setObjectName("ReadoutChip")
        self.value_label.setMinimumWidth(34)
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.slider.valueChanged.connect(self._on_change)
        row.addWidget(self.slider, 1)
        row.addWidget(self.value_label)

    def _on_change(self, value: int) -> None:
        self.value_label.setText(str(value))
        self.changed.emit(value)

    def set_value(self, value: int) -> None:
        was = self.slider.blockSignals(True)
        self.slider.setValue(int(value))
        self.value_label.setText(str(int(value)))
        self.slider.blockSignals(was)


class SmeterBar(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumHeight(10)
        self.setMaximumHeight(10)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._dbm: int | None = None
        self._open: bool | None = None
        self._t = None

    def set_theme(self, theme) -> None:
        self._t = theme
        self.update()

    def set_reading(self, dbm: int | None, squelch_open: bool | None) -> None:
        self._dbm = dbm
        self._open = squelch_open
        self.update()

    def paintEvent(self, event) -> None:
        t = self._t or current_theme()
        if t is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        segments = 25
        gap = 2
        seg_w = (self.width() - gap * (segments - 1)) / segments
        floor, ceiling = -120, 0
        filled = 0
        if self._dbm is not None:
            ratio = max(0.0, min(1.0, (self._dbm - floor) / (ceiling - floor)))
            filled = round(ratio * segments)
        p.setPen(Qt.NoPen)
        for i in range(segments):
            x = i * (seg_w + gap)
            seg_rect = QRect(int(x), 0, max(1, int(seg_w)), self.height())
            if i < filled:
                frac = i / (segments - 1)
                if frac > 0.83:
                    color = QColor(t.bad)
                elif frac > 0.66:
                    color = QColor(t.amber)
                else:
                    color = QColor(t.good)
            else:
                color = QColor(t.surface2)
            p.setBrush(color)
            p.drawRoundedRect(seg_rect, 1, 1)
        p.end()


class Sparkline(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumHeight(90)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._values: list[int] = []
        self._t = None

    def set_theme(self, theme) -> None:
        self._t = theme
        self.update()

    def set_values(self, values: list[int]) -> None:
        self._values = list(values)
        self.update()

    def paintEvent(self, event) -> None:
        if self._t is None:
            return
        t = self._t
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 1, -1, -1)
        p.setPen(QPen(QColor(t.border), 1))
        p.setBrush(QColor(t.surface3))
        p.drawRoundedRect(rect, 4, 4)
        inner = rect.adjusted(4, 4, -4, -4)
        if len(self._values) < 2:
            p.setPen(QColor(t.muted))
            p.drawText(inner, Qt.AlignCenter, "no scope data")
            p.end()
            return

        floor, ceiling = -120, 0
        count = len(self._values)
        step = inner.width() / (count - 1)
        points = []
        for i, value in enumerate(self._values):
            ratio = max(0.0, min(1.0, (value - floor) / (ceiling - floor)))
            x = inner.left() + i * step
            y = inner.bottom() - ratio * inner.height()
            points.append((x, y))


        path = QPainterPath()
        path.moveTo(points[0][0], inner.bottom())
        for x, y in points:
            path.lineTo(x, y)
        path.lineTo(points[-1][0], inner.bottom())
        path.closeSubpath()
        gradient = QLinearGradient(0, inner.top(), 0, inner.bottom())
        gradient.setColorAt(0.0, QColor(t.accent))
        gradient.setColorAt(1.0, QColor(t.surface3))
        p.setPen(Qt.NoPen)
        p.setBrush(gradient)
        p.drawPath(path)

        p.setPen(QPen(QColor(t.accent), 2))
        for i in range(1, len(points)):
            p.drawLine(int(points[i - 1][0]), int(points[i - 1][1]), int(points[i][0]), int(points[i][1]))
        p.end()

