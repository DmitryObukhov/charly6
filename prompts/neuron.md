# Neuron Prompt

## Purpose

Define the Charly6 neuron state model separately from the brain simulation engine,
brain construction helpers, GUI code, YAML parsing, runtime files, and world logic.

## Module

`charly6.neuron` defines a serializable `Neuron` class with `__slots__`.
It is not a dataclass because it exposes compatibility properties and legacy
serialization adapters.

Module constants:

- `DEFAULT_NUMBER_OF_LAYERS = 1`
- `DEFAULT_HISTORY_DEPTH = 32`
- `DEFAULT_CHARGE_MAX = 100.0`

Type aliases:

- `HistoryEntry = dict[str, Any]`
- `LegacyHistoryEntry = tuple[int, float, bool]`

## Neuron Fields

Identity and constants:

- `name`: unique string id; factories default it to the neuron index
- `number_of_layers`
- `history_depth`
- `charge_max`

Status processing:

- `status: list[bool]`
- `active`: property synonym for `status[0]`
- `eq`: Emotional Quantum, clamped to `[-charge_max, +charge_max]`

Trigger and signal:

- `signal: list[float]`
- `trigger: list[float]`
- `trigger_flex: float`

Charge controls:

- `charge`, clamped to `[charge_min, charge_max]`
- `charge_min`
- `recharge`
- `recharge_flex`
- `discharge_random`, clamped to `[0.0, 1.0]`

History:

- `history: list[dict]`, capped to `history_depth`
- each record contains `iteration`, `active`, `signal`, `trigger`, and `charge`

Compatibility state still present for the current GUI:

- `cumulative_signal`
- `tiredness`
- `cyclic_discharge`

## Compatibility Properties

- `active` reads and writes `status[0]`.
- Setting `active=True` also seeds `signal[0]` from `charge` if signal is zero.
- `elastic_trigger_delta` aliases `trigger_flex`.
- `elastic_recharge` aliases `recharge_flex`.
- `history_table` exposes legacy tuple history as `(iteration, signal, active)`
  and maps writes back into `history`.

## Construction Behavior

- `number_of_layers` and `history_depth` are coerced to positive integers.
- `charge_max` is coerced to a non-negative float.
- `status`, `signal`, and `trigger` are normalized to exactly `number_of_layers`.
- Scalar signal/trigger inputs populate layer 0 and use defaults for remaining layers.
- Legacy constructor arguments are accepted:
  - `active`
  - `elastic_trigger_delta`
  - `elastic_recharge`
  - `history_table`

## Methods

- `resize_layers(number_of_layers)` updates layer count and resizes status, signal,
  and trigger arrays while preserving existing values where possible.
- `record_history(iteration_idx)` appends the current layer-0 state and trims history
  to `history_depth`.
- `to_dict()` returns JSON-compatible data for all current fields plus `active`.
- `from_dict()` restores current serialized data and reads legacy field names:
  - `NUMBER_OF_LAYERS`, `HISTORY_DEPTH`, `CHARGE_MAX`
  - `signals`, `triggers`
  - `elastic_trigger_delta`, `elastic_recharge`
  - `history_table`
- Equality compares `to_dict()` output.

## Boundaries

- Do not import or reference Brain, Substrate, connectome, GUI, YAML config,
  runtime files, or world code.
- Keep processing rules in `charly6.brain_model`.
- The neuron object only owns state normalization, compatibility properties,
  serialization, and history.
