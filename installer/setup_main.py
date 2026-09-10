# -*- coding: utf-8 -*-
"""视频转实况图 —— 安装程序。

打包后是单个 Setup.exe；也支持命令行静默安装，方便自动化测试：
    setup_main.py --silent --dir <路径> [--no-desktop] [--no-launch]
"""
import os
import subprocess
import sys
import winreg
import zipfile

APP_NAME = "视频转实况图"
APP_VERSION = "1.1.0"
APP_PUBLISHER = "video2livephoto"
EXE_NAME = "LivePhoto.exe"
APP_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\LivePhoto"
CREATE_NO_WINDOW = 0x08000000


# --------------------------------------------------------------------------
def res_path(name):
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def payload_path():
    p = getattr(sys, "_MEIPASS", None)
    if p:
        return os.path.join(p, "app_payload.zip")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "build", "app_payload.zip")


def icon_path():
    for c in (os.path.join(getattr(sys, "_MEIPASS", "") or "", "app.ico"),
              os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "assets", "app.ico")):
        if os.path.exists(c):
            return c
    return ""


def default_dir():
    return os.path.join(os.environ.get("LOCALAPPDATA",
                                       os.path.expanduser("~")), "Programs", "LivePhoto")


def shortcut_paths():
    up = os.environ.get("USERPROFILE", "")
    ad = os.environ.get("APPDATA", "")
    return (os.path.join(up, "Desktop", APP_NAME + ".lnk"),
            os.path.join(ad, "Microsoft", "Windows", "Start Menu", "Programs",
                         APP_NAME + ".lnk"))


def _ps(command):
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", command],
        creationflags=CREATE_NO_WINDOW, capture_output=True, text=True)


def make_shortcut(lnk, target, workdir, icon, desc):
    d = os.path.dirname(lnk)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    ps = ('$ErrorActionPreference="Stop";'
          '$w=New-Object -ComObject WScript.Shell;'
          '$s=$w.CreateShortcut("%s");'
          '$s.TargetPath="%s";'
          '$s.WorkingDirectory="%s";'
          '%s'
          '$s.Description="%s";'
          '$s.Save();Write-Output "OK"') % (
        lnk, target, workdir,
        ('$s.IconLocation="%s";' % icon) if icon else "",
        desc)
    r = _ps(ps)
    return "OK" in (r.stdout or "")


# --------------------------------------------------------------------------
def kill_running(target_dir):
    exe = os.path.join(target_dir, EXE_NAME)
    try:
        subprocess.run(["taskkill", "/F", "/IM", EXE_NAME],
                       creationflags=CREATE_NO_WINDOW, capture_output=True)
    except Exception:
        pass


def extract_payload(target_dir, progress=None):
    pz = payload_path()
    if not os.path.exists(pz):
        raise RuntimeError("安装包数据缺失：%s" % pz)
    os.makedirs(target_dir, exist_ok=True)
    with zipfile.ZipFile(pz) as z:
        names = z.namelist()
        total = len(names)
        for i, n in enumerate(names):
            z.extract(n, target_dir)
            if progress:
                progress(i + 1, total)
    return target_dir


def write_registry(target_dir):
    exe = os.path.join(target_dir, EXE_NAME)
    size = 0
    for root, _d, files in os.walk(target_dir):
        for f in files:
            try:
                size += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, APP_KEY)
    vals = [
        ("DisplayName", APP_NAME),
        ("DisplayVersion", APP_VERSION),
        ("Publisher", APP_PUBLISHER),
        ("DisplayIcon", exe + ",0"),
        ("InstallLocation", target_dir),
        ("UninstallString", '"%s" --uninstall' % exe),
        ("QuietUninstallString", '"%s" --uninstall --yes' % exe),
    ]
    for k, v in vals:
        winreg.SetValueEx(key, k, 0, winreg.REG_SZ, v)
    winreg.SetValueEx(key, "EstimatedSize", 0, winreg.REG_DWORD, int(size / 1024))
    winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
    winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
    winreg.CloseKey(key)


def do_install(target_dir, desktop=True, startmenu=True, progress=None):
    """返回 (成功?, 说明)。"""
    target_dir = os.path.abspath(target_dir)
    if os.path.isdir(target_dir):
        kill_running(target_dir)
        import time
        time.sleep(0.4)
        try:
            import shutil
            shutil.rmtree(target_dir, ignore_errors=True)
        except Exception:
            pass
    extract_payload(target_dir, progress)
    exe = os.path.join(target_dir, EXE_NAME)
    if not os.path.exists(exe):
        return False, "解压后找不到 %s" % EXE_NAME
    icon = os.path.join(target_dir, "app.ico")
    desk_lnk, menu_lnk = shortcut_paths()
    made = []
    if desktop and make_shortcut(desk_lnk, exe, target_dir, icon, APP_NAME):
        made.append("桌面")
    if startmenu and make_shortcut(menu_lnk, exe, target_dir, icon, APP_NAME):
        made.append("开始菜单")
    write_registry(target_dir)
    return True, "快捷方式：" + ("、".join(made) if made else "（未创建）")


