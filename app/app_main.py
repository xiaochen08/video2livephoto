# -*- coding: utf-8 -*-
"""程序入口：默认打开图形界面。

隐藏参数（给自动化/诊断用）：
    --uninstall [--yes]              卸载
    --selftest <video> <outdir> <json>   跑一次真实转换并把结果写到 json
"""
import json
import os
import sys


def _selftest(argv):
    import traceback
    try:
        import livephoto as lp
        video, outdir, outjson = argv[1], argv[2], argv[3]
        result = {"ok": False}
        try:
            from PIL import Image  # noqa: F401
            result["pillow"] = True
        except Exception as e:
            result["pillow"] = "missing: %s" % e
        tracks = lp.probe(video)
        v = next(t for t in tracks if t.kind == "video")
        result["source"] = {"w": int(v.width), "h": int(v.height),
                            "codec": v.codec, "seconds": round(v.seconds, 3)}
        import uuid as uuidlib
        cid = str(uuidlib.uuid4()).upper()
        os.makedirs(outdir, exist_ok=True)
        raw, fw, fh = lp.extract_still(video, int(v.width), int(v.height))
        jpeg = lp.inject_exif(lp.encode_jpeg(raw, fw, fh, 95), cid)
        jpg = os.path.join(outdir, "SELFTEST.JPG")
        mov = os.path.join(outdir, "SELFTEST.MOV")
        with open(jpg, "wb") as f:
            f.write(jpeg)
        st = lp.remux(video, mov, cid, verify=True)
        result["uuid"] = cid
        result["jpg_readback"] = lp.read_apple_makernote(jpeg)
        result["lossless"] = st.get("verified")
        result["still"] = [fw, fh]
        result["ok"] = bool(result["jpg_readback"] == cid and result["lossless"])
        with open(outjson, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        return 0
    except Exception:
        try:
            with open(argv[3], "w", encoding="utf-8") as f:
                json.dump({"ok": False, "error": traceback.format_exc()}, f,
                          ensure_ascii=False, indent=1)
        except Exception:
            pass
        return 1


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--uninstall":
        import uninstall
        return uninstall.run("--yes" in argv)
    if argv and argv[0] == "--selftest" and len(argv) >= 4:
        return _selftest(argv)
    if argv and argv[0] == "--check-update":
        import update as upd
        r = upd.check()
        out = {"current": upd.CURRENT_VERSION, "has_update": r["has_update"],
               "latest": r["version"], "url": r["url"], "notes": r["notes"],
               "error": r["error"]}
        text = json.dumps(out, ensure_ascii=False, indent=1)
        # 窗口化程序没有控制台，给个文件参数方便自动化验证
        if len(argv) >= 2 and argv[1]:
            try:
                with open(argv[1], "w", encoding="utf-8") as f:
                    f.write(text)
            except Exception:
                pass
        print(text)
        return 1 if r["has_update"] else (2 if r["error"] else 0)
    if argv and argv[0] == "--version":
        import livephoto as lp
        print(lp.VERSION)
        return 0

    from gui import App
    App().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
