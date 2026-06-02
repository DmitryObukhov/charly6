"""Canvas layout helpers — neuron spatial placement via pseudo-Hilbert sequences.

Pseudo-Hilbert curve (PHC) plane-filling method
================================================
A Hilbert curve maps a 1-D line segment [0, 1] to a 2-D plane [0,1]² so that
points close on the line remain close on the plane.  It is built iteratively:

Order 1 (2×2 grid)
    The square is split into four quadrants; their centres are connected in a
    "∩" shape: bottom-left → top-left → top-right → bottom-right.

Order 2 (4×4 grid)
    Each quadrant gets a miniature copy of the order-1 curve.  The copies in
    the bottom-left and bottom-right corners are *reflected* so that the tail of
    each sub-curve meets the head of the next, keeping the overall path
    continuous without jumps.

Order n (2ⁿ × 2ⁿ grid)
    The same rule applies recursively.  For a 256×256 pixel canvas, order 8
    visits every pixel exactly once.

Mathematical properties
    Stability   — raising the order does not scramble the mapping; every point
                  on the line converges to a definite limit coordinate on the
                  plane.
    Continuity  — a small change in the 1-D index produces a small change in
                  the 2-D position.
    Space-filling limit — as order → ∞ the curve passes through *every* point
                  of the continuous plane.

Application here
    `hilbert_positions(n)` generates the smallest adequate PHC grid, then
    re-orders all grid² points by distance from the canvas centre (0.5, 0.5).
    Neuron 0 is placed nearest the centre; subsequent neurons fill outward,
    ring by ring, while Hilbert locality is preserved within each ring.
"""

from __future__ import annotations

import math


def _d2xy(grid: int, d: int) -> tuple[int, int]:
    """Convert a Hilbert curve linear index *d* to *(x, y)* on a *grid*×*grid* lattice.

    *grid* must be a power of 2.  Uses the standard rotate/reflect decomposition:
    the bottom-left quadrant (rx=0, ry=0) and bottom-right quadrant (rx=1, ry=0)
    are reflected before the sub-curve is placed, which is exactly the orientation
    rule described in the PHC construction above.
    """
    x = y = 0
    s = 1
    while s < grid:
        rx = 1 if (d & 2) else 0
        ry = 1 if (d & 1) ^ rx else 0
        if ry == 0:
            if rx == 1:          # bottom-right quadrant: reflect through diagonal
                x = s - 1 - x
                y = s - 1 - y
            x, y = y, x          # bottom-left quadrant: transpose (rotate 90°)
        x += s * rx
        y += s * ry
        d //= 4
        s *= 2
    return x, y


def hilbert_positions(n: int) -> list[tuple[float, float]]:
    """Return *n* canvas positions in [0, 1]² ordered from centre outward along a PHC.

    Algorithm
    ---------
    1. Choose the smallest order *p* such that (2^p)² ≥ n.
    2. Enumerate all (2^p)² lattice points in Hilbert order using `_d2xy`.
    3. Sort them by squared distance from (0.5, 0.5); Hilbert order breaks ties
       (Python's sort is stable), preserving spatial locality within each ring.
    4. Return the first *n* normalised coordinates.

    Result: neuron 0 is nearest the centre; the population expands outward,
    filling the brain canvas like a PHC unrolling from its midpoint.
    """
    if n <= 0:
        return []
    if n == 1:
        return [(0.5, 0.5)]
    # smallest power-of-2 grid such that grid² ≥ n
    order = max(1, math.ceil(math.log2(math.sqrt(n))))
    grid = 1 << order
    inv = 1.0 / (grid - 1)
    # Generate all grid² Hilbert points with distance² from centre
    points: list[tuple[float, float, float]] = []
    for d in range(grid * grid):
        gx, gy = _d2xy(grid, d)
        nx, ny = gx * inv, gy * inv
        points.append(((nx - 0.5) ** 2 + (ny - 0.5) ** 2, nx, ny))
    points.sort(key=lambda p: p[0])
    return [(p[1], p[2]) for p in points[:n]]
