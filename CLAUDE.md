# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Charly6 is a Python GUI application for building, visualizing, and inspecting neuromorphic network layouts. It loads a YAML brain definition, creates a spatial connectome, renders the network in Tkinter, and exposes input/output groups plus selected-neuron state and connectome inspection panels.

**Stack:** Python 3.14, Tkinter, PyYAML, pytest, ruff.

## Setup

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -e ".[dev]"
```

## Commands

```powershell
# Run the app
.\.venv\Scripts\python -m charly6
.\.venv\Scripts\python run.py

# Tests
.\.venv\Scripts\python -m pytest

# Lint
.\.venv\Scripts\python -m ruff check .
```

## Architecture

Use `src/charly6/` layout:

```text
src/charly6/
  __init__.py       # public exports
  __main__.py       # python -m charly6 entrypoint
  brain.py          # Brain, Neuron, Substrate simulation engine
  diagram.py        # PHC/Hilbert canvas layout helpers
  app.py            # Tkinter root window, YAML config, visualization
worlds/
  linear.py         # first physical world module with stable function API
tests/
pyproject.toml
```

### Simulation engine

- `Brain` owns a `Substrate` with `brain: list[Neuron]` and `connectome: list[tuple[src, dst, weight]]`.
- One call to `brain.process()` propagates signals from active neurons, applies recharge/discharge, updates `active`, and appends neuron history.
- `brain.get_inputs(signals)` injects floats into the first N neurons.
- `brain.set_outputs(indices)` reads boolean activations.
- Factory functions are `create_random_brain()` and `create_spatial_brain()`.

### GUI layer

- `app.py` owns the `tk.Tk` root and all top-level frames.
- Combined brain/world YAML is edited in the Config tab and may be loaded/saved through the File menu or tab buttons.
- The app stores UI state in `charly6.config.yaml`, including selected tab, visualization/runtime values, and `last_yaml`.
- Visualization settings may appear in legacy YAML files under `visualization`, `display`, or `runtime`, but they are stripped before saving brain YAML.
- The canvas renders neurons using positions from YAML `assembly` steps. Active neurons are green, inactive neurons are dark, selected/input/head neurons have extra markers.
- The Config tab has one combined editor. Brain defaults come from `DEFAULT_BRAIN_CONFIG`; world defaults are nested under `physical_world` from the selected plugin's `GetDefaultConfig`.
- World plugins are discovered from `worlds/` by importing modules with `GetDefaultConfig`, shown in a selector, and initialized/rendered from the nested `physical_world` config.
- Combined YAML loads and saves must validate required brain and world sections and report a specific error before accepting invalid YAML.
- Compatibility is checked after editor changes: every brain input must be present in world outputs, and every world input must be present in brain outputs.
- Runtime ticks use `root.after()`; no threads are used.
- Current GUI step/tick callbacks apply input physical values, refresh output ratios/charts, and increment the iteration counter. They do not currently call `brain.process()`.
- Right-click/click neuron interactions update the selected-neuron CAS, field editor, and input-connectome table.
- Selected-neuron scalar fields (`eq`, `charge`, cumulative signal, elastic trigger delta, recharge, discharge, tiredness, and active) are editable from the GUI.

### Physical world modules

- World implementations live in `worlds/` and follow the prompt/API in `prompts/physical_world.md`.
- `worlds.linear` is the first implementation: a deterministic 2D visualization where the agent has one X coordinate, `stomach_content` in `0..10`, and moves left/right from normalized `left_motor` and `right_motor` inputs. It also has a `light` object with `x` and `brightness`.
- World YAML uses one top-level `world` section for runtime and world settings (`base`, `dt`, `seed`, `input_validation`, `max_steps`, `dimensions`, `bounds`, `drag`); legacy top-level `simulation` remains readable but should not be emitted by defaults.
- World `outputs` use mapping format: `output_name: source_field` (for example, `velocity: velocity`).
- Keep the public API function names stable: `Init`, `Validate`, `GetDefaultConfig`, `Process`, `GetParams`, `SetParam`, `SetParams`, and `GetVisualization`.
- `GetVisualization` returns the module's lightweight raster `Image` type, avoiding extra runtime dependencies beyond PyYAML.

### YAML model

- `brain`: supports `neurons`, `head_size`, `connections_per_neuron`/`connections`, `max_synapse_length`/`max_synapse`, `weight_min`, `weight_max`, `total_input`, and `seed`.
- `assembly`: list of layout steps. Supported methods are `phc`, `spiral`, and `straight`/`stright`. Steps support `method`, `count`, and `params`/`options`; a `count` of `LAST` fills the remaining `brain.neurons`.
- `inputs`: list or mapping of named inputs. Each input supports `center`, `radius`, `number`, `eq_min`, `eq_max`, and `value`/`physical_value`.
- `outputs`: list or mapping of named output groups. Outputs can specify indices as a list, comma-separated string, or aliases `indices`, `actuators`, or `neurons`.
- `transfer_function` may appear in YAML, but the current GUI does not consume it.
- `physical_world` contains the selected world plugin's YAML (`world`, `objects`, `inputs`, and `outputs`).

## Key conventions

- Dataclasses with `slots=True` for data structures.
- `Neuron` fields: `active`, `eq`, `charge`, `cumulative_signal`, `elastic_trigger_delta`, `elastic_recharge`, `cyclic_discharge`, `tiredness`, `history_table`.
- Connectome is `list[tuple[int, int, float]]`: `(src_idx, dst_idx, weight)`.
- Spatial connectomes are generated destination-first from nearby source neurons and normalized so each destination receives `total_input` aggregate incoming weight.
- Keep simulation engine state in dataclasses and pass config through constructor/function arguments rather than global mutable state.
