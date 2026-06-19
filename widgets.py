"""
widgets.py — Reusable UI components: ToggleSwitch, HotkeyDialog, SettingsDialog.
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import (
    QEasingCurve, QPoint, QPropertyAnimation,
    Qt, pyqtProperty, pyqtSignal,  # type: ignore[reportAttributeAccessIssue]  # pyqtProperty: PyQt6 stub gap
)
from PyQt6.QtGui import QBrush, QColor, QPainter, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
    QPushButton, QSlider, QVBoxLayout, QWidget,
)

from theme import (
    HDR_ON, Palette, SIZE_OPTIONS, POSITION_OPTS,
    THEMES, THEME_GROUPS, get_palette, hex_to_rgb,
)

if TYPE_CHECKING:
    from settings import SettingsManager


# ═══════════════════════════════════════════════════════════════════════════════
#  ToggleSwitch
# ═══════════════════════════════════════════════════════════════════════════════
class ToggleSwitch(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, palette: Optional[Palette] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._checked    = False
        self._knob_x_val = 4.0
        self._palette    = palette or get_palette("Violet")
        self.setFixedSize(50, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._anim = QPropertyAnimation(self, b"knob_pos", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def setPalette(self, palette: Palette) -> None:  # type: ignore[override]
        self._palette = palette
        self.update()

    @pyqtProperty(float)
    def knob_pos(self) -> float:  # type: ignore[reportRedeclaration]  # Qt property getter/setter pair
        return self._knob_x_val

    @knob_pos.setter  # type: ignore[no-redef]
    def knob_pos(self, v: float) -> None:
        self._knob_x_val = v
        self.update()

    def setChecked(self, checked: bool, animate: bool = True) -> None:
        self._checked = checked
        target = 24.0 if checked else 4.0
        if animate:
            self._anim.setStartValue(self._knob_x_val)
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self._knob_x_val = target
            self.update()

    def isChecked(self) -> bool:
        return self._checked

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        new_state = not self._checked
        self.setChecked(new_state)
        self.toggled.emit(new_state)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        on_color  = QColor(self._palette.accent)
        off_color = QColor("#bcbcc8" if self._palette.is_light else "#2e2e42")
        p.setBrush(QBrush(on_color if self._checked else off_color))
        p.drawRoundedRect(self.rect().adjusted(1, 4, -1, -4), 9, 9)
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawEllipse(QPoint(int(self._knob_x_val) + 9, 13), 9, 9)
        p.end()


# ═══════════════════════════════════════════════════════════════════════════════
#  HotkeyDialog
# ═══════════════════════════════════════════════════════════════════════════════
_MOD_MAP = {
    Qt.KeyboardModifier.ControlModifier: "ctrl",
    Qt.KeyboardModifier.ShiftModifier:   "shift",
    Qt.KeyboardModifier.AltModifier:     "alt",
    Qt.KeyboardModifier.MetaModifier:    "windows",
}
_KEY_MAP = {
    Qt.Key.Key_F1:  "f1",  Qt.Key.Key_F2:  "f2",  Qt.Key.Key_F3:  "f3",
    Qt.Key.Key_F4:  "f4",  Qt.Key.Key_F5:  "f5",  Qt.Key.Key_F6:  "f6",
    Qt.Key.Key_F7:  "f7",  Qt.Key.Key_F8:  "f8",  Qt.Key.Key_F9:  "f9",
    Qt.Key.Key_F10: "f10", Qt.Key.Key_F11: "f11", Qt.Key.Key_F12: "f12",
    Qt.Key.Key_Insert: "insert", Qt.Key.Key_Delete: "delete",
    Qt.Key.Key_Home: "home", Qt.Key.Key_End: "end",
    Qt.Key.Key_PageUp: "page up", Qt.Key.Key_PageDown: "page down",
    Qt.Key.Key_Space: "space", Qt.Key.Key_Tab: "tab",
    Qt.Key.Key_Backspace: "backspace", Qt.Key.Key_Return: "enter",
    Qt.Key.Key_Up: "up", Qt.Key.Key_Down: "down",
    Qt.Key.Key_Left: "left", Qt.Key.Key_Right: "right",
}
_MODIFIER_KEYS = {
    Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt,
    Qt.Key.Key_Meta, Qt.Key.Key_Super_L, Qt.Key.Key_Super_R,
}


class HotkeyDialog(QDialog):
    def __init__(self, current_hotkey: str, parent=None,
                 palette: Optional[Palette] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Change Hotkey")
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(320)
        p = palette or get_palette("Violet")
        ar = p.accent_rgb
        bg_rgb = p.bg_rgb
        self.setStyleSheet(f"""
            QDialog {{ background: transparent; }}
            QFrame#hk_card {{
                background: rgba({bg_rgb},242);
                border: 1px solid rgba({ar},0.4);
                border-radius: 14px;
            }}
            QLabel {{ color: {p.text_pri}; background: transparent; }}
            QPushButton#hk_cancel {{
                background: transparent;
                border: 1px solid {p.hairline_strong};
                border-radius: 8px;
                color: {p.text_sec};
                font-size: 12px;
                padding: 6px 18px;
            }}
            QPushButton#hk_cancel:hover {{
                color: {p.text_pri};
                border-color: rgba({ar},0.5);
            }}
        """)
        self._combo: Optional[str] = None

        card = QFrame(self)
        card.setObjectName("hk_card")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(card)

        inner = QVBoxLayout(card)
        inner.setContentsMargins(20, 18, 20, 18)
        inner.setSpacing(14)

        title = QLabel("Change Hotkey")
        title.setStyleSheet(f"font-size:14px;font-weight:700;color:{p.text_pri};")
        inner.addWidget(title)

        self._prompt = QLabel(
            f"Current: {current_hotkey.upper()}\n\nPress a new key combination…")
        self._prompt.setStyleSheet(f"font-size:12px;color:{p.text_sec};")
        self._prompt.setWordWrap(True)
        inner.addWidget(self._prompt)

        cancel = QPushButton("Cancel")
        cancel.setObjectName("hk_cancel")
        cancel.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(cancel)
        inner.addLayout(row)

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        key = Qt.Key(event.key())
        if key == Qt.Key.Key_Escape:
            self.reject()
            return
        if key in _MODIFIER_KEYS:
            return

        mods = event.modifiers()
        parts = [v for k, v in _MOD_MAP.items() if mods & k]
        if key in _KEY_MAP:
            parts.append(_KEY_MAP[key])
        else:
            text = event.text().lower()
            if text and text.isprintable():
                parts.append(text)
            else:
                parts.append(Qt.Key(key).name.replace("Key_", "").lower())

        self._combo = "+".join(parts)
        self._prompt.setText(f"Captured: {self._combo.upper()}")
        self.accept()

    def get_combo(self) -> Optional[str]:
        return self._combo


# ═══════════════════════════════════════════════════════════════════════════════
#  SettingsDialog
# ═══════════════════════════════════════════════════════════════════════════════
class SettingsDialog(QDialog):
    def __init__(self, settings: "SettingsManager", change_hotkey_fn, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(360)

        self._settings         = settings
        self._change_hotkey_fn = change_hotkey_fn
        self._pending_hotkey   = settings.get("hotkey")

        p = get_palette(settings.get("overlay_theme"))
        self._palette = p
        ar     = p.accent_rgb
        bg_rgb = p.bg_rgb
        sr     = p.surface_rgb

        self.setStyleSheet(f"""
            QDialog {{ background: transparent; }}
            QFrame#sd_card {{
                background: rgba({bg_rgb},244);
                border: 1px solid rgba({ar},0.4);
                border-radius: 14px;
            }}
            QLabel {{ color: {p.text_pri}; background: transparent; }}
            QComboBox {{
                background: rgba({sr},0.7);
                border: 1px solid {p.hairline_strong};
                border-radius: 6px; padding: 4px 10px;
                font-size: 11px; color: {p.text_pri}; min-width: 140px;
            }}
            QComboBox:hover {{ border-color: rgba({ar},0.5); }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox::down-arrow {{
                image: none; width: 0; height: 0;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid {p.text_sec};
            }}
            QComboBox QAbstractItemView {{
                background: {p.surface};
                border: 1px solid {p.hairline_strong};
                color: {p.text_pri};
                selection-background-color: rgba({ar},0.22);
                outline: none; padding: 2px;
            }}
            QSlider::groove:horizontal {{
                height: 4px; background: {p.slider_track}; border-radius: 2px;
            }}
            QSlider::sub-page:horizontal {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                             stop:0 {p.accent_dim}, stop:1 {p.accent});
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                width: 14px; height: 14px; background: #ffffff;
                border-radius: 7px; margin: -5px 0; border: 2px solid {p.accent};
            }}
            QPushButton#sd_cancel {{
                background: transparent; border: 1px solid {p.hairline_strong};
                border-radius: 8px; color: {p.text_sec}; font-size: 12px; padding: 6px 18px;
            }}
            QPushButton#sd_cancel:hover {{
                color: {p.text_pri}; border-color: rgba({ar},0.45);
            }}
            QPushButton#sd_apply {{
                background: rgba({ar},0.20); border: 1px solid rgba({ar},0.55);
                border-radius: 8px; color: {p.accent_text}; font-size: 12px;
                padding: 6px 18px; font-weight: 600;
            }}
            QPushButton#sd_apply:hover {{ background: rgba({ar},0.32); }}
            QPushButton#sd_hotkey_btn {{
                background: transparent; border: 1px solid {p.hairline_strong};
                border-radius: 6px; color: {p.text_sec}; font-size: 11px; padding: 3px 10px;
            }}
            QPushButton#sd_hotkey_btn:hover {{
                color: {p.text_pri}; border-color: rgba({ar},0.5);
            }}
        """)

        card = QFrame(self)
        card.setObjectName("sd_card")
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(card)

        inner = QVBoxLayout(card)
        inner.setContentsMargins(20, 18, 20, 18)
        inner.setSpacing(12)

        title = QLabel("Settings")
        title.setObjectName("title_label")
        title.setStyleSheet(f"font-size:14px;font-weight:700;color:{p.text_pri};")
        inner.addWidget(title)
        inner.addWidget(self._divider(p))

        self._hotkey_val = QLabel(self._pending_hotkey.upper())
        self._hotkey_val.setStyleSheet(f"font-size:11px;color:{p.text_pri};")
        hk_btn = QPushButton("Change…")
        hk_btn.setObjectName("sd_hotkey_btn")
        hk_btn.clicked.connect(self._change_hotkey)
        inner.addLayout(self._row("Hotkey", p, self._hotkey_val, hk_btn))

        self._size_combo = QComboBox()
        for name in SIZE_OPTIONS:
            self._size_combo.addItem(name)
        cur_w = settings.get("overlay_width")
        self._size_combo.setCurrentText(
            next((n for n, v in SIZE_OPTIONS.items() if v == cur_w), "Normal"))
        inner.addLayout(self._row("Size", p, self._size_combo))

        self._theme_combo = self._build_theme_combo(settings.get("overlay_theme"), p)
        inner.addLayout(self._row("Theme", p, self._theme_combo))

        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(60, 100)
        self._opacity_slider.setValue(settings.get("overlay_opacity"))
        self._opacity_slider.setFixedWidth(120)
        self._opacity_pct = QLabel(f"{settings.get('overlay_opacity')}%")
        self._opacity_pct.setStyleSheet(
            f"font-size:11px;color:{p.text_pri};min-width:32px;")
        self._opacity_slider.valueChanged.connect(
            lambda v: self._opacity_pct.setText(f"{v}%"))
        op_row = self._row("Opacity", p, self._opacity_slider)
        op_row.addSpacing(4)
        op_row.addWidget(self._opacity_pct)
        inner.addLayout(op_row)

        self._pos_combo = QComboBox()
        for ps in POSITION_OPTS:
            self._pos_combo.addItem(ps)
        self._pos_combo.setCurrentText(settings.get("overlay_position"))
        inner.addLayout(self._row("Position", p, self._pos_combo))

        inner.addWidget(self._divider(p))

        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("sd_cancel")
        cancel_btn.clicked.connect(self.reject)
        apply_btn = QPushButton("Apply")
        apply_btn.setObjectName("sd_apply")
        apply_btn.clicked.connect(self.accept)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addSpacing(8)
        btn_row.addWidget(apply_btn)
        inner.addLayout(btn_row)

    def _build_theme_combo(self, current: str, p: Palette) -> QComboBox:
        combo = QComboBox()
        combo.setMinimumWidth(190)
        model = QStandardItemModel(combo)
        for group_name, names in THEME_GROUPS:
            header = QStandardItem(f"—  {group_name}  —")
            header.setEnabled(False)
            header.setSelectable(False)
            f = header.font(); f.setBold(True); header.setFont(f)
            header.setForeground(QColor(p.text_tert))
            model.appendRow(header)
            for name in names:
                item = QStandardItem(f"   {name}")
                item.setData(name, Qt.ItemDataRole.UserRole)
                model.appendRow(item)
        combo.setModel(model)
        # Select current theme
        for i in range(model.rowCount()):
            it = model.item(i)
            if it is not None and it.data(Qt.ItemDataRole.UserRole) == current:
                combo.setCurrentIndex(i)
                break
        return combo

    def _selected_theme(self) -> str:
        idx = self._theme_combo.currentIndex()
        item = self._theme_combo.model().item(idx)  # type: ignore[union-attr]
        if item is None:
            return self._settings.get("overlay_theme")
        name = item.data(Qt.ItemDataRole.UserRole)
        return name or self._settings.get("overlay_theme")

    @staticmethod
    def _row(label: str, p: Palette, *widgets) -> QHBoxLayout:
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet(f"font-size:11px;color:{p.text_sec};")
        row.addWidget(lbl)
        row.addStretch()
        for w in widgets:
            row.addWidget(w)
        return row

    @staticmethod
    def _divider(p: Palette) -> QFrame:
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet(f"background: {p.hairline};")
        div.setFixedHeight(1)
        return div

    def _change_hotkey(self) -> None:
        dlg = HotkeyDialog(self._pending_hotkey, self, palette=self._palette)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            combo = dlg.get_combo()
            if combo:
                self._pending_hotkey = combo
                self._hotkey_val.setText(combo.upper())

    def get_values(self) -> dict:
        return {
            "hotkey":           self._pending_hotkey,
            "overlay_width":    SIZE_OPTIONS[self._size_combo.currentText()],
            "overlay_theme":    self._selected_theme(),
            "overlay_opacity":  self._opacity_slider.value(),
            "overlay_position": self._pos_combo.currentText(),
        }
