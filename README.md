# SoundDeck 🎛️

A fast, always-on-top audio switcher overlay for Windows 11.  
Trigger it over any app — game, browser, full-screen video — and switch your
output device, communications device, or toggle HDR in two clicks.

---

## Features

| Feature | Detail |
|---|---|
| **Output device switching** | All active playback devices shown as cards |
| **Communications device** | Set your voice-chat device independently |
| **Per-device volume** | Slider tied to the selected output device |
| **Named profiles** | One-click to apply a saved output + comms + volume combo |
| **HDR toggle** | Live state readout; sends Win+Alt+B to toggle |
| **Global hotkey** | `Ctrl+Shift+A` — works over any foreground window |
| **System tray** | Tooltip shows current device; left-click opens overlay |
| **Start with Windows** | Toggle in the tray right-click menu |
| **Drag to reposition** | Click-drag the overlay to move it |

---

## Requirements

- **Windows 10 / 11** (Windows 11 recommended for best HDR support)
- **Python 3.10+** (only needed to build from source)

---

## Quick Start (pre-built)

1. Download `SoundDeck-v1.0.0-win64.zip` from the
   [**Releases**](../../releases/latest) page.
2. Extract the whole folder anywhere, then run `SoundDeck.exe` inside it.
   (One-folder build — keep the `_internal/` folder next to the exe.)
3. An icon appears in your system tray. Press **Ctrl+Shift+A** or click the
   tray icon to open the overlay.

> **Tip:** Right-click the tray icon → *Start with Windows* to auto-launch.

---

## Build from Source

```batch
build.bat
```

The script installs all Python dependencies, generates the icon, and produces
a one-folder build at `dist\SoundDeck\` (run `dist\SoundDeck\SoundDeck.exe`).
To relocate it, copy the entire `dist\SoundDeck\` folder.

---

## Usage

### Switching devices
Click any device card in **Output Device** or **Communications** to set it
as the Windows default for that role. The active device glows with a purple border.

### Volume
The slider controls the master volume of whichever output device is currently
selected. Changes apply immediately.

### Profiles
- Click a profile pill to apply it (sets output + comms device + volume at once).
- Click **+** to save your current settings as a new profile.
- Right-click a profile pill to **rename** or **delete** it.

### HDR
The toggle shows the live HDR state of your primary display.  
Clicking it sends **Win+Alt+B** — the same shortcut Windows uses natively.

> **Note:** HDR state is read via `DisplayConfigGetDeviceInfo`. If your display
> has HDR force-disabled (e.g. G-Sync compatibility mode), the toggle fires the
> shortcut but Windows may silently ignore it — that's a Windows limitation,
> not a SoundDeck bug.

### Hotkey
Default: **Ctrl+Shift+A**.  
If another application has claimed this combination, the registration will
fail and a warning is printed to the console. Run as Administrator if needed.

---

## Known limitations

- **Exclusive fullscreen apps** (rare; older games, some emulators) will minimize
  when the overlay gains focus. Borderless windowed mode — used by WoW, most
  modern games — is unaffected.
- HDR toggle is write-only when `SetAdvancedColorState` is blocked by the
  display driver (force-disable bit set). The Win+Alt+B fallback is used
  instead, which works in all tested scenarios.

---

## Profiles location

`%APPDATA%\SoundDeck\profiles.json` — plain JSON, easy to back up or share.

---

## License

MIT — do whatever you want with it.
