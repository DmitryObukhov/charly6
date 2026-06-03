# Charly6

Charly6 is a Python/Tkinter GUI for building and inspecting neuromorphic network layouts. It loads a YAML brain definition, creates a spatial connectome, visualizes neurons on a canvas, and provides panels for input/output values, selected-neuron state, connectome links, and activity charts.

## Requirements

- Python 3.14
- Tkinter, included with the standard Python installer on Windows
- PyYAML, installed through the project dependencies

## Setup

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -e ".[dev]"
```

## Run

From the project root:

```powershell
.\.venv\Scripts\python -m charly6
```

You can also launch through the root helper:

```powershell
.\.venv\Scripts\python run.py
```

## Configuration

The app remembers local UI state in `charly6.config.yaml`, including the last loaded brain YAML and visualization settings. The sample brain definition is `brain.yaml`.

Brain YAML supports these top-level sections:

- `brain`: neuron count, head size, connection count, synapse length, weight range, total input, and seed.
- `assembly`: layout steps. Current methods are `phc`, `spiral`, and `straight`/`stright`. A `count` of `LAST` fills the remaining `brain.neurons`.
- `inputs`: named physical inputs. Each input selects neurons around a `center` within a `radius`, assigns `number` selected neurons, and spreads `eq` from `eq_min` to `eq_max`.
- `outputs`: named output groups, each mapped to neuron indices.
- `transfer_function`: currently parsed as YAML content but not used by the GUI runtime.

## Physical Worlds

Physical world implementations live in `worlds/` and expose the stable API described by `prompts/physical_world.txt`: `Init`, `GetDefaultConfig`, `Process`, `GetParams`, `SetParam`, `SetParams`, and `GetVisualization`.

The first implementation is `worlds.linear`, a deterministic 2D visualization with a single agent coordinate on the X axis, a `light` object (`x`, `brightness`), and agent `stomach_content` in the range `0..10`. Its YAML keeps runtime settings such as `base`, `dt`, `seed`, `input_validation`, and `max_steps` inside the top-level `world` section. It accepts normalized `left_motor` and `right_motor` inputs, advances one physics step per `Process` call, and returns float observations such as `velocity`, `hunger`, and `light`.

World outputs use mapping format: `output_name: source_field`, for example `velocity: velocity`.

Example:

```yaml
brain:
  neurons: 2000
  head_size: 0
  connections_per_neuron: 10
  max_synapse_length: 0.3
  weight_min: 0.0
  weight_max: 1.0
  total_input: 1000.0
  seed: 42

assembly:
  - method: spiral
    count: LAST
    params: default

inputs:
  - hunger:
    center: 396
    radius: 5
    number: 50
    eq_min: 0
    eq_max: -100

outputs:
  - left_motor: [0, 1, 2, 3, 4]
```

## Interface

- `Brain` tab: generate default brain YAML, edit/load/save brain YAML, and initialize the network.
- `World` tab: select a world plugin, generate its default YAML through `GetDefaultConfig`, edit/load/save world YAML, and initialize the physical world.
- `Body` tab: view basic statistics.
- Lower `Inputs` tab: edit input physical values and read output group activation ratios.
- Bottom tabs: inspect the world view, selected-neuron CAS chart, active-count chart, neuron fields, selected-neuron input connectome, and inputs/outputs.

Brain/world YAML is validated when loaded or saved. The editors also check model compatibility after changes: brain input names must be available as world output names, and world input names must be available as brain output names.

Right-click or click neurons in the brain canvas to inspect state. Editable selected-neuron fields are applied on Enter or focus loss.

## Development

```powershell
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m ruff check .
```

Project layout:

```text
src/charly6/
  __main__.py   # python -m charly6 entrypoint
  app.py        # Tkinter GUI, YAML loading/saving, visualization
  brain.py      # Brain, Neuron, Substrate, connectome simulation engine
  diagram.py    # PHC/Hilbert placement helpers
tests/
```
