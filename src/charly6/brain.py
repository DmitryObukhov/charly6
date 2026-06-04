"""Brain factory functions and compatibility exports."""

from __future__ import annotations

import random

from charly6.brain_model import Brain, Connection, Substrate
from charly6.neuron import (
    DEFAULT_CHARGE_MAX,
    DEFAULT_HISTORY_DEPTH,
    DEFAULT_NUMBER_OF_LAYERS,
    HistoryEntry,
    Neuron,
)


def create_random_brain(
    neuron_count: int = 360,
    *,
    connections_per_neuron: int = 50,
    weight_min: float = 0.0,
    weight_max: float = 1.0,
    seed: int | None = None,
    number_of_layers: int = DEFAULT_NUMBER_OF_LAYERS,
    history_depth: int = DEFAULT_HISTORY_DEPTH,
    charge_max: float = DEFAULT_CHARGE_MAX,
) -> Brain:
    if neuron_count <= 0:
        raise ValueError("neuron_count must be > 0")
    neurons = [
        Neuron(
            name=str(idx),
            number_of_layers=number_of_layers,
            history_depth=history_depth,
            charge_max=charge_max,
        )
        for idx in range(neuron_count)
    ]
    rng = random.Random(seed)
    connectome: list[Connection] = []
    for src_idx in range(neuron_count):
        destinations = [i for i in range(neuron_count) if i != src_idx]
        sample_size = min(connections_per_neuron, len(destinations))
        for dst_idx in rng.sample(destinations, k=sample_size):
            connectome.append((src_idx, dst_idx, rng.uniform(weight_min, weight_max)))
    return Brain(
        substrate=Substrate(brain=neurons, connectome=connectome),
        number_of_layers=number_of_layers,
        history_depth=history_depth,
        charge_max=charge_max,
    )


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
    number_of_layers: int = DEFAULT_NUMBER_OF_LAYERS,
    history_depth: int = DEFAULT_HISTORY_DEPTH,
    charge_max: float = DEFAULT_CHARGE_MAX,
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

    neurons = [
        Neuron(
            name=str(idx),
            number_of_layers=number_of_layers,
            history_depth=history_depth,
            charge_max=charge_max,
        )
        for idx in range(n)
    ]
    for i, neuron in enumerate(neurons):
        neuron.eq = total_input
        neuron.trigger[0] = total_input
        neuron.charge = min(charge_max, total_input if i < head_count else total_input * 0.9)
        neuron.signal[0] = neuron.charge if i < head_count else 0.0

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

    return Brain(
        substrate=Substrate(brain=neurons, connectome=connectome),
        number_of_layers=number_of_layers,
        history_depth=history_depth,
        charge_max=charge_max,
    )
