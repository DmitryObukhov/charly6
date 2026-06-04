import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from charly6.brain import Brain as CompatBrain
from charly6.brain import Substrate as CompatSubstrate
from charly6.brain import create_random_brain
from charly6.brain_model import Brain, Substrate
from charly6.neuron import Neuron


def test_brain_serializes_to_json_compatible_data() -> None:
    brain = Brain(
        substrate=Substrate(
            brain=[
                Neuron(active=True, charge=2.0, history_table=[(0, 2.0, True)]),
                Neuron(eq=1.0, charge=0.5),
            ],
            connectome=[(0, 1, 0.75)],
        ),
        iteration_idx=3,
    )

    data = brain.to_dict()
    encoded = json.dumps(data)

    assert json.loads(encoded) == data


def test_brain_deserializes_from_serialized_data() -> None:
    brain = Brain(
        substrate=Substrate(
            brain=[
                Neuron(active=True, charge=2.0, history_table=[(0, 2.0, True)]),
                Neuron(eq=1.0, charge=0.5),
            ],
            connectome=[(0, 1, 0.75)],
        ),
        iteration_idx=3,
    )

    restored = Brain.from_dict(json.loads(json.dumps(brain.to_dict())))

    assert restored == brain
    assert restored.substrate.connectome == [(0, 1, 0.75)]
    assert restored.substrate.brain[0].history_table == [(0, 2.0, True)]


def test_brain_module_reexports_model_for_existing_imports() -> None:
    assert CompatBrain is Brain
    assert CompatSubstrate is Substrate


def test_factory_returns_serializable_brain_model() -> None:
    brain = create_random_brain(neuron_count=3, connections_per_neuron=1, seed=1)

    restored = Brain.from_dict(json.loads(json.dumps(brain.to_dict())))

    assert restored == brain


def test_brain_process_uses_layer_signal_status_and_weight() -> None:
    brain = Brain(
        substrate=Substrate(
            brain=[
                Neuron(name="src", number_of_layers=2, status=[False, True], signal=[10.0, 4.0]),
                Neuron(name="dst", number_of_layers=2, trigger=[1.0, 5.0]),
            ],
            connectome=[(0, 1, 2.0)],
        ),
        number_of_layers=2,
    )

    brain.process()

    dst = brain.substrate.brain[1]
    assert dst.signal == [0.0, 8.0]
    assert dst.status == [True, True]
    assert dst.active is True
    assert dst.history[-1]["signal"] == 0.0
