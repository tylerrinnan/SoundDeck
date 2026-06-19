"""
hdr.py — HDR state detection via DisplayConfigGetDeviceInfo.
Toggle via keyboard.send('windows+alt+b') — reliable cross-app key injection.
"""

import ctypes
import ctypes.wintypes as wt

from log import get_logger

QDC_ONLY_ACTIVE_PATHS                              = 0x00000002
DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME          = 1
DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO  = 9
DISPLAYCONFIG_DEVICE_INFO_SET_ADVANCED_COLOR_STATE = 10
ERROR_SUCCESS                                      = 0


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wt.DWORD), ("HighPart", wt.LONG)]


class DISPLAYCONFIG_PATH_SOURCE_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId",   LUID),
        ("id",          ctypes.c_uint32),
        ("modeInfoIdx", ctypes.c_uint32),
        ("statusFlags", ctypes.c_uint32),
    ]


class DISPLAYCONFIG_PATH_TARGET_INFO(ctypes.Structure):
    # refreshRate MUST be two separate uint32 fields — not a nested struct
    _fields_ = [
        ("adapterId",        LUID),
        ("id",               ctypes.c_uint32),
        ("modeInfoIdx",      ctypes.c_uint32),
        ("outputTechnology", ctypes.c_int32),
        ("rotation",         ctypes.c_int32),
        ("scaling",          ctypes.c_int32),
        ("refreshRateNumer", ctypes.c_uint32),
        ("refreshRateDenom", ctypes.c_uint32),
        ("scanLineOrdering", ctypes.c_int32),
        ("targetAvailable",  wt.BOOL),
        ("statusFlags",      ctypes.c_uint32),
    ]


class DISPLAYCONFIG_PATH_INFO(ctypes.Structure):
    _fields_ = [
        ("sourceInfo", DISPLAYCONFIG_PATH_SOURCE_INFO),
        ("targetInfo", DISPLAYCONFIG_PATH_TARGET_INFO),
        ("flags",      ctypes.c_uint32),
    ]


class DISPLAYCONFIG_MODE_INFO(ctypes.Structure):
    _fields_ = [
        ("infoType",  ctypes.c_int32),
        ("id",        ctypes.c_uint32),
        ("adapterId", LUID),
        ("modeInfo",  ctypes.c_byte * 64),   # union, padded to 64 bytes
    ]


class DISPLAYCONFIG_DEVICE_INFO_HEADER(ctypes.Structure):
    _fields_ = [
        ("type",      ctypes.c_int32),
        ("size",      ctypes.c_uint32),
        ("adapterId", LUID),
        ("id",        ctypes.c_uint32),
    ]


