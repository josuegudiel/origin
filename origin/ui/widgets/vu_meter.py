"""Barra VU horizontal con peak-hold suave. Recibe RMS por `set_level()`."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QTimer
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QSizePolicy, QWidget


class VuMeter(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._level = 0.0          # 0..1 nivel actual amortiguado
        self._raw = 0.0            # último RMS recibido
        self._peak = 0.0           # peak-hold con caída
        self.setMinimumHeight(24)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._timer = QTimer(self)
        self._timer.setInterval(33)  # ~30Hz
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_level(self, rms: float) -> None:
        # rms ~0.001..0.5 típico para voz. Mapeo logarítmico para que sea visualmente útil.
        norm = min(1.0, max(0.0, rms * 3.0))
        self._raw = norm

    def _tick(self) -> None:
        # Ataque rápido, release lento.
        target = self._raw
        if target > self._level:
            self._level = self._level + (target - self._level) * 0.6
        else:
            self._level = max(0.0, self._level - 0.03)
        if self._level > self._peak:
            self._peak = self._level
        else:
            self._peak = max(0.0, self._peak - 0.01)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        # Fondo
        p.fillRect(rect, QColor(30, 30, 35))
        # Nivel
        bar = QRectF(
            rect.left(),
            rect.top(),
            rect.width() * self._level,
            rect.height(),
        )
        if self._level > 0.9:
            color = QColor(220, 60, 60)
        elif self._level > 0.7:
            color = QColor(220, 180, 50)
        else:
            color = QColor(60, 180, 80)
        p.fillRect(bar, color)
        # Peak hold (linea fina)
        if self._peak > 0.0:
            peak_x = int(rect.left() + rect.width() * self._peak)
            p.setPen(QColor(255, 255, 255, 180))
            p.drawLine(peak_x, rect.top(), peak_x, rect.bottom())
        p.setPen(QColor(100, 100, 110))
        p.drawRect(rect)
        p.end()
        # Evitar warning unused
        _ = event
