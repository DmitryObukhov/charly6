"""Brain factory functions and compatibility exports."""

from __future__ import annotations

import random
from typing import Any

from charly6.brain_model import Brain, Connection, Substrate
from charly6.neuron import (
    DEFAULT_CHARGE_MAX,
    DEFAULT_HISTORY_DEPTH,
    DEFAULT_NUMBER_OF_LAYERS,
    HistoryEntry,
    Neuron,
)

try:
    import yaml
except ImportError:  # pragma: no cover - package dependency should provide PyYAML.
    yaml = None


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
    default_charge: float | None = None,
    default_recharge: float = 0.0,
    default_eq_min: float = 0.0,
    default_eq_max: float = 0.0,
) -> Brain:
    if neuron_count <= 0:
        raise ValueError("neuron_count must be > 0")
    rng = random.Random(seed)
    initial_charge = charge_max if default_charge is None else min(charge_max, max(0.0, default_charge))
    eq_min = min(default_eq_min, default_eq_max)
    eq_max = max(default_eq_min, default_eq_max)
    neurons = [
        Neuron(
            name=str(idx),
            number_of_layers=number_of_layers,
            history_depth=history_depth,
            charge_max=charge_max,
            charge=initial_charge,
            recharge=default_recharge,
            eq=rng.uniform(eq_min, eq_max),
        )
        for idx in range(neuron_count)
    ]
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


def Validate(config_yaml: str) -> tuple[bool, list[str]]:
    """Return whether a brain YAML config is valid and detected problems."""
    problems: list[str] = []
    try:
        if yaml is None:
            raise ValueError("PyYAML is required to validate brain YAML.")
        raw = yaml.safe_load(config_yaml) if config_yaml.strip() else {}
        if not isinstance(raw, dict):
            raise ValueError("YAML root must be a mapping.")
        _require_nonempty(raw, "ID")
        brain = _mapping(raw.get("brain"), "brain")
        _positive_int(brain.get("neurons"), "brain.neurons")
        _nonnegative_int(brain.get("head_size", 0), "brain.head_size")
        _nonnegative_int(brain.get("connections_per_neuron", brain.get("connections", 10)), "brain.connections_per_neuron")
        _nonnegative_float(brain.get("max_synapse_length", brain.get("max_synapse", 0.3)), "brain.max_synapse_length")
        float(brain.get("weight_min", 0.0))
        float(brain.get("weight_max", 1.0))
        _nonnegative_float(brain.get("total_input", 1000.0), "brain.total_input")
        _positive_int(brain.get("NUMBER_OF_LAYERS", brain.get("number_of_layers", 1)), "brain.NUMBER_OF_LAYERS")
        _positive_int(brain.get("HISTORY_DEPTH", brain.get("history_depth", 32)), "brain.HISTORY_DEPTH")
        charge_max = _nonnegative_float(brain.get("CHARGE_MAX", brain.get("charge_max", 100.0)), "brain.CHARGE_MAX")
        initialization = brain.get("Initialization", brain.get("initialization", {}))
        if initialization is not None:
            initialization = _mapping(initialization, "brain.Initialization")
            _charge_value(initialization.get("default_charge", "charge_max"), charge_max, "brain.Initialization.default_charge")
            default_recharge = _nonnegative_float(
                initialization.get("default_recharge", 0.2), "brain.Initialization.default_recharge"
            )
            if default_recharge > 1.0:
                problems.append("brain.Initialization.default_recharge must be a ratio in [0, 1].")
            float(initialization.get("default_eq_min", -0.1))
            float(initialization.get("default_eq_max", 0.1))
        if "assembly" not in raw:
            problems.append("Missing required top-level section: assembly")
        if "inputs" not in raw:
            problems.append("Missing required top-level section: inputs")
        if "outputs" not in raw:
            problems.append("Missing required top-level section: outputs")
    except Exception as exc:
        problems.append(str(exc))
    return not problems, problems


def validate(config_yaml: str) -> tuple[bool, list[str]]:
    """Lowercase alias for callers that prefer validate()."""
    return Validate(config_yaml)


def _mapping(value: Any, name: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping.")
    return value


def _require_nonempty(raw: dict, name: str) -> str:
    value = str(raw.get(name, "")).strip()
    if not value:
        raise ValueError(f"{name} must not be empty.")
    return value


def _positive_int(value: Any, name: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be > 0.")
    return parsed


def _nonnegative_int(value: Any, name: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise ValueError(f"{name} must be >= 0.")
    return parsed


def _nonnegative_float(value: Any, name: str) -> float:
    parsed = float(value)
    if parsed < 0.0:
        raise ValueError(f"{name} must be >= 0.")
    return parsed


def _charge_value(value: Any, charge_max: float, name: str) -> float:
    if isinstance(value, str) and value.strip().lower() == "charge_max":
        return charge_max
    parsed = float(value)
    if parsed < 0.0:
        raise ValueError(f"{name} must be >= 0.")
    if parsed > charge_max:
        raise ValueError(f"{name} must be <= charge_max.")
    return parsed


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
    default_charge: float | None = None,
    default_recharge: float = 0.0,
    default_eq_min: float = 0.0,
    default_eq_max: float = 0.0,
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
    initial_charge = charge_max if default_charge is None else min(charge_max, max(0.0, default_charge))
    eq_min = min(default_eq_min, default_eq_max)
    eq_max = max(default_eq_min, default_eq_max)
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
            charge=initial_charge,
            recharge=default_recharge,
            eq=rng.uniform(eq_min, eq_max),
        )
        for idx in range(n)
    ]
    for i, neuron in enumerate(neurons):
        neuron.trigger[0] = total_input
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