class DISPLAYCONFIG_SOURCE_DEVICE_NAME(ctypes.Structure):
    _fields_ = [
        ("header",            DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("viewGdiDeviceName", ctypes.c_wchar * 32),
    ]


class DISPLAYCONFIG_SET_ADVANCED_COLOR_STATE(ctypes.Structure):
    _fields_ = [
        ("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("value",  ctypes.c_uint32),
    ]


class DISPLAYCONFIG_ADVANCED_COLOR_INFO(ctypes.Structure):
    _fields_ = [
        ("header",              DISPLAYCONFIG_DEVICE_INFO_HEADER),  # 20 bytes
        ("value",               ctypes.c_uint32),
        ("colorEncoding",       ctypes.c_uint32),
        ("bitsPerColorChannel", ctypes.c_uint32),
    ]
    # sizeof = 32 bytes — must equal header.size


_log = get_logger("hdr")


def _is_hdr_active(value):
    color_enabled = (value >> 1) & 1
    wide_color    = (value >> 2) & 1
    force_off     = (value >> 3) & 1
    return bool(color_enabled and not wide_color and not force_off)


def _init_header(struct, info_type, adapter_id, dev_id):
    struct.header.type      = info_type
    struct.header.size      = ctypes.sizeof(type(struct))
    struct.header.adapterId = adapter_id
    struct.header.id        = dev_id


class HDRManager:
    _user32 = ctypes.windll.user32

    # Declare proper argtypes/restype for display config functions
    _user32.GetDisplayConfigBufferSizes.argtypes = [
        ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32)
    ]
    _user32.GetDisplayConfigBufferSizes.restype = ctypes.c_long

    _user32.QueryDisplayConfig.argtypes = [
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    _user32.QueryDisplayConfig.restype = ctypes.c_long

    _user32.DisplayConfigGetDeviceInfo.argtypes = [ctypes.c_void_p]
    _user32.DisplayConfigGetDeviceInfo.restype = ctypes.c_long

    _user32.DisplayConfigSetDeviceInfo.argtypes = [ctypes.c_void_p]
    _user32.DisplayConfigSetDeviceInfo.restype = ctypes.c_long

    def _query_paths(self):
        """Return (paths, num_paths) or (None, 0) on failure."""
        num_paths = ctypes.c_uint32(0)
        num_modes = ctypes.c_uint32(0)
        if self._user32.GetDisplayConfigBufferSizes(
            QDC_ONLY_ACTIVE_PATHS, ctypes.byref(num_paths), ctypes.byref(num_modes)
        ) != ERROR_SUCCESS or num_paths.value == 0:
            return None, 0
        paths = (DISPLAYCONFIG_PATH_INFO * num_paths.value)()
        modes = (DISPLAYCONFIG_MODE_INFO * num_modes.value)()
        if self._user32.QueryDisplayConfig(
            QDC_ONLY_ACTIVE_PATHS,
            ctypes.byref(num_paths), paths,
            ctypes.byref(num_modes), modes,
            None,
        ) != ERROR_SUCCESS:
            return None, 0
        return paths, num_paths.value

    def get_hdr_states(self) -> dict:
        """Return {gdi_device_name: is_hdr_on} for each HDR-capable active display."""
        result = {}
        paths, count = self._query_paths()
        if paths is None:
            return result
        seen = set()
        for i in range(count):
            src_key = (paths[i].sourceInfo.adapterId.LowPart,
                       paths[i].sourceInfo.adapterId.HighPart,
                       paths[i].sourceInfo.id)
            if src_key in seen:
                continue
            seen.add(src_key)
            src_info = DISPLAYCONFIG_SOURCE_DEVICE_NAME()
            _init_header(src_info, DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME,
                         paths[i].sourceInfo.adapterId, paths[i].sourceInfo.id)
            if self._user32.DisplayConfigGetDeviceInfo(ctypes.byref(src_info)) != ERROR_SUCCESS:
                continue
            gdi_name = src_info.viewGdiDeviceName
            color_info = DISPLAYCONFIG_ADVANCED_COLOR_INFO()
            _init_header(color_info, DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO,
                         paths[i].targetInfo.adapterId, paths[i].targetInfo.id)
            if self._user32.DisplayConfigGetDeviceInfo(ctypes.byref(color_info)) != ERROR_SUCCESS:
                continue
            if not (color_info.value & 1):  # bit 0: advancedColorSupported
                continue
            result[gdi_name] = _is_hdr_active(color_info.value)
        return result

    def set_hdr_state(self, dev_name: str, enable: bool) -> bool:
        """Enable or disable HDR on a specific display by GDI device name.
        Returns True if the API call succeeded."""
        paths, count = self._query_paths()
        if paths is None:
            _log.warning("set_hdr_state: failed to query display paths")
            return False
        for i in range(count):
            src_info = DISPLAYCONFIG_SOURCE_DEVICE_NAME()
            _init_header(src_info, DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME,
                         paths[i].sourceInfo.adapterId, paths[i].sourceInfo.id)
            if self._user32.DisplayConfigGetDeviceInfo(ctypes.byref(src_info)) != ERROR_SUCCESS:
                continue
            if src_info.viewGdiDeviceName != dev_name:
                continue
            set_info = DISPLAYCONFIG_SET_ADVANCED_COLOR_STATE()
            _init_header(set_info, DISPLAYCONFIG_DEVICE_INFO_SET_ADVANCED_COLOR_STATE,
                         paths[i].targetInfo.adapterId, paths[i].targetInfo.id)
            set_info.value = 1 if enable else 0
            ret = self._user32.DisplayConfigSetDeviceInfo(ctypes.byref(set_info))
            _log.info("set_hdr_state(%s, %s): ret=%d (size=%d)",
                      dev_name, enable, ret, ctypes.sizeof(set_info))
            return ret == ERROR_SUCCESS
        _log.warning("set_hdr_state: device %r not found in active paths", dev_name)
        return False
