#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视频转实况图 —— 便携版启动器。

真正的界面代码在 gui.py（和打包进安装包的完全同一份）。
双击本文件即可运行；Windows 上 .pyw 后缀不会弹出黑框。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from gui import main
except Exception as exc:                       # pragma: no cover
    import tkinter.messagebox as mb
    mb.showerror("启动失败", "无法加载 gui.py：%s" % exc)
    raise SystemExit(1)

if __name__ == "__main__":
    sys.exit(main())
