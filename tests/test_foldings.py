import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from foldings import phc
from foldings import spiral


def test_phc_generate_returns_requested_count_inside_space() -> None:
    points = phc.Generate(
        N=8,
        min_x=-1.0,
        max_x=1.0,
        min_y=2.0,
        max_y=4.0,
        x=0.0,
        y=3.0,
    )

    assert len(points) == 8
    assert all(-1.0 <= x <= 1.0 and 2.0 <= y <= 4.0 for x, y in points)


def test_spiral_generate_starts_at_requested_coordinate() -> None:
    points = spiral.Generate(
        N=4,
        min_x=0.0,
        max_x=1.0,
        min_y=0.0,
        max_y=1.0,
        x=0.25,
        y=0.75,
        options={"spacing": 0.1},
    )

    assert len(points) == 4
    assert points[0] == (0.25, 0.75)
