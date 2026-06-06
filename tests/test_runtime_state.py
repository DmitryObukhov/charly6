import sys
import sqlite3
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from charly6.app import DEFAULT_BRAIN_CONFIG, App, _brain_id_from_config, _runtime_safe_id
from charly6.brain_model import Brain, Substrate
from charly6.neuron import Neuron


def test_default_brain_config_starts_with_id() -> None:
    assert next(iter(DEFAULT_BRAIN_CONFIG)) == "ID"


def test_brain_id_is_required() -> None:
    with pytest.raises(ValueError, match="ID"):
        _brain_id_from_config({})


def test_runtime_safe_id_keeps_expected_filename_characters() -> None:
    assert _runtime_safe_id(" charly/6:1 ") == "charly_6_1"


def test_logic_history_sqlite_has_iteration_neuron_and_physical_rows(tmp_path: Path) -> None:
    app = object.__new__(App)
    app._brain_id = "test_brain"
    app._brain = Brain(
        substrate=Substrate(
            brain=[
                Neuron(active=True, signal=[1.5], trigger=[1.0], charge=3.0, eq=0.2),
                Neuron(active=False, signal=[0.5], trigger=[2.0], charge=4.0, eq=-0.1),
            ],
            connectome=[(0, 1, 1.0)],
        ),
        iteration_idx=7,
    )
    app._iteration = 3
    app._input_specs = [{"name": "hunger", "value": 0.75}]
    app._output_specs = [{"name": "motor", "indices": [0, 1]}]
    app._logic_history_path = tmp_path / "history.sqlite"

    app._initialize_logic_history_db()
    app._append_logic_history_db(app._logic_history_record())

    with sqlite3.connect(app._logic_history_path) as conn:
        iteration_row = conn.execute(
            "SELECT iteration, CES_pos, CES_neg FROM iterations"
        ).fetchone()
        io_rows = conn.execute(
            "SELECT direction, name, value FROM physical_io ORDER BY direction, name"
        ).fetchall()
        neuron_rows = conn.execute(
            """
            SELECT neuron_idx, active, signal, trigger, active_inputs, active_input_indices
            FROM neuron_history
            ORDER BY neuron_idx
            """
        ).fetchall()

    assert iteration_row == (3, 0.2, 0.0)
    assert io_rows == [("input", "hunger", 0.75), ("output", "motor", 0.5)]
    assert neuron_rows == [(0, 1, 1.5, 1.0, 0, "[]"), (1, 0, 0.5, 2.0, 1, "[0]")]


def test_append_logic_history_creates_single_sqlite_file_with_multiple_rows(tmp_path: Path) -> None:
    app = object.__new__(App)
    app._brain_id = "test_brain"
    app._brain = Brain(
        substrate=Substrate(brain=[Neuron(active=True, signal=[1.0], trigger=[0.5], charge=2.0)]),
        iteration_idx=1,
    )
    app._iteration = 1
    app._input_specs = []
    app._output_specs = []
    app._logic_history_path = tmp_path / "history.sqlite"
    app._logic_history_rows = []
    app._history_status_var = type("Status", (), {"set": lambda self, value: None})()
    app._history_tree = None

    app._initialize_logic_history_db()
    app._append_logic_history()
    app._iteration = 2
    app._brain.iteration_idx = 2
    app._append_logic_history()

    assert app._logic_history_path.exists()
    assert list(tmp_path.iterdir()) == [app._logic_history_path]
    with sqlite3.connect(app._logic_history_path) as conn:
        rows = conn.execute(
            """
            SELECT i.iteration, n.active, n.signal, n.trigger
            FROM iterations i
            JOIN neuron_history n ON n.iteration = i.iteration
            ORDER BY i.iteration, n.neuron_idx
            """
        ).fetchall()

    assert rows == [(1, 1, 1.0, 0.5), (2, 1, 1.0, 0.5)]


def test_logic_history_uses_preprocess_active_input_snapshot(tmp_path: Path) -> None:
    app = object.__new__(App)
    app._brain_id = "test_brain"
    app._brain = Brain(
        substrate=Substrate(
            brain=[
                Neuron(active=False, signal=[0.0], trigger=[1.0], charge=0.0),
                Neuron(active=False, signal=[12.0], trigger=[1.0], charge=0.0),
            ],
            connectome=[(0, 1, 1.0)],
        ),
        iteration_idx=2,
    )
    app._iteration = 2
    app._input_specs = []
    app._output_specs = []
    app._logic_history_path = tmp_path / "history.sqlite"
    app._last_active_input_indices = [[], [0]]

    app._initialize_logic_history_db()
    app._append_logic_history_db(app._logic_history_record())

    with sqlite3.connect(app._logic_history_path) as conn:
        row = conn.execute(
            """
            SELECT active_inputs, active_input_indices
            FROM neuron_history
            WHERE neuron_idx = 1
            """
        ).fetchone()

    assert row == (1, "[0]")


def test_logic_history_path_is_single_stable_sqlite_file() -> None:
    app = object.__new__(App)
    app._brain_id = "charly/6:1"

    assert app._create_logic_history_path().name == "charly_6_1_logic.sqlite"
