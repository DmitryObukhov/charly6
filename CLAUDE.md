# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Charly6 is a Python GUI application for neuromorphic network simulation and training. It is the GUI successor to `../charcir` (a CLI-only visualizer). The simulation engine concepts (Brain, Neuron, Substrate, connectome) originate there and should be reused or adapted.

**Stack:** Python 3.14+, Tkinter (stdlib GUI), pytest, ruff. No third-party runtime dependencies.

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

# Tests
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m pytest tests/test_brain.py   # single file

# Lint
.\.venv\Scripts\python -m ruff check .
```

## Architecture

Use `src/charly6/` layout (matching `charcir`):

```
src/charly6/
  __init__.py       # public exports
  __main__.py       # python -m charly6 entrypoint
  brain.py          # Brain, Neuron, Substrate simulation engine
  diagram.py        # canvas layout helpers
  app.py            # Tkinter root window, main loop
  trainer.py        # training loop, learning rules, reward signals
tests/
pyproject.toml
```

### Simulation engine (from charcir)

- **`Brain`** owns a `Substrate` (list of `Neuron` + connectome `list[tuple[src, dst, weight]]`).
- One call to `brain.process()` propagates signals: active neurons (charge ≥ threshold) push `charge * weight` to their destinations, then each neuron discharges or recharges and updates `active`.
- `brain.get_inputs(signals)` injects floats into the first N neurons; `brain.set_outputs(indices)` reads boolean activations.

### GUI layer

- `app.py` owns the `tk.Tk` root and all top-level frames.
- The canvas renders neurons as a circle diagram (see `charcir/src/charcir/diagram.py` for the layout math). Active neurons are green, inactive are black.
- The GUI drives the simulation via `root.after()` ticks — no threads for the sim loop.

### Training layer

- `trainer.py` wraps a `Brain` and implements learning rules (e.g., Hebbian, STDP, reward-modulated).
- Training state (weights, iteration count, loss curve) is separate from the `Brain` dataclass so the sim engine stays pure.

## Key conventions from charcir

- Dataclasses with `slots=True` for all data structures.
- `Neuron` fields: `active`, `eq`, `charge`, `cumulative_signal`, `elastic_trigger_delta`, `elastic_recharge`, `cyclic_discharge`, `tiredness`, `history_table`.
- Connectome is `list[tuple[int, int, float]]` — `(src_idx, dst_idx, weight)`.
- Factory functions (`create_random_brain`, `create_ring_brain`) return fully initialized `Brain` objects.
- All config via constructor args; no global mutable state.
