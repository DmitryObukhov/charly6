"""Hexagonal spiral folding generator."""

from __future__ import annotations

import math
from typing import Any


def Generate(
    N: int,
    min_x: float = 0.0,
    max_x: float = 1.0,
    min_y: float = 0.0,
    max_y: float = 1.0,
    x: float = 0.5,
    y: float = 0.5,
    d: str | float | int = "clockwise",
    R: int | None = None,
    options: Any = "",
) -> list[tuple[float, float]]:
    """Return N points on a hexagonal spiral starting at (x, y)."""
    count = int(N)
    if count <= 0:
        return []
    opts = _options_dict(options)
    spacing = _spacing(opts, count, min_x, max_x, min_y, max_y)
    clockwise = _clockwise(opts.get("clockwise", opts.get("direction", d)))
    offsets = [(0.0, 0.0), *_hex_spiral_offsets(max(count - 1, 0), clockwise)]
    return [
        (float(x) + dx * spacing, float(y) + dy * spacing)
        for dx, dy in offsets[:count]
    ]


def _options_dict(options: Any) -> dict:
    if isinstance(options, dict):
        return dict(options)
    return {}


def _spacing(options: dict, count: int, min_x: float, max_x: float, min_y: float, max_y: float) -> float:
    if "spacing" in options:
        return float(options["spacing"])
    side = max(math.ceil(math.sqrt(max(count, 1))), 2)
    return min(abs(max_x - min_x), abs(max_y - min_y)) / (side - 1)


def _clockwise(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.lower() not in {"ccw", "counterclockwise", "counter-clockwise", "false", "0", "left"}
    return True


def _hex_spiral_offsets(count: int, clockwise: bool) -> list[tuple[float, float]]:
    offsets: list[tuple[float, float]] = []
    radius = 1
    while len(offsets) < count:
        ring: list[tuple[float, float, float]] = []
        for q in range(-radius, radius + 1):
            r_min = max(-radius, -q - radius)
            r_max = min(radius, -q + radius)
            for r in range(r_min, r_max + 1):
                if max(abs(q), abs(r), abs(-q - r)) != radius:
                    continue
                px = q + r * 0.5
                py = r * math.sqrt(3.0) / 2.0
                angle = math.atan2(py, px)
                if angle < 0.0:
                    angle += math.tau
                ring.append((angle, px, py))
        ring.sort(key=lambda item: item[0], reverse=not clockwise)
        offsets.extend((px, py) for _, px, py in ring)
        radius += 1
    return offsets[:count]
