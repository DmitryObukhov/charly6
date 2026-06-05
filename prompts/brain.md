# Brain Factory Prompt

## Purpose

Define `charly6.brain` as the public compatibility module and brain construction
helper layer. It should not own the simulation engine.

## Module Responsibilities

- Re-export the public model types from `charly6.brain_model`:
  - `Brain`
  - `Connection`
  - `Substrate`
- Re-export neuron types and defaults from `charly6.neuron`:
  - `Neuron`
  - `HistoryEntry`
  - `DEFAULT_NUMBER_OF_LAYERS`
  - `DEFAULT_HISTORY_DEPTH`
  - `DEFAULT_CHARGE_MAX`
- Provide construction helpers:
  - `create_random_brain(...)`
  - `create_spatial_brain(...)`
- Provide validation helpers:
  - `Validate(config_yaml: str) -> tuple[bool, list[str]]`
  - `validate(config_yaml: str) -> tuple[bool, list[str]]`

## Validation

`Validate` validates brain YAML without constructing a brain or changing runtime
state.

Required behavior:

- Return `(True, [])` when the config is valid.
- Return `(False, problems)` when invalid.
- `problems` must be a list of human-readable strings.
- Validate that the root is a mapping.
- Validate that `ID` is present and non-empty.
- Validate that `brain` is a mapping.
- Validate core numeric fields:
  - `brain.neurons > 0`
  - `brain.head_size >= 0`
  - `brain.connections_per_neuron >= 0`
  - `brain.max_synapse_length >= 0`
  - `brain.total_input >= 0`
  - `brain.NUMBER_OF_LAYERS > 0`
  - `brain.HISTORY_DEPTH > 0`
  - `brain.CHARGE_MAX >= 0`
- Validate optional `brain.Initialization`:
  - `default_charge` is either `charge_max` or a numeric charge in `[0, CHARGE_MAX]`
  - `default_recharge` is a ratio in `[0, 1]` and is multiplied by `CHARGE_MAX`
  - `default_eq_min` and `default_eq_max` are numeric EQ bounds
- Validate that top-level `assembly`, `inputs`, and `outputs` are present.
- `validate` is a lowercase alias for `Validate`.

## `create_random_brain`

Build a random directed connectome.

Required behavior:

- Reject `neuron_count <= 0`.
- Create `Neuron` objects named by their array index.
- Pass `number_of_layers`, `history_depth`, `charge_max`, default charge,
  default recharge, and randomized default EQ into every neuron.
- For each source neuron, sample up to `connections_per_neuron` destinations excluding itself.
- Assign each connection a random weight in `[weight_min, weight_max]`.
- Use `random.Random(seed)` for deterministic construction when a seed is provided.
- Return a `Brain` with matching `number_of_layers`, `history_depth`, and `charge_max`.

## `create_spatial_brain`

Build a connectome from 2D neuron positions and spatial proximity.

Required behavior:

- Reject an empty `positions` list.
- Use a spatial grid based on `max_synapse_length` for candidate lookup.
- For each destination neuron with index `>= head_count`:
  - collect nearby source candidates within `max_synapse_length`
  - exclude self-connections
  - sample up to `connections_per_neuron`
  - assign raw random weights in `[weight_min, weight_max]`
  - normalize weights so `sum(abs(weight)) == total_input`
  - fall back to equal weights if the raw absolute total is effectively zero
- Head neurons (`idx < head_count`) receive no synaptic inputs.
- Create `Neuron` objects named by their array index.
- Pass `number_of_layers`, `history_depth`, `charge_max`, default charge,
  default recharge, and randomized default EQ into every neuron.
- Initialize every neuron charge from `default_charge`, capped to `charge_max`.
- Initialize every neuron recharge from `default_recharge`.
- Initialize every neuron EQ uniformly in `[default_eq_min, default_eq_max]`.
- Initialize every neuron with `trigger[0] = total_input`.
- Initialize `signal[0]` from charge only for head neurons.
- Return a `Brain` with matching constants and generated substrate.

## Boundaries

- Keep simulation processing in `charly6.brain_model`.
- Keep neuron state normalization and serialization in `charly6.neuron`.
- Do not import GUI, YAML config parsing, runtime persistence, or world code.
