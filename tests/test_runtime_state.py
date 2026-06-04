import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from charly6.app import DEFAULT_BRAIN_CONFIG, _brain_id_from_config, _runtime_safe_id


def test_default_brain_config_starts_with_id() -> None:
    assert next(iter(DEFAULT_BRAIN_CONFIG)) == "ID"


def test_brain_id_is_required() -> None:
    with pytest.raises(ValueError, match="ID"):
        _brain_id_from_config({})


def test_runtime_safe_id_keeps_expected_filename_characters() -> None:
    assert _runtime_safe_id(" charly/6:1 ") == "charly_6_1"
