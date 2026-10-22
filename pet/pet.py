#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小面宝宝桌宠  v0.1
==================
方案 B：跟手互动型

  1. 跟手      —— 头身随鼠标方向轻微偏移 + 小幅倾斜
  2. 拖拽      —— 按住拖到任意位置，松手有果冻弹性回弹，位置自动记住
  3. 双击睡觉  —— 下沉 + 压扁 + 冒 Zzz，单击唤醒
  4. 右键菜单  —— 说句话 / 睡觉 / 回到右下角 / 隐身 / 退出
  5. 只在 DSH 打开时出现 —— 定期检测 DSH Desktop 进程，不在就自动隐藏

实现要点：
  * 纯 ctypes 调用 Win32 `UpdateLayeredWindow` 做逐像素 alpha 的分层窗口，
    不做色键抠色，所以边缘是真正的半透明、不会有白边/锯齿块。
  * 透明区域（alpha 很低的像素）通过 WM_NCHITTEST 返回 HTTRANSPARENT，
    鼠标点击会穿透到下面的窗口，不会挡住你操作。
  * 除 Pillow 外无第三方依赖；Pillow 由 pet.py 同目录 .pylibs 提供。
"""

import ctypes
import json
import math
import os
import random
import sys
import time
import traceback
from ctypes import wintypes as wt
from pathlib import Path

BASE = Path(__file__).resolve().parent

# Pillow 放在本目录 .pylibs 下（这台机器的 pip 装不进系统目录），这里自己加进搜索路径
_LIBS = BASE / ".pylibs"
if _LIBS.exists() and str(_LIBS) not in sys.path:
    sys.path.insert(0, str(_LIBS))

from PIL import Image, ImageChops, ImageDraw, ImageFont

SPRITE_PATH = BASE / "assets" / "xiaomian-320h.png"
STATE_PATH = BASE / "state.json"
LOG_PATH = BASE / "pet.log"
CONFIG_PATH = BASE / "config.json"
PID_PATH = BASE / "pet.pid"
VERSION = "1.1"

# ---------------------------------------------------------------- 可调参数
SPRITE_H = 220          # 默认显示高度（逻辑像素）；会被 config.json 里的 height 覆盖
PAD_X = 26              # 左右留白（让倾斜/摇摆不被裁掉）
PAD_TOP = 76            # 上方留白（气泡、Zzz 用）
PAD_BOT = 6
FOLLOW_MAX = 16         # 跟手最大水平偏移（逻辑像素）
FOLLOW_MAX_Y = 10
TILT_MAX = 2.2          # 跟手最大倾斜角度
MISS_GRACE_AFTER_SEEN = 1.5   # 见过 DSH 后，连续确认这么多秒没在跑才退出
FPS_MS = 16             # 定时器间隔
FONT_PATH = Path(r"C:\Windows\Fonts\msyh.ttc")

LINES = [
    "我在这儿~",
    "你在忙什么呀？",
    "摸摸头~",
    "困了...",
    "你写的代码我看不懂",
    "要不要休息一下？",
    "再玩一会儿嘛",
    "我一直看着你哦",
    "小声点，我在发呆",
]

# ---------------------------------------------------------------- Win32 常量
WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
CS_DBLCLKS = 0x0008
ULW_ALPHA = 0x00000002
AC_SRC_OVER, AC_SRC_ALPHA = 0x00, 0x01
BI_RGB = 0
SW_SHOWNOACTIVATE, SW_HIDE = 4, 0
HWND_TOPMOST = -1
SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE = 0x0002, 0x0001, 0x0010
WM_DESTROY, WM_TIMER, WM_NCHITTEST = 0x0002, 0x0113, 0x0084
WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK = 0x0201, 0x0202, 0x0203
WM_RBUTTONUP, WM_MOUSEMOVE = 0x0205, 0x0200
WM_KEYDOWN = 0x0100
HTTRANSPARENT, HTCLIENT = -1, 1
SPI_GETWORKAREA = 0x0030
TH32CS_SNAPPROCESS = 0x00000002
MF_STRING, MF_SEPARATOR = 0x00000000, 0x00000800
TPM_RETURNCMD, TPM_RIGHTBUTTON = 0x0100, 0x0002
IDM_TALK, IDM_SLEEP, IDM_HOME, IDM_HIDE, IDM_QUIT = 1, 2, 3, 4, 5

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
        ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)), ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", wt.LONG), ("dwFlags", wt.DWORD),
        ("szExeFile", wt.WCHAR * 260),
    ]


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.UINT), ("style", wt.UINT), ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON), ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR), ("hIconSm", wt.HICON),
    ]


for fn, res, args in [
    # kernel32：句柄类返回值必须声明成 HANDLE，否则 64 位下会被截断成 int 而失效
    (kernel32.OpenProcess, wt.HANDLE, [wt.DWORD, wt.BOOL, wt.DWORD]),
    (kernel32.GetExitCodeProcess, wt.BOOL, [wt.HANDLE, ctypes.POINTER(wt.DWORD)]),
    (kernel32.CloseHandle, wt.BOOL, [wt.HANDLE]),
    (kernel32.CreateToolhelp32Snapshot, wt.HANDLE, [wt.DWORD, wt.DWORD]),
    (kernel32.Process32FirstW, wt.BOOL, [wt.HANDLE, ctypes.c_void_p]),
    (kernel32.Process32NextW, wt.BOOL, [wt.HANDLE, ctypes.c_void_p]),
    (kernel32.GetModuleHandleW, wt.HMODULE, [wt.LPCWSTR]),
    (user32.RegisterClassExW, wt.WORD, [ctypes.POINTER(WNDCLASSEXW)]),
    (user32.CreateWindowExW, wt.HWND, [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                       wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]),
    (user32.DefWindowProcW, ctypes.c_ssize_t, [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]),
    (user32.UpdateLayeredWindow, wt.BOOL, [wt.HWND, wt.HDC, ctypes.POINTER(wt.POINT),
                                           ctypes.POINTER(wt.SIZE), wt.HDC, ctypes.POINTER(wt.POINT),
                                           wt.DWORD, ctypes.POINTER(BLENDFUNCTION), wt.DWORD]),
    (user32.SetTimer, ctypes.c_size_t, [wt.HWND, ctypes.c_size_t, wt.UINT, wt.LPVOID]),
    (user32.GetMessageW, wt.BOOL, [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]),
    (user32.DispatchMessageW, ctypes.c_ssize_t, [ctypes.POINTER(wt.MSG)]),
    (user32.TrackPopupMenu, ctypes.c_int, [wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, wt.HWND, wt.LPVOID]),
    (gdi32.CreateDIBSection, wt.HBITMAP, [wt.HDC, ctypes.POINTER(BITMAPINFO), wt.UINT,
                                          ctypes.POINTER(ctypes.c_void_p), wt.HANDLE, wt.DWORD]),
    (gdi32.CreateCompatibleDC, wt.HDC, [wt.HDC]),
    (gdi32.SelectObject, wt.HGDIOBJ, [wt.HDC, wt.HGDIOBJ]),
]:
    fn.restype = res
    fn.argtypes = args


def pid_alive(pid) -> bool:
    """判断某个进程是否还活着（守护进程也用它，所以句柄类型必须声明清楚）"""
    if not pid:
        return False
    h = kernel32.OpenProcess(0x1000, False, int(pid))     # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = wt.DWORD()
        if not kernel32.GetExitCodeProcess(h, ctypes.byref(code)):
            return False
        return code.value == 259                          # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(h)


def dsh_running():
    """检测 DSH Desktop 是否在跑（Toolhelp 快照，纯 ctypes，很轻）

    返回值：True=在跑，False=确认没跑，None=枚举失败（状态未知）。
    枚举失败绝不能当成"已经关闭"，否则偶发的快照失败会让桌宠闪退重开。

    设环境变量 XIAOMIAN_FAKE_NO_DSH=1 可强制返回 False（仅用于测试退出逻辑）"""
    if os.environ.get("XIAOMIAN_FAKE_NO_DSH") == "1":
        return False
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == 2 ** 64 - 1:
        return None
    found = False
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        any_entry = False
        while ok:
            any_entry = True
            name = entry.szExeFile.upper()
            if "DSH" in name or "DEEPSEEK HARNESS" in name:
                found = True
                break
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
        if not any_entry:
            return None          # 一个进程都没枚举到，显然是快照异常
        return found
    except Exception:
        return None
    finally:
        kernel32.CloseHandle(snap)


class Pet:
    def __init__(self, force=False, preview=False):
        self.force = force
        self.preview = preview
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass

        dpi = user32.GetDpiForSystem() if hasattr(user32, "GetDpiForSystem") else 96
        self.scale = max(1.0, dpi / 96.0)
        self.sprite_h = self._load_height()

        sprite = Image.open(SPRITE_PATH).convert("RGBA")
        target_h = round(self.sprite_h * self.scale)
        ratio = target_h / sprite.height
        self.sprite = sprite.resize((round(sprite.width * ratio), target_h), Image.LANCZOS)

        self.pad_x = round(PAD_X * self.scale)
        self.pad_top = round(PAD_TOP * self.scale)
        self.pad_bot = round(PAD_BOT * self.scale)
        self.w = self.sprite.width + 2 * self.pad_x
        self.h = self.sprite.height + self.pad_top + self.pad_bot

        self.font = ImageFont.truetype(str(FONT_PATH), round(15 * self.scale))
        self._fonts = {}

        # 状态
        self.home = self._load_home()
        self.off_x = self.off_y = 0.0
        self.vel_x = self.vel_y = 0.0
        self.dragging = False
        self.drag_origin = (0, 0)
        self.drag_off = (0.0, 0.0)
        self.last_cursor = self._cursor()
        self.cursor_vel = (0.0, 0.0)
        self.sleeping = False
        self.sleep_t = 0.0
        self.bubble = None          # (text, t0)
        self.visible = False
        self.alpha = 0.0            # 淡入淡出
        self.hide_until = 0.0
        self._cache = {}
        self._alpha_map = None
        self._prev_time = time.monotonic()
        self._dsh_ok = force or dsh_running()
        self._seen_dsh = self._dsh_ok     # 是否见过 DSH（见过之后，它一消失就立刻退出）
        self._gone_since = None
        self._t = 0.0

        if not preview:
            # 单实例：守护进程和手动启动可能撞车，已有一个在跑就直接让位
            try:
                other = int(PID_PATH.read_text().strip())
            except Exception:
                other = 0
            if other and other != os.getpid() and pid_alive(other):
                self._log(f"已有桌宠在运行 pid={other}，本次退出")
                raise SystemExit(0)
            self._create_window()
            self._write_pid()
        if not self._dsh_ok and not preview:
            self._log("DSH 未运行，桌宠等待启动（20 秒内没出现就退出）")

    # ------------------------------------------------------------ 预览
    def build_preview(self, out_path: Path):
        """把几种状态渲染到一张对比图，方便肉眼检查（不创建窗口、不动鼠标）"""
        states = [
            ("待机呼吸", dict(sleeping=False, off_x=0.0, bubble=None)),
            ("跟手右倾", dict(sleeping=False, off_x=FOLLOW_MAX * self.scale, bubble=None)),
            ("跟手左倾", dict(sleeping=False, off_x=-FOLLOW_MAX * self.scale, bubble=None)),
            ("睡觉 Zzz", dict(sleeping=True, off_x=0.0, bubble=None)),
            ("说话气泡", dict(sleeping=False, off_x=0.0, bubble=(random.choice(LINES), time.monotonic()))),
        ]
        shots = []
        self._t = 1.0
        for _name, st in states:
            self.sleeping = st["sleeping"]
            self.off_x = st["off_x"]
            self.off_y = 0.0
            self.bubble = st["bubble"]
            shots.append(self._render())

        gap = round(10 * self.scale)
        W = sum(s.width for s in shots) + gap * (len(shots) - 1)
        H = max(s.height for s in shots)
        sheet = Image.new("RGBA", (W, H), (42, 44, 50, 255))
        x = 0
        for s in shots:
            sheet.alpha_composite(s, (x, H - s.height))
            x += s.width + gap
        out_path.parent.mkdir(parents=True, exist_ok=True)
        sheet.convert("RGB").save(out_path)
        return out_path

    # ------------------------------------------------------------ 窗口
    def _write_pid(self):
        """写 pid 文件，守护进程靠它判断桌宠是否还活着"""
        try:
            PID_PATH.write_text(str(os.getpid()))
        except Exception:
            pass

    def _remove_pid(self):
        try:
            if PID_PATH.exists() and PID_PATH.read_text().strip() == str(os.getpid()):
                PID_PATH.unlink()
        except Exception:
            pass

    def _load_height(self):
        """显示高度：默认 220，可在 config.json 里改 {"height": 260}"""
        try:
            cfg = json.loads(CONFIG_PATH.read_text("utf-8"))
            v = int(cfg.get("height", SPRITE_H))
            return max(80, min(900, v))
        except Exception:
            return SPRITE_H

    def _create_window(self):
        hinst = kernel32.GetModuleHandleW(None)
        self._wndproc = WNDPROC(self._on_message)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.style = CS_DBLCLKS
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = hinst
        wc.lpszClassName = "XiaoMianPet"
        if not user32.RegisterClassExW(ctypes.byref(wc)):
            err = ctypes.get_last_error()
            if err != 1410:  # 已注册
                raise OSError(f"RegisterClassExW 失败 {err}")
        ex = WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        self.hwnd = user32.CreateWindowExW(
            ex, "XiaoMianPet", "小面宝宝", WS_POPUP,
            int(self.home[0]), int(self.home[1]), self.w, self.h,
            None, None, hinst, None,
        )
        if not self.hwnd:
            raise OSError(f"CreateWindowExW 失败 {ctypes.get_last_error()}")

        self.memdc = gdi32.CreateCompatibleDC(None)
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = self.w
        bmi.bmiHeader.biHeight = -self.h        # 负值 = 自上而下
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB
        self.bits = ctypes.c_void_p()
        self.dib = gdi32.CreateDIBSection(None, ctypes.byref(bmi), 0,
                                          ctypes.byref(self.bits), None, 0)
        gdi32.SelectObject(self.memdc, self.dib)
        user32.SetTimer(self.hwnd, 1, FPS_MS, None)

    def _load_home(self):
        work = wt.RECT()
        user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(work), 0)
        default = (work.right - self.w - round(30 * self.scale),
                   work.bottom - self.h + self.pad_bot)
        try:
            st = json.loads(STATE_PATH.read_text("utf-8"))
            x, y = int(st["x"]), int(st["y"])
            # 防止换了显示器之后跑到屏幕外
            if work.left - self.w < x < work.right and work.top < y < work.bottom + self.h:
                return (x, y)
        except Exception:
            pass
        return default

    def _save_home(self):
        try:
            STATE_PATH.write_text(
                json.dumps({"x": int(self.home[0]), "y": int(self.home[1])}), "utf-8")
        except Exception:
            pass

    # ------------------------------------------------------------ 渲染
    def _sprite_variant(self, angle_q, sy_q):
        key = (angle_q, sy_q)
        if key in self._cache:
            return self._cache[key]
        sy = sy_q / 1000.0
        img = self.sprite
        if abs(sy - 1.0) > 0.001:
            img = img.resize((img.width, max(1, round(img.height * sy))), Image.BILINEAR)
        if angle_q:
            img = img.rotate(angle_q / 2.0, resample=Image.BICUBIC, expand=True)
        if len(self._cache) > 64:
            self._cache.clear()
        self._cache[key] = img
        return img

    def _render(self):
        canvas = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))

        if self.sleeping:
            sy_q = 970
            angle_q = 0
        else:
            breath = math.sin(self._t * 1.75) * 0.008
            sy_q = round((1.0 + breath) * 1000)
            angle_q = round(self.off_x / (FOLLOW_MAX * self.scale) * TILT_MAX * 2)

        img = self._sprite_variant(angle_q, sy_q)
        # 贴图：水平居中，底边对齐精灵底边
        px = self.pad_x + (self.sprite.width - img.width) // 2
        py = self.pad_top + self.sprite.height - img.height + (round(6 * self.scale) if self.sleeping else 0)
        canvas.alpha_composite(img, (max(0, px), max(0, py)))

        if self.sleeping:
            self._draw_zzz(canvas)
        if self.bubble:
            text, t0 = self.bubble
            age = time.monotonic() - t0
            if age > 4.5:
                self.bubble = None
            else:
                fade = 1.0 if age < 3.6 else max(0.0, 1 - (age - 3.6) / 0.9)
                self._draw_bubble(canvas, text, fade)

        self._alpha_map = canvas.getchannel("A").tobytes()
        return canvas

    def _font(self, size):
        """缓存字号 -> 字体对象（每帧都 truetype 一次太贵）"""
        f = self._fonts.get(size)
        if f is None:
            try:
                f = ImageFont.truetype(str(FONT_PATH), size)
            except Exception:
                f = self.font
            self._fonts[size] = f
        return f

    def _draw_zzz(self, canvas):
        """三个由小变大的 Z 从头顶往右上飘，飘到一半开始淡出"""
        d = ImageDraw.Draw(canvas)
        base_x = self.pad_x + self.sprite.width * 0.68
        base_y = self.pad_top - round(4 * self.scale)
        for i in range(3):
            phase = (self._t * 0.45 + i * 0.33) % 1.0
            size = round((15 + 17 * phase) * self.scale)
            f = self._font(size)
            x = base_x + phase * round(34 * self.scale)
            y = base_y - phase * round(54 * self.scale)
            alpha = int(255 * min(1.0, (1 - phase) * 1.8))
            # 描边让 Z 在任何壁纸上都看得见
            for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
                d.text((x + dx, y + dy), "Z", font=f, fill=(255, 255, 255, int(alpha * 0.65)))
            d.text((x, y), "Z", font=f, fill=(84, 116, 186, alpha))

    def _draw_bubble(self, canvas, text, fade=1.0):
        d = ImageDraw.Draw(canvas)
        tw = d.textlength(text, font=self.font)
        pad = round(9 * self.scale)
        bw = int(tw + pad * 2)
        bh = round(28 * self.scale)
        bx = (self.w - bw) // 2
        by = max(0, self.pad_top - bh - round(10 * self.scale))
        a = int(240 * fade)
        d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=round(12 * self.scale),
                            fill=(255, 255, 255, a), outline=(210, 205, 200, a), width=2)
        # 小尾巴
        cx = self.w // 2
        d.polygon([(cx - 6, by + bh - 1), (cx + 6, by + bh - 1), (cx, by + bh + round(8 * self.scale))],
                  fill=(255, 255, 255, a))
        d.text((bx + pad, by + round(5 * self.scale)), text,
               font=self.font, fill=(70, 70, 70, a))

    def _blit(self, canvas, x, y):
        a = canvas.getchannel("A")
        pm = ImageChops.multiply(canvas.convert("RGB"), Image.merge("RGB", (a, a, a)))
        frame = Image.merge("RGBA", (*pm.split(), a)).tobytes("raw", "BGRA")
        ctypes.memmove(self.bits, frame, min(len(frame), self.w * self.h * 4))
        size = wt.SIZE(self.w, self.h)
        src = wt.POINT(0, 0)
        dst = wt.POINT(int(x), int(y))
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, int(max(0, min(255, self.alpha * 255))), AC_SRC_ALPHA)
        user32.UpdateLayeredWindow(self.hwnd, None, ctypes.byref(dst), ctypes.byref(size),
                                   self.memdc, ctypes.byref(src), 0, ctypes.byref(blend), ULW_ALPHA)

    # ------------------------------------------------------------ 动画
    def _cursor(self):
        p = wt.POINT()
        user32.GetCursorPos(ctypes.byref(p))
        return (p.x, p.y)

    def _tick(self):
        now = time.monotonic()
        dt = min(0.1, now - self._prev_time)
        self._prev_time = now
        self._t += dt

        # DSH 在线检测（每 ~0.5 秒）；ok=None 表示枚举失败，保持原判断
        if not self.force and int(self._t * 2) != int((self._t - dt) * 2):
            ok = dsh_running()
            if ok is not None:
                if ok != self._dsh_ok:
                    self._dsh_ok = ok
                    self._log("DSH 已启动，桌宠出现" if ok else "DSH 已关闭")
                if ok:
                    self._seen_dsh = True

        # DSH 不在 -> 桌宠退出（不是隐藏）。
        # 宽限期：启动时 20 秒（覆盖"和 DSH 同时被拉起"的竞态）；
        #         见过 DSH 之后 1.5 秒（3 次轮询），避免偶发枚举失败造成闪退重开。
        if not self.force and not self._dsh_ok:
            if self._gone_since is None:
                self._gone_since = now
            grace = MISS_GRACE_AFTER_SEEN if self._seen_dsh else 20.0
            if now - self._gone_since >= grace:
                self._log("DSH 未运行，桌宠退出")
                user32.PostQuitMessage(0)
                return
        else:
            self._gone_since = None

        want = (self._dsh_ok or self.force) and now >= self.hide_until

        if want and not self.visible:
            user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
            user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            self.visible = True
        elif not want and self.visible:
            user32.ShowWindow(self.hwnd, SW_HIDE)
            self.visible = False

        self.alpha = min(1.0, self.alpha + dt * 4) if want else max(0.0, self.alpha - dt * 6)
        if not want and self.alpha <= 0:
            return

        cur = self._cursor()
        cvx = (cur[0] - self.last_cursor[0]) / dt if dt > 0 else 0
        cvy = (cur[1] - self.last_cursor[1]) / dt if dt > 0 else 0
        self.last_cursor = cur
        self.cursor_vel = (cvx, cvy)

        # 跟手目标偏移
        if self.sleeping or self.dragging:
            tx = ty = 0.0
        else:
            cx = self.home[0] + self.off_x + self.w / 2
            cy = self.home[1] + self.off_y + self.pad_top + self.sprite.height * 0.35
            nx = max(-1.0, min(1.0, (cur[0] - cx) / (self.w * 2.2)))
            ny = max(-1.0, min(1.0, (cur[1] - cy) / (self.h * 2.2)))
            tx = nx * FOLLOW_MAX * self.scale
            ty = ny * FOLLOW_MAX_Y * self.scale

        if self.dragging:
            self.off_x, self.off_y = self.drag_off
        else:
            # 阻尼弹簧 -> 果冻感
            k, c = 130.0, 12.0
            ax = k * (tx - self.off_x) - c * self.vel_x
            ay = k * (ty - self.off_y) - c * self.vel_y
            self.vel_x += ax * dt
            self.vel_y += ay * dt
            self.off_x += self.vel_x * dt
            self.off_y += self.vel_y * dt

        if self.sleeping:
            self.sleep_t += dt

        if not self.visible:
            return

        canvas = self._render()
        self._blit(canvas, self.home[0] + self.off_x, self.home[1] + self.off_y)

    # ------------------------------------------------------------ 交互
    def _hit(self, cx, cy):
        if not self._alpha_map:
            return False
        if 0 <= cx < self.w and 0 <= cy < self.h:
            return self._alpha_map[cy * self.w + cx] > 24
        return False

    def _on_message(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TIMER:
                self._tick()
                return 0
            if msg == WM_NCHITTEST:
                x = ctypes.c_short(lparam & 0xFFFF).value
                y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
                return HTCLIENT if self._hit(x, y) else HTTRANSPARENT
            if msg == WM_LBUTTONDOWN:
                self.dragging = True
                self.drag_origin = self._cursor()
                self.drag_off = (self.off_x, self.off_y)
                user32.SetCapture(hwnd)
                return 0
            if msg == WM_MOUSEMOVE and self.dragging:
                cur = self._cursor()
                self.drag_off = (self.drag_off[0] + cur[0] - self.drag_origin[0],
                                 self.drag_off[1] + cur[1] - self.drag_origin[1])
                self.drag_origin = cur
                self.off_x, self.off_y = self.drag_off
                return 0
            if msg == WM_LBUTTONUP:
                if self.dragging:
                    self.dragging = False
                    user32.ReleaseCapture()
                    self.home = (self.home[0] + self.off_x, self.home[1] + self.off_y)
                    self.home = self._clamp(self.home)
                    self._save_home()
                    self.off_x = self.off_y = 0.0
                    self.vel_x = max(-900, min(900, self.cursor_vel[0] * 0.5))
                    self.vel_y = max(-900, min(900, self.cursor_vel[1] * 0.5))
                elif self.sleeping:
                    self.sleeping = False
                    self.vel_y = -320.0        # 醒来弹一下
                    self.bubble = ("唔…我醒了", time.monotonic())
                else:
                    self.vel_y = -260.0
                    self.bubble = (random.choice(LINES), time.monotonic())
                return 0
            if msg == WM_LBUTTONDBLCLK:
                self.dragging = False
                user32.ReleaseCapture()
                self.sleeping = not self.sleeping
                if self.sleeping:
                    self.bubble = ("那我睡一会儿…", time.monotonic())
                    self.sleep_t = 0.0
                else:
                    self.vel_y = -320.0
                return 0
            if msg == WM_RBUTTONUP:
                self._menu()
                return 0
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
        except Exception:
            self._log(traceback.format_exc())
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _clamp(self, pos):
        work = wt.RECT()
        user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(work), 0)
        x = max(work.left - self.pad_x, min(pos[0], work.right - self.w + self.pad_x))
        y = max(work.top - self.pad_top + round(20 * self.scale), min(pos[1], work.bottom - self.h + self.pad_bot))
        return (x, y)

    def _menu(self):
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, MF_STRING, IDM_TALK, "说句话")
        user32.AppendMenuW(menu, MF_STRING, IDM_SLEEP, "醒过来" if self.sleeping else "睡觉")
        user32.AppendMenuW(menu, MF_STRING, IDM_HOME, "回到右下角")
        user32.AppendMenuW(menu, MF_STRING, IDM_HIDE, "隐身 10 分钟")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, IDM_QUIT, "退出")
        p = wt.POINT()
        user32.GetCursorPos(ctypes.byref(p))
        user32.SetForegroundWindow(self.hwnd)
        cmd = user32.TrackPopupMenu(menu, TPM_RETURNCMD | TPM_RIGHTBUTTON,
                                    p.x, p.y, 0, self.hwnd, None)
        user32.DestroyMenu(menu)

        if cmd == IDM_TALK:
            self.bubble = (random.choice(LINES), time.monotonic())
        elif cmd == IDM_SLEEP:
            self.sleeping = not self.sleeping
            self.bubble = ("那我睡一会儿…" if self.sleeping else "唔…我醒了", time.monotonic())
        elif cmd == IDM_HOME:
            self.home = self._load_default_home()
            self.off_x = self.off_y = 0.0
            self._save_home()
        elif cmd == IDM_HIDE:
            self.hide_until = time.monotonic() + 600
            self._log("隐身 10 分钟")
        elif cmd == IDM_QUIT:
            user32.DestroyWindow(self.hwnd)

    def _load_default_home(self):
        work = wt.RECT()
        user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(work), 0)
        return (work.right - self.w - round(30 * self.scale),
                work.bottom - self.h + self.pad_bot)

    def _log(self, text):
        try:
            with LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
        except Exception:
            pass

    # ------------------------------------------------------------ 主循环
    def run(self):
        msg = wt.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            self._save_home()
            self._remove_pid()


if __name__ == "__main__":
    force = "--force" in sys.argv
    if "--version" in sys.argv:
        print(f"小面宝宝桌宠 v{VERSION}")
        sys.exit(0)
    try:
        if "--preview" in sys.argv:
            pet = Pet(force=True, preview=True)
            out = pet.build_preview(BASE.parent / "preview-states.png")
            # 顺便量一下单帧渲染耗时
            t0 = time.perf_counter()
            for _ in range(60):
                pet._render()
            ms = (time.perf_counter() - t0) / 60 * 1000
            print(f"预览图已保存: {out}")
            print(f"单帧渲染耗时: {ms:.1f} ms  ->  约 {1000/ms:.0f} FPS 上限")
        else:
            Pet(force=force).run()
    except Exception:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        raise


