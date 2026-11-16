# -*- coding: utf-8 -*-
"""Build the supported Windows desktop package.

The former PyInstaller entry point packaged the retired Tk GUI, which emitted a
JPG/MOV pair and bypassed the desktop LIVP export pipeline.  Keep this filename
as a compatibility entry point, but route it to the Electron builder so every
installer contains the same single-file export implementation.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def main() -> int:
    npm = "npm.cmd" if os.name == "nt" else "npm"
    command = [npm, "run", "package:win"]
    print(">>> " + " ".join(command))
    completed = subprocess.run(command, cwd=ROOT, check=False)
    if completed.returncode:
        raise SystemExit(f"现代桌面安装包构建失败，返回码 {completed.returncode}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
