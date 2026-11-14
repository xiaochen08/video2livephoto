from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from core.protocol.media import MediaError


def _creation_flags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ToolInfo:
    path: str
    version_line: str
    version: str
    sha256: str


@dataclass(frozen=True)
class Toolchain:
    ffmpeg: ToolInfo
    ffprobe: ToolInfo
    config_version: str = "m1-toolchain.v1"

    @classmethod
    def from_paths(
        cls,
        ffmpeg_path: str | os.PathLike[str],
        ffprobe_path: str | os.PathLike[str],
        *,
        expected_ffmpeg_sha256: str | None = None,
        expected_ffprobe_sha256: str | None = None,
    ) -> "Toolchain":
        ffmpeg = _inspect_tool(Path(ffmpeg_path), "ffmpeg", expected_ffmpeg_sha256)
        ffprobe = _inspect_tool(Path(ffprobe_path), "ffprobe", expected_ffprobe_sha256)
        return cls(ffmpeg=ffmpeg, ffprobe=ffprobe)

    @classmethod
    def discover(cls) -> "Toolchain":
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            raise MediaError(
                code="TOOLCHAIN_MISSING",
                stage="toolchain",
                path=None,
                stream_index=None,
                retryable=False,
                message="缺少可用的 ffmpeg 或 ffprobe",
                diagnostics={"ffmpeg": ffmpeg, "ffprobe": ffprobe},
            )
        return cls.from_paths(ffmpeg, ffprobe)

    def to_dict(self) -> dict[str, object]:
        return {
            "config_version": self.config_version,
            "ffmpeg": self.ffmpeg.__dict__.copy(),
            "ffprobe": self.ffprobe.__dict__.copy(),
        }

    def run_version(self, executable: str, timeout_seconds: float = 10.0) -> str:
        result = subprocess.run(
            [executable, "-version"],
            shell=False,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            creationflags=_creation_flags(),
        )
        if result.returncode != 0:
            raise MediaError(
                code="TOOLCHAIN_INCOMPATIBLE",
                stage="toolchain",
                path=executable,
                stream_index=None,
                retryable=False,
                message="媒体工具无法执行版本自检",
                diagnostics={
                    "returncode": result.returncode,
                    "stderr": result.stderr[-2000:],
                },
            )
        return result.stdout.splitlines()[0] if result.stdout else ""


def _inspect_tool(path: Path, label: str, expected_sha256: str | None) -> ToolInfo:
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise MediaError(
            code="TOOLCHAIN_MISSING",
            stage="toolchain",
            path=str(path),
            stream_index=None,
            retryable=False,
            message=f"缺少 {label} 可执行文件",
        ) from exc
    if not resolved.is_file():
        raise MediaError(
            code="TOOLCHAIN_INCOMPATIBLE",
            stage="toolchain",
            path=str(resolved),
            stream_index=None,
            retryable=False,
            message=f"{label} 路径不是普通文件",
        )
    result = subprocess.run(
        [str(resolved), "-version"],
        shell=False,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        creationflags=_creation_flags(),
    )
    if result.returncode != 0 or not result.stdout:
        raise MediaError(
            code="TOOLCHAIN_INCOMPATIBLE",
            stage="toolchain",
            path=str(resolved),
            stream_index=None,
            retryable=False,
            message=f"{label} 版本自检失败",
            diagnostics={
                "returncode": result.returncode,
                "stderr": result.stderr[-2000:],
            },
        )
    version_line = result.stdout.splitlines()[0]
    match = re.search(r"version\s+([^\s]+)", version_line)
    version = match.group(1) if match else version_line
    sha256 = _hash_file(resolved)
    if expected_sha256 and sha256.lower() != expected_sha256.lower():
        raise MediaError(
            code="TOOLCHAIN_MISMATCH",
            stage="toolchain",
            path=str(resolved),
            stream_index=None,
            retryable=False,
            message=f"{label} SHA-256 与冻结值不一致",
            diagnostics={"expected": expected_sha256, "actual": sha256},
        )
    return ToolInfo(str(resolved), version_line, version, sha256)


def process_creation_flags() -> int:
    return _creation_flags()


def ensure_executable_args(args: Sequence[str]) -> list[str]:
    """Return a copy for auditability; shell expansion is never used."""
    return [str(arg) for arg in args]


def query_private_bytes(pid: int | None = None) -> int | None:
    """Best-effort Windows PrivateUsage measurement without a third-party package."""
    if os.name != "nt":
        return None
    import ctypes

    class _CountersEx(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    handle = (
        kernel32.GetCurrentProcess()
        if pid is None
        else kernel32.OpenProcess(0x0410, False, pid)
    )
    if not handle:
        return None
    try:
        counters = _CountersEx()
        counters.cb = ctypes.sizeof(_CountersEx)
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return None
        return int(counters.PrivateUsage)
    finally:
        if pid is not None:
            kernel32.CloseHandle(handle)


class ProcessMemorySampler:
    def __init__(self, pid: int, interval_seconds: float = 0.05) -> None:
        self.pid = pid
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.peak_private_bytes: int | None = None

    def start(self) -> None:
        def sample() -> None:
            while not self._stop.is_set():
                current = query_private_bytes(self.pid)
                if current is not None:
                    self.peak_private_bytes = max(self.peak_private_bytes or 0, current)
                self._stop.wait(self.interval_seconds)

        self._thread = threading.Thread(
            target=sample, name="m1-memory-sampler", daemon=True
        )
        self._thread.start()

    def stop(self) -> int | None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        return self.peak_private_bytes
