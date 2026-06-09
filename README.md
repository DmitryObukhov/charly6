# Charly6

Charly6 is a Python/Tkinter GUI for building and inspecting neuromorphic network layouts. It loads a YAML brain definition, creates a spatial connectome, visualizes neurons on a canvas, and provides panels for input/output values, selected-neuron state, connectome links, and activity charts.

## Requirements

- Python 3.14
- Tkinter, included with the standard Python installer on Windows
- PyYAML, installed through the project dependencies

**Linux note:** Python 3.12 also works. Install tkinter separately:
```bash
sudo apt install python3-tk
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pip install websockets
```

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

The app uses one combined YAML file based on the brain config. Brain sections stay
at the top level, and the physical world config lives under `physical_world`.

Combined YAML supports these top-level sections:

- `brain`: neuron count, head size, connection count, synapse length, weight range, total input, seed, constants, and `Initialization` defaults.
- `assembly`: topology folding steps. Current folding modules are `phc` and `spiral`; legacy `straight`/`stright` is still accepted. A `count` of `LAST` fills the remaining `brain.neurons`.
- `inputs`: named physical inputs. Each input selects neurons around a `center` within a `radius`, assigns `number` selected neurons, and spreads `eq` from `eq_min` to `eq_max`.
- `outputs`: named output groups, each mapped to neuron indices.
- `transfer_function`: currently parsed as YAML content but not used by the GUI runtime.
- `physical_world`: nested world plugin YAML with its own `world`, `objects`, `inputs`, and `outputs`.

## Physical Worlds

Physical world implementations live in `worlds/` and expose the stable API described by `prompts/physical_world.md`: `Init`, `Validate`, `GetDefaultConfig`, `Process`, `GetParams`, `SetParam`, `SetParams`, and `GetVisualization`.

The first implementation is `worlds.linear`, a deterministic 2D visualization with a single agent coordinate on the X axis, a `light` object (`x`, `brightness`), and agent `stomach_content` in the range `0..10`. Its YAML keeps runtime settings such as `base`, `dt`, `seed`, `input_validation`, and `max_steps` inside the top-level `world` section. It accepts normalized `left_motor` and `right_motor` inputs, advances one physics step per `Process` call, and returns float observations such as `velocity`, `hunger`, and `light`.
The second implementation is `worlds.charlie_worm`, a WebSocket bridge to an external Vue 3 2D physics simulation.

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
  NUMBER_OF_LAYERS: 1
  HISTORY_DEPTH: 32
  CHARGE_MAX: 100.0
  Initialization:
    default_charge: charge_max
    default_recharge: 0.2
    default_eq_min: -0.1
    default_eq_max: 0.1

assembly:
  # Available foldings:
  # - phc: pseudo-Hilbert curve, fills the configured space from the first coordinate outward.
  # - spiral: hexagonal spiral, starts at the first coordinate and grows ring by ring.
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

## CharlieWorm 2D World Plugin

`worlds/charlie_worm.py` connects the charly6 brain to a Vue 3 2D worm simulation running in the browser. Both windows run simultaneously — Tkinter shows brain activity, the browser shows the worm moving in the 2D world.

The plugin runs a WebSocket server on port 8765 in a daemon thread. Vue sends sensor data, `Process()` passes it to the brain every 100ms, and brain motor outputs are sent back to Vue.

**Brain inputs (from Vue 2D world):**
- `foodSmell` — food proximity [0..1], pleasure
- `waterSmell` — water proximity [0..1], pleasure
- `lightLux` — light brightness [0..1], pain
- `wallImpact` — wall collision [0..1], pain

**Brain outputs (to Vue 2D world):**
`move_n`, `move_ne`, `move_e`, `move_se`, `move_s`, `move_sw`, `move_w`, `move_nw`

**Running:**
```bash
# Terminal 1 — charly6
source .venv/bin/activate
python run.py
# In UI: Load YAML → brain.yaml → Init → Run

# Terminal 2 — Vue 2D world (separate repo)
cd CharlieWorm
npm run dev
# open http://localhost:5173
```

## Interface

- `Config` tab: generate/edit/load/save the combined brain/world YAML, select a world plugin, inject its default config, and initialize the brain or world.
- `Body` tab: view basic statistics.
- Lower `Inputs` tab: edit input physical values and read output group activation ratios.
- Bottom tabs: inspect the world view, selected-neuron CAS chart, active-count chart, neuron fields, selected-neuron input connectome, and inputs/outputs.

Combined YAML is validated when loaded or saved. Brain and world validators return `(ok, problems)`, and the editor also checks model compatibility after changes: brain input names must be available as world output names, and world input names must be available as brain output names.

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
worlds/
  linear.py        # 1D world — reference implementation
  charlie_worm.py  # 2D world bridge — Vue frontend via WebSocket
tests/
```
