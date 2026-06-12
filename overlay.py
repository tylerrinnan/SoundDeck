"""
overlay.py — SoundDeck floating overlay window.
"""

from __future__ import annotations
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Callable, List, Optional

from PyQt6.QtCore import (
    QEasingCurve, QEvent, QFileInfo, QObject, QPoint, QPropertyAnimation,
    QRect, Qt, QTimer, pyqtSignal,
)
from PyQt6.QtGui import QCursor, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileIconProvider, QFrame,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu,
    QProgressBar, QPushButton, QScrollArea, QSlider, QStyle, QVBoxLayout,
    QWidget, QGraphicsOpacityEffect,
)

from theme import (
    get_palette,
    build_overlay_qss, build_menu_qss, build_card_style,
    hdr_pill_style, gsync_pill_style,
)
from widgets import HotkeyDialog, SettingsDialog

if TYPE_CHECKING:
    from audio import AudioManager, AudioDevice
    from hdr import HDRManager
    from profiles import ProfileManager
    from display import DisplayManager
    from mixer import MixerManager, AudioSession
    from settings import SettingsManager
    from gsync import GSyncManager
    from caps import Registry as CapsRegistry


_com_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="com")
_com_initialized = threading.local()


def _com_thread(fn: Callable) -> None:
    """Run *fn* in a pooled thread with COM initialized (reuses threads).

    Unhandled exceptions are logged. ThreadPoolExecutor swallows them onto
    the Future, which nobody waits on — silent failure would make
    "selecting devices does nothing" undebuggable.
    """
    def _wrapper() -> None:
        if not getattr(_com_initialized, "done", False):
            import comtypes
            try:
                comtypes.CoInitialize()
            except Exception:
                pass
            _com_initialized.done = True
        try:
            fn()
        except Exception as e:
            import traceback
            print(f"[com_thread] unhandled: {e}\n{traceback.format_exc()}")
    _com_pool.submit(_wrapper)


# ═══════════════════════════════════════════════════════════════════════════════
#  Click-outside filter
# ═══════════════════════════════════════════════════════════════════════════════
class ClickOutsideFilter(QObject):
    def __init__(self, overlay: "OverlayWindow") -> None:
        super().__init__()
        self._overlay = overlay

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.MouseButtonPress:
            # Ignore clicks while a child dialog (Settings/Hotkey/QInputDialog)
            # or popup (QMenu) is up. Those windows can extend past the
            # overlay's geometry, so clicks inside them would otherwise look
            # "outside" and close the overlay underneath.
            app = QApplication.instance()
            if app is not None and (app.activeModalWidget() is not None
                                    or app.activePopupWidget() is not None):
                return False
            pos = event.globalPosition().toPoint()  # type: ignore[attr-defined]
            if self._overlay.isVisible() and not self._overlay.geometry().contains(pos):
                self._overlay.hide_overlay()
        return False


