# Brain Model Prompt

## Purpose

Define the Charly6 brain state model separately from brain construction helpers,
GUI code, YAML parsing, runtime persistence, and world integration.

## Module

`charly6.brain_model` owns the simulation state classes:

- `Connection`: tuple of `(src_idx, dst_idx, weight)`
- `Substrate`: small dataclass with `brain: list[Neuron]` and `connectome: list[Connection]`
- `Brain`: small dataclass with `substrate`, `iteration_idx`, `number_of_layers`,
  `history_depth`, and `charge_max`

Default constants come from `charly6.neuron`:

- `DEFAULT_NUMBER_OF_LAYERS = 1`
- `DEFAULT_HISTORY_DEPTH = 32`
- `DEFAULT_CHARGE_MAX = 100.0`

## Serialization

- `Substrate.to_dict()` serializes neurons through `Neuron.to_dict()`.
- Connectome tuples serialize as JSON-compatible lists.
- `Substrate.from_dict()` restores neuron objects and tuple connectome entries.
- `Brain.to_dict()` includes substrate, iteration index, and brain-level constants.
- `Brain.from_dict()` restores substrate, iteration index, and constants with defaults.

## Input Processing

- `Brain.get_inputs(inputs)` injects each input value into the matching neuron index.
- It adds the value to `signal[0]`, clamps visible charge into `[charge_min, charge_max]`,
  updates `active` from layer-0 trigger math, and accumulates `cumulative_signal`.
- It rejects input lists longer than the neuron count.

## Simulation Processing

`Brain.process()` must:

- Normalize every neuron for the current brain constants.
- Assign the default neuron name from its array index if missing.
- Apply `history_depth`, `charge_max`, and layer count to every neuron.
- Resize status/signal/trigger arrays through `Neuron.resize_layers()`.
- Use previous-tick statuses and signals so propagation is synchronous.
- For every connection and every layer, add:

```text
src.signal[layer] * float(src.status[layer]) * weight_for_layer
```

- Apply scalar weights to every layer.
- Allow list/tuple weights internally; shorter lists repeat their last value.
- Set each destination neuron's `signal` to the propagated layer signal array.
- Increase `cumulative_signal` by the sum of propagated signals.
- Set each layer status from:

```text
signal[layer] > trigger[layer] + trigger_flex + eq
```

- Force `status[0] = True` if any layer is active, preserving legacy `active` behavior.
- Apply random discharge to `charge_min` when `discharge_random` fires.
- Decrease active-neuron charge by `cyclic_discharge` down to `charge_min`.
- Increase inactive-neuron charge by `recharge + recharge_flex` up to `charge_max`.
- Increase tiredness with cyclic discharge and decrease it with recharge.
- Append history through `Neuron.record_history(iteration_idx)`.
- Increment `iteration_idx` after processing.

## Outputs

`Brain.set_outputs(output_indices=None)` returns active flags for all neurons or
for the requested indices.

## Boundaries

- Keep neuron field serialization delegated to `charly6.neuron`.
- Keep random/spatial brain construction in `charly6.brain`.
- Do not embed GUI code, YAML config parsing, runtime file persistence, world logic,
  or random brain construction in `charly6.brain_model`.
