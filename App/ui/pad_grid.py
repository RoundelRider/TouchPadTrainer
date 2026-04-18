"""
ui.pad_grid
~~~~~~~~~~~
Reusable 4×4 capacitive-pad grid widget.

Used in three places:
  - TestPanelWidget  : live colour mirroring during a test run
  - ResultsViewWidget: RT-band heatmap after a session
  - ConfigEditorWidget: pad selector (click to activate, right-click = faulty)

PadCell
-------
A single square cell that paints itself with a rounded-rect in one of four
visual states: idle, active (any colour), faulty (grey strikethrough), or
selected (blue tint, used by the config editor).

PadGridWidget
-------------
A 4×4 grid of PadCell widgets.  Provides a clean API so callers never
need to access individual cells directly.
"""

from __future__ import annotations

from PyQt6.QtCore    import Qt, QSize, pyqtSignal
from PyQt6.QtGui     import (QPainter, QColor, QBrush, QPen,
                              QFont, QPainterPath)
from PyQt6.QtWidgets import QWidget, QGridLayout, QSizePolicy

# Arduino LED colour codes → HTML colours
_COLOR_MAP: dict[int, str] = {
    0: "#FFFFFF",   # white
    1: "#00C853",   # green
    2: "#F44336",   # red
}

_IDLE_COLOR    = "#E0E0E0"
_IDLE_BORDER   = "#BDBDBD"
_ACTIVE_BORDER = "#212121"
_FAULTY_COLOR  = "#B0B0B0"
_FAULTY_BORDER = "#909090"
_SELECTED_COLOR  = "#90CAF9"   # light-blue for config-editor selection
_SELECTED_BORDER = "#1565C0"


class PadCell(QWidget):
    """
    A single rounded-square pad cell.

    Signals
    -------
    left_clicked(pad_index)   : emitted on left mouse-button release
    right_clicked(pad_index)  : emitted on right mouse-button release
    """

    left_clicked  = pyqtSignal(int)
    right_clicked = pyqtSignal(int)

    def __init__(self, pad_index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._index    = pad_index
        self._color    = QColor(_IDLE_COLOR)
        self._border   = QColor(_IDLE_BORDER)
        self._active   = False
        self._faulty   = False
        self._selected = False

        self.setMinimumSize(44, 44)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)

    # ------------------------------------------------------------------
    # State setters
    # ------------------------------------------------------------------

    def set_active(self, hex_color: str) -> None:
        """Light the pad in *hex_color*."""
        self._color    = QColor(hex_color)
        self._border   = QColor(_ACTIVE_BORDER)
        self._active   = True
        self._faulty   = False
        self.update()

    def set_idle(self) -> None:
        """Return to the unlit idle state."""
        self._color    = QColor(_IDLE_COLOR)
        self._border   = QColor(_IDLE_BORDER)
        self._active   = False
        self.update()

    def set_faulty(self, faulty: bool) -> None:
        """Mark or unmark the pad as faulty (rendered with an X)."""
        self._faulty = faulty
        self.update()

    def set_selected(self, selected: bool) -> None:
        """Highlight the pad as selected (config editor use)."""
        self._selected = selected
        self.update()

    @property
    def is_selected(self) -> bool:
        return self._selected

    @property
    def is_faulty(self) -> bool:
        return self._faulty

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect().adjusted(3, 3, -3, -3)

        # Choose fill and border colours
        if self._faulty:
            fill   = QColor(_FAULTY_COLOR)
            border = QColor(_FAULTY_BORDER)
        elif self._selected and not self._active:
            fill   = QColor(_SELECTED_COLOR)
            border = QColor(_SELECTED_BORDER)
        elif self._active:
            fill   = self._color
            border = self._border
        else:
            fill   = QColor(_IDLE_COLOR)
            border = QColor(_IDLE_BORDER)

        p.setBrush(QBrush(fill))
        p.setPen(QPen(border, 1.5))
        p.drawRoundedRect(rect, 9, 9)

        # Label text
        if self._faulty:
            p.setPen(QColor("#555555"))
            font = QFont()
            font.setPointSize(9)
            font.setBold(True)
            p.setFont(font)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "✕")
        else:
            # Contrast: dark text on light pad, light text on dark/vivid pad
            luma = (fill.red() * 299 + fill.green() * 587 +
                    fill.blue() * 114) / 1000
            text_color = QColor("#111111") if luma > 128 else QColor("#FFFFFF")
            p.setPen(text_color)
            font = QFont()
            font.setPointSize(9)
            font.setBold(True)
            p.setFont(font)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                       str(self._index + 1))

    # ------------------------------------------------------------------
    # Mouse events
    # ------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        # Accept here so release fires on this widget
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.left_clicked.emit(self._index)
        elif event.button() == Qt.MouseButton.RightButton:
            self.right_clicked.emit(self._index)
        event.accept()

    def sizeHint(self) -> QSize:
        return QSize(52, 52)


