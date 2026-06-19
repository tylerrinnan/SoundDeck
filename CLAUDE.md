# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project
Windows system-tray audio switcher + display utility. PyQt6 overlay, pycaw/comtypes COM audio, NVAPI for G-Sync, PyInstaller frozen exe. Pure-logic modules have a `pytest` suite (`tests/`); COM/Qt paths are still verified by running.

## Architecture

```
main.py          Entry point: hotkey, single-instance mutex, manager wiring
  ├─ audio.py    Windows Core Audio (pycaw + raw COM vtable for SetDefaultEndpoint)
  ├─ mixer.py    Per-app audio sessions (volume/mute per PID)
  ├─ hdr.py      HDR state via DisplayConfigGetDeviceInfo; toggle via Win+Alt+B
  ├─ display.py  Refresh rate enumeration + ChangeDisplaySettingsEx
  ├─ gsync.py    Per-display NVAPI Adaptive Sync (G-Sync Compatible) toggle
  ├─ profiles.py JSON profile persistence (~\AppData\Roaming\SoundDeck\profiles.json)
  ├─ settings.py App-wide settings persistence (hotkey, theme, size, position, opacity)
  ├─ tray.py     pystray system tray icon, startup registry, tooltip
  ├─ theme.py    Colour palette, THEMES dict, all QSS builder functions
  ├─ widgets.py  Reusable dialogs/widgets: ToggleSwitch, HotkeyDialog, SettingsDialog
  └─ overlay.py  Main overlay window: layout, device/profile/mixer/display sections
```

## Module responsibilities

| Module | Owns | Depends on |
|--------|------|------------|
| `theme.py` | Colours, THEMES, SIZE_OPTIONS, POSITION_OPTS, QSS builders | nothing |
| `widgets.py` | ToggleSwitch, HotkeyDialog, SettingsDialog | theme |
| `audio.py` | Device enumeration, default device switching, volume | comtypes, pycaw |
| `mixer.py` | Per-app session enum, volume/mute per PID | pycaw, psutil |
| `hdr.py` | HDR detection + toggle per display | ctypes (user32) |
| `display.py` | Refresh rate enum + switching | ctypes (user32) |
| `gsync.py` | Per-display G-Sync Compatible detect + toggle via NVAPI Adaptive Sync API | ctypes (nvapi64) |
| `profiles.py` | Profile CRUD, active profile tracking | nothing |
| `settings.py` | Key-value settings persistence | nothing |
| `overlay.py` | Main UI window, refresh loop, user interaction | all above + theme, widgets |
| `tray.py` | System tray icon + menu | audio (for tooltip), pystray |
| `main.py` | Wiring, hotkey registration, app lifecycle | all above |

## Threading model
- **UI thread**: All Qt widget operations. Never call COM/pycaw here.
- **`_com_thread(fn)`**: Submits work to a 3-thread `ThreadPoolExecutor` (`_com_pool`). Each pool thread calls `comtypes.CoInitialize()` once on first use. This avoids per-call thread creation overhead.
- **`_bg_refresh()`**: Guarded by `threading.Lock` — only one refresh in flight at a time. The mixer refresh (`_schedule_mixer_refresh`) also acquires this lock inside the pool thread.
- **Signals**: `_refresh_ready`, `_vol_ready`, `_mixer_ready` marshal data back to the UI thread.

## Key facts
- **COMMUNICATIONS section** lists **Windows recording (capture) devices** (`EDataFlow.eCapture`). OUTPUT DEVICE lists playback (render) devices. They are separate lists.
- `AudioManager.get_playback_devices()` uses `EDataFlow.eRender`; `get_recording_devices()` uses `EDataFlow.eCapture`.
- `get_default_comms_capture_id()` / `set_comms_capture_device()` handle the capture-side comms default.
- Default device roles: E_CONSOLE=0, E_MULTIMEDIA=2, E_COMMS=1.
- `set_output_device` sets both E_CONSOLE and E_MULTIMEDIA roles; `set_comms_capture_device` sets E_COMMS on the capture endpoint.

## COM audio (audio.py)
- `CPolicyConfigClient` CLSID: `{870AF99C-171D-4F9E-AF0D-E63DF40C2BC9}`
- Windows 11: CoCreateInstance as IUnknown (INPROC→LOCAL→ALL), then QI for `IPolicyConfig` (`{F8679F50...}`); `IPolicyConfigVista` (`{568B9108...}`) may return E_NOINTERFACE.
- `SetDefaultEndpoint` is vtable slot 13 regardless of which interface succeeds.
- All `_ole32` calls use `c_long` return (not HRESULT) so failures are values, not raised OSError.
- `get_volume` uses direct `IMMDeviceEnumerator.GetDevice(id)` → `Activate(IAudioEndpointVolume)` with cache. Falls back to full enumeration only on error.
- `_enumerator()` caches one `IMMDeviceEnumerator` per COM-pool thread (`threading.local`); `_drop_enumerator()` is called on any failure so a stale proxy self-heals on the next call. Never construct the enumerator directly elsewhere.
- Logging is centralized in `log.py` (one `logging` sink, persistent file handle). Use `from log import log` for plain-string lines (`audio`, `gsync`) or `get_logger("name")` for a stdlib child logger (`hdr`). Never re-open the log file directly. Path: `~\AppData\Roaming\SoundDeck\sounddeck.log`

