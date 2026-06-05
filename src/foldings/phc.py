"""Pseudo-Hilbert curve folding generator."""

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
    d: str | float | int = "center",
    R: int | None = None,
    options: Any = "",
) -> list[tuple[float, float]]:
    """Return N PHC points in the requested rectangular space."""
    count = int(N)
    if count <= 0:
        return []
    if count == 1:
        return [(float(x), float(y))]

    grid_points = _hilbert_unit_points(count)
    width = max_x - min_x
    height = max_y - min_y
    sx = 0.0 if abs(width) <= 1e-12 else (float(x) - min_x) / width
    sy = 0.0 if abs(height) <= 1e-12 else (float(y) - min_y) / height
    sx = min(1.0, max(0.0, sx))
    sy = min(1.0, max(0.0, sy))
    grid_points.sort(key=lambda point: (point[0] - sx) ** 2 + (point[1] - sy) ** 2)
    return [
        (min_x + px * width, min_y + py * height)
        for px, py in grid_points[:count]
    ]


def _hilbert_unit_points(count: int) -> list[tuple[float, float]]:
    order = max(1, math.ceil(math.log2(math.sqrt(count))))
    grid = 1 << order
    inv = 1.0 / (grid - 1)
    points: list[tuple[float, float]] = []
    for idx in range(grid * grid):
        gx, gy = _d2xy(grid, idx)
        points.append((gx * inv, gy * inv))
    return points


def _d2xy(grid: int, idx: int) -> tuple[int, int]:
    x = y = 0
    s = 1
    while s < grid:
        rx = 1 if (idx & 2) else 0
        ry = 1 if (idx & 1) ^ rx else 0
        if ry == 0:
            if rx == 1:
                x = s - 1 - x
                y = s - 1 - y
            x, y = y, x
        x += s * rx
        y += s * ry
        idx //= 4
        s *= 2
    return x, y
