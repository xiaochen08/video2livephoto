from __future__ import annotations

import json
import sys
from typing import Any

from .models import M3ProjectError
from .service import M3ProjectService


class JsonlIpcServer:
    """Versioned JSONL bridge for Electron main/preload.

    One request per line and one response per line keeps the bridge usable in
    a frozen Python worker and easy to diagnose from a Windows log file.
    """

    PROTOCOL = "m3.ipc.v1"

    def __init__(self) -> None:
        self.service: M3ProjectService | None = None

    def run(self) -> int:
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                request = json.loads(line)
                response = self.handle(request)
            except Exception as exc:  # keep the worker alive for the next request
                response = {
                    "ok": False,
                    "error": {
                        "code": getattr(exc, "code", "IPC_ERROR"),
                        "message": str(exc),
                        "details": getattr(exc, "details", {}),
                    },
                }
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        if self.service is not None:
            self.service.close()
        return 0

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        if request.get("protocol", self.PROTOCOL) != self.PROTOCOL:
            raise M3ProjectError("IPC_VERSION_UNSUPPORTED", "IPC 协议版本不受支持。")
        method = str(request.get("method", ""))
        params = dict(request.get("params") or {})
        if method == "ping":
            return {"ok": True, "protocol": self.PROTOCOL, "service": "m3-python"}
        if method == "import":
            self.service = M3ProjectService.import_media(
                params["source_path"],
                project_path=params["project_path"],
                cache_root=params.get("cache_root"),
            )
            return {"ok": True, "project": self.service.to_dict()}
        if method == "open":
            if self.service is not None:
                self.service.close()
            self.service = M3ProjectService.open_project(params["project_path"])
            return {"ok": True, "project": self.service.to_dict()}
        if self.service is None:
            raise M3ProjectError("PROJECT_NOT_OPEN", "请先导入或打开项目。")
        if method == "state":
            return {"ok": True, "project": self.service.to_dict()}
        if method == "frame_window":
            frames = self.service.frame_window(
                int(params["center_index"]), int(params.get("radius", 3))
            )
            return {"ok": True, "frames": [frame.__dict__ for frame in frames]}
        if method == "add_cut":
            self.service.add_cut(
                int(params["boundary_index"]),
                needs_review=bool(params.get("needs_review", True)),
            )
        elif method == "move_cut":
            self.service.move_cut(str(params["cut_id"]), int(params["boundary_index"]))
        elif method == "delete_cut":
            self.service.delete_cut(str(params["cut_id"]))
        elif method == "merge_segments":
            self.service.merge_segments(
                str(params["left_clip_id"]),
                str(params["right_clip_id"]),
                audio_enabled=params.get("audio_enabled"),
            )
        elif method == "set_segment_audio":
            self.service.set_segment_audio(
                str(params["clip_id"]), bool(params["enabled"])
            )
        elif method == "set_all_audio":
            self.service.set_all_audio(bool(params["enabled"]))
        elif method == "mark_cut_checked":
            self.service.mark_cut_checked(
                str(params["cut_id"]), bool(params.get("checked", True))
            )
        elif method == "undo":
            self.service.undo()
        elif method == "redo":
            self.service.redo()
        elif method == "confirm_export":
            return {
                "ok": True,
                "export": self.service.confirm_export(
                    allow_unreviewed=bool(params.get("allow_unreviewed", False))
                ),
            }
        else:
            raise M3ProjectError("IPC_METHOD_UNKNOWN", f"未知 IPC 方法：{method}")
        return {"ok": True, "project": self.service.to_dict()}


def main() -> int:
    return JsonlIpcServer().run()


if __name__ == "__main__":
    raise SystemExit(main())