# --------------------------------------------------------------------------
def silent_main(argv):
    target = default_dir()
    desktop = startmenu = True
    launch = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--dir" and i + 1 < len(argv):
            target = argv[i + 1]; i += 2; continue
        if a == "--no-desktop":
            desktop = False
        elif a == "--no-startmenu":
            startmenu = False
        elif a == "--launch":
            launch = True
        i += 1
    ok, msg = do_install(target, desktop, startmenu)
    print("installed=%s dir=%s %s" % (ok, target, msg))
    if ok and launch:
        subprocess.Popen([os.path.join(target, EXE_NAME)], cwd=target)
    return 0 if ok else 1


# --------------------------------------------------------------------------
def gui_main():
    import threading
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("%s %s 安装程序" % (APP_NAME, APP_VERSION))
    root.geometry("560x400")
    root.resizable(False, False)
    try:
        ic = os.path.join(getattr(sys, "_MEIPASS", ""), "app.ico")
        if os.path.exists(ic):
            root.iconbitmap(ic)
    except Exception:
        pass

    tk.Label(root, text=APP_NAME, font=("Microsoft YaHei UI", 17, "bold")).pack(
        anchor="w", padx=20, pady=(18, 0))
    tk.Label(root, text="把任意视频转成 iPhone 实况图 · 视频不重新编码",
             fg="#666").pack(anchor="w", padx=20)

    box = tk.LabelFrame(root, text=" 安装位置 ", padx=10, pady=10)
    box.pack(fill="x", padx=20, pady=14)
    dirvar = tk.StringVar(value=default_dir())
    e = tk.Entry(box, textvariable=dirvar)
    e.pack(side="left", fill="x", expand=True)

    def browse():
        p = filedialog.askdirectory(title="选择安装位置", initialdir=dirvar.get())
        if p:
            dirvar.set(os.path.join(p, "LivePhoto"))
    tk.Button(box, text="浏览…", command=browse).pack(side="left", padx=(8, 0))

    opt = tk.LabelFrame(root, text=" 选项 ", padx=10, pady=8)
    opt.pack(fill="x", padx=20)
    v_desk = tk.BooleanVar(value=True)
    v_menu = tk.BooleanVar(value=True)
    v_run = tk.BooleanVar(value=True)
    tk.Checkbutton(opt, text="创建桌面快捷方式", variable=v_desk).pack(anchor="w")
    tk.Checkbutton(opt, text="创建开始菜单快捷方式", variable=v_menu).pack(anchor="w")
    tk.Checkbutton(opt, text="安装完成后立即打开", variable=v_run).pack(anchor="w")

    status = tk.Label(root, text="点「开始安装」继续。", fg="#444")
    status.pack(anchor="w", padx=20, pady=(12, 4))
    bar = ttk.Progressbar(root, mode="determinate", maximum=100)
    bar.pack(fill="x", padx=20)

    btns = tk.Frame(root)
    btns.pack(fill="x", padx=20, pady=16)
    go = tk.Button(btns, text="开始安装", width=14, height=1,
                   font=("Microsoft YaHei UI", 10, "bold"))
    go.pack(side="right")
    cancel = tk.Button(btns, text="取消", width=10, command=root.destroy)
    cancel.pack(side="right", padx=(0, 8))

    state = {"done": False}

    def say(t):
        status.configure(text=t)
        root.update_idletasks()

    def worker(target):
        try:
            def prog(i, n):
                root.after(0, lambda: bar.configure(value=i * 100.0 / max(n, 1)))
            say("正在释放程序文件…")
            ok, msg = do_install(target, v_desk.get(), v_menu.get(), prog)
            root.after(0, lambda: bar.configure(value=100))
            if not ok:
                root.after(0, lambda: messagebox.showerror("安装失败", msg))
                root.after(0, lambda: go.configure(state="normal", text="开始安装"))
                return
            state["done"] = True
            say("安装完成。%s" % msg)

            def finish():
                go.configure(state="normal", text="完成", command=on_finish)
                cancel.configure(text="关闭")
                messagebox.showinfo("安装完成",
                                    "「%s」已安装到：\n%s\n\n%s"
                                    % (APP_NAME, target, msg))
            root.after(0, finish)
        except Exception as exc:
            import traceback
            tb = traceback.format_exc()
            root.after(0, lambda: messagebox.showerror("安装失败", "%s\n\n%s" % (exc, tb)))
            root.after(0, lambda: go.configure(state="normal", text="开始安装"))

    def on_finish():
        if v_run.get():
            exe = os.path.join(dirvar.get().strip(), EXE_NAME)
            if os.path.exists(exe):
                subprocess.Popen([exe], cwd=os.path.dirname(exe))
        root.destroy()

    def start():
        target = dirvar.get().strip().strip('"')
        if not target:
            messagebox.showwarning("提示", "请填写安装位置。")
            return
        if state["done"]:
            on_finish()
            return
        go.configure(state="disabled", text="安装中…")
        threading.Thread(target=worker, args=(target,), daemon=True).start()

    go.configure(command=start)
    root.mainloop()
    return 0


def main():
    argv = sys.argv[1:]
    if "--silent" in argv:
        return silent_main(argv)
    return gui_main()


if __name__ == "__main__":
    sys.exit(main())
