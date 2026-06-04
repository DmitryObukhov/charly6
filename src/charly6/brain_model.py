"""Brain state model and serialization helpers."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence, TypeAlias

from charly6.neuron import DEFAULT_CHARGE_MAX, DEFAULT_HISTORY_DEPTH, DEFAULT_NUMBER_OF_LAYERS, Neuron

Connection: TypeAlias = tuple[int, int, float]


@dataclass(slots=True)
class Substrate:
    brain: list[Neuron] = field(default_factory=list)
    connectome: list[Connection] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation of this substrate."""
        return {
            "brain": [neuron.to_dict() for neuron in self.brain],
            "connectome": [
                [src_idx, dst_idx, weight]
                for src_idx, dst_idx, weight in self.connectome
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Substrate:
        """Create a substrate from a mapping produced by :meth:`to_dict`."""
        return cls(
            brain=[Neuron.from_dict(neuron) for neuron in data.get("brain", [])],
            connectome=[
                (int(src_idx), int(dst_idx), float(weight))
                for src_idx, dst_idx, weight in data.get("connectome", [])
            ],
        )


@dataclass(slots=True)
class Brain:
    substrate: Substrate = field(default_factory=Substrate)
    iteration_idx: int = 0
    number_of_layers: int = DEFAULT_NUMBER_OF_LAYERS
    history_depth: int = DEFAULT_HISTORY_DEPTH
    charge_max: float = DEFAULT_CHARGE_MAX

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation of this brain."""
        return {
            "substrate": self.substrate.to_dict(),
            "iteration_idx": self.iteration_idx,
            "number_of_layers": self.number_of_layers,
            "history_depth": self.history_depth,
            "charge_max": self.charge_max,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Brain:
        """Create a brain from a mapping produced by :meth:`to_dict`."""
        return cls(
            substrate=Substrate.from_dict(data.get("substrate", {})),
            iteration_idx=int(data.get("iteration_idx", 0)),
            number_of_layers=int(data.get("number_of_layers", DEFAULT_NUMBER_OF_LAYERS)),
            history_depth=int(data.get("history_depth", DEFAULT_HISTORY_DEPTH)),
            charge_max=float(data.get("charge_max", DEFAULT_CHARGE_MAX)),
        )

    def get_inputs(self, inputs: Sequence[float]) -> None:
        neurons = self.substrate.brain
        if len(inputs) > len(neurons):
            raise ValueError("inputs length cannot exceed neuron count")
        for idx, signal in enumerate(inputs):
            value = float(signal)
            neurons[idx].signal[0] += value
            neurons[idx].charge = min(neurons[idx].charge_max, max(neurons[idx].charge_min, value))
            neurons[idx].active = value > neurons[idx].trigger[0] + neurons[idx].trigger_flex + neurons[idx].eq
            neurons[idx].cumulative_signal += value

    def process(self) -> None:
        neurons = self.substrate.brain
        layers = max(1, self.number_of_layers)
        for idx, neuron in enumerate(neurons):
            neuron.name = neuron.name or str(idx)
            neuron.history_depth = self.history_depth
            neuron.charge_max = self.charge_max
            neuron.resize_layers(layers)

        previous_status = [list(neuron.status) for neuron in neurons]
        previous_signal = [list(neuron.signal) for neuron in neurons]
        propagated = [[0.0] * layers for _ in neurons]

        for src_idx, dst_idx, weight in self.substrate.connectome:
            if src_idx >= len(neurons) or dst_idx >= len(neurons):
                continue
            weights = self._connection_weights(weight, layers)
            for layer_idx in range(layers):
                propagated[dst_idx][layer_idx] += (
                    previous_signal[src_idx][layer_idx]
                    * float(previous_status[src_idx][layer_idx])
                    * weights[layer_idx]
                )

        for idx, neuron in enumerate(neurons):
            neuron.signal = propagated[idx]
            neuron.cumulative_signal += sum(propagated[idx])
            statuses = []
            for layer_idx in range(layers):
                threshold = neuron.trigger[layer_idx] + neuron.trigger_flex + neuron.eq
                statuses.append(neuron.signal[layer_idx] > threshold)
            if any(statuses):
                statuses[0] = True
            neuron.status = statuses

            if neuron.discharge_random and neuron.charge > neuron.charge_min:
                if random.random() < neuron.discharge_random:
                    neuron.charge = neuron.charge_min
            if neuron.active:
                discharge = max(0.0, neuron.cyclic_discharge)
                neuron.charge = max(neuron.charge_min, neuron.charge - discharge)
                neuron.tiredness += discharge
            else:
                recharge = max(0.0, neuron.recharge + neuron.recharge_flex)
                neuron.charge = min(neuron.charge_max, neuron.charge + recharge)
                neuron.tiredness = max(0.0, neuron.tiredness - recharge)
            neuron.record_history(self.iteration_idx)
        self.iteration_idx += 1

    def _connection_weights(self, weight: Any, layers: int) -> list[float]:
        if isinstance(weight, (list, tuple)):
            weights = [float(value) for value in weight]
            if len(weights) < layers:
                weights.extend([weights[-1] if weights else 0.0] * (layers - len(weights)))
            return weights[:layers]
        return [float(weight)] * layers

    def set_outputs(self, output_indices: Sequence[int] | None = None) -> list[bool]:
        neurons = self.substrate.brain
        indices = range(len(neurons)) if output_indices is None else output_indices
        return [neurons[idx].active for idx in indices]
