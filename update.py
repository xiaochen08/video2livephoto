# -*- coding: utf-8 -*-
"""版本检查 / 在线更新。

服务端只要放一个静态文件即可，默认地址：
    https://yiyangzai.cn/livephoto/version.json

内容可以是 JSON：
    {
      "version": "1.1.0",
      "url": "https://yiyangzai.cn/livephoto/视频转实况图-Setup.exe",
      "notes": "修复了 xxx；新增了 yyy",
      "mandatory": false
    }

也可以只放一行纯文本版本号（向后兼容）：
    1.1.0
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import threading
import urllib.error
import urllib.request

APP_NAME = "视频转实况图"
CURRENT_VERSION = "1.1.0"

# 默认更新地址；可用环境变量 LIVEPHOTO_UPDATE_URL 覆盖（方便测试/换域名）
DEFAULT_UPDATE_URL = "https://yiyangzai.cn/livephoto/version.json"
HOMEPAGE = "https://yiyangzai.cn"
TIMEOUT = 6
UA = "LivePhotoMaker/%s (+%s)" % (CURRENT_VERSION, HOMEPAGE)


def update_url() -> str:
    return os.environ.get("LIVEPHOTO_UPDATE_URL", DEFAULT_UPDATE_URL).strip()


def parse_version(text):
    """把 '1.2.3' / 'v1.2.3' / '1.2.3-beta' 解析成可比较的元组。"""
    s = str(text).strip().lstrip("vV")
    parts = []
    for chunk in s.replace("-", ".").replace("_", ".").split("."):
        num = ""
        for ch in chunk:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:4])


def is_newer(remote, local=CURRENT_VERSION) -> bool:
    return parse_version(remote) > parse_version(local)


def _ssl_context():
    """尽量用系统证书；实在不行退回不校验（只用于读取一个版本号）。"""
    try:
        ctx = ssl.create_default_context()
        return ctx
    except Exception:
        return ssl._create_unverified_context()      # noqa: SLF001


def fetch_manifest(url=None, timeout=TIMEOUT):
    """拉取版本信息。返回 dict 或抛异常。"""
    url = url or update_url()
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    })
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        raw = resp.read(65536).decode("utf-8", "replace").strip()
    if not raw:
        raise ValueError("服务器返回空内容")
    if raw.lstrip().startswith("{"):
        data = json.loads(raw)
    else:
        data = {"version": raw.splitlines()[0].strip()}
    version = str(data.get("version", "")).strip()
    if not version:
        raise ValueError("版本信息里没有 version 字段")
    return {
        "version": version,
        "url": str(data.get("url", "") or "").strip(),
        "notes": str(data.get("notes", "") or "").strip(),
        "mandatory": bool(data.get("mandatory", False)),
        "raw": data,
    }


def check(url=None, timeout=TIMEOUT):
    """检查更新。

    返回 dict： {'has_update': bool, 'version':..., 'url':..., 'notes':..., 'error': None|str}
    永不由网络问题抛异常——查不到就安静地返回 has_update=False。
    """
    result = {"has_update": False, "version": "", "url": "", "notes": "",
              "mandatory": False, "current": CURRENT_VERSION, "error": None}
    try:
        m = fetch_manifest(url, timeout)
        result["version"] = m["version"]
        result["url"] = m["url"] or HOMEPAGE
        result["notes"] = m["notes"]
        result["mandatory"] = m["mandatory"]
        result["has_update"] = is_newer(m["version"])
    except urllib.error.HTTPError as e:
        result["error"] = "服务器返回 HTTP %s" % e.code
    except urllib.error.URLError as e:
        result["error"] = "连不上服务器（%s）" % getattr(e, "reason", e)
    except Exception as e:                       # 超时、JSON 坏、DNS 失败……
        result["error"] = "%s: %s" % (type(e).__name__, e)
    return result


def check_async(callback, url=None, timeout=TIMEOUT):
    """后台线程里检查，结果回调 callback(result)。界面不会被卡住。"""
    def worker():
        try:
            callback(check(url, timeout))
        except Exception as e:                   # 回调自己炸了也不能影响主线程
            try:
                callback({"has_update": False, "error": str(e), "version": "",
                          "url": "", "notes": "", "mandatory": False,
                          "current": CURRENT_VERSION})
            except Exception:
                pass

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return t


def open_url(url):
    """用系统默认浏览器打开链接。"""
    try:
        if sys.platform == "win32":
            os.startfile(url)                    # type: ignore[attr-defined]
        else:
            import webbrowser
            webbrowser.open(url)
        return True
    except Exception:
        return False


def download(url, dest_path, progress=None, timeout=60):
    """把安装包下载到 dest_path。progress(已下载, 总大小) 可为 None。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        tmp = dest_path + ".part"
        with open(tmp, "wb") as f:
            while True:
                chunk = resp.read(262144)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if os.path.exists(dest_path):
            os.remove(dest_path)
        os.rename(tmp, dest_path)
    return dest_path
