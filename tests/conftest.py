from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def ffmpeg_path() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        pytest.skip("ffmpeg is not available")
    return path


@pytest.fixture(scope="session")
def ffprobe_path() -> str:
    path = shutil.which("ffprobe")
    if not path:
        pytest.skip("ffprobe is not available")
    return path


def _run_ffmpeg(ffmpeg: str, args: list[str]) -> None:
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        raise RuntimeError(result.stderr)


@pytest.fixture()
def small_mp4(tmp_path: Path, ffmpeg_path: str) -> Path:
    path = tmp_path / "普通 中文 sample.mp4"
    _run_ffmpeg(
        ffmpeg_path,
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x240:rate=30",
            "-t",
            "1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-shortest",
            "-c:v",
            "libx264",
            "-bf",
            "2",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ],
    )
    return path


@pytest.fixture()
def vfr_mp4(tmp_path: Path, ffmpeg_path: str) -> Path:
    path = tmp_path / "vfr.mp4"
    _run_ffmpeg(
        ffmpeg_path,
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=30",
            "-t",
            "1.2",
            "-vf",
            "select='if(lt(n,10),1,not(mod(n,3)))',setpts='if(lt(N,10),N,10+(N-10)*3)/30/TB'",
            "-fps_mode",
            "vfr",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
    )
    return path


@pytest.fixture()
def fragmented_mp4(tmp_path: Path, ffmpeg_path: str) -> Path:
    path = tmp_path / "fragmented.mp4"
    _run_ffmpeg(
        ffmpeg_path,
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=30",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+frag_keyframe+empty_moov+default_base_moof",
            str(path),
        ],
    )
    return path


@pytest.fixture()
def fragmented_av_mp4(tmp_path: Path, ffmpeg_path: str) -> Path:
    path = tmp_path / "fragmented-av.mp4"
    _run_ffmpeg(
        ffmpeg_path,
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-bf",
            "2",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-movflags",
            "+frag_keyframe+empty_moov+default_base_moof",
            str(path),
        ],
    )
    return path


@pytest.fixture()
def negative_pts_edit_list_mp4(tmp_path: Path, ffmpeg_path: str) -> Path:
    path = tmp_path / "negative-audio-pts-edit-list.mp4"
    _run_ffmpeg(
        ffmpeg_path,
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            "1",
            "-filter_complex",
            "[1:a]adelay=500:all=1[a]",
            "-map",
            "0:v",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-bf",
            "2",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ],
    )
    return path


@pytest.fixture()
def hard_cut_mp4(tmp_path: Path, ffmpeg_path: str) -> Path:
    path = tmp_path / "hard-cut.mp4"
    _run_ffmpeg(
        ffmpeg_path,
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=red:size=160x90:rate=30:d=0.5",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:size=160x90:rate=30:d=0.5",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-g",
            "1",
            str(path),
        ],
    )
    return path


@pytest.fixture()
def black_transition_mp4(tmp_path: Path, ffmpeg_path: str) -> Path:
    path = tmp_path / "black-transition.mp4"
    _run_ffmpeg(
        ffmpeg_path,
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=red:size=160x90:rate=30:d=0.4",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:size=160x90:rate=30:d=0.2",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:size=160x90:rate=30:d=0.4",
            "-filter_complex",
            "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-g",
            "1",
            str(path),
        ],
    )
    return path


@pytest.fixture()
def dissolve_mp4(tmp_path: Path, ffmpeg_path: str) -> Path:
    path = tmp_path / "dissolve.mp4"
    _run_ffmpeg(
        ffmpeg_path,
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=red:size=160x90:rate=30:d=1",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:size=160x90:rate=30:d=1",
            "-filter_complex",
            "[0:v][1:v]xfade=transition=fade:duration=0.4:offset=0.6[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-g",
            "1",
            str(path),
        ],
    )
    return path


@pytest.fixture()
def short_shot_sequence_mp4(tmp_path: Path, ffmpeg_path: str) -> Path:
    path = tmp_path / "short-shot-sequence.mp4"
    _run_ffmpeg(
        ffmpeg_path,
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=yellow:size=160x90:rate=30:d=0.2",
            "-f",
            "lavfi",
            "-i",
            "color=c=green:size=160x90:rate=30:d=1.0",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-g",
            "1",
            str(path),
        ],
    )
    return path
