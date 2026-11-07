"""The live preview, including dragging a blur box."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from .style import ACCENT, INK


class PreviewWidget(QWidget):
    boxDrawn = Signal(list)
    boxCleared = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._image: QImage | None = None
        self._box: list[float] | None = None
        self._drag_start: QPointF | None = None
        self._drag_current: QPointF | None = None
        self.setMinimumSize(480, 270)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

    # ------------------------------------------------------------------ inputs
    def set_image(self, image: QImage) -> None:
        self._image = image
        self.update()

    def set_box(self, box: list[float] | None) -> None:
        self._box = box
        self.update()

    # -------------------------------------------------------------------- paint
    def _image_rect(self) -> QRectF:
        area = QRectF(self.rect())
        if self._image is None or self._image.isNull():
            return area
        iw, ih = self._image.width(), self._image.height()
        if iw <= 0 or ih <= 0:
            return area
        scale = min(area.width() / iw, area.height() / ih)
        w, h = iw * scale, ih * scale
        return QRectF(area.center().x() - w / 2, area.center().y() - h / 2, w, h)

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), QColor(INK))
        target = self._image_rect()
        if self._image is not None and not self._image.isNull():
            painter.drawImage(target, self._image)

        # frame edge
        painter.setPen(QPen(QColor("#2b2838"), 1))
        painter.drawRect(target.adjusted(0, 0, -1, -1))

        box = self._box
        if self._drag_start is not None and self._drag_current is not None:
            box = self._normalised_box(self._drag_start, self._drag_current)
        if box is not None:
            r = QRectF(
                target.x() + box[0] * target.width(),
                target.y() + box[1] * target.height(),
                box[2] * target.width(),
                box[3] * target.height(),
            )
            painter.setPen(QPen(QColor(ACCENT), 2, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(124, 92, 246, 38))
            painter.drawRect(r)
            painter.setBrush(QColor(ACCENT))
            for point in (r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight()):
                painter.drawEllipse(point, 4.0, 4.0)
        painter.end()

    # -------------------------------------------------------------------- mouse
    @staticmethod
    def _normalised_box(a: QPointF, b: QPointF) -> list[float]:
        x0, x1 = sorted((a.x(), b.x()))
        y0, y1 = sorted((a.y(), b.y()))
        return [x0, y0, max(0.0, x1 - x0), max(0.0, y1 - y0)]

    def _clamp_to_image(self, pos: QPointF) -> QPointF:
        target = self._image_rect()
        if target.width() <= 0 or target.height() <= 0:
            return pos
        x = min(max(pos.x(), target.left()), target.right())
        y = min(max(pos.y(), target.top()), target.bottom())
        return QPointF((x - target.left()) / target.width(), (y - target.top()) / target.height())

    def mousePressEvent(self, event) -> None:  # noqa: N802, ANN001
        if self._image is None:
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.boxCleared.emit()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = self._clamp_to_image(event.position())
            self._drag_current = self._drag_start
            self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802, ANN001
        if self._drag_start is None:
            return
        self._drag_current = self._clamp_to_image(event.position())
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802, ANN001
        if self._drag_start is None or event.button() != Qt.MouseButton.LeftButton:
            return
        end = self._clamp_to_image(event.position())
        box = self._normalised_box(self._drag_start, end)
        self._drag_start = None
        self._drag_current = None
        if box[2] > 0.02 and box[3] > 0.02:
            self._box = box
            self.boxDrawn.emit(box)
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802, ANN001
        self.boxCleared.emit()
