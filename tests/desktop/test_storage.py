from __future__ import annotations

from pathlib import Path

from desktop.storage import StorageVolume, select_default_volume


def test_select_default_volume_prefers_non_system_ssd_with_most_free_space() -> None:
    volumes = [
        StorageVolume(Path("C:/"), free_bytes=900, total_bytes=1_000, is_ssd=True),
        StorageVolume(Path("E:/"), free_bytes=5_000, total_bytes=7_000, is_ssd=True),
        StorageVolume(Path("F:/"), free_bytes=8_000, total_bytes=9_000, is_ssd=False),
        StorageVolume(Path("L:/"), free_bytes=3_000, total_bytes=8_000, is_ssd=True),
    ]

    selected = select_default_volume(volumes, system_drive="C:")

    assert selected.root == Path("E:/")


def test_select_default_volume_falls_back_to_non_system_volume_without_ssd_metadata() -> None:
    volumes = [
        StorageVolume(Path("C:/"), free_bytes=9_000, total_bytes=10_000, is_ssd=None),
        StorageVolume(Path("D:/"), free_bytes=2_000, total_bytes=3_000, is_ssd=None),
        StorageVolume(Path("E:/"), free_bytes=4_000, total_bytes=5_000, is_ssd=None),
    ]

    selected = select_default_volume(volumes, system_drive="C:")

    assert selected.root == Path("E:/")
