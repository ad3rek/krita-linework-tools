# SPDX-License-Identifier: GPL-3.0-or-later
"""Compact sections using the current Krita/Qt style and palette."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QToolButton, QVBoxLayout, QHBoxLayout, QFrame, QSizePolicy


class OptionsSection(QWidget):
    def __init__(self, title, expanded=True):
        super().__init__()
        self.header = QToolButton(self)
        self.header.setText(title)
        self.title = title
        self.expanded = expanded
        self.header.setAutoRaise(True)
        self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.header.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        font = self.header.font(); font.setBold(True); self.header.setFont(font)
        self.header.setAccessibleName(title)
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0); header_row.setSpacing(8)
        header_row.addWidget(self.header)
        separator = QFrame(self)
        separator.setFrameShape(QFrame.HLine); separator.setFrameShadow(QFrame.Sunken)
        header_row.addWidget(separator, 1)
        self.content = QWidget(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(2)
        layout.addLayout(header_row); layout.addWidget(self.content)
        self.header.clicked.connect(lambda: self.set_expanded(not self.expanded))
        self.set_expanded(expanded)

    def set_expanded(self, expanded):
        self.expanded = expanded
        self.header.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.header.setToolTip(('Recolher ' if expanded else 'Expandir ')+self.title.lower())
        self.header.setAccessibleDescription('Expandida' if expanded else 'Recolhida')
        self.content.setVisible(expanded)
