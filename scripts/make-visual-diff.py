from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageChops, ImageEnhance


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "evidence"


def compare(name: str) -> dict[str, float | str]:
    reference = Image.open(EVIDENCE / f"reference-20261115-{name}-1440x900.png").convert("RGBA")
    target = Image.open(EVIDENCE / f"target-20261115-{name}-1440x900.png").convert("RGBA")
    if reference.size != target.size:
        raise RuntimeError(f"size mismatch for {name}: {reference.size} != {target.size}")
    overlay = Image.blend(reference, target, 0.5)
    diff = ImageChops.difference(reference, target).convert("RGB")
    diff = ImageEnhance.Brightness(diff).enhance(3.0)
    overlay.save(EVIDENCE / f"{name}-overlay-1440x900.png")
    diff.save(EVIDENCE / f"{name}-diff-1440x900.png")
    raw = ImageChops.difference(reference.convert("RGB"), target.convert("RGB"))
    values = list(raw.getdata())
    mean = sum(sum(pixel) / 3 for pixel in values) / len(values)
    maximum = max(max(pixel) for pixel in values)
    changed = sum(1 for pixel in values if max(pixel) > 8) / len(values)
    return {"mean_abs_channel": round(mean, 3), "max_abs_channel": maximum, "changed_pixel_ratio_gt8": round(changed, 4)}


metrics = {name: compare(name) for name in ("home", "editor")}
(EVIDENCE / "visual-diff-metrics-20261115.json").write_text(
    json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
)
print(json.dumps(metrics, ensure_ascii=False))
