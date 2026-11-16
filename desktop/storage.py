from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class StorageVolume:
    """A mounted fixed volume that can hold project and export data."""

    root: Path
    free_bytes: int
    total_bytes: int
    is_ssd: bool | None


def _drive_key(path: Path | str) -> str:
    return str(path).rstrip("\\/").upper()


def select_default_volume(
    volumes: Iterable[StorageVolume], *, system_drive: str = "C:"
) -> StorageVolume:
    """Choose the non-system SSD with the most free space.

    When SSD metadata is unavailable, all non-system fixed volumes are eligible.
    The system volume is used only as a last resort on single-volume machines.
    """

    values = list(volumes)
    if not values:
        raise ValueError("no storage volumes available")
    system_key = _drive_key(system_drive)
    non_system = [item for item in values if _drive_key(item.root) != system_key]
    candidates = non_system or values
    known_ssd = [item for item in candidates if item.is_ssd is True]
    if known_ssd:
        candidates = known_ssd
    return max(candidates, key=lambda item: (item.free_bytes, item.total_bytes))


def _creation_flags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _discover_ssd_volumes() -> list[StorageVolume]:
    if os.name != "nt":
        return []
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        return []
    script = r"""
$ssd = @(
  Get-PhysicalDisk -ErrorAction Stop |
    Where-Object { $_.MediaType -eq 'SSD' } |
    ForEach-Object { [int]$_.DeviceId }
)
$rows = @(
  Get-Partition -ErrorAction Stop |
    Where-Object { $null -ne $_.DriveLetter -and $ssd -contains [int]$_.DiskNumber } |
    ForEach-Object {
      $volume = Get-Volume -DriveLetter $_.DriveLetter -ErrorAction SilentlyContinue
      if ($null -ne $volume -and $volume.Size -gt 0) {
        [pscustomobject]@{
          drive = "$($_.DriveLetter):"
          free = [int64]$volume.SizeRemaining
          total = [int64]$volume.Size
        }
      }
    }
)
$rows | ConvertTo-Json -Compress
"""
    try:
        result = subprocess.run(
            [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            shell=False,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3.0,
            creationflags=_creation_flags(),
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        payload = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return []
    rows = payload if isinstance(payload, list) else [payload]
    volumes: list[StorageVolume] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        drive = str(row.get("drive") or "").strip()
        if not drive:
            continue
        root = Path(f"{drive.rstrip('\\/')}\\")
        try:
            free_bytes = int(row.get("free", 0))
            total_bytes = int(row.get("total", 0))
        except (TypeError, ValueError):
            continue
        if total_bytes > 0:
            volumes.append(StorageVolume(root, free_bytes, total_bytes, True))
    return volumes


def _discover_fixed_volumes() -> list[StorageVolume]:
    if os.name != "nt":
        try:
            usage = shutil.disk_usage(Path("/"))
        except OSError:
            return []
        return [StorageVolume(Path("/"), usage.free, usage.total, None)]

    get_drive_type = ctypes.windll.kernel32.GetDriveTypeW
    volumes: list[StorageVolume] = []
    for index in range(26):
        letter = chr(ord("A") + index)
        root = Path(f"{letter}:\\")
        if int(get_drive_type(str(root))) != 3:  # DRIVE_FIXED
            continue
        try:
            usage = shutil.disk_usage(root)
        except OSError:
            continue
        volumes.append(StorageVolume(root, usage.free, usage.total, None))
    return volumes


def discover_storage_volumes() -> list[StorageVolume]:
    ssd_volumes = _discover_ssd_volumes()
    return ssd_volumes or _discover_fixed_volumes()


def _system_drive() -> str:
    if os.name == "nt":
        return os.environ.get("SystemDrive", "C:")
    return "/"


@lru_cache(maxsize=1)
def default_storage_root() -> Path:
    """Return ``<largest eligible drive>:\\Video2LivePhoto`` for this session."""

    volumes = discover_storage_volumes()
    try:
        selected = select_default_volume(volumes, system_drive=_system_drive())
        return selected.root / "Video2LivePhoto"
    except ValueError:
        fallback = Path(os.environ.get("SystemDrive", "C:\\"))
        return fallback / "Video2LivePhoto"