# ═══════════════════════════════════════════════════════════════════════════════
#  OverlayWindow
# ═══════════════════════════════════════════════════════════════════════════════
class OverlayWindow(QWidget):

    _refresh_ready = pyqtSignal(list, list, object, object, float, float, object, object, object, int)
    _vol_ready     = pyqtSignal(int)
    _mic_vol_ready = pyqtSignal(int)
    _peak_ready    = pyqtSignal(float, float)
    _mixer_ready   = pyqtSignal(list)
    _mute_ready    = pyqtSignal(bool, bool)
    _gsync_finish_ready = pyqtSignal(object)  # final state: bool | None

    def __init__(
        self,
        audio:            "AudioManager",
        hdr:              "HDRManager",
        profiles:         "ProfileManager",
        display:          "DisplayManager",
        mixer:            "MixerManager",
        settings:         "SettingsManager",
        gsync:            "GSyncManager",
        caps_registry:    "CapsRegistry",
        change_hotkey_fn: Optional[Callable] = None,
        profile_hotkeys_changed_fn: Optional[Callable] = None,
    ) -> None:
        super().__init__()
        self._audio            = audio
        self._hdr              = hdr
        self._profiles         = profiles
        self._display          = display
        self._mixer            = mixer
        self._settings         = settings
        self._gsync            = gsync
        self._caps_registry    = caps_registry
        self._change_hotkey_fn = change_hotkey_fn
        self._profile_hotkeys_changed_fn = profile_hotkeys_changed_fn

        self._devices: List["AudioDevice"] = []
        self._capture_devices: List["AudioDevice"] = []
        self._active_output_id:   Optional[str] = None
        self._active_comms_id:    Optional[str] = None
        self._active_profile_name: Optional[str] = profiles.get_active()
        self._dragging    = False
        self._drag_pos    = QPoint()
        self._refresh_lock = threading.Lock()  # guards background refresh
        self._user_switch_seq = 0  # incremented on user device selection

        # Fingerprints — skip widget rebuild when data hasn't changed
        self._last_device_key:   tuple = ()
        self._last_profile_key:  tuple = ()
        self._last_display_key:  tuple = ()
        self._last_mixer_key:    tuple = ()
        self._mixer_dragging:    bool  = False

        # Display state: {dev_name: (label, rates, current_rate)}
        self._display_info: dict = {}
        # HDR state: {dev_name: bool}
        self._hdr_states: dict = {}
        # G-Sync: capability is per-display (which displays NVAPI exposes),
        # but the on/off toggle is global on this driver — see gsync.py.
        self._gsync_capable: set[str] = set()
        self._gsync_global:  Optional[bool] = None  # None = unknown / not avail
        self._gsync_busy:    bool = False

        # Mixer state
        self._mixer_sessions: list = []
        self._mixer_expanded: bool = False
        # App-icon extraction: QFileIconProvider returns an exe's own embedded
        # icon on Windows. Cache QPixmaps per exe path (keyed by path) so we
        # never re-hit the shell during the 3s mixer refresh.
        self._icon_provider = QFileIconProvider()
        self._icon_cache: dict[str, QPixmap] = {}

        # Volume freeze: ignore polled / bg-refresh slider writes for a short
        # window after the user applies a volume change, so the OS has time
        # to propagate the new level before we read it back. Without this,
        # the next poll can race ahead and snap the slider back to the old
        # value the OS still reports.
        self._vol_freeze_until: float = 0.0
        self._mic_freeze_until: float = 0.0
        # Same idea for mute: an in-flight bg refresh can return with the
        # pre-click mute state and flip the button back.
        self._out_mute_freeze_until: float = 0.0
        self._mic_mute_freeze_until: float = 0.0

        # Skip the heavy bg refresh on show if one just completed — repeated
        # show/hide otherwise re-enumerates devices, HDR state, and NVAPI
        # calls every time, which blocks one COM pool thread for ~hundreds
        # of ms each round. State changes mid-window are picked up by the
        # next show after the throttle expires.
        self._last_bg_refresh_done: float = 0.0
        self._bg_refresh_throttle:  float = 0.8

        self._setup_window()
        self._setup_ui()
        self._setup_animation()
        self._outside_filter = ClickOutsideFilter(self)
        QApplication.instance().installEventFilter(self._outside_filter)  # type: ignore[union-attr]
        self._refresh_ready.connect(self._apply_bg_refresh)
        self._vol_ready.connect(self._set_volume_display)
        self._mic_vol_ready.connect(self._set_mic_volume_display)
        self._peak_ready.connect(self._set_peak_levels)
        self._mixer_ready.connect(self._apply_mixer_refresh)
        self._gsync_finish_ready.connect(self._on_gsync_finish)
        self._mute_ready.connect(self._apply_mute_state)

        # 3-second mixer auto-refresh (runs only while overlay is visible)
        self._mixer_timer = QTimer(self)
        self._mixer_timer.setInterval(3000)
        self._mixer_timer.timeout.connect(self._schedule_mixer_refresh)

        # Volume sync: poll system volume every 80 ms while visible
        self._vol_poll_timer = QTimer(self)
        self._vol_poll_timer.setInterval(80)
        self._vol_poll_timer.timeout.connect(self._poll_volume)

        # Pre-warm: fetch device data now so first open is instant
        _com_thread(self._bg_refresh)

    # ── Window setup ──────────────────────────────────────────────────────────
    def _setup_window(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        palette = get_palette(self._settings.get("overlay_theme"))
        self.setFixedWidth(self._settings.get("overlay_width"))
        self.setStyleSheet(build_overlay_qss(palette))

    # ── Fade animation ─────────────────────────────────────────────────────────
    def _setup_animation(self) -> None:
        self._opacity_fx = QGraphicsOpacityEffect(self)
        self._opacity_fx.setEnabled(False)
        self.setGraphicsEffect(self._opacity_fx)

        self._fade_in = QPropertyAnimation(self._opacity_fx, b"opacity", self)
        self._fade_in.setDuration(90)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_in.finished.connect(lambda: self._opacity_fx.setEnabled(False))

        self._fade_out = QPropertyAnimation(self._opacity_fx, b"opacity", self)
        self._fade_out.setDuration(70)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade_out.finished.connect(super().hide)

    # ── Build UI ──────────────────────────────────────────────────────────────
    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._card = QFrame(self)
        self._card.setObjectName("card")
        self._card.setStyleSheet(self._card_style())
        root.addWidget(self._card)

        inner = QVBoxLayout(self._card)
        inner.setContentsMargins(12, 10, 12, 12)
        inner.setSpacing(8)

        inner.addLayout(self._build_titlebar())

        # Output section card
        out_card, out_inner = self._build_section_card("Output")
        self._output_list = QVBoxLayout()
        self._output_list.setSpacing(2)
        out_inner.addLayout(self._output_list)
        out_inner.addLayout(self._build_volume_row(is_mic=False))
        self._output_peak = self._make_peak_meter()
        out_inner.addWidget(self._output_peak)
        inner.addWidget(out_card)

        # Microphone section card
        mic_card, mic_inner = self._build_section_card("Microphone")
        self._comms_list = QVBoxLayout()
        self._comms_list.setSpacing(2)
        mic_inner.addLayout(self._comms_list)
        mic_inner.addLayout(self._build_volume_row(is_mic=True))
        self._mic_peak = self._make_peak_meter()
        mic_inner.addWidget(self._mic_peak)
        inner.addWidget(mic_card)

        # Apps mixer (collapsible, default open)
        apps_card, apps_inner = self._build_section_card_with_toggle("Apps")
        self._mixer_container = QWidget()
        self._mixer_list = QHBoxLayout(self._mixer_container)
        self._mixer_list.setSpacing(6)
        self._mixer_list.setContentsMargins(0, 2, 0, 0)
        apps_inner.addWidget(self._mixer_container)
        self._mixer_expanded = True
        self._mixer_container.setVisible(True)
        inner.addWidget(apps_card)

        # Profiles row (no card)
        prof_box = QVBoxLayout()
        prof_box.setSpacing(4)
        prof_lbl = QLabel("Profiles")
        prof_lbl.setObjectName("section_label")
        prof_box.addWidget(prof_lbl)
        self._profiles_scroll = self._build_profiles_row()
        prof_box.addWidget(self._profiles_scroll)
        inner.addLayout(prof_box)

        # Display section card (visible only when there are rows)
        disp_card, disp_inner = self._build_section_card("Display")
        self._display_rows_layout = QVBoxLayout()
        self._display_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._display_rows_layout.setSpacing(4)
        disp_inner.addLayout(self._display_rows_layout)
        self._rate_row_widget = disp_card
        self._rate_row_widget.setVisible(False)
        inner.addWidget(self._rate_row_widget)

    def _build_titlebar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        title = QLabel("SoundDeck")
        title.setObjectName("title_label")
        sound_btn = QPushButton("\U0001f50a")  # \ud83d\udd0a
        sound_btn.setObjectName("close_btn")
        sound_btn.setFixedSize(22, 22)
        sound_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        sound_btn.setToolTip("Open Windows sound settings")
        sound_btn.clicked.connect(self._open_sound_settings)
        gear_btn = QPushButton("\u2699")
        gear_btn.setObjectName("close_btn")
        gear_btn.setFixedSize(22, 22)
        gear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        gear_btn.setToolTip("Settings")
        gear_btn.clicked.connect(self.open_settings_dialog)
        close_btn = QPushButton("\u2715")
        close_btn.setObjectName("close_btn")
        close_btn.setFixedSize(22, 22)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.hide_overlay)
        row.addWidget(title)
        row.addStretch()
        row.addWidget(sound_btn)
        row.addSpacing(2)
        row.addWidget(gear_btn)
        row.addSpacing(2)
        row.addWidget(close_btn)
        return row

    def _open_sound_settings(self) -> None:
        try:
            os.startfile("ms-settings:sound")
        except Exception:
            try:
                os.startfile("mmsys.cpl")
            except Exception as e:
                print(f"[overlay] open sound settings failed: {e}")

    def _build_section_card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("section_card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(6)
        lbl = QLabel(title)
        lbl.setObjectName("section_label")
        layout.addWidget(lbl)
        return card, layout

    def _build_section_card_with_toggle(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("section_card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(6)

        hdr = QHBoxLayout()
        lbl = QLabel(title)
        lbl.setObjectName("section_label")
        self._mixer_toggle_btn = QPushButton("\u25be")  # \u25be
        self._mixer_toggle_btn.setObjectName("mixer_toggle")
        self._mixer_toggle_btn.setFixedSize(20, 20)
        self._mixer_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mixer_toggle_btn.clicked.connect(self._toggle_mixer_section)
        hdr.addWidget(lbl)
        hdr.addStretch()
        hdr.addWidget(self._mixer_toggle_btn)
        layout.addLayout(hdr)
        return card, layout

    def _build_volume_row(self, is_mic: bool) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        mute_btn = QPushButton("\U0001f50a")
        mute_btn.setObjectName("mute_btn")
        mute_btn.setFixedSize(26, 24)
        mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        mute_btn.setProperty("muted", "false")

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)

        pct = QLabel("100%")
        pct.setObjectName("vol_pct")
        pct.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        debounce = QTimer(self)
        debounce.setSingleShot(True)
        debounce.setInterval(30)

        if is_mic:
            self._mic_slider = slider
            self._mic_pct = pct
            self._mic_mute_btn = mute_btn
            self._mic_debounce = debounce
            slider.valueChanged.connect(self._on_mic_volume_changed)
            debounce.timeout.connect(self._apply_mic_volume)
            mute_btn.clicked.connect(self._toggle_mic_mute)
            mute_btn.setToolTip("Mute microphone")
        else:
            self._vol_slider = slider
            self._vol_pct = pct
            self._mute_btn = mute_btn
            self._vol_debounce = debounce
            slider.valueChanged.connect(self._on_volume_changed)
            debounce.timeout.connect(self._apply_volume)
            mute_btn.clicked.connect(self._toggle_output_mute)
            mute_btn.setToolTip("Mute output")

        row.addWidget(mute_btn)
        row.addWidget(slider, 1)
        row.addWidget(pct)
        return row

    def _make_peak_meter(self) -> QProgressBar:
        bar = QProgressBar()
        bar.setObjectName("peak_meter")
        bar.setRange(0, 1000)
        bar.setValue(0)
        bar.setTextVisible(False)
        bar.setFixedHeight(3)
        return bar

    def _build_profiles_row(self) -> QScrollArea:
        container = QWidget()
        self._profiles_row = QHBoxLayout(container)
        self._profiles_row.setContentsMargins(0, 0, 0, 0)
        self._profiles_row.setSpacing(6)

        self._profiles_row.addStretch()

        self._add_profile_btn = QPushButton("+")
        self._add_profile_btn.setObjectName("add_profile_btn")
        self._add_profile_btn.setFixedSize(28, 26)
        self._add_profile_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_profile_btn.setToolTip("Save current settings as a new profile")
        self._add_profile_btn.clicked.connect(self._save_new_profile)
        self._profiles_row.addWidget(self._add_profile_btn)

        scroll = QScrollArea()
        scroll.setWidget(container)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedHeight(32)
        scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}"
                             "QWidget{background:transparent;}")
        return scroll

    # ══════════════════════════════════════════════════════════════════════════
    #  Settings / hotkey dialogs
    # ══════════════════════════════════════════════════════════════════════════
    def _palette(self):
        return get_palette(self._settings.get("overlay_theme"))

    def _card_style(self) -> str:
        return build_card_style(self._palette(), self._settings.get("overlay_opacity"))

    def open_settings_dialog(self) -> None:
        dlg = SettingsDialog(self._settings, self._change_hotkey_fn, parent=self)
        prev_pos = self._settings.get("overlay_position")
        if dlg.exec() == QDialog.DialogCode.Accepted:
            vals = dlg.get_values()
            with self._settings.batch():
                for k, v in vals.items():
                    self._settings.set(k, v)
                # Choosing a named anchor is an explicit placement request —
                # drop the remembered free-form spot so the anchor takes effect.
                if vals.get("overlay_position") != prev_pos:
                    self._settings.set("overlay_geometry", None)
            # Always re-register: rebinding to the same combo is a user's
            # natural way to refresh a stale OS hook (e.g. after sleep/lock).
            if self._change_hotkey_fn:
                self._change_hotkey_fn(vals["hotkey"])
            self._apply_display_settings()

    def open_hotkey_dialog(self) -> None:
        current = self._settings.get("hotkey")
        dlg = HotkeyDialog(current, parent=self, palette=self._palette())
        if dlg.exec() == QDialog.DialogCode.Accepted:
            combo = dlg.get_combo()
            if combo and self._change_hotkey_fn:
                self._change_hotkey_fn(combo)

    def _apply_display_settings(self) -> None:
        self.setFixedWidth(self._settings.get("overlay_width"))
        self.setStyleSheet(build_overlay_qss(self._palette()))
        self._card.setStyleSheet(self._card_style())
        # Re-apply HDR pill styles (palette-dependent)
        self._last_display_key = ()
        self._rebuild_display_section()
        self.adjustSize()
        self._position_on_screen()

    # ══════════════════════════════════════════════════════════════════════════
    #  Display (refresh rate + HDR)
    # ══════════════════════════════════════════════════════════════════════════
    def _rebuild_display_section(self) -> None:
        gsync_visible = bool(self._gsync_capable)
        new_key = (
            tuple(
                (n, tuple(r), c, self._hdr_states.get(n))
                for n, (_, r, c) in self._display_info.items()
            ),
            gsync_visible, self._gsync_global,
        )
        if new_key == self._last_display_key:
            return
        self._last_display_key = new_key

        self._clear_layout(self._display_rows_layout)
        per_display_labels = [
            f"\U0001f5a5  {label}"
            for dev_name, (label, rates, _) in self._display_info.items()
            if len(rates) > 1 or dev_name in self._hdr_states
        ]
        all_labels = list(per_display_labels)
        if gsync_visible:
            all_labels.append("\U0001f3ae  Global")  # game-controller emoji
        label_w = 0
        if all_labels:
            fm = self.fontMetrics()
            label_w = max(fm.horizontalAdvance(t) for t in all_labels)
        has_rows = False

        # Global row: single G-SYNC pill controlling NVAPI DRS VRR_MODE.
        if gsync_visible:
            has_rows = True
            row = QHBoxLayout(); row.setSpacing(8)
            lbl = QLabel("\U0001f3ae  Global")
            lbl.setObjectName("subtle_label")
            lbl.setMinimumWidth(label_w)
            row.addWidget(lbl)
            row.addStretch()
            gs_on = bool(self._gsync_global)
            gpill = QPushButton("G-SYNC")
            gpill.setFixedHeight(18)
            gpill.setCursor(Qt.CursorShape.PointingHandCursor)
            gpill.setStyleSheet(gsync_pill_style(self._palette(), gs_on))
            gpill.setToolTip(
                "Toggle G-Sync (Adaptive Sync) globally — fullscreen + windowed.\n"
                "Public NVAPI does not expose a durable per-display toggle on "
                "GeForce drivers, so this acts as a global switch."
            )
            gpill.clicked.connect(self._on_gsync_global_toggled)
            row.addWidget(gpill)
            self._display_rows_layout.addLayout(row)

        for dev_name, (label, rates, current) in self._display_info.items():
            has_multi = len(rates) > 1
            has_hdr   = dev_name in self._hdr_states
            if not has_multi and not has_hdr:
                continue
            has_rows = True
            row = QHBoxLayout()
            row.setSpacing(8)
            lbl = QLabel(f"\U0001f5a5  {label}")
            lbl.setObjectName("subtle_label")
            lbl.setMinimumWidth(label_w)
            row.addWidget(lbl)
            if has_multi:
                combo = QComboBox()
                combo.setObjectName("rate_combo")
                combo.setCursor(Qt.CursorShape.PointingHandCursor)
                for hz in sorted(rates, reverse=True):
                    combo.addItem(f"{hz} Hz", hz)
                idx = combo.findData(current)
                if idx >= 0:
                    combo.blockSignals(True)
                    combo.setCurrentIndex(idx)
                    combo.blockSignals(False)
                combo.currentIndexChanged.connect(
                    lambda _, c=combo, n=dev_name: self._select_refresh_rate(c.currentData(), n)
                )
                row.addWidget(combo)
            row.addStretch()
            if has_hdr:
                hdr_on = self._hdr_states[dev_name]
                pill = QPushButton("HDR")
                pill.setFixedHeight(18)
                pill.setCursor(Qt.CursorShape.PointingHandCursor)
                pill.setStyleSheet(hdr_pill_style(self._palette(), hdr_on))
                pill.setToolTip("Toggle HDR")
                pill.clicked.connect(
                    lambda _, n=dev_name, p=pill: self._on_display_hdr_toggled(n, p)
                )
                row.addWidget(pill)
            self._display_rows_layout.addLayout(row)

        self._rate_row_widget.setVisible(has_rows)

    def _select_refresh_rate(self, hz: int, dev_name: str) -> None:
        if dev_name in self._display_info:
            label, rates, _ = self._display_info[dev_name]
            self._display_info[dev_name] = (label, rates, hz)
        self._last_display_key = ()
        self._rebuild_display_section()

        primary = next(iter(self._display_info), None)
        if self._active_profile_name and dev_name == primary:
            p = self._profiles.get(self._active_profile_name)
            if p:
                p.refresh_rate = hz
                self._profiles.add_or_update(p)

        # The combo updates immediately but ChangeDisplaySettingsExW takes
        # 1-3s and the screen blanks during the flip. Show a wait cursor on
        # the overlay so the user has in-app confirmation that the click
        # registered, not just the eventual screen change.
        self.setCursor(Qt.CursorShape.WaitCursor)
        QTimer.singleShot(1500, self.unsetCursor)

        def _do() -> None:
            ok = self._display.set_refresh_rate(hz, dev_name)
            if not ok:
                QTimer.singleShot(300, lambda: _com_thread(self._bg_refresh))

        _com_thread(_do)

    # ══════════════════════════════════════════════════════════════════════════
    #  Mixer
    # ══════════════════════════════════════════════════════════════════════════
    def _toggle_mixer_section(self) -> None:
        self._mixer_expanded = not self._mixer_expanded
        self._mixer_container.setVisible(self._mixer_expanded)
        self._mixer_toggle_btn.setText("\u25be" if self._mixer_expanded else "\u25b8")
        if self._mixer_expanded:
            self._rebuild_mixer_list(self._mixer_sessions)
            self._mixer_timer.start()
        else:
            self._mixer_timer.stop()
        self.adjustSize()

    def _schedule_mixer_refresh(self) -> None:
        """Fire a background mixer refresh if no other refresh is in flight."""
        def _do() -> None:
            if not self._refresh_lock.acquire(blocking=False):
                return
            try:
                sessions = self._mixer.get_sessions()
            except Exception:
                sessions = []
            finally:
                self._refresh_lock.release()
            self._mixer_ready.emit(sessions)
        _com_thread(_do)

    def _apply_mixer_refresh(self, sessions: list) -> None:
        self._mixer_sessions = sessions
        if self._mixer_expanded and not self._mixer_dragging:
            self._rebuild_mixer_list(sessions)

    def _rebuild_mixer_list(self, sessions: list) -> None:
        new_key = tuple((s.pid, int(s.volume * 100), s.muted) for s in sessions)
        if new_key == self._last_mixer_key:
            return
        self._last_mixer_key = new_key
        self._clear_layout(self._mixer_list)
        for session in sessions:
            self._mixer_list.addWidget(self._make_mixer_row(session))
        self._mixer_list.addStretch()

    def _app_icon(self, exe_path: str, pid: int, size: int = 20) -> QPixmap:
        """Return the app's own icon as a QPixmap (cached per exe path).
        The System row (pid 0, no exe) gets the stock volume/speaker icon."""
        key = exe_path or f"pid:{pid}"
        cached = self._icon_cache.get(key)
        if cached is not None:
            return cached
        px = QPixmap()
        if exe_path:
            try:
                icon = self._icon_provider.icon(QFileInfo(exe_path))
                if not icon.isNull():
                    px = icon.pixmap(size, size)
            except Exception:
                pass
        elif pid == 0:
            try:
                sp = QStyle.StandardPixmap.SP_MediaVolume
                icon = self.style().standardIcon(sp)
                if not icon.isNull():
                    px = icon.pixmap(size, size)
            except Exception:
                pass
        self._icon_cache[key] = px
        return px

    def _make_mixer_row(self, session) -> QWidget:
        col_widget = QWidget()
        col_widget.setFixedWidth(60)
        col = QVBoxLayout(col_widget)
        col.setContentsMargins(3, 3, 3, 3)
        col.setSpacing(3)

        icon_lbl = QLabel()
        icon_lbl.setFixedHeight(20)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        px = self._app_icon(getattr(session, "exe_path", ""), session.pid)
        if not px.isNull():
            icon_lbl.setPixmap(px)

        name_lbl = QLabel(session.name[:10])
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        name_lbl.setWordWrap(True)
        name_lbl.setObjectName("mono_label")

        slider = QSlider(Qt.Orientation.Vertical)
        slider.setRange(0, 100)
        slider.setValue(int(session.volume * 100))
        slider.setFixedHeight(72)

        pct_lbl = QLabel(f"{int(session.volume * 100)}%")
        pct_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        pct_lbl.setObjectName("vol_pct")

        mute_btn = QPushButton("\U0001f507" if session.muted else "\U0001f50a")
        mute_btn.setObjectName("close_btn")
        mute_btn.setFixedSize(22, 22)

        debounce = QTimer(col_widget)
        debounce.setSingleShot(True)
        debounce.setInterval(40)

        def on_slider_change(val: int) -> None:
            pct_lbl.setText(f"{val}%")
            debounce.start()

        pid = session.pid

        def on_debounce() -> None:
            val = slider.value()
            _com_thread(lambda: self._mixer.set_session_volume(pid, val / 100.0))

        def on_mute() -> None:
            new_muted = not session.muted
            session.muted = new_muted
            mute_btn.setText("\U0001f507" if new_muted else "\U0001f50a")
            _com_thread(lambda: self._mixer.set_session_mute(pid, new_muted))

        slider.sliderPressed.connect(lambda: setattr(self, '_mixer_dragging', True))
        slider.sliderReleased.connect(self._on_mixer_slider_released)
        slider.valueChanged.connect(on_slider_change)
        debounce.timeout.connect(on_debounce)
        mute_btn.clicked.connect(on_mute)

        col.addWidget(icon_lbl)
        col.addWidget(name_lbl)
        col.addWidget(slider, 0, Qt.AlignmentFlag.AlignHCenter)
        col.addWidget(pct_lbl)
        col.addWidget(mute_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        return col_widget

    def _on_mixer_slider_released(self) -> None:
        self._mixer_dragging = False
        self._last_mixer_key = ()

    # ══════════════════════════════════════════════════════════════════════════
    #  Refresh
    # ══════════════════════════════════════════════════════════════════════════
    def refresh(self) -> None:
        """Synchronous refresh — still available for external callers."""
        self._devices          = self._audio.get_playback_devices()
        self._capture_devices  = self._audio.get_recording_devices()
        self._active_output_id = self._audio.get_default_output_id()
        self._active_comms_id  = self._audio.get_default_comms_capture_id()
        self._last_device_key  = ()
        self._last_profile_key = ()
        self._rebuild_device_lists()
        self._refresh_volume()
        try:
            self._hdr_states = self._hdr.get_hdr_states()
        except Exception:
            pass
        self._last_display_key = ()
        self._rebuild_display_section()
        self._rebuild_profiles()

    def _rebuild_device_lists(self) -> None:
        new_key = (
            tuple(d.id for d in self._devices), self._active_output_id,
            tuple(d.id for d in self._capture_devices), self._active_comms_id,
        )
        if new_key == self._last_device_key:
            return
        self._last_device_key = new_key

        self._clear_layout(self._output_list)
        self._clear_layout(self._comms_list)

        for dev in self._devices:
            self._output_list.addWidget(
                self._make_device_row(dev, is_output=True))
        for dev in self._capture_devices:
            self._comms_list.addWidget(
                self._make_device_row(dev, is_output=False))

    def _make_device_row(self, dev: "AudioDevice", is_output: bool) -> QPushButton:
        active_id = self._active_output_id if is_output else self._active_comms_id
        is_active = dev.id == active_id

        dot   = "\u25cf" if is_active else "\u25cb"
        label = f"  {dot}  {dev.icon()}  {dev.short_name(60)}"

        btn = QPushButton(label)
        btn.setObjectName("dev_row")
        btn.setProperty("active", "true" if is_active else "false")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)

        if is_output:
            btn.clicked.connect(lambda _=False, d=dev: self._select_output(d))
        else:
            btn.clicked.connect(lambda _=False, d=dev: self._select_comms(d))
        return btn

    def _refresh_volume(self) -> None:
        if self._active_output_id:
            vol = self._audio.get_volume(self._active_output_id)
            self._set_volume_display(int(vol * 100))

    def _vol_skip_update(self) -> bool:
        return (self._vol_slider.isSliderDown()
                or self._vol_debounce.isActive()
                or time.monotonic() < self._vol_freeze_until)

    def _mic_skip_update(self) -> bool:
        return (self._mic_slider.isSliderDown()
                or self._mic_debounce.isActive()
                or time.monotonic() < self._mic_freeze_until)

    def _poll_volume(self) -> None:
        """Poll system volume, mic volume, and peak levels while visible."""
        skip_vol = self._vol_skip_update()
        skip_mic = self._mic_skip_update()
        out_id = self._active_output_id
        mic_id = self._active_comms_id
        if not out_id and not mic_id:
            return
        def _do() -> None:
            try:
                if not skip_vol and out_id:
                    self._vol_ready.emit(int(self._audio.get_volume(out_id) * 100))
                if not skip_mic and mic_id:
                    self._mic_vol_ready.emit(int(self._audio.get_volume(mic_id) * 100))
                out_peak = self._audio.get_output_peak(out_id) if out_id else 0.0
                mic_peak = self._audio.get_peak_level(mic_id) if mic_id else 0.0
                self._peak_ready.emit(out_peak, mic_peak)
            except Exception:
                pass
        _com_thread(_do)

    def _set_volume_display(self, pct: int) -> None:
        self._vol_slider.blockSignals(True)
        self._vol_slider.setValue(pct)
        self._vol_pct.setText(f"{pct}%")
        self._vol_slider.blockSignals(False)

    def _set_mic_volume_display(self, pct: int) -> None:
        self._mic_slider.blockSignals(True)
        self._mic_slider.setValue(pct)
        self._mic_pct.setText(f"{pct}%")
        self._mic_slider.blockSignals(False)

    def _on_mic_volume_changed(self, value: int) -> None:
        self._mic_pct.setText(f"{value}%")
        self._mic_debounce.start()

    def _apply_mic_volume(self) -> None:
        value = self._mic_slider.value()
        if self._active_comms_id:
            dev_id = self._active_comms_id
            _com_thread(lambda: self._audio.set_volume(dev_id, value / 100.0))
        self._mic_freeze_until = time.monotonic() + 0.25

    def _set_peak_levels(self, out_peak: float, mic_peak: float) -> None:
        self._output_peak.setValue(int(out_peak * 1000))
        self._mic_peak.setValue(int(mic_peak * 1000))

    def _set_mute_display(self, is_mic: bool, muted: bool) -> None:
        btn = self._mic_mute_btn if is_mic else self._mute_btn
        btn.setText("\U0001f507" if muted else "\U0001f50a")  # 🔇 or 🔊
        btn.setProperty("muted", "true" if muted else "false")
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def _toggle_output_mute(self) -> None:
        if not self._active_output_id:
            return
        new_muted = self._mute_btn.property("muted") != "true"
        self._set_mute_display(False, new_muted)
        dev_id = self._active_output_id
        _com_thread(lambda: self._audio.set_mute(dev_id, new_muted))
        self._out_mute_freeze_until = time.monotonic() + 0.25

    def _toggle_mic_mute(self) -> None:
        if not self._active_comms_id:
            return
        new_muted = self._mic_mute_btn.property("muted") != "true"
        self._set_mute_display(True, new_muted)
        dev_id = self._active_comms_id
        _com_thread(lambda: self._audio.set_mute(dev_id, new_muted))
        self._mic_mute_freeze_until = time.monotonic() + 0.25

    def _apply_mute_state(self, out_muted: bool, mic_muted: bool) -> None:
        now = time.monotonic()
        if now >= self._out_mute_freeze_until:
            self._set_mute_display(False, out_muted)
        if now >= self._mic_mute_freeze_until:
            self._set_mute_display(True,  mic_muted)

    def _rebuild_profiles(self) -> None:
        profiles = self._profiles.get_profiles()
        new_key = (tuple((p.name, p.hotkey) for p in profiles), self._active_profile_name)
        if new_key == self._last_profile_key:
            return
        self._last_profile_key = new_key

        while self._profiles_row.count() > 2:
            item = self._profiles_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for i, profile in enumerate(profiles):
            pill = QPushButton(profile.name)
            pill.setObjectName("profile_pill")
            is_active = profile.name == self._active_profile_name
            pill.setProperty("active", "true" if is_active else "false")
            pill.setCursor(Qt.CursorShape.PointingHandCursor)
            if profile.hotkey:
                pill.setToolTip(f"Hotkey: {profile.hotkey.upper()}")
            pill.clicked.connect(lambda _=False, n=profile.name: self._apply_profile(n))
            pill.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            pill.customContextMenuRequested.connect(
                lambda pos, n=profile.name, w=pill: self._profile_context_menu(pos, n, w))
            self._profiles_row.insertWidget(i, pill)
            pill.style().unpolish(pill)
            pill.style().polish(pill)

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                OverlayWindow._clear_layout(item.layout())

    # ══════════════════════════════════════════════════════════════════════════
    #  Interaction
    # ══════════════════════════════════════════════════════════════════════════
    def _select_output(self, dev: "AudioDevice") -> None:
        print(f"[overlay] selecting output: {dev.name} ({dev.id})")
        self._user_switch_seq += 1
        self._active_output_id = dev.id
        self._last_device_key  = ()
        self._update_active_profile()
        self._rebuild_device_lists()
        self._rebuild_profiles()

        def _do() -> None:
            try:
                self._audio.invalidate_volume_cache()
                self._audio.set_output_device(dev.id)
                vol = self._audio.get_volume(dev.id)
                self._vol_ready.emit(int(vol * 100))
            except Exception as e:
                print(f"[overlay] select_output error: {e}")

        _com_thread(_do)

    def _select_comms(self, dev: "AudioDevice") -> None:
        print(f"[overlay] selecting comms: {dev.name} ({dev.id})")
        self._user_switch_seq += 1
        self._active_comms_id = dev.id
        self._last_device_key = ()
        self._update_active_profile()
        self._rebuild_device_lists()
        self._rebuild_profiles()

        def _do() -> None:
            try:
                self._audio.set_comms_capture_device(dev.id)
                mic_vol = self._audio.get_volume(dev.id)
                self._mic_vol_ready.emit(int(mic_vol * 100))
            except Exception as e:
                print(f"[overlay] select_comms error: {e}")

        _com_thread(_do)

    def _on_volume_changed(self, value: int) -> None:
        self._vol_pct.setText(f"{value}%")
        self._vol_debounce.start()

    def _apply_volume(self) -> None:
        value = self._vol_slider.value()
        if self._active_output_id:
            dev_id = self._active_output_id
            _com_thread(lambda: self._audio.set_volume(dev_id, value / 100.0))
        self._vol_freeze_until = time.monotonic() + 0.25
        self._update_active_profile()

    def _update_active_profile(self) -> None:
        if not self._active_profile_name:
            return
        from profiles import Profile
        existing = self._profiles.get(self._active_profile_name)
        self._profiles.add_or_update(Profile(
            name             = self._active_profile_name,
            output_device_id = self._active_output_id or "",
            comms_device_id  = self._active_comms_id  or "",
            output_volume    = self._vol_slider.value() / 100.0,
            refresh_rate     = existing.refresh_rate if existing else 0,
        ))

    def _on_gsync_global_toggled(self) -> None:
        if self._gsync_busy:
            return
        current = bool(self._gsync_global)
        target  = not current
        self._gsync_busy = True
        self._gsync_global = target              # optimistic
        self._last_display_key = ()
        self._rebuild_display_section()          # instant visual feedback

        def _do() -> None:
            ok = self._gsync.set_global_enabled(target)
            try:
                state = self._gsync.is_global_enabled()
            except Exception:
                state = None
            final = state if state is not None else (target if ok else current)
            # Marshal back to UI thread via signal — QTimer.singleShot from a
            # non-Qt thread without a QObject context never fires.
            self._gsync_finish_ready.emit(final)
        _com_thread(_do)

    def _on_gsync_finish(self, final: object) -> None:
        self._gsync_busy = False
        if final != self._gsync_global:
            self._gsync_global = final  # type: ignore[assignment]
            self._last_display_key = ()
            self._rebuild_display_section()

    def _on_display_hdr_toggled(self, dev_name: str, pill: QPushButton) -> None:
        current = self._hdr_states.get(dev_name, False)
        enable  = not current
        pill.setEnabled(False)
        pill.setStyleSheet(hdr_pill_style(self._palette(), enable))

        def _do() -> None:
            ok = self._hdr.set_hdr_state(dev_name, enable)
            import time; time.sleep(0.4)
            try:
                states = self._hdr.get_hdr_states()
            except Exception:
                states = {}
            if not ok and not states:
                try:
                    import keyboard
                    keyboard.send("windows+alt+b")
                    time.sleep(0.5)
                    states = self._hdr.get_hdr_states()
                except Exception:
                    pass
            if states:
                self._hdr_states = states
            else:
                self._hdr_states[dev_name] = enable
            self._last_display_key = ()
            QTimer.singleShot(0, self._rebuild_display_section)
        _com_thread(_do)

    def _apply_profile(self, name: str) -> None:
        profile = self._profiles.get(name)
        if profile is None:
            return

        self._active_profile_name = name
        self._profiles.set_active(name)
        self._user_switch_seq += 1
        # Only mark the UI as "this is the active device" if it actually
        # exists in our current enumeration — otherwise the device row would
        # show a filled dot for a ghost that audio never bound to.
        want_out  = profile.output_device_id
        want_comm = profile.comms_device_id
        if want_out and any(d.id == want_out for d in self._devices):
            self._active_output_id = want_out
        if want_comm and any(d.id == want_comm for d in self._capture_devices):
            self._active_comms_id = want_comm
        self._last_device_key  = ()
        self._last_profile_key = ()
        self._rebuild_device_lists()
        self._set_volume_display(int(profile.output_volume * 100))
        self._rebuild_profiles()

        registry = self._caps_registry
        cap_items = list(profile.caps.items())

        def _do_apply() -> None:
            for cap_name, state in cap_items:
                cap = registry.get(cap_name)
                if cap is None:
                    print(f"[overlay] unknown capability {cap_name!r} in profile {name!r}")
                    continue
                try:
                    cap.apply(state)
                except Exception as e:
                    print(f"[overlay] {cap_name} apply error: {e}")

        _com_thread(_do_apply)

    def apply_profile_by_hotkey(self, name: str) -> None:
        """Apply a profile triggered by global hotkey (works even when overlay is hidden)."""
        self._apply_profile(name)

    def _save_new_profile(self) -> None:
        name, ok = QInputDialog.getText(
            self, "Save Profile", "Profile name:", QLineEdit.EchoMode.Normal, "")
        if not ok or not name.strip():
            return
        from profiles import Profile
        self._profiles.add_or_update(Profile(
            name             = name.strip(),
            output_device_id = self._active_output_id or "",
            comms_device_id  = self._active_comms_id  or "",
            output_volume    = self._vol_slider.value() / 100.0,
        ))
        self._active_profile_name = name.strip()
        self._profiles.set_active(name.strip())
        self._last_profile_key    = ()
        self._rebuild_profiles()

    def _profile_context_menu(self, pos: QPoint, name: str, widget: QPushButton) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(build_menu_qss(self._palette()))
        profile = self._profiles.get(name)
        set_hk_a = menu.addAction("\u2328\ufe0f  Set Hotkey")
        clear_hk_a = None
        if profile and profile.hotkey:
            clear_hk_a = menu.addAction(f"\u2715  Clear Hotkey ({profile.hotkey.upper()})")
        menu.addSeparator()
        rename_a = menu.addAction("\u270f\ufe0f  Rename")
        delete_a = menu.addAction("\U0001f5d1\ufe0f  Delete")
        action = menu.exec(widget.mapToGlobal(pos))
        if action == set_hk_a:
            current = profile.hotkey if profile else ""
            dlg = HotkeyDialog(current or "none", parent=self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                combo = dlg.get_combo()
                if combo and profile:
                    profile.hotkey = combo
                    self._profiles.add_or_update(profile)
                    self._last_profile_key = ()
                    self._rebuild_profiles()
                    if self._profile_hotkeys_changed_fn:
                        self._profile_hotkeys_changed_fn()
        elif clear_hk_a and action == clear_hk_a:
            if profile:
                profile.hotkey = ""
                self._profiles.add_or_update(profile)
                self._last_profile_key = ()
                self._rebuild_profiles()
                if self._profile_hotkeys_changed_fn:
                    self._profile_hotkeys_changed_fn()
        elif action == rename_a:
            new_name, ok = QInputDialog.getText(
                self, "Rename Profile", "New name:", QLineEdit.EchoMode.Normal, name)
            if ok and new_name.strip():
                self._profiles.rename(name, new_name.strip())
                if self._active_profile_name == name:
                    self._active_profile_name = new_name.strip()
                    self._profiles.set_active(new_name.strip())
                self._last_profile_key = ()
                self._rebuild_profiles()
                if self._profile_hotkeys_changed_fn:
                    self._profile_hotkeys_changed_fn()
        elif action == delete_a:
            self._profiles.delete(name)
            if self._active_profile_name == name:
                self._active_profile_name = None
                self._profiles.set_active(None)
            self._last_profile_key = ()
            self._rebuild_profiles()
            if self._profile_hotkeys_changed_fn:
                self._profile_hotkeys_changed_fn()

    # ══════════════════════════════════════════════════════════════════════════
    #  Show / hide / toggle
    # ══════════════════════════════════════════════════════════════════════════
    def show_overlay(self) -> None:
        self._rebuild_profiles()
        self._position_on_screen()
        self._opacity_fx.setOpacity(0.0)
        self._opacity_fx.setEnabled(True)
        super().show()
        self.raise_()
        self.activateWindow()
        self._fade_in.start()
        self._vol_poll_timer.start()
        if time.monotonic() - self._last_bg_refresh_done > self._bg_refresh_throttle:
            _com_thread(self._bg_refresh)
        if self._mixer_expanded:
            self._mixer_timer.start()

    def _bg_refresh(self) -> None:
        """Fetch all slow data off the UI thread (thread-safe via lock)."""
        if not self._refresh_lock.acquire(blocking=False):
            return
        seq = self._user_switch_seq
        try:
            devices         = self._audio.get_playback_devices()
            capture_devices = self._audio.get_recording_devices()
            output_id       = self._audio.get_default_output_id()
            comms_id        = self._audio.get_default_comms_capture_id()
            vol = self._audio.get_volume(output_id) if output_id else 1.0
            mic_vol = self._audio.get_volume(comms_id) if comms_id else 1.0
            out_muted = self._audio.get_mute(output_id) if output_id else False
            mic_muted = self._audio.get_mute(comms_id)  if comms_id  else False
            self._mute_ready.emit(out_muted, mic_muted)
            try:
                hdr_state = self._hdr.get_hdr_states()
            except Exception:
                hdr_state = {}
            try:
                display_info = {}
                for dev_name, label in self._display.get_all_displays():
                    rates   = self._display.get_available_refresh_rates(dev_name)
                    current = self._display.get_current_refresh_rate(dev_name)
                    display_info[dev_name] = (label, rates, current)
            except Exception:
                display_info = {}
            gsync_capable: set = set()
            gsync_global: Optional[bool] = None
            if self._gsync.is_available():
                for dev_name in display_info.keys():
                    try:
                        if self._gsync.is_capable(dev_name):
                            gsync_capable.add(dev_name)
                    except Exception:
                        pass
                if gsync_capable:
                    try:
                        gsync_global = self._gsync.is_global_enabled()
                    except Exception:
                        gsync_global = None
            self._refresh_ready.emit(
                devices, capture_devices, output_id, comms_id,
                vol, mic_vol, hdr_state, display_info,
                {"capable": gsync_capable, "global": gsync_global}, seq,
            )
            try:
                sessions = self._mixer.get_sessions()
            except Exception:
                sessions = []
            self._mixer_ready.emit(sessions)
            self._last_bg_refresh_done = time.monotonic()
        finally:
            self._refresh_lock.release()

    def _apply_bg_refresh(
        self,
        devices: List["AudioDevice"],
        capture_devices: List["AudioDevice"],
        output_id: Optional[str],
        comms_id: Optional[str],
        vol: float,
        mic_vol: float,
        hdr_state: object,
        display_info: object,
        gsync_state: object,
        seq: int = 0,
    ) -> None:
        """Apply fetched data on the UI thread."""
        self._devices          = devices
        self._capture_devices  = capture_devices
        # Only overwrite active device IDs if the user hasn't switched since
        # this refresh started — prevents stale OS reads from reverting clicks.
        if seq == self._user_switch_seq:
            self._active_output_id = output_id
            self._active_comms_id  = comms_id
        self._display_info  = display_info  # type: ignore[assignment]
        self._hdr_states    = hdr_state     # type: ignore[assignment]
        if isinstance(gsync_state, dict):
            self._gsync_capable = set(gsync_state.get("capable", set()) or set())
            if not self._gsync_busy:
                self._gsync_global = gsync_state.get("global")

        self._rebuild_device_lists()
        self._rebuild_profiles()
        self._rebuild_display_section()
        if not self._vol_skip_update():
            self._set_volume_display(int(vol * 100))
        if not self._mic_skip_update():
            self._set_mic_volume_display(int(mic_vol * 100))

    def invalidate_state(self) -> None:
        """Called by main.py on system resume / session unlock.

        Drops cached fingerprints and the stale active-device IDs that the
        OS may have moved out from under us during suspend, then kicks an
        immediate bg refresh so we re-read live state instead of polling
        with a defunct endpoint ID (which floods the log with
        "Element not found" until the next show).
        """
        self._last_bg_refresh_done = 0.0
        self._last_device_key      = ()
        self._last_profile_key     = ()
        self._last_display_key     = ()
        self._last_mixer_key       = ()
        # Clear so _poll_volume short-circuits until bg_refresh resyncs.
        self._active_output_id = None
        self._active_comms_id  = None
        _com_thread(self._bg_refresh)

    def hide_overlay(self) -> None:
        if self.isVisible():
            self._save_position()
            self._mixer_timer.stop()
            self._vol_poll_timer.stop()
            self._opacity_fx.setOpacity(1.0)
            self._opacity_fx.setEnabled(True)
            self._fade_out.start()

    def toggle_overlay(self) -> None:
        if self.isVisible():
            self.hide_overlay()
        else:
            self.show_overlay()

    def _position_on_screen(self) -> None:
        """Place the overlay: restore the last free-form location if it is still
        visible on a connected screen, else fall back to the named anchor."""
        self.adjustSize()
        if self._restore_position():
            return
        self._anchor_on_screen()

    def _anchor_on_screen(self) -> None:
        screen = QApplication.screenAt(QCursor.pos())
        if not screen:
            screen = QApplication.primaryScreen()
        if not screen:
            return
        sg = screen.availableGeometry()
        self.adjustSize()
        w, h, m = self.width(), self.height(), 20
        pos = self._settings.get("overlay_position")
        coords: dict[str, tuple[int, int]] = {
            "Center":        (sg.center().x() - w // 2, sg.center().y() - h // 2),
            "Top Center":    (sg.center().x() - w // 2, sg.top() + m),
            "Top Right":     (sg.right() - w - m,       sg.top() + m),
            "Bottom Right":  (sg.right() - w - m,       sg.bottom() - h - m),
            "Bottom Left":   (sg.left() + m,             sg.bottom() - h - m),
        }
        x, y = coords.get(pos, coords["Center"])
        self.move(x, y)

    def _restore_position(self) -> bool:
        """Move to the saved [x, y] if a meaningful part of the window would
        land on a connected screen. Returns False when there's nothing saved
        or the spot is off-screen (e.g. a monitor was unplugged)."""
        geo = self._settings.get("overlay_geometry")
        if not (isinstance(geo, (list, tuple)) and len(geo) == 2):
            return False
        try:
            x, y = int(geo[0]), int(geo[1])
        except (TypeError, ValueError):
            return False
        rect = QRect(x, y, self.width(), self.height())
        for screen in QApplication.screens():
            inter = screen.availableGeometry().intersected(rect)
            if inter.width() >= 80 and inter.height() >= 40:
                self.move(x, y)
                return True
        return False

    def _save_position(self) -> None:
        """Persist the current window location so the next show reuses it."""
        if self.isMinimized():
            return
        p = self.pos()
        self._settings.set("overlay_geometry", [p.x(), p.y()])

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Escape:
            self.hide_overlay()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if self._dragging:
            self._save_position()
        self._dragging = False

    def paintEvent(self, event) -> None:  # type: ignore[override]
        pass
