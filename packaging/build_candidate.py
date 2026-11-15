"""Build and inspect a Windows Electron candidate without mutating main.

The script intentionally refuses to invent an installer when the Electron
workspace or electron-builder dependency is absent.  It is usable from the
integrated worktree once the UI agent adds a package.json:

    py -3 -m packaging.build_candidate inspect --project app
    py -3 -m packaging.build_candidate build --project app --output delivery/v1.0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class PackagingBlocked(RuntimeError):
    pass


@dataclass(frozen=True)
class EnvironmentReport:
    python: str
    node: str | None
    npm: str | None
    electron_project: str | None
    electron_builder: str | None
    bundled_python: str | None
    bundled_ffmpeg: str | None
    missing: tuple[str, ...]


def _version(executable: str, args: tuple[str, ...] = ("--version",)) -> str | None:
    try:
        result = subprocess.run(
            [executable, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            shell=False,
        )
    except OSError:
        return None
    if result.returncode:
        return None
    return (
        (result.stdout or result.stderr).strip().splitlines()[0]
        if (result.stdout or result.stderr)
        else None
    )


def _project_dir(project: str | os.PathLike[str]) -> Path:
    path = Path(project).resolve()
    if not path.is_dir():
        raise PackagingBlocked(f"Electron 项目目录不存在: {path}")
    return path


def inspect_environment(project: str | os.PathLike[str]) -> EnvironmentReport:
    root = _project_dir(project)
    package = root / "package.json"
    node = shutil.which("node")
    npm = shutil.which("npm")
    builder = None
    if (root / "node_modules" / ".bin" / "electron-builder.cmd").exists():
        builder = str(root / "node_modules" / ".bin" / "electron-builder.cmd")
    if package.is_file():
        try:
            payload = json.loads(package.read_text(encoding="utf-8"))
            deps = {
                **payload.get("dependencies", {}),
                **payload.get("devDependencies", {}),
            }
            if "electron-builder" in deps and builder is None:
                builder = (
                    "npm exec electron-builder (dependency declared, install required)"
                )
        except (OSError, ValueError):
            pass
    runtime = root / "runtime"
    bundled_python = runtime / "desktop-ipc-server.exe"
    bundled_ffmpeg = runtime / "ffmpeg" / "ffmpeg.exe"
    bundled_ffprobe = runtime / "ffmpeg" / "ffprobe.exe"
    missing: list[str] = []
    if not package.is_file():
        missing.append("package.json")
    if node is None:
        missing.append("node")
    if npm is None:
        missing.append("npm")
    if builder is None:
        missing.append("electron-builder")
    if not bundled_python.is_file():
        missing.append("runtime/desktop-ipc-server.exe")
    if not bundled_ffmpeg.is_file() or not bundled_ffprobe.is_file():
        missing.append("runtime/ffmpeg/ffmpeg.exe+ffprobe.exe")
    return EnvironmentReport(
        python=sys.version.split()[0],
        node=_version(node) if node else None,
        npm=_version(npm) if npm else None,
        electron_project=str(root) if package.is_file() else None,
        electron_builder=builder,
        bundled_python=str(bundled_python) if bundled_python.is_file() else None,
        bundled_ffmpeg=str(bundled_ffmpeg) if bundled_ffmpeg.is_file() else None,
        missing=tuple(missing),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_licenses(project: Path, output: Path, environment: EnvironmentReport) -> Path:
    package = project / "package.json"
    package_payload: dict[str, Any] = {}
    if package.is_file():
        try:
            package_payload = json.loads(package.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    manifest = {
        "schema_version": 1,
        "application": package_payload.get("name", "video2livephoto"),
        "application_version": package_payload.get("version", "unknown"),
        "source_license": "MIT (original project; retain copyright notice)",
        "dependencies": {
            "electron": package_payload.get("devDependencies", {}).get("electron")
            or package_payload.get("dependencies", {}).get("electron"),
            "electron-builder": package_payload.get("devDependencies", {}).get(
                "electron-builder"
            )
            or package_payload.get("dependencies", {}).get("electron-builder"),
            "python": "Python runtime must be bundled or explicitly declared; external Python is not accepted for final Windows candidate",
            "ffmpeg": "Build-specific GPL/LGPL and codec redistribution review required before release",
        },
        "environment": asdict(environment),
        "unsigned": True,
        "notes": [
            "This is a local candidate manifest, not a public release approval.",
            "iPhone/Photos compatibility remains external device validation.",
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    path = output / "THIRD_PARTY_LICENSES.json"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def build_candidate(
    project: str | os.PathLike[str],
    output: str | os.PathLike[str],
    *,
    install_deps: bool = False,
) -> Path:
    root = _project_dir(project)
    destination = Path(output).resolve()
    environment = inspect_environment(root)
    if environment.missing:
        raise PackagingBlocked("候选打包依赖缺失: " + ", ".join(environment.missing))
    package = root / "package.json"
    if install_deps:
        lock = root / "package-lock.json"
        npm_executable = shutil.which("npm.cmd") or shutil.which("npm") or "npm.cmd"
        command = (
            [npm_executable, "ci"] if lock.is_file() else [npm_executable, "install"]
        )
        result = subprocess.run(command, cwd=root, shell=False, check=False)
        if result.returncode:
            raise PackagingBlocked(f"依赖安装失败，返回码 {result.returncode}")
        environment = inspect_environment(root)
    builder = root / "node_modules" / ".bin" / "electron-builder.cmd"
    npm_executable = shutil.which("npm.cmd") or shutil.which("npm")
    if not builder.exists():
        # `npm exec` is only attempted when electron-builder is declared, so an
        # offline machine reports a concrete missing dependency instead of
        # silently downloading an arbitrary version.
        deps = json.loads(package.read_text(encoding="utf-8")).get(
            "devDependencies", {}
        )
        if "electron-builder" not in deps:
            raise PackagingBlocked("package.json 未声明 electron-builder")
        command = [
            npm_executable or "npm.cmd",
            "exec",
            "--offline",
            "--",
            "electron-builder",
            "--win",
            "nsis",
            "--config.directories.output=" + str(destination),
        ]
    else:
        command = [
            npm_executable or "npm.cmd",
            "exec",
            "--offline",
            "--",
            "electron-builder",
            "--win",
            "nsis",
            "--config.directories.output=" + str(destination),
        ]
    destination.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(command, cwd=root, shell=False, check=False)
    if result.returncode:
        raise PackagingBlocked(f"electron-builder 失败，返回码 {result.returncode}")
    installers = sorted(destination.glob("*.exe"))
    if not installers:
        raise PackagingBlocked("electron-builder 未生成 .exe 候选包")
    package_path = installers[0]
    write_licenses(root, destination, environment)
    (destination / "CANDIDATE_SHA256.txt").write_text(
        f"{_sha256(package_path)}  {package_path.name}\n",
        encoding="utf-8",
        newline="\n",
    )
    return package_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--project", required=True)
    build = sub.add_parser("build")
    build.add_argument("--project", required=True)
    build.add_argument("--output", required=True)
    build.add_argument("--install-deps", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            report = inspect_environment(args.project)
            print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
            return 0 if not report.missing else 2
        package = build_candidate(
            args.project, args.output, install_deps=args.install_deps
        )
        print(
            json.dumps(
                {"ok": True, "installer": str(package), "sha256": _sha256(package)},
                ensure_ascii=False,
            )
        )
        return 0
    except PackagingBlocked as exc:
        print(json.dumps({"ok": False, "blocked": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
