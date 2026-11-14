from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.media.errors import MediaError
from core.media.fragment_inspector import inspect_fragments
from core.media.frame_index import build_frame_index
from core.media.normalize import normalize_fragmented
from core.media.probe import probe_media
from core.media.toolchain import Toolchain


def _toolchain(args: argparse.Namespace) -> Toolchain:
    if bool(args.ffmpeg) != bool(args.ffprobe):
        raise MediaError(
            code="TOOLCHAIN_ARGUMENTS",
            stage="diagnostic",
            path=None,
            stream_index=None,
            retryable=False,
            message="--ffmpeg 与 --ffprobe 必须同时提供",
        )
    return (
        Toolchain.from_paths(args.ffmpeg, args.ffprobe)
        if args.ffmpeg
        else Toolchain.discover()
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m core.media.diagnostic")
    parser.add_argument("--ffmpeg")
    parser.add_argument("--ffprobe")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("probe", "index", "inspect-fragments", "normalize"):
        command = sub.add_parser(name)
        command.add_argument("path")
        if name == "probe":
            command.add_argument("--full-sha256", action="store_true")
        if name in {"index", "normalize"}:
            command.add_argument("--cache-root", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    args = _parser().parse_args(argv)
    try:
        if args.command == "inspect-fragments":
            result = inspect_fragments(args.path)
            payload = {
                "ok": True,
                "result": {
                    "is_fragmented": result.is_fragmented,
                    "has_moof": result.has_moof,
                    "has_mvex": result.has_mvex,
                    "top_level_boxes": [
                        item.decode("latin1") for item in result.top_level_boxes
                    ],
                    "diagnostics": list(result.diagnostics),
                },
            }
        else:
            toolchain = _toolchain(args)
            if args.command == "probe":
                payload = {
                    "ok": True,
                    "result": probe_media(
                        args.path,
                        toolchain=toolchain,
                        include_full_sha256=args.full_sha256,
                    ).to_dict(),
                }
            elif args.command == "index":
                payload = {
                    "ok": True,
                    "result": build_frame_index(
                        args.path,
                        cache_root=Path(args.cache_root),
                        toolchain=toolchain,
                    ).to_dict(),
                }
            else:
                payload = {
                    "ok": True,
                    "result": normalize_fragmented(
                        args.path,
                        cache_root=Path(args.cache_root),
                        toolchain=toolchain,
                    ).to_dict(),
                }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except MediaError as exc:
        print(
            json.dumps(
                {"ok": False, "error": exc.to_dict()}, ensure_ascii=False, indent=2
            )
        )
        return 2
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "DIAGNOSTIC_FAILED",
                        "message": str(exc),
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 3


if __name__ == "__main__":
    sys.exit(main())