## Mixer (mixer.py)
- Enumerates ALL active render endpoints (not just default) to catch apps outputting to non-default devices.
- `_find_session_iface` caches `ISimpleAudioVolume` per PID for 5 seconds (`_CACHE_TTL`). Cache is probed with `GetMasterVolume()` before reuse — stale pointers (from dead COM apartments) are evicted automatically.
- Deduplicates sessions by instance ID, then by PID.

## Display / HDR
- `display.py` uses `EnumDisplaySettingsExW` / `ChangeDisplaySettingsExW` for refresh rate.
- `hdr.py` uses `DisplayConfigGetDeviceInfo` type 9 (advanced color info) to read HDR state; type 10 to set it.
- Falls back to `keyboard.send("windows+alt+b")` if `SetAdvancedColorState` fails.

## G-Sync (gsync.py)
- Loads `nvapi64.dll`, calls `nvapi_QueryInterface(funcId)` for each NVAPI function (offsets are stable across drivers).
- **Global VRR_MODE via DRS** is the *write* path. The per-display `NvAPI_DISP_SetAdaptiveSyncData` API auto-reverts on consumer GeForce drivers within ~1s (driver bug), so it cannot be used. The overlay exposes a single global pill that toggles the same setting NVCP / `gsync-toggle` use.
  - `_FN_DRS_GET_SETTING(VRR_MODE_ID=0x1194F158)` reads the value; `_FN_DRS_SET_SETTING` + `_FN_DRS_SAVE_SETTINGS` writes it. `NVAPI_SETTING_NOT_FOUND` → treat as `VRR_MODE_FULLSCREEN_ONLY` (NVCP default).
  - VRR_MODE values: `0=DISABLED`, `1=FULLSCREEN_ONLY`, `2=FULLSCREEN_AND_WINDOWED` (the "on" state).
- **Per-display read path** is still used for capability detection only:
  - `NvAPI_DISP_GetDisplayIdByDisplayName` (0xAE457190) maps `\\.\DISPLAY1`-style names to NVAPI displayIds. Cached per dev_name.
  - `NvAPI_DISP_GetAdaptiveSyncData` (0xB73D1EE9) returning `NVAPI_OK` is the capability bit. **GET struct stamp**: drivers want `size=40, version=1` (`0x00010028`), NOT the 24-byte V1 in public NVAPI headers — there are undocumented trailing fields.
  - `is_capable(name)` is one-way sticky: once a display reports capable, never revoke. Some drivers fail this Get when `VRR_MODE=0`, which would otherwise make the global pill vanish after toggling off.
- All NVAPI calls run inside `_com_thread()` — never on the Qt UI thread.

## Build & run
```
python main.py               # run from source (fastest dev loop)
python -m pytest             # pure-logic tests (tests/, COM/Qt-free, fast)
python -m pyright            # type-check gate (config in pyproject.toml, basic mode)
build.bat                    # pip install + make_icon.py + PyInstaller --onedir
rebuild.bat                  # taskkill SoundDeck.exe + rmdir dist + build.bat + launch
dist\SoundDeck\SoundDeck.exe # built artifact (one folder, not one file)
```
- Dev/test deps: `pip install -r requirements-dev.txt` (adds pytest; pyright via `pip install pyright`).
- pyright is clean at 0 errors; COM-object boundaries (comtypes/NVAPI) are typed `Any` on purpose, third-party stub gaps use scoped `# type: ignore[...]`.
- `comtypes.client.gen_dir = None` set at import time — prevents comtypes writing .py wrappers in frozen exe.
- `build.bat` passes hidden-imports for `pycaw.*`, `comtypes`, `pystray._win32`, `PIL` and `--collect-all=pycaw --collect-all=comtypes`. Add new dynamic imports to that list, not just `requirements.txt`.
- Single-instance enforced via named mutex `SoundDeck_SingleInstance_Mutex` (`main._ensure_single_instance`).

## Dependencies
pycaw, comtypes, PyQt6, pystray, Pillow, keyboard, psutil, pywin32

## Settings (settings.py)
- `SettingsManager.batch()` context manager defers disk writes until the block exits. Use `with settings.batch():` when applying multiple settings at once.

## Icon (make_icon.py)
- `make_icon(size=64)` returns an RGBA PIL Image. Used by both `tray.py` (runtime) and the build script (ICO generation).
- `tray.py` imports `make_icon` — do NOT duplicate the drawing code.

## Special instructions
- Be terse, code only, no explanations unless asked.
- Minimize token usage without sacrificing quality.
- All COM calls MUST run in `_com_thread()` — never on the Qt UI thread.
- When adding new settings, add to `SettingsManager._DEFAULTS` and update `SettingsDialog` in `widgets.py`.
- When adding new themes, add to `THEMES` dict in `theme.py`.
- Profiles are `Mode` objects (`mode.py`): a `caps` dict keyed by `Capability.name`. The legacy flat `Profile(...)` factory and `migrate_flat_dict` keep old call sites/JSON working. Add a new capability = new `caps/*.py` module + one line in `build_default_registry`.
- Profile capture: `_save_new_profile` snapshots the full current state via `Registry.snapshot()` (audio + refresh + HDR + G-Sync, off-thread); `_update_active_profile` edits only the audio caps via `Mode`'s setters so sibling caps are never dropped. Apply runs every cap in `_apply_profile`.
- Fingerprint pattern: every rebuild method checks a `_last_*_key` tuple and short-circuits if unchanged.
