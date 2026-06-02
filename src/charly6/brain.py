"""Brain simulation engine (Neuron, Substrate, Brain, factory functions)."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Sequence, TypeAlias

HistoryEntry: TypeAlias = tuple[int, float, bool]
Connection: TypeAlias = tuple[int, int, float]


@dataclass(slots=True)
class Neuron:
    active: bool = False
    eq: float = 0.0
    cumulative_signal: float = 0.0
    elastic_trigger_delta: float = 0.0
    charge: float = 0.0
    elastic_recharge: float = 0.0
    cyclic_discharge: float = 0.0
    tiredness: float = 0.0
    history_table: list[HistoryEntry] = field(default_factory=list)


@dataclass(slots=True)
class Substrate:
    brain: list[Neuron] = field(default_factory=list)
    connectome: list[Connection] = field(default_factory=list)


@dataclass(slots=True)
class Brain:
    substrate: Substrate = field(default_factory=Substrate)
    iteration_idx: int = 0

    def get_inputs(self, inputs: Sequence[float]) -> None:
        neurons = self.substrate.brain
        if len(inputs) > len(neurons):
            raise ValueError("inputs length cannot exceed neuron count")
        for idx, signal in enumerate(inputs):
            value = float(signal)
            neurons[idx].charge += value
            neurons[idx].cumulative_signal += value

    def process(self) -> None:
        neurons = self.substrate.brain
        propagated = [0.0] * len(neurons)
        for src_idx, dst_idx, weight in self.substrate.connectome:
            src = neurons[src_idx]
            if src.charge >= src.eq + src.elastic_trigger_delta:
                propagated[dst_idx] += src.charge * weight
        for idx, neuron in enumerate(neurons):
            incoming = propagated[idx]
            if incoming:
                neuron.charge += incoming
                neuron.cumulative_signal += incoming
            threshold = neuron.eq + neuron.elastic_trigger_delta
            neuron.active = neuron.charge >= threshold
            if neuron.active:
                discharge = max(0.0, neuron.cyclic_discharge)
                neuron.charge = max(0.0, neuron.charge - discharge)
                neuron.tiredness += discharge
            else:
                recharge = max(0.0, neuron.elastic_recharge)
                neuron.charge += recharge
                neuron.tiredness = max(0.0, neuron.tiredness - recharge)
            neuron.history_table.append((self.iteration_idx, neuron.cumulative_signal, neuron.active))
        self.iteration_idx += 1

    def set_outputs(self, output_indices: Sequence[int] | None = None) -> list[bool]:
        neurons = self.substrate.brain
        indices = range(len(neurons)) if output_indices is None else output_indices
        return [neurons[idx].active for idx in indices]


def create_random_brain(
    neuron_count: int = 360,
    *,
    connections_per_neuron: int = 50,
    weight_min: float = 0.0,
    weight_max: float = 1.0,
    seed: int | None = None,
) -> Brain:
    if neuron_count <= 0:
        raise ValueError("neuron_count must be > 0")
    neurons = [Neuron() for _ in range(neuron_count)]
    rng = random.Random(seed)
    connectome: list[Connection] = []
    for src_idx in range(neuron_count):
        destinations = [i for i in range(neuron_count) if i != src_idx]
        sample_size = min(connections_per_neuron, len(destinations))
        for dst_idx in rng.sample(destinations, k=sample_size):
            connectome.append((src_idx, dst_idx, rng.uniform(weight_min, weight_max)))
    return Brain(substrate=Substrate(brain=neurons, connectome=connectome))


def create_spatial_brain(
    positions: list[tuple[float, float]],
    *,
    connections_per_neuron: int = 10,
    max_synapse_length: float = 0.3,
    weight_min: float = 0.0,
    weight_max: float = 1.0,
    total_input: float = 1000.0,
    head_count: int = 0,
    seed: int | None = None,
) -> Brain:
    """Create a brain whose connectome is built from spatial proximity.

    For each destination neuron d (index >= head_count):
      1. Collect all source neurons within *max_synapse_length* in brain space.
      2. Randomly sample up to *connections_per_neuron* of them.
      3. Assign raw weights uniform in [weight_min, weight_max].
      4. Normalise: scale weights so Σ|w| == *total_input* for neuron d's inputs.

    Head neurons (index < head_count) receive NO synaptic inputs — they are
    driven externally (clicks / get_inputs).

    Initial state:
      eq     = total_input  for all neurons (fires when full input arrives)
      charge = total_input  for head neurons  (ready to propagate when activated)
      charge = total_input * 0.9 for body neurons (90 % primed; one active
               input at full charge is enough to trigger firing)
    """
    n = len(positions)
    if n == 0:
        raise ValueError("positions must not be empty")

    rng = random.Random(seed)
    max_d2 = max_synapse_length ** 2

    # Spatial grid: cell side = max_synapse_length → 3×3 cells cover search radius
    cell = max(max_synapse_length, 1e-9)
    grid: dict[tuple[int, int], list[int]] = {}
    for idx, (px, py) in enumerate(positions):
        grid.setdefault((int(px / cell), int(py / cell)), []).append(idx)

    neurons = [Neuron() for _ in range(n)]
    for i, neuron in enumerate(neurons):
        neuron.eq = total_input
        neuron.charge = total_input if i < head_count else total_input * 0.9

    connectome: list[Connection] = []

    for dst_idx, (dx, dy) in enumerate(positions):
        if dst_idx < head_count:
            continue  # head neurons receive no synaptic inputs
        gx = int(dx / cell)
        gy = int(dy / cell)

        candidates: list[int] = []
        for cgx in range(gx - 1, gx + 2):
            for cgy in range(gy - 1, gy + 2):
                for src_idx in grid.get((cgx, cgy), []):
                    if src_idx == dst_idx:
                        continue
                    sx, sy = positions[src_idx]
                    if (sx - dx) ** 2 + (sy - dy) ** 2 <= max_d2:
                        candidates.append(src_idx)

        k = min(connections_per_neuron, len(candidates))
        if k == 0:
            continue

        chosen = rng.sample(candidates, k)
        raw = [rng.uniform(weight_min, weight_max) for _ in chosen]

        total_abs = sum(abs(w) for w in raw)
        if total_abs > 1e-12:
            scale = total_input / total_abs
            raw = [w * scale for w in raw]
        else:
            raw = [total_input / k] * k  # fallback: equal weights

        for src_idx, w in zip(chosen, raw):
            connectome.append((src_idx, dst_idx, w))

    return Brain(substrate=Substrate(brain=neurons, connectome=connectome))
