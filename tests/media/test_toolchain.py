from __future__ import annotations

import subprocess

import pytest

from core.media.errors import MediaError
from core.media.toolchain import ToolInfo, Toolchain, probe_gpu_encoder


def test_toolchain_records_versions_and_hashes(
    ffmpeg_path: str, ffprobe_path: str
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    payload = toolchain.to_dict()
    assert payload["ffmpeg"]["version"]
    assert len(payload["ffmpeg"]["sha256"]) == 64
    assert payload["ffprobe"]["version"]
    assert len(payload["ffprobe"]["sha256"]) == 64


def test_toolchain_rejects_hash_mismatch(ffmpeg_path: str, ffprobe_path: str) -> None:
    with pytest.raises(MediaError) as exc:
        Toolchain.from_paths(
            ffmpeg_path,
            ffprobe_path,
            expected_ffmpeg_sha256="0" * 64,
        )
    assert exc.value.code == "TOOLCHAIN_MISMATCH"


def test_default_discovery_uses_the_frozen_manifest() -> None:
    toolchain = Toolchain.discover()
    assert toolchain.ffmpeg.version == "N-120646-g6711c6a89b-20250810"
    assert toolchain.ffprobe.version == "N-120646-g6711c6a89b-20250810"


def test_gpu_probe_requires_a_real_encoder_start(monkeypatch: pytest.MonkeyPatch) -> None:
    toolchain = Toolchain(
        ffmpeg=ToolInfo("ffmpeg.exe", "ffmpeg version test", "test", "0" * 64),
        ffprobe=ToolInfo("ffprobe.exe", "ffprobe version test", "test", "0" * 64),
    )
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(args, **kwargs):
        calls.append((list(args), kwargs))
        return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("core.media.toolchain.subprocess.run", fake_run)

    encoder, note = probe_gpu_encoder(toolchain)

    assert encoder == "h264_nvenc"
    assert "h264_nvenc" in note
    assert calls[0][0][calls[0][0].index("-f") + 1] == "lavfi"
    assert "-frames:v" in calls[0][0]
    assert calls[0][1]["stdin"] is subprocess.DEVNULL