class PadGridWidget(QWidget):
    """
    A 4×4 grid of PadCell widgets representing one physical panel.

    Signals
    -------
    pad_left_clicked(pad_index)   : forwarded from the child cell
    pad_right_clicked(pad_index)  : forwarded from the child cell
    """

    pad_left_clicked  = pyqtSignal(int)
    pad_right_clicked = pyqtSignal(int)

    def __init__(self, panel_index: int = 0,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._panel = panel_index
        self._cells: list[PadCell] = []
        self._build_grid()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_grid(self) -> None:
        layout = QGridLayout(self)
        layout.setSpacing(5)
        layout.setContentsMargins(4, 4, 4, 4)
        for row in range(4):
            for col in range(4):
                idx  = row * 4 + col
                cell = PadCell(idx, self)
                cell.left_clicked.connect(self.pad_left_clicked)
                cell.right_clicked.connect(self.pad_right_clicked)
                self._cells.append(cell)
                layout.addWidget(cell, row, col)

    # ------------------------------------------------------------------
    # Public API — lighting
    # ------------------------------------------------------------------

    def light_pad(self, pad: int, color_code: int) -> None:
        """
        Light pad *pad* using an Arduino colour code.

        Parameters
        ----------
        pad        : 0-based pad index (0–15)
        color_code : 0 = white, 1 = green, 2 = red
        """
        if 0 <= pad < 16:
            self._cells[pad].set_active(
                _COLOR_MAP.get(color_code, "#FFFFFF"))

    def light_pad_hex(self, pad: int, hex_color: str) -> None:
        """Light pad *pad* with an arbitrary HTML hex colour."""
        if 0 <= pad < 16:
            self._cells[pad].set_active(hex_color)

    def clear_pad(self, pad: int) -> None:
        """Return pad *pad* to the idle (unlit) state."""
        if 0 <= pad < 16:
            self._cells[pad].set_idle()

    def clear_all(self) -> None:
        """Return all 16 pads to the idle state."""
        for cell in self._cells:
            cell.set_idle()

    # ------------------------------------------------------------------
    # Public API — state flags
    # ------------------------------------------------------------------

    def set_faulty(self, pad: int, faulty: bool) -> None:
        if 0 <= pad < 16:
            self._cells[pad].set_faulty(faulty)

    def set_selected(self, pad: int, selected: bool) -> None:
        if 0 <= pad < 16:
            self._cells[pad].set_selected(selected)

    def is_selected(self, pad: int) -> bool:
        return 0 <= pad < 16 and self._cells[pad].is_selected

    def is_faulty(self, pad: int) -> bool:
        return 0 <= pad < 16 and self._cells[pad].is_faulty

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def panel_index(self) -> int:
        return self._panel

    def cells(self) -> list[PadCell]:
        """Direct access to the cell list (e.g. for config editor mouse events)."""
        return self._cells
