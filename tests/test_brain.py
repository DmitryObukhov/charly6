import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from charly6.brain import Brain as CompatBrain
from charly6.brain import Substrate as CompatSubstrate
from charly6.brain import Validate
from charly6.brain import create_random_brain
from charly6.brain import create_spatial_brain
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


def test_spatial_factory_applies_initialization_defaults() -> None:
    brain = create_spatial_brain(
        [(0.0, 0.0), (0.1, 0.0)],
        charge_max=100.0,
        default_charge=75.0,
        default_recharge=20.0,
        default_eq_min=-0.1,
        default_eq_max=0.1,
        seed=1,
    )

    for neuron in brain.substrate.brain:
        assert neuron.charge == 75.0
        assert neuron.recharge == 20.0
        assert -0.1 <= neuron.eq <= 0.1


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


def test_brain_process_preserves_neuron_references_after_copy_back() -> None:
    source = Neuron(status=[True], signal=[2.0], charge=10.0)
    dst = Neuron(trigger=[1.0], charge=5.0)
    brain = Brain(substrate=Substrate(brain=[source, dst], connectome=[(0, 1, 1.0)]), charge_max=10.0)
    original_refs = list(brain.substrate.brain)

    brain.process()

    assert brain.substrate.brain == original_refs
    assert brain.substrate.brain[1] is dst
    assert dst.active is True


def test_activation_drops_charge_immediately_and_recharges_inactive_until_full() -> None:
    source = Neuron(status=[True], signal=[2.0], charge=10.0)
    dst = Neuron(trigger=[1.0], charge=5.0, charge_min=1.0, recharge=2.0, charge_max=10.0)
    brain = Brain(substrate=Substrate(brain=[source, dst], connectome=[(0, 1, 1.0)]), charge_max=10.0)

    brain.process()

    assert dst.active is True
    assert dst.drop_charge_next_cycle is True
    assert dst.charge == 0.0

    brain.process()

    assert dst.active is False
    assert dst.drop_charge_next_cycle is True
    assert dst.charge == 2.0

    for expected_charge in (4.0, 6.0, 8.0, 10.0):
        brain.process()
        assert dst.active is False
        assert dst.charge == expected_charge

    assert dst.drop_charge_next_cycle is False


def test_charge_below_minimum_blocks_activation() -> None:
    source = Neuron(status=[True], signal=[5.0], charge=10.0)
    dst = Neuron(trigger=[1.0], charge=0.0, charge_min=1.0, recharge=0.0)
    brain = Brain(substrate=Substrate(brain=[source, dst], connectome=[(0, 1, 1.0)]))

    brain.process()

    assert dst.signal[0] == 5.0
    assert dst.active is False
    assert dst.status == [False]


def test_brain_validate_reports_problems() -> None:
    ok, problems = Validate(
        """
ID: test
brain:
  neurons: 2
assembly: []
inputs: []
outputs: []
"""
    )

    assert ok is True
    assert problems == []

    ok, problems = Validate("brain:\n  neurons: 0\n")

    assert ok is False
    assert problems
