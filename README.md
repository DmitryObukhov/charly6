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

- `Brain` tab: edit/load/save brain YAML and initialize the network.
- `World` tab: adjust runtime tick interval, maximum iterations, sequence-line display, neuron radius, and head-sequence controls.
- `Body` tab: view basic statistics.
- `Inputs` tab: edit input physical values and read output group activation ratios.
- Bottom tabs: inspect the world view, selected-neuron CAS chart, active-count chart, neuron fields, and selected-neuron input connectome.

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
