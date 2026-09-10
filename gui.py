# -*- coding: utf-8 -*-
"""视频转实况图 —— 图形界面。既能在源码下跑，也能被 PyInstaller 冻结。"""
import os
import queue
import sys
import threading
import traceback
import uuid as uuidlib

# --- 高分屏适配：必须在创建窗口前调用 ---
def _enable_dpi_awareness():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)      # per-monitor aware
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


_enable_dpi_awareness()


import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import livephoto as lp

try:
    import update as upd
except ImportError:                      # 单独跑 gui.py 时可能没有
    upd = None

VIDEO_TYPES = [("视频文件", "*.mp4 *.mov *.m4v *.MP4 *.MOV"), ("所有文件", "*.*")]
IMAGE_TYPES = [("图片", "*.jpg *.jpeg *.png *.JPG *.JPEG *.PNG"), ("所有文件", "*.*")]


def res_path(*parts):
    """兼容源码运行与 PyInstaller 打包后的资源路径。"""
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, *parts)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("视频转实况图 · Live Photo")
        self.geometry("760x600")
        self.minsize(680, 540)
        self.video = tk.StringVar()
        self.cover = tk.StringVar()
        self.outdir = tk.StringVar()
        self.quality = tk.IntVar(value=97)
        self.busy = False
        self._checking = False
        self.update_btn = None
        self._uq = queue.Queue()          # 工作线程 -> 主线程 的传递队列
        self._set_icon()
        self._build()
        self.after(300, self._poll_update)
        if upd is not None:
            # 启动 2 秒后静默检查一次，不打扰用户
            self.after(2000, lambda: self.check_update(False))

    def _set_icon(self):
        for name in ("app.ico", os.path.join("assets", "app.ico")):
            p = res_path(name)
            if os.path.exists(p):
                try:
                    self.iconbitmap(p)
                    return
                except Exception:
                    pass

    # ---- 界面 ---------------------------------------------------------
    def _build(self):
        pad = {"padx": 12, "pady": 6}
        tk.Label(self, text="把视频转成 iPhone 实况图",
                 font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w", padx=14, pady=(14, 2))
        tk.Label(self, text="视频不会被重新编码，采样数据一字节不差；只重写容器与元数据。",
                 fg="#666").pack(anchor="w", padx=14, pady=(0, 10))

        frm = tk.Frame(self)
        frm.pack(fill="x", **pad)
        frm.columnconfigure(1, weight=1)

        tk.Label(frm, text="视频").grid(row=0, column=0, sticky="w")
        tk.Entry(frm, textvariable=self.video).grid(row=0, column=1, sticky="ew", padx=6)
        tk.Button(frm, text="选择…", width=8, command=self.pick_video).grid(row=0, column=2)

        tk.Label(frm, text="封面图").grid(row=1, column=0, sticky="w")
        tk.Entry(frm, textvariable=self.cover).grid(row=1, column=1, sticky="ew", padx=6)
        tk.Button(frm, text="选择…", width=8, command=self.pick_cover).grid(row=1, column=2)
        tk.Label(frm, text="留空 = 自动从视频里取一帧（原生分辨率）",
                 fg="#888").grid(row=2, column=1, sticky="w", padx=6)

        tk.Label(frm, text="输出目录").grid(row=3, column=0, sticky="w")
        tk.Entry(frm, textvariable=self.outdir).grid(row=3, column=1, sticky="ew", padx=6)
        tk.Button(frm, text="选择…", width=8, command=self.pick_out).grid(row=3, column=2)
        tk.Label(frm, text="留空 = 与视频放在一起", fg="#888").grid(
            row=4, column=1, sticky="w", padx=6)

        qf = tk.Frame(self)
        qf.pack(fill="x", **pad)
        tk.Label(qf, text="封面 JPEG 质量").pack(side="left")
        tk.Scale(qf, from_=70, to=100, orient="horizontal", variable=self.quality,
                 length=240).pack(side="left", padx=8)

        self.btn = tk.Button(self, text="开始转换", height=2,
                             font=("Microsoft YaHei UI", 11, "bold"), command=self.run)
        self.btn.pack(fill="x", padx=12, pady=(2, 8))

        self.log = tk.Text(self, height=14, wrap="word", state="disabled",
                           bg="#1e2430", fg="#d7e2f0", insertbackground="#d7e2f0",
                           font=("Microsoft YaHei UI", 9))
        self.log.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        bar = tk.Frame(self)
        bar.pack(fill="x", padx=12, pady=(0, 12))
        tk.Button(bar, text="打开输出文件夹", command=self.open_out).pack(side="left")
        tk.Label(bar, text="  转好后请把同名的 .JPG 和 .MOV 一起传到 iPhone",
                 fg="#888").pack(side="left")
        ver = upd.CURRENT_VERSION if upd is not None else "?"
        self.update_btn = tk.Button(bar, text="检查更新", width=10,
                                    command=lambda: self.check_update(True))
        self.update_btn.pack(side="right")
        tk.Label(bar, text="v" + ver, fg="#888").pack(side="right", padx=(0, 8))

        self.out("选好视频后点「开始转换」。")
        self.out("转好会得到一对同名文件：XXX.JPG + XXX.MOV。")
        self.out("两个文件必须一起传，照片 App 才会把它们合成一张实况图。\n")

    def out(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def open_out(self):
        d = self.outdir.get().strip().strip('"')
        if not d:
            v = self.video.get().strip().strip('"')
            d = os.path.dirname(v) if v else ""
        if d and os.path.isdir(d):
            os.startfile(d)
        else:
            messagebox.showinfo("提示", "还没有可打开的输出目录。")

    # ---- 检查更新 -----------------------------------------------------
    def check_update(self, manual):
        if upd is None:
            if manual:
                messagebox.showwarning("检查更新", "缺少 update.py，无法检查更新。")
            return
        if self._checking:
            return
        self._checking = True
        if manual:
            self.update_btn.configure(state="disabled", text="检查中…")
            self.out("正在检查更新…")

        # 不能在工作线程里直接碰 tkinter，丢进队列由主线程取
        upd.check_async(lambda r: self._uq.put((r, manual)))

    def _poll_update(self):
        try:
            while True:
                r, manual = self._uq.get_nowait()
                self._update_done(r, manual)
        except queue.Empty:
            pass
        self.after(300, self._poll_update)

    def _update_done(self, r, manual):
        self._checking = False
        self.update_btn.configure(state="normal", text="检查更新")
        if r.get("error"):
            if manual:
                self.out("检查更新失败：%s" % r["error"])
                messagebox.showwarning("检查更新", "检查失败：\n%s" % r["error"])
            return
        if r.get("has_update"):
            self.out("")
            self.out("发现新版本 %s（当前 %s）" % (r["version"], r["current"]))
            if r.get("notes"):
                self.out("更新说明：%s" % r["notes"])
            txt = "当前版本：%s\n最新版本：%s\n" % (r["current"], r["version"])
            if r.get("notes"):
                txt += "\n更新说明：\n%s\n" % r["notes"]
            txt += "\n现在去下载吗？"
            if messagebox.askyesno("发现新版本", txt):
                if not upd.open_url(r["url"]):
                    messagebox.showinfo("下载地址", r["url"])
        elif manual:
            self.out("已经是最新版本（%s）" % r["current"])
            messagebox.showinfo("检查更新", "已经是最新版本 %s" % r["current"])

    # ---- 选择 ---------------------------------------------------------
    def pick_video(self):
        p = filedialog.askopenfilename(title="选择视频", filetypes=VIDEO_TYPES)
        if p:
            self.video.set(p)
            if not self.outdir.get():
                self.outdir.set(os.path.dirname(p))

    def pick_cover(self):
        p = filedialog.askopenfilename(title="选择封面图", filetypes=IMAGE_TYPES)
        if p:
            self.cover.set(p)

    def pick_out(self):
        p = filedialog.askdirectory(title="选择输出目录")
        if p:
            self.outdir.set(p)

    # ---- 转换 ---------------------------------------------------------
    def run(self):
        if self.busy:
            return
        src = self.video.get().strip().strip('"')
        if not os.path.isfile(src):
            messagebox.showwarning("提示", "请先选择一个存在的视频文件。")
            return
        self.busy = True
        self.btn.configure(state="disabled", text="转换中…")
        threading.Thread(target=self._work, args=(src,), daemon=True).start()

    def _work(self, src):
        try:
            tracks = lp.probe(src)
            video = next((t for t in tracks if t.kind == "video"), None)
            if video is None:
                raise lp.LivePhotoError("这个文件里没有视频轨")
            vw = int(round(video.width)) or 1920
            vh = int(round(video.height)) or 1080

            cid = str(uuidlib.uuid4()).upper()
            out_dir = self.outdir.get().strip().strip('"') or os.path.dirname(src)
            os.makedirs(out_dir, exist_ok=True)
            name = lp.safe_stem(src)
            jpg_path = os.path.join(out_dir, name + ".JPG")
            mov_path = os.path.join(out_dir, name + ".MOV")

            self.after(0, self.out, "输入：%s  (%dx%d, %.2f 秒, %s)" % (
                os.path.basename(src), vw, vh, video.seconds, video.codec))

            cover = self.cover.get().strip().strip('"')
            if cover:
                self.after(0, self.out, "封面：使用 %s" % os.path.basename(cover))
                jpeg, _ = lp.load_cover(cover, self.quality.get())
            else:
                self.after(0, self.out, "封面：正在用系统解码器抽帧…")
                raw, fw, fh = lp.extract_still(src, vw, vh)
                jpeg = lp.encode_jpeg(raw, fw, fh, self.quality.get())
                vw, vh = fw, fh

            jpeg = lp.inject_exif(jpeg, cid)
            with open(jpg_path, "wb") as f:
                f.write(jpeg)

            self.after(0, self.out, "视频：无损重封装中…")
            st = lp.remux(src, mov_path, cid, verify=True)

            self.after(0, self.out, "")
            self.after(0, self.out, "配对 ID ：%s" % cid)
            self.after(0, self.out, "封面图  ：%s" % jpg_path)
            self.after(0, self.out, "视频    ：%s" % mov_path)
            ok = bool(st.get("verified"))
            self.after(0, self.out, "无损校验：%s" % ("通过" if ok else "未通过"))
            if not ok:
                self.after(0, self.out, "  !! 采样数据与原文件不一致，请勿使用该文件")
            if video.seconds > 3.0:
                self.after(0, self.out,
                           "提示：视频 %.1f 秒，超过标准实况图的约 3 秒；"
                           "照片 App 能用，锁屏壁纸可能被系统拒绝。" % video.seconds)
            self.after(0, self.out, "")
            self.after(0, self.out, "完成。记得把这两个文件一起传到 iPhone。")
            self.after(0, messagebox.showinfo, "完成",
                       "转换完成！\n\n%s\n%s\n\n请把这两个文件一起传到 iPhone。"
                       % (os.path.basename(jpg_path), os.path.basename(mov_path)))
        except Exception as exc:
            self.after(0, self.out, "失败：%s" % exc)
            self.after(0, self.out, traceback.format_exc())
            self.after(0, messagebox.showerror, "转换失败", str(exc))
        finally:
            self.busy = False
            self.after(0, lambda: self.btn.configure(state="normal", text="开始转换"))


def main():
    App().mainloop()
    return 0
