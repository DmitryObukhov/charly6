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

## `create_random_brain`

Build a random directed connectome.

Required behavior:

- Reject `neuron_count <= 0`.
- Create `Neuron` objects named by their array index.
- Pass `number_of_layers`, `history_depth`, and `charge_max` into every neuron.
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
- Pass `number_of_layers`, `history_depth`, and `charge_max` into every neuron.
- Initialize every neuron with `eq = total_input` and `trigger[0] = total_input`.
- Initialize head neuron charge to `min(charge_max, total_input)`.
- Initialize body neuron charge to `min(charge_max, total_input * 0.9)`.
- Initialize `signal[0]` from charge only for head neurons.
- Return a `Brain` with matching constants and generated substrate.

## Boundaries

- Keep simulation processing in `charly6.brain_model`.
- Keep neuron state normalization and serialization in `charly6.neuron`.
- Do not import GUI, YAML config parsing, runtime persistence, or world code.
