"""Página Acerca de — versión, licencia, créditos."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QLabel, QVBoxLayout, QWidget

from ... import __version__
from ..i18n.tr import register_retranslatable, tr


class AboutPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)

        self._title = QLabel()
        self._title.setStyleSheet("font-size: 18pt; font-weight: 700;")
        root.addWidget(self._title)

        form = QFormLayout()
        self._lbl_version_caption = QLabel()
        self._lbl_version_value = QLabel(__version__)
        self._lbl_license_caption = QLabel()
        self._lbl_license_value = QLabel("Apache-2.0")
        form.addRow(self._lbl_version_caption, self._lbl_version_value)
        form.addRow(self._lbl_license_caption, self._lbl_license_value)
        root.addLayout(form)

        self._lbl_credits_title = QLabel()
        self._lbl_credits_title.setStyleSheet("font-weight: 600; margin-top: 12px;")
        self._lbl_credits_body = QLabel()
        self._lbl_credits_body.setWordWrap(True)
        self._lbl_credits_body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self._lbl_credits_title)
        root.addWidget(self._lbl_credits_body)

        root.addStretch(1)
        register_retranslatable(self.retranslate)
        self.retranslate()

    def retranslate(self) -> None:
        self._title.setText(tr("about.title"))
        self._lbl_version_caption.setText(tr("about.version"))
        self._lbl_license_caption.setText(tr("about.license"))
        self._lbl_credits_title.setText(tr("about.credits"))
        self._lbl_credits_body.setText(tr("about.credits.body"))
