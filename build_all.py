# -*- coding: utf-8 -*-
"""一键构建：冻结 GUI 程序 -> 打包负载 -> 生成单个 Setup.exe"""
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, "app")
INST = os.path.join(ROOT, "installer")
ASSETS = os.path.join(ROOT, "assets")
BUILD = os.path.join(ROOT, "build")
DIST = os.path.join(ROOT, "dist")
SETUP_NAME = "视频转实况图-Setup"


WORK = os.path.join(ROOT, "build", "work")


def run(cmd):
    print("\n>>> " + " ".join('"%s"' % c if " " in c else c for c in cmd))
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        raise SystemExit("构建失败，返回码 %d" % r.returncode)


# 所有中间产物都收进 build/，保持根目录干净
LAYOUT = ["--workpath", WORK, "--distpath", DIST, "--specpath", os.path.join(BUILD, "spec")]


def stage_sources():
    for name in ("livephoto.py", "update.py", "gui.py"):
        shutil.copy2(os.path.join(ROOT, name), os.path.join(APP, name))
    shutil.copy2(os.path.join(ASSETS, "app.ico"), os.path.join(APP, "app.ico"))
    print("已同步 app/: livephoto.py, update.py, gui.py, app.ico")


def build_app():
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean"] + LAYOUT + [
         "--windowed", "--onedir",
         "--name", "LivePhoto",
         "--icon", os.path.join(ASSETS, "app.ico"),
         "--add-data", "%s%s." % (os.path.join(ASSETS, "app.ico"), os.pathsep),
         "--paths", APP,
         "--exclude-module", "numpy", "--exclude-module", "matplotlib",
         "--exclude-module", "pytest", "--exclude-module", "tkinter.test",
         os.path.join(APP, "app_main.py")])
    return os.path.join(DIST, "LivePhoto")


def zip_payload(app_dir):
    os.makedirs(BUILD, exist_ok=True)
    out = os.path.join(BUILD, "app_payload.zip")
    if os.path.exists(out):
        os.remove(out)
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for root, _dirs, files in os.walk(app_dir):
            for f in files:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, app_dir)
                z.write(full, rel)
                n += 1
    print("负载 %d 个文件, %.1f MB -> %s" % (n, os.path.getsize(out) / 1048576.0, out))
    return out


def build_setup():
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean"] + LAYOUT + [
         "--windowed", "--onefile",
         "--name", SETUP_NAME,
         "--icon", os.path.join(ASSETS, "app.ico"),
         "--add-data", "%s%s." % (os.path.join(BUILD, "app_payload.zip"), os.pathsep),
         "--add-data", "%s%s." % (os.path.join(ASSETS, "app.ico"), os.pathsep),
         "--exclude-module", "numpy", "--exclude-module", "matplotlib",
         os.path.join(INST, "setup_main.py")])
    return os.path.join(DIST, SETUP_NAME + ".exe")


def main():
    print("=== 1/4 同步源码 ===");  stage_sources()
    print("=== 2/4 冻结 GUI 程序 ==="); app_dir = build_app()
    print("=== 3/4 打包负载 ===");  zip_payload(app_dir)
    print("=== 4/4 生成安装包 ==="); setup = build_setup()
    print("\n完成：%s  (%.1f MB)" % (setup, os.path.getsize(setup) / 1048576.0))


if __name__ == "__main__":
    main()
