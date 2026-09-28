"""게임으로 키 입력 보내기 (자동 투안용).

- DirectInput 을 쓰는 게임도 받도록 가상키가 아닌 '스캔코드'로 SendInput 한다.
- 엉뚱한 창에 키가 눌리지 않도록, 전경 창이 마비노기일 때만 보낸다.
"""
import ctypes
import ctypes.wintypes as wt
import os
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MAPVK_VK_TO_VSC = 0

VK_SHIFT, VK_CONTROL, VK_MENU = 0x10, 0x11, 0x12
EXTENDED_VK = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5C, 0x6F, 0x90}
MOD_NAMES = {VK_CONTROL: "Ctrl", VK_MENU: "Alt", VK_SHIFT: "Shift"}

GAME_EXES = {"client.exe", "mabinogi.exe"}
GAME_TITLES = ("마비노기", "mabinogi")


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


def _key_event(vk: int, up: bool):
    scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0)
    if vk in EXTENDED_VK:
        flags |= KEYEVENTF_EXTENDEDKEY
    inp = INPUT(INPUT_KEYBOARD, _INPUTUNION(ki=KEYBDINPUT(0, scan, flags, 0, 0)))
    if user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) != 1:
        raise OSError(f"SendInput 실패 (오류 {ctypes.get_last_error()})")


def press(combo: dict, hold: float = 0.05):
    """combo = {"vk": int, "mods": [vk...], "label": str}"""
    mods = combo.get("mods", [])
    for m in mods:
        _key_event(m, False)
    _key_event(combo["vk"], False)
    time.sleep(hold)
    _key_event(combo["vk"], True)
    for m in reversed(mods):
        _key_event(m, True)


def foreground_info() -> tuple[str, str]:
    """(실행 파일 이름, 창 제목)"""
    hwnd = user32.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    title = buf.value
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    exe = ""
    h = kernel32.OpenProcess(0x1000, False, pid.value)      # PROCESS_QUERY_LIMITED_INFORMATION
    if h:
        size = wt.DWORD(512)
        path = ctypes.create_unicode_buffer(512)
        if kernel32.QueryFullProcessImageNameW(h, 0, path, ctypes.byref(size)):
            exe = os.path.basename(path.value)
        kernel32.CloseHandle(h)
    return exe, title


def game_is_foreground() -> bool:
    exe, title = foreground_info()
    return exe.lower() in GAME_EXES or any(t in title.lower() for t in GAME_TITLES)


def combo_label(vk: int, mods: list[int]) -> str:
    names = [MOD_NAMES[m] for m in mods if m in MOD_NAMES]
    scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    lparam = (scan << 16) | ((1 << 24) if vk in EXTENDED_VK else 0)
    buf = ctypes.create_unicode_buffer(64)
    key = buf.value if user32.GetKeyNameTextW(lparam, buf, 64) else f"VK{vk:02X}"
    return "+".join(names + [key or f"VK{vk:02X}"])
