# -*- coding: utf-8 -*-
"""卸载：删快捷方式 -> 清注册表 -> 删程序目录（靠一个临时批处理延迟自删）。"""
import os
import subprocess
import sys
import tempfile
import winreg

APP_NAME = "视频转实况图"
APP_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\LivePhoto"
EXE_NAME = "LivePhoto.exe"


def install_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def shortcut_paths():
    up = os.environ.get("USERPROFILE", "")
    ad = os.environ.get("APPDATA", "")
    return [os.path.join(up, "Desktop", APP_NAME + ".lnk"),
            os.path.join(ad, "Microsoft", "Windows", "Start Menu", "Programs",
                         APP_NAME + ".lnk")]


def remove_shortcuts():
    n = 0
    for p in shortcut_paths():
        try:
            if os.path.exists(p):
                os.remove(p)
                n += 1
        except OSError:
            pass
    return n


def remove_registry():
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, APP_KEY)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def is_installed():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APP_KEY):
            return True
    except OSError:
        return False


def _spawn_self_delete(path):
    """程序自己删不掉自己，交给一个延迟批处理。"""
    bat = os.path.join(tempfile.gettempdir(), "lp_uninstall_%d.bat" % os.getpid())
    with open(bat, "w", encoding="mbcs", errors="replace") as f:
        f.write("@echo off\r\n")
        f.write("ping 127.0.0.1 -n 3 >nul\r\n")
        f.write('rd /s /q "%s" 2>nul\r\n' % path)
        f.write('del "%%~f0" 2>nul\r\n')
    flags = 0x00000008 | 0x00000200          # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(["cmd", "/c", bat], creationflags=flags, close_fds=True)


def run(silent_yes=False):
    target = install_dir()
    if not silent_yes:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        ok = messagebox.askyesno(
            "卸载 " + APP_NAME,
            "确定要卸载「%s」吗？\n\n程序目录：\n%s\n\n"
            "（已经转好的 .JPG / .MOV 文件不会被删除）" % (APP_NAME, target))
        root.destroy()
        if not ok:
            return 0

    remove_shortcuts()
    remove_registry()
    _spawn_self_delete(target)
    if not silent_yes:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("卸载完成", "「%s」已卸载。\n\n目录会在几秒后自动删除。" % APP_NAME)
        root.destroy()
    return 0
