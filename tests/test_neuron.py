import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from charly6.brain import Neuron as BrainNeuron
from charly6.neuron import Neuron


def test_neuron_serializes_to_json_compatible_data() -> None:
    neuron = Neuron(
        active=True,
        eq=1.5,
        status=[True, False],
        signal=[4.0, 2.0],
        trigger=[3.0, 3.0],
        number_of_layers=2,
        cumulative_signal=2.5,
        elastic_trigger_delta=0.25,
        charge=3.5,
        elastic_recharge=0.75,
        cyclic_discharge=1.25,
        tiredness=4.5,
        drop_charge_next_cycle=True,
        history_table=[(1, 2.0, True), (2, 3.0, False)],
    )

    data = neuron.to_dict()
    encoded = json.dumps(data)

    assert json.loads(encoded) == data


def test_neuron_deserializes_from_serialized_data() -> None:
    neuron = Neuron(
        active=True,
        eq=1.5,
        cumulative_signal=2.5,
        elastic_trigger_delta=0.25,
        charge=3.5,
        elastic_recharge=0.75,
        cyclic_discharge=1.25,
        tiredness=4.5,
        drop_charge_next_cycle=True,
        history_table=[(1, 2.0, True), (2, 3.0, False)],
    )

    restored = Neuron.from_dict(json.loads(json.dumps(neuron.to_dict())))

    assert restored == neuron
    assert restored.history_table == [(1, 2.0, True), (2, 3.0, False)]


def test_active_is_status_zero_synonym() -> None:
    neuron = Neuron(number_of_layers=2)

    neuron.active = True

    assert neuron.status == [True, False]
    assert neuron.active is True


def test_history_is_limited_to_history_depth() -> None:
    neuron = Neuron(history_depth=2)

    for iteration in range(3):
        neuron.signal[0] = float(iteration)
        neuron.record_history(iteration)

    assert [entry["iteration"] for entry in neuron.history] == [1, 2]


def test_brain_reexports_neuron_for_existing_imports() -> None:
    assert BrainNeuron is Neuron
