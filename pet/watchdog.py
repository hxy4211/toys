"""
小面宝宝守护进程
================
职责很简单，就两件：

  * 检测到 DSH Desktop 启动  -> 拉起桌宠（桌宠自己是个独立进程，关掉就真的没了）
  * 检测到 DSH Desktop 退出  -> 桌宠会自己退出（本守护进程兜底：超时还没走就强杀）

守护进程本身没有窗口、常驻内存约 12 MB。放在开机启动里，这样你每次打开 DSH，
小面都会自己冒出来；关掉 DSH，它就彻底关闭、不在后台留驻。

桌宠和守护进程各自维护一个 pid 文件，用来判断对方是否还活着：
  pet.pid       桌宠
  watchdog.pid  本守护进程（同时用于保证只有一个守护进程）
"""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes as wt
from pathlib import Path

BASE = Path(__file__).resolve().parent
PET_SCRIPT = BASE / "pet.py"
PET_PID = BASE / "pet.pid"
WD_PID = BASE / "watchdog.pid"
LOG = BASE / "watchdog.log"

POLL_SEC = 1.5          # 轮询间隔
PET_KILL_GRACE = 6.0    # DSH 退出后，等桌宠自己走这么多秒，还没走就强杀

TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# 64 位下必须声明句柄类型，否则 HANDLE 会被当成 int 截断，
# 导致 OpenProcess 拿到的句柄失效、pid_alive 永远返回 False（单实例检测就失效了）
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.GetExitCodeProcess.restype = wt.BOOL
kernel32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
kernel32.CloseHandle.restype = wt.BOOL
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.TerminateProcess.restype = wt.BOOL
kernel32.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
kernel32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]

INVALID_HANDLE = 2 ** 64 - 1


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)), ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", wt.LONG), ("dwFlags", wt.DWORD),
        ("szExeFile", wt.WCHAR * 260),
    ]


def log(msg):
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def dsh_running():
    """DSH Desktop 是否在运行"""
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID_HANDLE:
        return False
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            name = entry.szExeFile.upper()
            if "DSH" in name or "DEEPSEEK HARNESS" in name:
                return True
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
        return False
    finally:
        kernel32.CloseHandle(snap)


def pid_alive(pid):
    if not pid:
        return False
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return False
    try:
        code = wt.DWORD()
        if not kernel32.GetExitCodeProcess(h, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(h)


def read_pid(path):
    try:
        return int(path.read_text().strip())
    except Exception:
        return 0


def pet_alive():
    return pid_alive(read_pid(PET_PID))


def start_pet():
    exe = Path(sys.executable).with_name("pythonw.exe")
    if not exe.exists():
        exe = Path(sys.executable)
    try:
        subprocess.Popen(
            [str(exe), str(PET_SCRIPT)],
            cwd=str(BASE),
            creationflags=subprocess.CREATE_NO_WINDOW,
            close_fds=True,
        )
        log(f"已拉起桌宠：{exe.name} {PET_SCRIPT.name}")
    except Exception as e:
        log(f"拉起桌宠失败: {e}")


def kill_pet(pid):
    if not pid:
        return
    h = kernel32.OpenProcess(0x0001, False, int(pid))   # PROCESS_TERMINATE
    if h:
        try:
            kernel32.TerminateProcess(h, 0)
            log(f"强杀桌宠 pid={pid}")
        finally:
            kernel32.CloseHandle(h)


def main():
    # 单实例
    old = read_pid(WD_PID)
    if old and old != os.getpid() and pid_alive(old):
        log(f"已有守护进程在运行 pid={old}，本次退出")
        return 0
    WD_PID.write_text(str(os.getpid()))
    log(f"守护进程启动 pid={os.getpid()}")

    pet_missing_since = None
    try:
        while True:
            dsh = dsh_running()
            alive = pet_alive()

            if dsh and not alive:
                start_pet()
                pet_missing_since = None
                time.sleep(1.2)      # 给它一点启动时间，别连续拉起
                continue

            if not dsh and alive:
                # 桌宠会自己检测到 DSH 退出并关闭；这里只做兜底
                now = time.monotonic()
                if pet_missing_since is None:
                    pet_missing_since = now
                    log("DSH 已退出，等桌宠自行关闭")
                elif now - pet_missing_since > PET_KILL_GRACE:
                    kill_pet(read_pid(PET_PID))
                    pet_missing_since = None
            else:
                pet_missing_since = None

            time.sleep(POLL_SEC)
    finally:
        try:
            if read_pid(WD_PID) == os.getpid():
                WD_PID.unlink(missing_ok=True)
        except Exception:
            pass
        log("守护进程退出")


if __name__ == "__main__":
    sys.exit(main())
