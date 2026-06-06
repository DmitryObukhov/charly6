import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from charly6.body import Body


def test_body_linear_translation_returns_active_indices_count() -> None:
    body = Body.from_config({
        "mappings": [
            {
                "target": "hunger",
                "source": "hunger",
                "formula": "linear",
                "min": 0.0,
                "max": 10.0,
            }
        ]
    })

    translations = body.translate(
        {"hunger": 5.0},
        [{"name": "hunger", "indices": [10, 11, 12, 13]}],
    )

    translation = translations["hunger"]
    assert translation.normalized == 0.5
    assert translation.count == 2
    assert translation.indices == [10, 11]


def test_body_inverse_linear_translation() -> None:
    body = Body.from_config({
        "mappings": [
            {
                "target": "light",
                "source": "light",
                "formula": "inverse_linear",
                "min": 0.0,
                "max": 10.0,
            }
        ]
    })

    translations = body.translate(
        {"light": 2.5},
        [{"name": "light", "indices": [1, 2, 3, 4]}],
    )

    assert translations["light"].count == 3
    assert translations["light"].indices == [1, 2, 3]


def test_body_validate_reports_missing_interfaces() -> None:
    ok, problems = Body.Validate(
        {
            "mappings": [
                {"target": "hunger", "source": "hunger", "min": 0.0, "max": 1.0},
                {"target": "pain", "source": "damage", "min": 0.0, "max": 1.0},
            ]
        },
        brain_inputs={"hunger"},
        world_outputs={"hunger"},
    )

    assert not ok
    assert "body targets missing from brain inputs: pain" in problems
    assert "body sources missing from world outputs: damage" in problems
