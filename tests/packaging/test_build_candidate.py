from __future__ import annotations

import json

from packaging.build_candidate import inspect_environment, write_licenses


def test_packaging_reports_missing_electron_project(tmp_path):
    report = inspect_environment(tmp_path)
    assert "package.json" in report.missing
    assert "electron-builder" in report.missing


def test_license_manifest_is_explicit_about_unsigned_candidate(tmp_path):
    report = inspect_environment(tmp_path)
    manifest = write_licenses(tmp_path, tmp_path / "out", report)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["unsigned"] is True
    assert "ffmpeg" in payload["dependencies"]
