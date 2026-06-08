"""Main application window."""

from __future__ import annotations

import importlib
import json
import math
import pkgutil
import random
import re
import shutil
import sqlite3
import subprocess
import tkinter as tk
from collections import deque
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from charly6.body import Body, BodyTranslation
from charly6.brain import Brain, create_spatial_brain
import worlds

_MARGIN = 16.0
# Dot caps are computed dynamically in _draw_brain as a fraction of neuron spacing.

CONFIG_PATH = Path("charly6.config.yaml")
LOG_DIR = Path("logs")
RUNTIME_DIR = Path("runtime")
WORLD_CONFIG_SECTION = "physical_world"
BODY_CONFIG_SECTION = "body"

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only when PyYAML is absent.
    yaml = None


DEFAULT_BRAIN_CONFIG: dict = {
    "ID": "charly_6_1",
    "brain": {
        "neurons": 3000,
        "head_size": 0,
        "connections_per_neuron": 10,
        "max_synapse_length": 0.30,
        "weight_min": 0.0,
        "weight_max": 1.0,
        "total_input": 1000.0,
        "seed": None,
        "NUMBER_OF_LAYERS": 1,
        "HISTORY_DEPTH": 32,
        "CHARGE_MAX": 100.0,
        "Initialization": {
            "default_charge": "charge_max",
            "default_recharge": 0.2,
            "default_eq_min": -0.1,
            "default_eq_max": 0.1,
        },
    },
    "assembly": [
        {
            "method": "phc",
            "count": 3000,
            "params": "default",
        },
    ],
    "inputs": [
        {
            "name": "hunger",
            "center": 2400,
            "radius": 20,
            "number": 30,
            "eq_min": 0,
            "eq_max": -100,
        },
        {
            "name": "light",
            "center": 1400,
            "radius": 80,
            "number": 30,
            "eq_min": 0,
            "eq_max": -100,
        },
    ],
    "outputs": [
        {"left_motor": [0, 1, 2, 3, 4]},
        {"right_motor": [5, 6, 7, 8, 9]},
    ],
    "body": {
        "mappings": [
            {
                "target": "hunger",
                "source": "hunger",
                "formula": "linear",
                "min": 0.0,
                "max": 10.0,
                "clamp": True,
                "rounding": "round",
            },
            {
                "target": "light",
                "source": "light",
                "formula": "linear",
                "min": 0.0,
                "max": 10.0,
                "clamp": True,
                "rounding": "round",
            },
        ],
    },
}

DEFAULT_VISUALIZATION_CONFIG: dict = {
    "display": {
        "show_seq_lines": False,
        "circle_radius": 3,
    },
    "runtime": {
        "tick_ms": 100,
        "max_iter": 0,
        "seq_window": 9,
    },
}


def _parse_yaml_text(text: str) -> dict:
    if yaml is not None:
        data = yaml.safe_load(text) if text.strip() else {}
        return data or {}
    return _parse_simple_yaml(text)


def _dump_yaml(data: dict) -> str:
    if yaml is not None:
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    return _dump_simple_yaml(data)


def _brain_id_from_config(cfg: dict) -> str:
    raw_id = cfg.get("ID")
    if raw_id is None:
        raise ValueError("Missing required top-level section: ID")
    brain_id = str(raw_id).strip()
    if not brain_id:
        raise ValueError("ID must not be empty.")
    return brain_id


def _runtime_safe_id(brain_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", brain_id.strip())
    safe = safe.strip("._")
    if not safe:
        raise ValueError("ID must contain at least one filename-safe character.")
    return safe


def _write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, separators=(",", ":"))
        file.write("\n")
    tmp_path.replace(path)


def _json_list_length(text: str) -> int:
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return 0
    return len(value) if isinstance(value, list) else 0


def _split_visualization_sections(cfg: dict) -> tuple[dict, dict]:
    """Strip app visualization settings from brain YAML, returning them separately."""
    brain_cfg = dict(cfg)
    visualization = brain_cfg.pop("visualization", {})
    if visualization is None:
        visualization = {}
    elif not isinstance(visualization, dict):
        raise ValueError("visualization must be a mapping.")
    else:
        visualization = dict(visualization)

    for section in ("display", "runtime"):
        if section in brain_cfg:
            visualization.setdefault(section, brain_cfg.pop(section))

    return brain_cfg, visualization


def _strip_top_level_sections(text: str, section_names: tuple[str, ...]) -> str:
    """Remove top-level YAML sections while preserving the rest of the source text."""
    lines = text.splitlines(keepends=True)
    kept: list[str] = []
    skip_section = False

    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        is_top_level_data = bool(stripped) and not stripped.startswith("#") and indent == 0

        if is_top_level_data:
            key = stripped.split(":", 1)[0] if ":" in stripped else ""
            if key in section_names:
                skip_section = True
                continue
            skip_section = False

        if skip_section and (indent > 0 or not stripped):
            continue

        kept.append(line)

    return "".join(kept)


def _visualization_config(cfg: dict) -> dict:
    visualization = cfg.get("visualization", {})
    if isinstance(visualization, dict):
        return visualization
    return {}


def _parse_simple_yaml(text: str) -> dict:
    lines: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        lines.append((len(raw_line) - len(raw_line.lstrip(" ")), raw_line.strip()))

    def parse_block(index: int, indent: int):
        if index >= len(lines):
            return {}, index
        if lines[index][0] < indent:
            return {}, index
        if lines[index][0] == indent and lines[index][1].startswith("- "):
            return parse_list(index, indent)
        return parse_mapping(index, indent)

    def parse_list(index: int, indent: int):
        items = []
        while index < len(lines):
            line_indent, line = lines[index]
            if line_indent < indent:
                break
            if line_indent != indent or not line.startswith("- "):
                break
            item_text = line[2:].strip()
            index += 1
            if not item_text:
                item, index = parse_block(index, indent + 2)
                items.append(item)
                continue
            if ":" not in item_text:
                items.append(_parse_yaml_scalar(item_text))
                continue

            key, raw_value = item_text.split(":", 1)
            item = {}
            value = raw_value.strip()
            if value:
                item[key.strip()] = _parse_yaml_scalar(value)
            else:
                if index < len(lines) and lines[index][0] > indent:
                    nested, next_index = parse_block(index, lines[index][0])
                    item[key.strip()] = nested
                    index = next_index
                else:
                    item[key.strip()] = None

            if index < len(lines) and lines[index][0] > indent:
                extra, index = parse_mapping(index, lines[index][0])
                if isinstance(extra, dict):
                    item.update(extra)
            items.append(item)
        return items, index

    def parse_mapping(index: int, indent: int):
        mapping = {}
        while index < len(lines):
            line_indent, line = lines[index]
            if line_indent < indent:
                break
            if line_indent != indent:
                break
            if line.startswith("- "):
                break
            if ":" not in line:
                raise ValueError(f"Invalid YAML line: {line}")
            key, raw_value = line.split(":", 1)
            key = key.strip()
            value = raw_value.strip()
            index += 1
            if value:
                mapping[key] = _parse_yaml_scalar(value)
            elif index < len(lines) and lines[index][0] > indent:
                mapping[key], index = parse_block(index, lines[index][0])
            else:
                mapping[key] = None
        return mapping, index

    parsed, index = parse_block(0, 0)
    if index != len(lines):
        raise ValueError(f"Invalid YAML line: {lines[index][1]}")
    if not isinstance(parsed, dict):
        raise ValueError("YAML root must be a mapping.")
    return parsed


def _parse_yaml_scalar(value: str):
    lowered = value.lower()
    if lowered in {"null", "none", "~"}:
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _dump_simple_yaml(data: dict, indent: int = 0) -> str:
    lines: list[str] = []
    pad = " " * indent
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"{pad}{key}:")
            lines.append(_dump_simple_yaml(value, indent + 2).rstrip())
        elif isinstance(value, list):
            lines.append(f"{pad}{key}:")
            for item in value:
                if isinstance(item, dict):
                    if not item:
                        lines.append(f"{pad}  - {{}}")
                        continue
                    first = True
                    for item_key, item_value in item.items():
                        prefix = "- " if first else "  "
                        item_pad = f"{pad}  {prefix}"
                        if isinstance(item_value, dict):
                            lines.append(f"{item_pad}{item_key}:")
                            lines.append(_dump_simple_yaml(item_value, indent + 4).rstrip())
                        elif isinstance(item_value, list):
                            lines.append(f"{item_pad}{item_key}:")
                            lines.append(_dump_simple_yaml({item_key: item_value}, indent + 4).split(":", 1)[1].strip())
                        else:
                            lines.append(f"{item_pad}{item_key}: {_format_yaml_scalar(item_value)}")
                        first = False
                else:
                    lines.append(f"{pad}  - {_format_yaml_scalar(item)}")
        else:
            lines.append(f"{pad}{key}: {_format_yaml_scalar(value)}")
    return "\n".join(lines) + "\n"


def _format_yaml_scalar(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Charly6 — Neuromorphic Simulator")
        self._vars: dict[str, tk.Variable] = {}
        self._running = False
        self._tick_id: str | None = None
        self._iteration: int = 0
        self._vars["tick_ms"] = tk.IntVar(value=100)
        self._vars["max_iter"] = tk.IntVar(value=0)
        self._vars["seq_window"] = tk.IntVar(value=9)
        self._vars["avg_activity_window"] = tk.IntVar(value=100)
        self._vars["summary_depth"] = tk.IntVar(value=1000)
        self._vars["summary_show_active"] = tk.BooleanVar(value=True)
        self._vars["summary_show_inputs"] = tk.BooleanVar(value=True)
        self._vars["summary_show_ces_pos"] = tk.BooleanVar(value=True)
        self._vars["summary_show_ces_neg"] = tk.BooleanVar(value=True)
        self._vars["record_video"] = tk.BooleanVar(value=False)
        self._vars["video_fps"] = tk.IntVar(value=30)
        self._vars["video_file"] = tk.StringVar(value="")
        self._vars["video_summary_on_map"] = tk.BooleanVar(value=False)
        self._vars["video_summary_height"] = tk.IntVar(value=40)
        self._brain: Brain | None = None
        self._brain_id: str | None = None
        self._runtime_active_overrides: dict[int, bool] = {}
        self._positions: list[tuple[float, float]] = []
        self._in_counts: list[int] = []
        self._out_counts: list[int] = []
        self._input_indices: set[int] = set()
        self._input_specs: list[dict] = []
        self._output_specs: list[dict] = []
        self._body: Body | None = None
        self._last_active_input_indices: list[list[int]] = []
        self._input_value_vars: dict[str, tk.StringVar] = {}
        self._output_value_vars: dict[str, tk.StringVar] = {}
        self._inputs_editor_frame: ttk.Frame | None = None
        self._head_size: int = 0
        self._seq_cursor: int = 0
        self._seq_window: list[int] = []   # indices active in current brightness window
        self._seq_running: bool = False
        self._seq_tick_id: str | None = None
        self._seq_label: ttk.Label | None = None
        self._circle_radius: float = 3.0
        # chart history (last 1000 ticks)
        self._act_history: deque[float] = deque(maxlen=1000)
        self._active_input_history: deque[float] = deque(maxlen=1000)
        self._ces_pos_history: deque[float] = deque(maxlen=1000)
        self._ces_neg_history: deque[float] = deque(maxlen=1000)
        self._last_active_input_count: int = 0
        self._cas_neuron_idx: int | None = None
        self._highlight_neuron_idx: int | None = None
        self._cas_charge: deque[float] = deque(maxlen=1000)
        self._cas_active: deque[float] = deque(maxlen=1000)
        self._cas_signal: deque[float] = deque(maxlen=1000)
        self._logic_history_path: Path | None = None
        self._logic_history_rows: deque[dict] = deque(maxlen=1000)
        self._video_recording: bool = False
        self._video_frame_dir: Path | None = None
        self._video_frame_count: int = 0
        self._video_output_path: Path | None = None
        self._history_tree: ttk.Treeview | None = None
        self._history_detail_text: scrolledtext.ScrolledText | None = None
        self._history_status_var = tk.StringVar(value="No logic history file")
        # view transform (zoom + pan)
        self._view_x: float = 0.5   # brain-space x at canvas centre
        self._view_y: float = 0.5   # brain-space y at canvas centre
        self._view_scale: float = 1.0
        self._drag_start: tuple[int, int] | None = None
        self._drag_moved: bool = False
        self._adj_in:  dict[int, list[tuple[int, float]]] = {}  # dst → [(src, w)]
        self._adj_out: dict[int, list[tuple[int, float]]] = {}  # src → [(dst, w)]
        self._neuron_fields_panel: dict = {}
        self._neuron_connectome_panel: dict = {}
        self._brain_yaml_path: Path | None = None
        self._world_yaml_path: Path | None = None
        self._world_initialized: bool = False
        self._world_first_process_pending: bool = False
        self._world_photo: tk.PhotoImage | None = None
        self._world_plugins = self._discover_world_plugins()
        self._world_model_var: tk.StringVar | None = None
        self._world_module = self._world_plugins.get("worlds.linear") or next(iter(self._world_plugins.values()))
        self._log_path = self._create_log_path()
        self._log_lines: list[str] = []
        self._log_text: scrolledtext.ScrolledText | None = None
        self._log_filter_var = tk.StringVar(value="")
        self._log_search_var = tk.StringVar(value="")
        self._log_status_var = tk.StringVar(value="")
        self._build_menu()
        self._build_layout()
        self._log(f"Opened log {self._log_path}")
        self.state('zoomed')
        self._load_config(CONFIG_PATH)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Menu ──────────────────────────────────────────────────────────────────

    def _discover_world_plugins(self) -> dict[str, object]:
        plugins: dict[str, object] = {}
        for module_info in pkgutil.iter_modules(worlds.__path__, f"{worlds.__name__}."):
            module = importlib.import_module(module_info.name)
            if callable(getattr(module, "GetDefaultConfig", None)):
                plugins[module_info.name] = module
        if not plugins:
            raise RuntimeError("No world plugins with GetDefaultConfig found.")
        return dict(sorted(plugins.items()))

    def _world_module_name_from_config(self, cfg: dict) -> str | None:
        section = cfg.get("world", {})
        if not isinstance(section, dict):
            return None
        raw_base = section.get("base")
        if raw_base is None and isinstance(cfg.get("simulation"), dict):
            raw_base = cfg["simulation"].get("base")
        if not raw_base:
            return None
        base = str(raw_base).replace("\\", "/")
        if base.endswith(".py"):
            base = base[:-3]
        return base.replace("/", ".")

    def _world_module_for_config(self, cfg: dict):
        module_name = self._world_module_name_from_config(cfg)
        if module_name:
            module = self._world_plugins.get(module_name)
            if module is None:
                try:
                    module = importlib.import_module(module_name)
                except ImportError as exc:
                    raise ValueError(f"Unknown world plugin: {module_name}") from exc
            if not callable(getattr(module, "GetDefaultConfig", None)):
                raise ValueError(f"World plugin {module_name} does not define GetDefaultConfig.")
            return module
        return self._selected_world_module()

    def _selected_world_module(self):
        if self._world_model_var is not None:
            name = self._world_model_var.get()
            if name in self._world_plugins:
                return self._world_plugins[name]
        return self._world_module

    def _select_world_module(self, module) -> None:
        self._world_module = module
        if self._world_model_var is not None:
            self._world_model_var.set(module.__name__)

    def _build_menu(self) -> None:
        bar = tk.Menu(self)
        file_menu = tk.Menu(bar, tearoff=0)
        file_menu.add_command(label="Load brain YAML...", command=self._load_brain_yaml_dialog)
        file_menu.add_command(label="Save brain YAML", command=self._save_brain_yaml)
        file_menu.add_command(label="Save brain YAML as...", command=self._save_brain_yaml_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        bar.add_cascade(label="File", menu=file_menu)
        self.config(menu=bar)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        # Outer horizontal split: viz (left) | control (right)
        self._main_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self._main_pane.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Left: vertical split brain (top) | world/charts (bottom), with run controls below.
        left = ttk.Frame(self._main_pane)
        self._main_pane.add(left, weight=3)

        self._build_execution_controls(left)

        self._viz_pane = ttk.PanedWindow(left, orient=tk.VERTICAL)
        self._viz_pane.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        brain_frame = ttk.LabelFrame(self._viz_pane, text=" Brain ")
        self._viz_pane.add(brain_frame, weight=1)
        self._neuron_info_label = ttk.Label(
            brain_frame, text="", font=("Courier", 9), anchor="w", foreground="#888888"
        )
        self._neuron_info_label.pack(side=tk.BOTTOM, fill=tk.X, padx=4, pady=(0, 2))

        self._brain_top_nb = ttk.Notebook(brain_frame)
        self._brain_top_nb.pack(fill=tk.BOTH, expand=True)

        brain_map_tab = ttk.Frame(self._brain_top_nb)
        self._brain_top_nb.add(brain_map_tab, text=" Brain Map ")
        self._brain_canvas = tk.Canvas(brain_map_tab, bg="#0d1117")
        self._brain_canvas.pack(fill=tk.BOTH, expand=True)
        self._brain_canvas.bind("<Configure>",      self._on_brain_resize)
        self._brain_canvas.bind("<MouseWheel>",      self._on_brain_scroll)
        self._brain_canvas.bind("<ButtonPress-1>",   self._on_brain_drag_start)
        self._brain_canvas.bind("<B1-Motion>",       self._on_brain_drag)
        self._brain_canvas.bind("<ButtonRelease-1>", self._on_brain_drag_end)
        self._brain_canvas.bind("<Button-3>",        self._on_brain_right_click)

        brain_avg_tab = ttk.Frame(self._brain_top_nb)
        self._brain_top_nb.add(brain_avg_tab, text=" Brain Average ")
        avg_controls = ttk.Frame(brain_avg_tab)
        avg_controls.pack(side=tk.TOP, fill=tk.X, padx=6, pady=4)
        ttk.Label(avg_controls, text="N").pack(side=tk.LEFT, padx=(0, 4))
        self._avg_activity_entry = ttk.Entry(
            avg_controls,
            textvariable=self._vars["avg_activity_window"],
            width=6,
        )
        self._avg_activity_entry.pack(side=tk.LEFT)
        self._avg_activity_entry.bind("<Return>", lambda _event: self._draw_brain_average())
        self._avg_activity_entry.bind("<FocusOut>", lambda _event: self._draw_brain_average())
        self._brain_average_canvas = tk.Canvas(brain_avg_tab, bg="#0d1117")
        self._brain_average_canvas.pack(fill=tk.BOTH, expand=True)
        self._brain_average_canvas.bind("<Configure>", self._draw_brain_average)

        self._bottom_nb = ttk.Notebook(self._viz_pane)
        self._viz_pane.add(self._bottom_nb, weight=1)

        world_tab = ttk.Frame(self._bottom_nb)
        self._bottom_nb.add(world_tab, text=" World ")
        self._world_canvas = tk.Canvas(world_tab, bg="#111827")
        self._world_canvas.pack(fill=tk.BOTH, expand=True)
        self._world_canvas.bind("<Configure>", self._on_world_resize)

        cas_tab = ttk.Frame(self._bottom_nb)
        self._bottom_nb.add(cas_tab, text=" Neuron CAS ")
        self._cas_canvas = tk.Canvas(cas_tab, bg="#0d1117")
        self._cas_canvas.pack(fill=tk.BOTH, expand=True)
        self._cas_canvas.bind("<Configure>", self._draw_cas)

        act_tab = ttk.Frame(self._bottom_nb)
        self._bottom_nb.add(act_tab, text=" Activity Summary ")
        act_controls = ttk.Frame(act_tab)
        act_controls.pack(side=tk.TOP, fill=tk.X, padx=6, pady=4)
        for key, label in (
            ("summary_show_active", "Active count %"),
            ("summary_show_inputs", "Active input neurons"),
            ("summary_show_ces_pos", "CES pos"),
            ("summary_show_ces_neg", "CES neg"),
        ):
            ttk.Checkbutton(
                act_controls,
                text=label,
                variable=self._vars[key],
                command=self._draw_act_count,
            ).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(act_controls, text="Depth").pack(side=tk.LEFT, padx=(8, 4))
        self._summary_depth_entry = ttk.Entry(
            act_controls,
            textvariable=self._vars["summary_depth"],
            width=7,
        )
        self._summary_depth_entry.pack(side=tk.LEFT)
        self._summary_depth_entry.bind("<Return>", lambda _event: self._draw_act_count())
        self._summary_depth_entry.bind("<FocusOut>", lambda _event: self._draw_act_count())
        ttk.Checkbutton(
            act_controls,
            text="On map",
            variable=self._vars["video_summary_on_map"],
            command=self._draw_brain,
        ).pack(side=tk.LEFT, padx=(10, 3))
        ttk.Label(act_controls, text="Height").pack(side=tk.LEFT, padx=(8, 3))
        self._video_summary_height_entry = ttk.Entry(
            act_controls,
            textvariable=self._vars["video_summary_height"],
            width=5,
        )
        self._video_summary_height_entry.pack(side=tk.LEFT, padx=3)
        self._video_summary_height_entry.bind("<Return>", lambda _event: self._draw_brain())
        self._video_summary_height_entry.bind("<FocusOut>", lambda _event: self._draw_brain())
        self._act_canvas = tk.Canvas(act_tab, bg="#0d1117")
        self._act_canvas.pack(fill=tk.BOTH, expand=True)
        self._act_canvas.bind("<Configure>", self._draw_act_count)

        neuron_fields_tab = ttk.Frame(self._bottom_nb)
        self._bottom_nb.add(neuron_fields_tab, text=" Neuron fields ")
        self._neuron_fields_panel = self._build_neuron_fields_section(neuron_fields_tab, row=0)

        neuron_connectome_tab = ttk.Frame(self._bottom_nb)
        self._bottom_nb.add(neuron_connectome_tab, text=" Neuron connectome ")
        self._neuron_connectome_panel = self._build_neuron_connectome_section(neuron_connectome_tab, row=0)

        inputs_tab = ttk.Frame(self._bottom_nb)
        self._bottom_nb.add(inputs_tab, text=" Inputs ")
        self._build_inputs_tab(inputs_tab)

        self._bottom_nb.bind("<<NotebookTabChanged>>", lambda _: self._refresh_charts())

        # Right: tabbed control panel
        ctrl = ttk.Frame(self._main_pane)
        self._main_pane.add(ctrl, weight=1)

        self._notebook = ttk.Notebook(ctrl)
        self._notebook.pack(fill=tk.BOTH, expand=True)

        self._init_tab = ttk.Frame(self._notebook)
        self._history_tab = ttk.Frame(self._notebook)
        self._log_tab = ttk.Frame(self._notebook)

        self._notebook.add(self._init_tab,    text="Config")
        self._notebook.add(self._history_tab, text="History")
        self._notebook.add(self._log_tab, text="Log")

        self._build_init_tab()
        self._build_history_tab()
        self._build_log_tab()

    # ── Tab: Initialization ───────────────────────────────────────────────────

    def _build_execution_controls(self, parent: tk.Widget) -> None:
        ctrl = ttk.LabelFrame(parent, text=" Execution controls ")
        ctrl.pack(side=tk.BOTTOM, fill=tk.X, pady=(4, 0))
        ctrl.pack_propagate(True)

        btn_row = ttk.Frame(ctrl)
        btn_row.pack(padx=8, pady=6, anchor="center")
        ttk.Button(btn_row, text="↺  Reset", command=self._on_reset).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn_row, text="■  Pause", command=self._on_stop).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn_row, text="▶  Run", command=self._on_start).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn_row, text="⏭  Step", command=self._on_step).pack(side=tk.LEFT, padx=3)

        video_row = ttk.Frame(ctrl)
        video_row.pack(padx=8, pady=(0, 6), anchor="center", fill=tk.X)
        ttk.Checkbutton(video_row, text="Record video", variable=self._vars["record_video"]).pack(side=tk.LEFT, padx=3)
        ttk.Label(video_row, text="FPS").pack(side=tk.LEFT, padx=(10, 3))
        ttk.Entry(video_row, textvariable=self._vars["video_fps"], width=5).pack(side=tk.LEFT, padx=3)
        ttk.Label(video_row, text="File").pack(side=tk.LEFT, padx=(10, 3))
        self._video_file_entry = ttk.Entry(video_row, textvariable=self._vars["video_file"], width=42)
        self._video_file_entry.pack(side=tk.LEFT, padx=3, fill=tk.X, expand=True)
        self._vars["video_file"].set(str(self._default_video_path()))

        self._iter_label = ttk.Label(ctrl, text="Iteration: 0", foreground="gray")
        self._iter_label.pack(padx=8, pady=(0, 6), anchor="center")

    def _update_iteration_display(self) -> None:
        self._iter_label.config(text=f"Iteration: {self._iteration}")
        self._draw_brain()
        self._draw_brain_average()

    def _build_init_tab(self) -> None:
        p = self._init_tab
        p.columnconfigure(0, weight=1)
        p.rowconfigure(0, weight=1)

        editor_frame = ttk.LabelFrame(p, text=" Brain + body + world config YAML ")
        editor_frame.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 4))
        editor_frame.rowconfigure(0, weight=1)
        editor_frame.columnconfigure(0, weight=1)

        self._brain_yaml_editor = scrolledtext.ScrolledText(
            editor_frame,
            wrap=tk.NONE,
            undo=True,
            font=("Courier", 10),
            height=24,
        )
        self._brain_yaml_editor.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self._set_brain_yaml_text(_dump_yaml(self._default_combined_config()))
        self._brain_yaml_editor.bind("<<Modified>>", self._on_yaml_editor_modified)

        self._yaml_path_label = ttk.Label(editor_frame, text="Unsaved YAML", foreground="gray", anchor="w")
        self._yaml_path_label.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 6))

        self._vars["show_seq_lines"] = tk.BooleanVar(value=False)

        act = ttk.Frame(p)
        act.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        ttk.Button(act, text="Default", command=self._load_default_brain_yaml).pack(side=tk.LEFT, padx=4)
        ttk.Button(act, text="Load YAML", command=self._load_brain_yaml_dialog).pack(side=tk.LEFT, padx=4)
        ttk.Button(act, text="Save YAML", command=self._save_brain_yaml).pack(side=tk.LEFT, padx=4)
        ttk.Button(act, text="Save YAML as...", command=self._save_brain_yaml_dialog).pack(side=tk.LEFT, padx=4)
        self._world_model_var = tk.StringVar(value=self._world_module.__name__)
        ttk.Combobox(
            act,
            textvariable=self._world_model_var,
            values=list(self._world_plugins),
            state="readonly",
            width=18,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(act, text="Default World", command=self._load_default_world_yaml).pack(side=tk.LEFT, padx=4)
        ttk.Button(act, text="Validate", command=self._on_validate_config).pack(side=tk.RIGHT, padx=4)
        ttk.Button(act, text="Init", command=self._on_initialize_all).pack(side=tk.RIGHT, padx=4)
        self._status_label = ttk.Label(act, text="Not initialized", foreground="gray")
        self._status_label.pack(side=tk.LEFT, padx=8)
        self._world_status_label = ttk.Label(act, text="World not initialized", foreground="gray")
        self._world_status_label.pack(side=tk.LEFT, padx=8)
        self._compat_status_label = ttk.Label(act, text="", foreground="gray")
        self._compat_status_label.pack(side=tk.LEFT, padx=8)

    # ── Tab: Run time ─────────────────────────────────────────────────────────

    def _build_runtime_tab(self) -> None:
        p = self._runtime_tab
        p.columnconfigure(0, weight=1)
        p.rowconfigure(0, weight=1)
        self._vars["tick_ms"] = tk.IntVar(value=100)
        self._vars["max_iter"] = tk.IntVar(value=0)
        self._vars["seq_window"] = tk.IntVar(value=9)
        editor_frame = ttk.LabelFrame(p, text=" World config YAML ")
        editor_frame.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 4))
        editor_frame.rowconfigure(0, weight=1)
        editor_frame.columnconfigure(0, weight=1)

        self._world_yaml_editor = scrolledtext.ScrolledText(
            editor_frame,
            wrap=tk.NONE,
            undo=True,
            font=("Courier", 10),
            height=24,
        )
        self._world_yaml_editor.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self._set_world_yaml_text(self._world_module.GetDefaultConfig())
        self._world_yaml_editor.bind("<<Modified>>", self._on_yaml_editor_modified)

        self._world_yaml_path_label = ttk.Label(editor_frame, text="Unsaved YAML", foreground="gray", anchor="w")
        self._world_yaml_path_label.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 6))

        act = ttk.Frame(p)
        act.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        ttk.Button(act, text="Default", command=self._load_default_world_yaml).pack(side=tk.LEFT, padx=4)
        self._world_model_var = tk.StringVar(value=self._world_module.__name__)
        ttk.Combobox(
            act,
            textvariable=self._world_model_var,
            values=list(self._world_plugins),
            state="readonly",
            width=18,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(act, text="Load YAML", command=self._load_world_yaml_dialog).pack(side=tk.LEFT, padx=4)
        ttk.Button(act, text="Save YAML", command=self._save_world_yaml).pack(side=tk.LEFT, padx=4)
        ttk.Button(act, text="Save YAML as...", command=self._save_world_yaml_dialog).pack(side=tk.LEFT, padx=4)
        ttk.Button(act, text="Init", command=self._on_world_initialize).pack(side=tk.RIGHT, padx=4)
        self._world_status_label = ttk.Label(act, text="Not initialized", foreground="gray")
        self._world_status_label.pack(side=tk.LEFT, padx=8)
        self._compat_status_label = ttk.Label(act, text="", foreground="gray")
        self._compat_status_label.pack(side=tk.LEFT, padx=8)
        return

        sim = ttk.LabelFrame(p, text=" Simulation ")
        sim.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        sim.columnconfigure(1, weight=1)

        self._slider(sim, "tick_ms", "Tick interval (ms)", 1, 2000, 100, row=0)
        self._slider(sim, "max_iter", "Max iterations (0 = ∞)", 0, 100_000, 0, row=1)

        head_seq = ttk.LabelFrame(p, text=" Head sequence ")
        head_seq.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        seq_btn_row = ttk.Frame(head_seq)
        seq_btn_row.pack(padx=6, pady=6, anchor="w")
        ttk.Button(seq_btn_row, text="▶  Run",  command=self._on_seq_start).pack(side=tk.LEFT, padx=2)
        ttk.Button(seq_btn_row, text="■  Stop", command=self._on_seq_stop).pack(side=tk.LEFT, padx=2)
        ttk.Button(seq_btn_row, text="⏭  Step", command=self._on_seq_step).pack(side=tk.LEFT, padx=2)
        ttk.Button(seq_btn_row, text="↺  Reset", command=self._on_seq_reset).pack(side=tk.LEFT, padx=2)
        win_frame = ttk.Frame(head_seq)
        win_frame.pack(fill=tk.X, padx=4, pady=(0, 2))
        win_frame.columnconfigure(1, weight=1)
        self._slider(win_frame, "seq_window", "Window size", 1, 30, 9, row=0)
        self._seq_label = ttk.Label(head_seq, text="Step: —", foreground="gray")
        self._seq_label.pack(padx=6, pady=(0, 6), anchor="w")

    # ── Tab: Activity ─────────────────────────────────────────────────────────

    def _build_activity_tab(self) -> None:
        p = self._activity_tab
        p.columnconfigure(0, weight=1)
        p.rowconfigure(1, weight=1)

        stats = ttk.LabelFrame(p, text=" Statistics ")
        stats.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))

        self._stat_labels: dict[str, ttk.Label] = {}
        rows = [("Active neurons", "—"), ("Avg charge", "—"), ("Iteration", "0")]
        for i, (name, init) in enumerate(rows):
            ttk.Label(stats, text=name, width=18, anchor="w").grid(row=i, column=0, padx=6, pady=2, sticky="w")
            lbl = ttk.Label(stats, text=init, anchor="w")
            lbl.grid(row=i, column=1, padx=4, pady=2, sticky="w")
            self._stat_labels[name] = lbl

        chart_frame = ttk.LabelFrame(p, text=" Activity chart ")
        chart_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
        chart_frame.rowconfigure(0, weight=1)
        chart_frame.columnconfigure(0, weight=1)
        self._activity_canvas = tk.Canvas(chart_frame, bg="#0d1117")
        self._activity_canvas.grid(row=0, column=0, sticky="nsew")

    def _build_log_tab(self) -> None:
        p = self._log_tab
        p.columnconfigure(0, weight=1)
        p.rowconfigure(1, weight=1)

        controls = ttk.Frame(p)
        controls.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        controls.columnconfigure(1, weight=1)
        controls.columnconfigure(3, weight=1)

        ttk.Label(controls, text="Search").grid(row=0, column=0, sticky="w", padx=(0, 4))
        search = ttk.Entry(controls, textvariable=self._log_search_var)
        search.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Label(controls, text="Filter").grid(row=0, column=2, sticky="w", padx=(0, 4))
        regex_filter = ttk.Entry(controls, textvariable=self._log_filter_var)
        regex_filter.grid(row=0, column=3, sticky="ew")

        self._log_status_label = ttk.Label(p, textvariable=self._log_status_var, foreground="gray", anchor="w")
        self._log_status_label.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))

        self._log_text = scrolledtext.ScrolledText(
            p,
            wrap=tk.NONE,
            undo=False,
            font=("Courier", 9),
            height=24,
            state=tk.DISABLED,
        )
        self._log_text.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
        self._log_text.tag_configure("search_match", background="#facc15", foreground="#111827")
        self._log_filter_var.trace_add("write", lambda *_: self._refresh_log_view())
        self._log_search_var.trace_add("write", lambda *_: self._refresh_log_view())
        self._refresh_log_view()

    # ── Widget helpers ────────────────────────────────────────────────────────

    def _build_history_tab(self) -> None:
        p = self._history_tab
        p.columnconfigure(0, weight=1)
        p.rowconfigure(1, weight=1)
        p.rowconfigure(3, weight=2)

        ttk.Label(p, textvariable=self._history_status_var, foreground="gray", anchor="w").grid(
            row=0, column=0, sticky="ew", padx=8, pady=(8, 4)
        )

        table_frame = ttk.LabelFrame(p, text=" Logic history ")
        table_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        columns = ("iteration", "active", "ces_pos", "ces_neg", "physical")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=10)
        for col, heading, width, anchor in [
            ("iteration", "Iteration", 72, "e"),
            ("active", "Active", 64, "e"),
            ("ces_pos", "CES+", 82, "e"),
            ("ces_neg", "CES-", 82, "e"),
            ("physical", "Physical interface", 220, "w"),
        ]:
            tree.heading(col, text=heading)
            tree.column(col, width=width, minwidth=width, anchor=anchor)
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        tree.bind("<<TreeviewSelect>>", self._on_history_row_select)
        self._history_tree = tree

        ttk.Label(p, text="Selected iteration record", foreground="gray", anchor="w").grid(
            row=2, column=0, sticky="ew", padx=8, pady=(6, 0)
        )
        detail = scrolledtext.ScrolledText(
            p,
            wrap=tk.NONE,
            undo=False,
            font=("Courier", 8),
            height=12,
            state=tk.DISABLED,
        )
        detail.grid(row=3, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self._history_detail_text = detail
        self._refresh_history_view()

    def _create_log_path(self) -> Path:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = LOG_DIR / f"{timestamp}.log"
        counter = 1
        while path.exists():
            path = LOG_DIR / f"{timestamp}_{counter}.log"
            counter += 1
        path.touch()
        return path

    def _runtime_state_paths(self) -> tuple[Path, Path]:
        if self._brain_id is None:
            raise ValueError("Brain ID is not set.")
        safe_id = _runtime_safe_id(self._brain_id)
        return RUNTIME_DIR / f"{safe_id}_neurons", RUNTIME_DIR / f"{safe_id}_connectome"

    def _default_video_path(self) -> Path:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        raw_id = self._brain_id or "current"
        try:
            safe_id = _runtime_safe_id(raw_id)
        except ValueError:
            safe_id = "current"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return RUNTIME_DIR / f"{safe_id}_{timestamp}.mp4"

    def _resolve_video_output_path(self) -> Path:
        raw_path = str(self._vars["video_file"].get()).strip()
        path = Path(raw_path) if raw_path else self._default_video_path()
        if not path.is_absolute() and path.parent == Path("."):
            path = RUNTIME_DIR / path
        if not path.suffix:
            path = path.with_suffix(".mp4")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._vars["video_file"].set(str(path))
        return path

    def _create_logic_history_path(self) -> Path:
        if self._brain_id is None:
            raise ValueError("Brain ID is not set.")
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        safe_id = _runtime_safe_id(self._brain_id)
        return RUNTIME_DIR / f"{safe_id}_logic.sqlite"

    def _start_logic_history(self) -> None:
        try:
            self._logic_history_path = self._create_logic_history_path()
            self._cleanup_legacy_logic_history_files()
            self._migrate_logic_history_db()
            self._initialize_logic_history_db()
        except (OSError, ValueError, sqlite3.Error) as exc:
            self._logic_history_path = None
            self._history_status_var.set(f"Logic history unavailable: {exc}")
            self._log(f"Logic history initialization failed: {exc}")
            return
        self._logic_history_rows.clear()
        self._history_status_var.set(f"Logic history DB: {self._logic_history_path}")
        self._refresh_history_view()
        self._log(f"Opened logic history DB {self._logic_history_path}")

    def _cleanup_legacy_logic_history_files(self) -> None:
        if self._brain_id is None or self._logic_history_path is None:
            return
        safe_id = _runtime_safe_id(self._brain_id)
        for path in RUNTIME_DIR.glob(f"{safe_id}_logic_*"):
            if path.resolve() == self._logic_history_path.resolve():
                continue
            if path.is_file():
                path.unlink()

    def _initialize_logic_history_db(self) -> None:
        if self._logic_history_path is None:
            raise ValueError("Logic history DB path is not set.")
        if self._brain is None:
            raise ValueError("Brain is not initialized.")
        with sqlite3.connect(self._logic_history_path) as conn:
            conn.execute("DROP TABLE IF EXISTS neuron_history")
            conn.execute("DROP TABLE IF EXISTS physical_io")
            conn.execute("DROP TABLE IF EXISTS iterations")
            conn.execute("DROP TABLE IF EXISTS metadata")
            conn.execute("""
                CREATE TABLE iterations (
                    iteration INTEGER PRIMARY KEY,
                    brain_iteration INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    CES_neg REAL NOT NULL,
                    CES_pos REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE neuron_history (
                    iteration INTEGER NOT NULL,
                    neuron_idx INTEGER NOT NULL,
                    active INTEGER NOT NULL,
                    signal REAL NOT NULL,
                    trigger REAL NOT NULL,
                    active_inputs INTEGER NOT NULL,
                    active_input_indices TEXT NOT NULL,
                    PRIMARY KEY (iteration, neuron_idx),
                    FOREIGN KEY (iteration) REFERENCES iterations(iteration)
                )
            """)
            conn.execute("""
                CREATE TABLE physical_io (
                    iteration INTEGER NOT NULL,
                    direction TEXT NOT NULL,
                    name TEXT NOT NULL,
                    value REAL NOT NULL,
                    PRIMARY KEY (iteration, direction, name),
                    FOREIGN KEY (iteration) REFERENCES iterations(iteration)
                )
            """)
            conn.execute(
                "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            conn.executemany(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                [
                    ("format", "charly6.logic_history.sqlite.v2"),
                    ("id", str(self._brain_id)),
                    ("created_at", datetime.now().isoformat(timespec="seconds")),
                    ("neuron_count", str(len(self._brain.substrate.brain))),
                ],
            )

    def _migrate_logic_history_db(self) -> None:
        if self._logic_history_path is None or not self._logic_history_path.exists():
            return
        with sqlite3.connect(self._logic_history_path) as conn:
            table = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='neuron_history'"
            ).fetchone()
            if table is None:
                return
            columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(neuron_history)").fetchall()
            }
            if "active_input_indices" in columns and "active_inputs" not in columns:
                conn.create_function("json_list_length", 1, _json_list_length)
                conn.execute("ALTER TABLE neuron_history ADD COLUMN active_inputs INTEGER NOT NULL DEFAULT 0")
                conn.execute(
                    """
                    UPDATE neuron_history
                    SET active_inputs = json_list_length(active_input_indices)
                    """
                )

    def _save_runtime_state(self) -> None:
        if self._brain is None:
            return
        try:
            neurons_path, connectome_path = self._runtime_state_paths()
            metadata = {
                "id": self._brain_id,
                "iteration_idx": self._brain.iteration_idx,
                "ui_iteration": self._iteration,
                "saved_at": datetime.now().isoformat(timespec="seconds"),
            }
            _write_json_atomic(neurons_path, {
                **metadata,
                "format": "charly6.neurons.v1",
                "count": len(self._brain.substrate.brain),
                "neurons": [neuron.to_dict() for neuron in self._brain.substrate.brain],
            })
            _write_json_atomic(connectome_path, {
                **metadata,
                "format": "charly6.connectome.v1",
                "count": len(self._brain.substrate.connectome),
                "connectome": [
                    [src_idx, dst_idx, weight]
                    for src_idx, dst_idx, weight in self._brain.substrate.connectome
                ],
            })
        except (OSError, ValueError) as exc:
            self._log(f"Runtime state save failed: {exc}")

    def _physical_interface_values(self) -> dict[str, dict[str, float]]:
        inputs = {
            str(spec["name"]): float(spec.get("value", 0.0))
            for spec in self._input_specs
        }
        outputs = self._brain_output_values()
        return {"inputs": inputs, "outputs": outputs}

    def _active_input_indices(self) -> list[list[int]]:
        if self._brain is None:
            return []
        neurons = self._brain.substrate.brain
        indices: list[list[int]] = [[] for _ in neurons]
        for src_idx, dst_idx, weight in self._brain.substrate.connectome:
            if src_idx >= len(neurons) or dst_idx >= len(neurons):
                continue
            src = neurons[src_idx]
            if not src.status or not src.status[0]:
                continue
            if not src.signal or src.signal[0] * float(weight) == 0.0:
                continue
            indices[dst_idx].append(src_idx)
        return indices

    def _logic_history_active_input_indices(self) -> list[list[int]]:
        if self._brain is None:
            return []
        neurons = self._brain.substrate.brain
        last_indices = object.__getattribute__(self, "__dict__").get(
            "_last_active_input_indices", []
        )
        if len(last_indices) == len(neurons):
            return last_indices
        return self._active_input_indices()

    def _update_last_active_input_indices(self) -> None:
        self._last_active_input_indices = self._active_input_indices()

    def _logic_history_record(self) -> dict:
        if self._brain is None:
            raise ValueError("Brain is not initialized.")
        neurons = self._brain.substrate.brain
        active_neurons = [neuron for neuron in neurons if neuron.active]
        ces_pos = sum(neuron.eq for neuron in active_neurons if neuron.eq > 0.0)
        ces_neg = sum(neuron.eq for neuron in active_neurons if neuron.eq < 0.0)
        active_input_indices = self._logic_history_active_input_indices()
        return {
            "format": "charly6.logic_history.v1",
            "id": self._brain_id,
            "timestamp": datetime.now().isoformat(timespec="milliseconds"),
            "iteration": self._iteration,
            "brain_iteration": self._brain.iteration_idx,
            "CES_pos": ces_pos,
            "CES_neg": ces_neg,
            "physical_interface": self._physical_interface_values(),
            "neurons": [
                {
                    "index": idx,
                    "active": neuron.active,
                    "trigger0": neuron.trigger[0] if neuron.trigger else 0.0,
                    "signal0": neuron.signal[0] if neuron.signal else 0.0,
                    "active_input_indices": active_input_indices[idx] if idx < len(active_input_indices) else [],
                    "charge": neuron.charge,
                }
                for idx, neuron in enumerate(neurons)
            ],
        }

    def _append_logic_history(self) -> None:
        if self._brain is None:
            return
        if self._logic_history_path is None:
            self._start_logic_history()
            if self._logic_history_path is None:
                return
        try:
            record = self._logic_history_record()
            self._append_logic_history_db(record)
        except (sqlite3.Error, TypeError, ValueError) as exc:
            self._log(f"Logic history DB save failed: {exc}")
            self._history_status_var.set(f"Logic history DB save failed: {exc}")
            return
        self._logic_history_rows.append(record)
        self._history_status_var.set(f"Logic history DB: {self._logic_history_path}")
        self._refresh_history_view()

    def _append_logic_history_db(self, record: dict) -> None:
        if self._logic_history_path is None:
            raise ValueError("Logic history DB path is not set.")
        interface = record.get("physical_interface", {})
        inputs = interface.get("inputs", {})
        outputs = interface.get("outputs", {})
        with sqlite3.connect(self._logic_history_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO iterations
                    (iteration, brain_iteration, timestamp, CES_neg, CES_pos)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    record.get("iteration", 0),
                    record.get("brain_iteration", 0),
                    record.get("timestamp", ""),
                    record.get("CES_neg", 0.0),
                    record.get("CES_pos", 0.0),
                ),
            )
            conn.executemany(
                """
                INSERT OR REPLACE INTO physical_io
                    (iteration, direction, name, value)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (record.get("iteration", 0), "input", str(name), float(value))
                    for name, value in inputs.items()
                ] + [
                    (record.get("iteration", 0), "output", str(name), float(value))
                    for name, value in outputs.items()
                ],
            )
            conn.executemany(
                """
                INSERT OR REPLACE INTO neuron_history
                    (iteration, neuron_idx, active, signal, trigger, active_inputs, active_input_indices)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        record.get("iteration", 0),
                        int(neuron.get("index", 0)),
                        1 if neuron.get("active", False) else 0,
                        float(neuron.get("signal0", 0.0)),
                        float(neuron.get("trigger0", 0.0)),
                        len(neuron.get("active_input_indices", [])),
                        json.dumps(
                            [int(idx) for idx in neuron.get("active_input_indices", [])],
                            separators=(",", ":"),
                        ),
                    )
                    for neuron in record.get("neurons", [])
                ],
            )

    def _log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"{timestamp}  {message}"
        self._log_lines.append(line)
        try:
            with self._log_path.open("a", encoding="utf-8") as log_file:
                log_file.write(line + "\n")
        except OSError as exc:
            self._log_status_var.set(f"Could not write log: {exc}")
        self._refresh_log_view()

    def _refresh_log_view(self) -> None:
        text = self._log_text
        if text is None:
            return

        lines = self._log_lines
        filter_pattern = self._log_filter_var.get().strip()
        search_pattern = self._log_search_var.get().strip()
        status = f"Current log: {self._log_path}"

        if filter_pattern:
            try:
                filter_regex = re.compile(filter_pattern)
            except re.error as exc:
                lines = []
                status = f"Invalid filter regex: {exc}"
            else:
                lines = [line for line in lines if filter_regex.search(line)]

        rendered = "\n".join(lines)
        if rendered:
            rendered += "\n"

        text.configure(state=tk.NORMAL)
        text.delete("1.0", tk.END)
        text.insert("1.0", rendered)
        text.tag_remove("search_match", "1.0", tk.END)

        if search_pattern:
            try:
                search_regex = re.compile(search_pattern)
            except re.error as exc:
                status = f"Invalid search regex: {exc}"
            else:
                self._highlight_log_matches(search_regex)

        text.configure(state=tk.DISABLED)
        self._log_status_var.set(status)
        text.see(tk.END)

    def _highlight_log_matches(self, regex: re.Pattern[str]) -> None:
        text = self._log_text
        if text is None:
            return
        content = text.get("1.0", "end-1c")
        for match in regex.finditer(content):
            if match.start() == match.end():
                continue
            text.tag_add("search_match", f"1.0+{match.start()}c", f"1.0+{match.end()}c")

    def _append_history_view_row(self, record: dict) -> None:
        tree = self._history_tree
        if tree is None:
            return
        item_id = str(len(self._logic_history_rows) - 1)
        interface = record.get("physical_interface", {})
        physical_summary = self._physical_interface_summary(interface)
        tree.insert(
            "",
            tk.END,
            iid=item_id,
            values=(
                record.get("iteration", ""),
                sum(1 for neuron in record.get("neurons", []) if neuron.get("active")),
                f"{float(record.get('CES_pos', 0.0)):.6f}",
                f"{float(record.get('CES_neg', 0.0)):.6f}",
                physical_summary,
            ),
        )
        tree.see(item_id)

    def _refresh_history_view(self) -> None:
        tree = self._history_tree
        if tree is None:
            return
        tree.delete(*tree.get_children())
        for idx, record in enumerate(self._logic_history_rows):
            interface = record.get("physical_interface", {})
            tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(
                    record.get("iteration", ""),
                    sum(1 for neuron in record.get("neurons", []) if neuron.get("active")),
                    f"{float(record.get('CES_pos', 0.0)):.6f}",
                    f"{float(record.get('CES_neg', 0.0)):.6f}",
                    self._physical_interface_summary(interface),
                ),
            )
        if self._logic_history_path is not None:
            self._history_status_var.set(f"Logic history DB: {self._logic_history_path}")

    def _physical_interface_summary(self, interface: dict) -> str:
        parts: list[str] = []
        for group_name in ("inputs", "outputs"):
            group = interface.get(group_name, {})
            if isinstance(group, dict):
                rendered = ", ".join(
                    f"{name}={float(value):.3f}"
                    for name, value in group.items()
                )
                if rendered:
                    parts.append(f"{group_name}: {rendered}")
        return " | ".join(parts)

    def _on_history_row_select(self, _event=None) -> None:
        tree = self._history_tree
        detail = self._history_detail_text
        if tree is None or detail is None:
            return
        selected = tree.selection()
        if not selected:
            return
        try:
            record = list(self._logic_history_rows)[int(selected[0])]
        except (IndexError, ValueError):
            return
        rendered = json.dumps(record, ensure_ascii=False, indent=2)
        detail.configure(state=tk.NORMAL)
        detail.delete("1.0", tk.END)
        detail.insert("1.0", rendered + "\n")
        detail.configure(state=tk.DISABLED)

    def _build_inputs_tab(self, parent: tk.Widget) -> None:
        p = parent
        p.columnconfigure(0, weight=1)
        p.rowconfigure(0, weight=1)

        frame = ttk.LabelFrame(p, text=" Inputs editor ")
        frame.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        frame.columnconfigure(0, weight=1)
        self._inputs_editor_frame = frame
        self._refresh_inputs_editor()

    def _refresh_inputs_editor(self) -> None:
        if self._inputs_editor_frame is None:
            return
        frame = self._inputs_editor_frame
        for child in frame.winfo_children():
            child.destroy()

        if not self._input_specs and not self._output_specs:
            ttk.Label(frame, text="Initialize a brain YAML to edit inputs.", foreground="gray").grid(
                row=0, column=0, sticky="w", padx=8, pady=8
            )
            return

        row = 0
        if self._input_specs:
            ttk.Label(frame, text="Input", font=("Helvetica", 9, "bold")).grid(
                row=row, column=0, sticky="w", padx=8, pady=(8, 2)
            )
            ttk.Label(frame, text="Physical value", font=("Helvetica", 9, "bold")).grid(
                row=row, column=1, sticky="ew", padx=8, pady=(8, 2)
            )
            row += 1
            for spec in self._input_specs:
                name = spec["name"]
                ttk.Label(frame, text=name, width=18, anchor="w").grid(
                    row=row, column=0, sticky="w", padx=8, pady=3
                )
                var = self._input_value_vars.setdefault(name, tk.StringVar(value=str(spec.get("value", 0.0))))
                entry = ttk.Entry(frame, textvariable=var, width=16)
                entry.grid(row=row, column=1, sticky="ew", padx=8, pady=3)
                entry.bind("<Return>", lambda _event, input_name=name: self._apply_input_value(input_name))
                entry.bind("<FocusOut>", lambda _event, input_name=name: self._apply_input_value(input_name))
                row += 1

        if self._output_specs:
            if row:
                ttk.Separator(frame, orient=tk.HORIZONTAL).grid(
                    row=row, column=0, columnspan=2, sticky="ew", padx=8, pady=8
                )
                row += 1
            ttk.Label(frame, text="Output", font=("Helvetica", 9, "bold")).grid(
                row=row, column=0, sticky="w", padx=8, pady=(2, 2)
            )
            ttk.Label(frame, text="Value", font=("Helvetica", 9, "bold")).grid(
                row=row, column=1, sticky="ew", padx=8, pady=(2, 2)
            )
            row += 1
            for spec in self._output_specs:
                name = spec["name"]
                ttk.Label(frame, text=name, width=18, anchor="w").grid(
                    row=row, column=0, sticky="w", padx=8, pady=3
                )
                var = self._output_value_vars.setdefault(name, tk.StringVar(value="-"))
                entry = ttk.Entry(frame, textvariable=var, width=16, state="readonly")
                entry.grid(row=row, column=1, sticky="ew", padx=8, pady=3)
                row += 1

        frame.columnconfigure(1, weight=1)
        self._refresh_output_values()

    def _build_neuron_fields_section(self, parent: tk.Widget, row: int) -> dict:
        """Build the selected neuron's scalar fields panel."""
        parent.rowconfigure(row, weight=1)
        parent.columnconfigure(0, weight=1)
        sel_lf = ttk.LabelFrame(parent, text=" Selected Neuron ")
        sel_lf.grid(row=row, column=0, sticky="nsew", padx=8, pady=(0, 6))
        sel_lf.columnconfigure(0, weight=1)

        header = ttk.Label(
            sel_lf, text="No neuron selected",
            foreground="gray", font=("Helvetica", 9, "bold"), anchor="center",
        )
        header.grid(row=0, column=0, sticky="ew", padx=6, pady=(4, 2))

        fgrid = ttk.Frame(sel_lf)
        fgrid.grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 4))
        fgrid.columnconfigure(1, weight=1)
        vals: dict[str, tk.Widget | tk.Variable] = {}
        for i, (key, name) in enumerate([
            ("index",   "Index"),
            ("name",    "name"),
            ("pos",     "Position"),
            ("inputs",  "Inputs"),
            ("outputs", "Outputs"),
            ("active",  "active"),
            ("drop_next", "drop_charge_next_cycle"),
            ("layers",  "number_of_layers"),
            ("hist_depth", "history_depth"),
            ("charge_max", "charge_max"),
            ("status",  "status[]"),
            ("signal",  "signal[]"),
            ("trigger", "trigger[]"),
            ("eq",      "eq"),
            ("trig_flex", "trigger_flex"),
            ("charge",  "charge"),
            ("charge_min", "charge_min"),
            ("recharge", "recharge"),
            ("recharge_flex", "recharge_flex"),
            ("discharge_random", "discharge_random"),
            ("cumul",   "cumul. signal"),
            ("etd",     "elastic Δ trig."),
            ("erchg",   "elastic recharge"),
            ("cdschg",  "cyclic discharge"),
            ("tired",   "tiredness"),
            ("hist",    "history entries"),
        ]):
            ttk.Label(fgrid, text=name, width=18, anchor="w",
                      font=("Helvetica", 8)).grid(row=i, column=0, padx=4, pady=1, sticky="w")
            lbl = ttk.Label(fgrid, text="—", font=("Courier", 8), anchor="w")
            lbl.grid(row=i, column=1, padx=2, pady=1, sticky="ew")
            vals[key] = lbl

        self._make_neuron_fields_editable(vals)
        return {"header": header, "vals": vals}

    def _make_neuron_fields_editable(self, vals: dict[str, tk.Widget | tk.Variable]) -> None:
        editable_float_fields = {
            "charge_max",
            "eq",
            "trig_flex",
            "charge",
            "charge_min",
            "recharge",
            "recharge_flex",
            "discharge_random",
            "cumul",
            "etd",
            "erchg",
            "cdschg",
            "tired",
        }
        for key in editable_float_fields:
            old = vals[key]
            grid_info = old.grid_info()
            parent = old.master
            old.destroy()
            var = tk.StringVar(value="")
            ent = ttk.Entry(parent, textvariable=var, font=("Courier", 8), width=12)
            ent.grid(**grid_info)
            ent.bind("<Return>", self._apply_selected_neuron_field)
            ent.bind("<FocusOut>", self._apply_selected_neuron_field)
            vals[key] = ent
            vals[f"{key}_var"] = var

        for key in ("active", "drop_next"):
            old = vals[key]
            grid_info = old.grid_info()
            parent = old.master
            old.destroy()
            var = tk.BooleanVar(value=False)
            chk = ttk.Checkbutton(parent, variable=var, command=self._apply_selected_neuron_bool)
            chk.grid(**grid_info)
            vals[key] = chk
            vals[f"{key}_var"] = var

    def _build_neuron_connectome_section(self, parent: tk.Widget, row: int) -> dict:
        """Build the selected neuron's input-link status table."""
        parent.rowconfigure(row, weight=1)
        parent.columnconfigure(0, weight=1)
        sel_lf = ttk.LabelFrame(parent, text=" Input Connectome ")
        sel_lf.grid(row=row, column=0, sticky="nsew", padx=8, pady=(0, 6))
        sel_lf.columnconfigure(0, weight=1)
        sel_lf.rowconfigure(1, weight=1)

        header = ttk.Label(
            sel_lf, text="No neuron selected",
            foreground="gray", font=("Helvetica", 9, "bold"), anchor="center",
        )
        header.grid(row=0, column=0, sticky="ew", padx=6, pady=(4, 2))

        links_lf = ttk.LabelFrame(sel_lf, text=" Input links ")
        links_lf.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 2))
        links_lf.columnconfigure(0, weight=1)
        links_lf.rowconfigure(0, weight=1)

        _cols = ("src", "status", "active", "charge", "threshold", "weight", "signal")
        tree = ttk.Treeview(links_lf, columns=_cols, show="headings", height=6)
        for col, heading, w in [
            ("src",    "#",       34),
            ("status", "Status",  56),
            ("active", "Active",  46),
            ("charge", "Charge",  58),
            ("threshold", "Thresh.", 62),
            ("weight", "Weight",  62),
            ("signal", "Signal",  62),
        ]:
            tree.heading(col, text=heading)
            tree.column(col, width=w, minwidth=w, anchor="e" if col != "active" else "center")
        vsb = ttk.Scrollbar(links_lf, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        tree.bind("<<TreeviewSelect>>", self._on_connectome_row_select)
        tree.bind("<Double-1>", self._on_connectome_row_double_click)

        total_signal = ttk.Label(
            sel_lf, text="Total input signal:  —",
            font=("Courier", 8), anchor="w", foreground="#888888",
        )
        total_signal.grid(row=2, column=0, sticky="ew", padx=6, pady=(2, 4))

        return {"header": header, "tree": tree, "total_signal": total_signal}

    def _slider(
        self,
        parent: tk.Widget,
        key: str,
        label: str,
        from_: float,
        to: float,
        default: float,
        *,
        row: int,
        resolution: float = 1.0,
    ) -> None:
        """One labeled slider row: [label] [──────●──] [value]."""
        is_int = resolution >= 1.0
        var: tk.Variable = tk.IntVar(value=int(default)) if is_int else tk.DoubleVar(value=default)
        self._vars[key] = var

        fmt = (lambda v: str(int(round(v)))) if is_int else (lambda v: f"{round(v / resolution) * resolution:.2f}")

        ttk.Label(parent, text=label, width=22, anchor="w").grid(row=row, column=0, padx=4, pady=3, sticky="w")

        val_lbl = ttk.Label(parent, text=fmt(default), width=7, anchor="e")
        val_lbl.grid(row=row, column=2, padx=4, pady=3)

        def _update(v: str) -> None:
            fv = float(v)
            val_lbl.config(text=fmt(fv))
            if is_int:
                var.set(int(round(fv)))

        ttk.Scale(
            parent, variable=var, from_=from_, to=to, orient=tk.HORIZONTAL, command=_update
        ).grid(row=row, column=1, sticky="ew", padx=4, pady=3)

    # ── Config I/O ────────────────────────────────────────────────────────────

    def _get_config(self) -> dict:
        cfg = {
            "tab": self._notebook.index(self._notebook.select()),
            "visualization": self._get_visualization_config(),
        }
        if self._brain_yaml_path is not None:
            cfg["last_yaml"] = str(self._brain_yaml_path)
        return cfg

    def _get_visualization_config(self) -> dict:
        return {
            "display": {
                "show_seq_lines": bool(self._vars["show_seq_lines"].get()),
                "circle_radius": self._circle_radius,
                "summary_show_active": bool(self._vars["summary_show_active"].get()),
                "summary_show_inputs": bool(self._vars["summary_show_inputs"].get()),
                "summary_show_ces_pos": bool(self._vars["summary_show_ces_pos"].get()),
                "summary_show_ces_neg": bool(self._vars["summary_show_ces_neg"].get()),
                "video_summary_on_map": bool(self._vars["video_summary_on_map"].get()),
            },
            "runtime": {
                key: self._vars[key].get()
                for key in (
                    "tick_ms",
                    "max_iter",
                    "seq_window",
                    "avg_activity_window",
                    "summary_depth",
                    "video_summary_height",
                )
                if key in self._vars
            },
        }

    def _apply_config(self, cfg: dict) -> None:
        if (tab := cfg.get("tab")) is not None:
            try:
                self._notebook.select(int(tab))
            except tk.TclError:
                pass
        last_yaml = cfg.get("last_yaml")
        loaded_yaml = False
        if last_yaml:
            path = Path(last_yaml)
            if path.exists():
                loaded_yaml = self._load_brain_yaml(path, apply_visualization=False, auto_initialize=False)

        visualization = _visualization_config(cfg)
        if visualization:
            self._apply_visualization_config(visualization)
        else:
            # Legacy app config shape used params for visualization controls.
            self._apply_legacy_params_config(cfg.get("params", {}))

        if loaded_yaml:
            self._initialize_loaded_config("app config")

    def _load_config(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            cfg = _parse_yaml_text(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return
        self._log(f"Loaded app config {path}")
        # Defer until layout is fully realized so sashpos() takes effect
        self.after(200, lambda: self._apply_config(cfg))

    def _save_config(self, path: Path) -> None:
        try:
            path.write_text(_dump_yaml(self._get_config()), encoding="utf-8")
        except OSError:
            pass
        else:
            self._log(f"Saved app config {path}")

    def _set_brain_yaml_text(self, text: str) -> None:
        self._brain_yaml_editor.delete("1.0", tk.END)
        self._brain_yaml_editor.insert("1.0", text)
        self._brain_yaml_editor.edit_modified(False)

    def _brain_yaml_text(self) -> str:
        return self._brain_yaml_editor.get("1.0", "end-1c")

    def _read_brain_yaml(self) -> dict:
        return self._validate_brain_yaml_text(self._brain_yaml_text())

    def _default_combined_config(self) -> dict:
        cfg = _parse_yaml_text(_dump_yaml(DEFAULT_BRAIN_CONFIG))
        cfg[WORLD_CONFIG_SECTION] = _parse_yaml_text(self._selected_world_module().GetDefaultConfig())
        return cfg

    def _combined_world_config(self, cfg: dict) -> dict:
        if WORLD_CONFIG_SECTION in cfg:
            section = cfg[WORLD_CONFIG_SECTION]
            if not isinstance(section, dict):
                raise ValueError(f"{WORLD_CONFIG_SECTION} must be a mapping.")
            return section
        # Backward compatibility for a standalone world YAML pasted into the editor.
        if all(section in cfg for section in ("world", "objects", "inputs", "outputs")):
            return cfg
        raise ValueError(f"Missing required top-level section: {WORLD_CONFIG_SECTION}")

    def _validate_brain_text(self, text: str) -> tuple[bool, list[str]]:
        try:
            self._validate_brain_yaml_text(text)
        except (TypeError, ValueError) as exc:
            return False, [str(exc)]
        return True, []

    def _validate_world_text(self, text: str) -> tuple[bool, list[str]]:
        try:
            self._validate_world_yaml_text(text)
        except (TypeError, ValueError) as exc:
            return False, [str(exc)]
        return True, []

    def _validate_body_config(
        self,
        cfg: dict,
        *,
        world_outputs: set[str] | None = None,
    ) -> tuple[bool, list[str]]:
        brain_inputs, _ = self._brain_interface_names(cfg)
        ok, problems = Body.Validate(
            cfg.get(BODY_CONFIG_SECTION),
            brain_inputs=brain_inputs,
            world_outputs=world_outputs,
        )
        if not ok:
            raise ValueError("; ".join(problems))
        return ok, problems

    def _load_default_brain_yaml(self) -> None:
        self._brain_yaml_path = None
        self._set_brain_yaml_text(_dump_yaml(self._default_combined_config()))
        self._yaml_path_label.config(text="Unsaved YAML", foreground="gray")
        self._status_label.config(text="Default YAML loaded", foreground="gray")
        self._log("Loaded default brain YAML")
        self._validate_model_compatibility()
        self._initialize_loaded_config("default YAML")

    def _validate_brain_yaml_text(self, text: str) -> dict:
        data = _parse_yaml_text(text)
        if not isinstance(data, dict):
            raise ValueError("YAML root must be a mapping.")
        brain_cfg, _ = _split_visualization_sections(data)
        self._validate_brain_config(brain_cfg)
        return brain_cfg

    def _validate_brain_config(self, cfg: dict) -> None:
        _runtime_safe_id(_brain_id_from_config(cfg))
        self._require_mapping_section(cfg, "brain")
        self._require_section(cfg, "assembly")
        self._require_section(cfg, "inputs")
        self._require_section(cfg, "outputs")
        self._require_mapping_section(cfg, BODY_CONFIG_SECTION)
        brain_cfg = cfg["brain"]
        target_n = self._yaml_int(brain_cfg, "neurons", minimum=1)
        self._yaml_int(brain_cfg, "head_size", default=0, minimum=0)
        self._yaml_int(brain_cfg, "connections_per_neuron", aliases=("connections",), default=10, minimum=0)
        self._yaml_float(brain_cfg, "max_synapse_length", aliases=("max_synapse",), default=0.30, minimum=0.0)
        self._yaml_float(brain_cfg, "weight_min", default=0.0)
        self._yaml_float(brain_cfg, "weight_max", default=1.0)
        self._yaml_float(brain_cfg, "total_input", default=1000.0)
        self._yaml_int(brain_cfg, "NUMBER_OF_LAYERS", aliases=("number_of_layers",), default=1, minimum=1)
        self._yaml_int(brain_cfg, "HISTORY_DEPTH", aliases=("history_depth",), default=32, minimum=1)
        charge_max = self._yaml_float(brain_cfg, "CHARGE_MAX", aliases=("charge_max",), default=100.0, minimum=0.0)
        self._brain_initialization_config(brain_cfg, charge_max)
        positions = self._assembly_positions(cfg, target_n)
        self._validate_input_specs(cfg, len(positions))
        self._initialize_outputs(cfg, len(positions))
        self._validate_body_config(cfg)

    def _require_section(self, cfg: dict, name: str):
        if name not in cfg:
            raise ValueError(f"Missing required top-level section: {name}")
        return cfg[name]

    def _require_mapping_section(self, cfg: dict, name: str) -> dict:
        section = self._require_section(cfg, name)
        if not isinstance(section, dict):
            raise ValueError(f"{name} must be a mapping.")
        return section

    def _brain_initialization_config(self, brain_cfg: dict, charge_max: float) -> dict[str, float]:
        raw = brain_cfg.get("Initialization", brain_cfg.get("initialization", {}))
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ValueError("brain.Initialization must be a mapping.")
        default_recharge_ratio = self._yaml_float(
            raw, "default_recharge", default=0.2, minimum=0.0
        )
        if default_recharge_ratio > 1.0:
            raise ValueError("brain.Initialization.default_recharge must be <= 1.0")
        default_eq_min = self._yaml_float(raw, "default_eq_min", default=-0.1)
        default_eq_max = self._yaml_float(raw, "default_eq_max", default=0.1)
        return {
            "default_charge": self._brain_initial_charge(raw.get("default_charge", "charge_max"), charge_max),
            "default_recharge": default_recharge_ratio * charge_max,
            "default_eq_min": min(default_eq_min, default_eq_max),
            "default_eq_max": max(default_eq_min, default_eq_max),
        }

    def _brain_initial_charge(self, value, charge_max: float) -> float:
        if isinstance(value, str) and value.strip().lower() == "charge_max":
            return charge_max
        charge = float(value)
        if charge < 0.0:
            raise ValueError("brain.Initialization.default_charge must be >= 0.")
        if charge > charge_max:
            raise ValueError("brain.Initialization.default_charge must be <= CHARGE_MAX.")
        return charge

    def _validate_input_specs(self, cfg: dict, neuron_count: int) -> None:
        raw_specs = self._require_section(cfg, "inputs")
        if isinstance(raw_specs, dict):
            raw_specs = [{name: spec} for name, spec in raw_specs.items()]
        if not isinstance(raw_specs, list):
            raise ValueError("inputs must be a list or mapping.")
        for raw_spec in raw_specs:
            name, spec = self._normalize_input_spec(raw_spec)
            center = self._yaml_int(spec, "center", minimum=0)
            self._yaml_int(spec, "radius", minimum=0)
            self._yaml_int(spec, "number", minimum=0)
            self._yaml_float(spec, "eq_min", default=0.0)
            self._yaml_float(spec, "eq_max", default=0.0)
            self._yaml_float(spec, "value", aliases=("physical_value",), default=0.0)
            if center >= neuron_count:
                raise ValueError(f"inputs.{name}.center must be < neuron count")

    def _brain_interface_names(self, cfg: dict) -> tuple[set[str], set[str]]:
        inputs = self._interface_names(cfg.get("inputs", []), self._normalize_input_spec)
        outputs = self._interface_names(cfg.get("outputs", []), self._normalize_output_spec)
        return inputs, outputs

    def _interface_names(self, raw_specs, normalizer) -> set[str]:
        if raw_specs is None:
            return set()
        if isinstance(raw_specs, dict):
            raw_specs = [{name: spec} for name, spec in raw_specs.items()]
        if not isinstance(raw_specs, list):
            raise ValueError("interface specs must be a list or mapping.")
        names: set[str] = set()
        for raw_spec in raw_specs:
            name, _ = normalizer(raw_spec)
            names.add(name)
        return names

    def _validate_world_yaml_text(self, text: str) -> dict:
        data = _parse_yaml_text(text)
        if not isinstance(data, dict):
            raise ValueError("YAML root must be a mapping.")
        data = self._combined_world_config(data)
        for section in ("world", "objects", "inputs", "outputs"):
            if section not in data:
                raise ValueError(f"Missing required top-level section: {section}")
        module = self._world_module_for_config(data)
        validator = getattr(module, "Validate", None)
        if callable(validator):
            ok, problems = validator(_dump_yaml(data))
            if not ok:
                raise ValueError("; ".join(problems) if problems else "World validation failed.")
        else:
            parser = getattr(module, "_parse_config", None)
            if callable(parser):
                parser(_dump_yaml(data))
        return data

    def _world_interface_names(self, cfg: dict) -> tuple[set[str], set[str]]:
        inputs = {str(item.get("name", "")).strip() for item in cfg.get("inputs", []) if isinstance(item, dict)}
        raw_outputs = cfg.get("outputs", [])
        if isinstance(raw_outputs, dict):
            outputs = {str(name).strip() for name in raw_outputs}
        else:
            outputs = {str(item.get("name", "")).strip() for item in raw_outputs if isinstance(item, dict)}
        return {name for name in inputs if name}, {name for name in outputs if name}

    def _on_yaml_editor_modified(self, event: tk.Event) -> None:
        widget = event.widget
        if not widget.edit_modified():
            return
        widget.edit_modified(False)
        self._validate_model_compatibility()

    def _validate_model_compatibility(self) -> bool:
        if not hasattr(self, "_compat_status_label"):
            return False
        try:
            brain_cfg = self._validate_brain_yaml_text(self._brain_yaml_text())
        except ValueError as exc:
            self._compat_status_label.config(text=f"Brain YAML: {exc}", foreground="red")
            return False
        try:
            world_cfg = self._validate_world_yaml_text(self._world_yaml_text())
        except ValueError as exc:
            self._compat_status_label.config(text=f"World YAML: {exc}", foreground="red")
            return False

        brain_inputs, brain_outputs = self._brain_interface_names(brain_cfg)
        world_inputs, world_outputs = self._world_interface_names(world_cfg)
        try:
            self._validate_body_config(brain_cfg, world_outputs=world_outputs)
        except ValueError as exc:
            self._compat_status_label.config(text=f"Incompatible: {exc}", foreground="red")
            return False
        missing_brain_outputs = sorted(world_inputs - brain_outputs)
        if missing_brain_outputs:
            parts = []
            if missing_brain_outputs:
                parts.append(f"brain outputs missing: {', '.join(missing_brain_outputs)}")
            self._compat_status_label.config(text="Incompatible: " + "; ".join(parts), foreground="red")
            return False
        self._compat_status_label.config(text="Compatible", foreground="green")
        return True

    def _on_validate_config(self) -> bool:
        brain_ok, brain_problems = self._validate_brain_text(self._brain_yaml_text())
        world_ok, world_problems = self._validate_world_text(self._brain_yaml_text())
        compatible = self._validate_model_compatibility() if brain_ok and world_ok else False
        problems = [f"Brain: {problem}" for problem in brain_problems]
        problems.extend(f"World: {problem}" for problem in world_problems)
        if not problems and not compatible:
            problems.append(self._compat_status_label.cget("text") or "Config is incompatible.")
        if problems:
            self._status_label.config(text="Invalid config", foreground="red")
            self._world_status_label.config(text="Invalid config", foreground="red")
            self._compat_status_label.config(text="; ".join(problems), foreground="red")
            messagebox.showerror("Validate config", "\n".join(problems))
            self._log("Config validation failed: " + "; ".join(problems))
            return False
        self._status_label.config(text="Config valid", foreground="green")
        self._world_status_label.config(text="Config valid", foreground="green")
        self._compat_status_label.config(text="Valid and compatible", foreground="green")
        self._log("Config validation passed")
        return True

    def _load_brain_yaml_dialog(self) -> None:
        p = filedialog.askopenfilename(
            filetypes=[("YAML", "*.yaml *.yml"), ("All", "*.*")],
            defaultextension=".yaml",
        )
        if p:
            self._load_brain_yaml(Path(p))

    def _load_brain_yaml(
        self,
        path: Path,
        *,
        apply_visualization: bool = True,
        auto_initialize: bool = True,
    ) -> bool:
        try:
            text = path.read_text(encoding="utf-8")
            data = _parse_yaml_text(text)
            if isinstance(data, dict) and WORLD_CONFIG_SECTION not in data:
                data[WORLD_CONFIG_SECTION] = _parse_yaml_text(self._selected_world_module().GetDefaultConfig())
                text = _dump_yaml(data)
            self._validate_brain_yaml_text(text)
            self._validate_world_yaml_text(text)
            _, visualization = _split_visualization_sections(_parse_yaml_text(text))
        except (OSError, ValueError) as exc:
            messagebox.showerror("Load YAML", f"Could not load YAML:\n{exc}")
            self._log(f"Brain YAML load failed ({path}): {exc}")
            return False
        self._brain_yaml_path = path
        self._set_brain_yaml_text(
            _strip_top_level_sections(text, ("visualization", "display", "runtime"))
            if visualization
            else text
        )
        self._yaml_path_label.config(text=str(path), foreground="gray")
        if apply_visualization and visualization:
            self._apply_visualization_config(visualization)
        self._save_config(CONFIG_PATH)
        self._log(f"Loaded brain YAML {path}")
        self._validate_model_compatibility()
        if auto_initialize:
            self._initialize_loaded_config(str(path))
        return True

    def _save_brain_yaml(self) -> None:
        if self._brain_yaml_path is None:
            self._save_brain_yaml_dialog()
            return
        self._write_brain_yaml(self._brain_yaml_path)

    def _save_brain_yaml_dialog(self) -> None:
        p = filedialog.asksaveasfilename(
            filetypes=[("YAML", "*.yaml *.yml"), ("All", "*.*")],
            defaultextension=".yaml",
            initialfile="brain.yaml",
        )
        if p:
            self._write_brain_yaml(Path(p))

    def _write_brain_yaml(self, path: Path) -> None:
        try:
            text = self._brain_yaml_text()
            self._validate_brain_yaml_text(text)
            self._validate_world_yaml_text(text)
            data = _parse_yaml_text(text)
            _, visualization = _split_visualization_sections(data)
            text_to_write = (
                _strip_top_level_sections(text, ("visualization", "display", "runtime"))
                if visualization
                else text
            )
            path.write_text(text_to_write, encoding="utf-8")
            self._set_brain_yaml_text(text_to_write)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Save YAML", f"Could not save YAML:\n{exc}")
            self._log(f"Brain YAML save failed ({path}): {exc}")
            return
        self._brain_yaml_path = path
        self._yaml_path_label.config(text=str(path), foreground="gray")
        self._save_config(CONFIG_PATH)
        self._log(f"Saved brain YAML {path}")
        self._validate_model_compatibility()

    def _set_world_yaml_text(self, text: str) -> None:
        data = _parse_yaml_text(self._brain_yaml_text())
        if not isinstance(data, dict):
            data = _parse_yaml_text(_dump_yaml(DEFAULT_BRAIN_CONFIG))
        world_data = _parse_yaml_text(text)
        if not isinstance(world_data, dict):
            raise ValueError("World YAML root must be a mapping.")
        data[WORLD_CONFIG_SECTION] = world_data
        self._set_brain_yaml_text(_dump_yaml(data))

    def _world_yaml_text(self) -> str:
        data = _parse_yaml_text(self._brain_yaml_text())
        if not isinstance(data, dict):
            raise ValueError("YAML root must be a mapping.")
        return _dump_yaml(self._combined_world_config(data))

    def _load_default_world_yaml(self) -> None:
        module = self._selected_world_module()
        self._select_world_module(module)
        self._world_initialized = False
        self._world_first_process_pending = False
        self._set_world_yaml_text(module.GetDefaultConfig())
        self._world_status_label.config(text=f"Default YAML loaded ({module.__name__})", foreground="gray")
        self._log(f"Loaded default world YAML ({module.__name__})")
        self._validate_model_compatibility()
        self._initialize_loaded_config(f"default world YAML ({module.__name__})")
        self._draw_world()

    def _load_world_yaml_dialog(self) -> None:
        p = filedialog.askopenfilename(
            filetypes=[("YAML", "*.yaml *.yml"), ("All", "*.*")],
            defaultextension=".yaml",
        )
        if p:
            self._load_world_yaml(Path(p))

    def _load_world_yaml(self, path: Path) -> None:
        try:
            text = path.read_text(encoding="utf-8")
            data = self._validate_world_yaml_text(text)
            module = self._world_module_for_config(data)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Load world YAML", f"Could not load YAML:\n{exc}")
            self._log(f"World YAML load failed ({path}): {exc}")
            return
        self._select_world_module(module)
        self._world_yaml_path = path
        self._set_world_yaml_text(text)
        self._world_yaml_path_label.config(text=str(path), foreground="gray")
        self._save_config(CONFIG_PATH)
        self._log(f"Loaded world YAML {path}")
        self._validate_model_compatibility()
        self._initialize_loaded_config(str(path))

    def _save_world_yaml(self) -> None:
        if self._world_yaml_path is None:
            self._save_world_yaml_dialog()
            return
        self._write_world_yaml(self._world_yaml_path)

    def _save_world_yaml_dialog(self) -> None:
        p = filedialog.asksaveasfilename(
            filetypes=[("YAML", "*.yaml *.yml"), ("All", "*.*")],
            defaultextension=".yaml",
            initialfile="world.yaml",
        )
        if p:
            self._write_world_yaml(Path(p))

    def _write_world_yaml(self, path: Path) -> None:
        try:
            text = self._world_yaml_text()
            self._validate_world_yaml_text(text)
            path.write_text(text, encoding="utf-8")
        except (OSError, ValueError) as exc:
            messagebox.showerror("Save world YAML", f"Could not save YAML:\n{exc}")
            self._log(f"World YAML save failed ({path}): {exc}")
            return
        self._world_yaml_path = path
        self._world_yaml_path_label.config(text=str(path), foreground="gray")
        self._save_config(CONFIG_PATH)
        self._log(f"Saved world YAML {path}")
        self._validate_model_compatibility()

    def _apply_visualization_config(self, visualization: dict) -> None:
        display = visualization.get("display", {})
        runtime = visualization.get("runtime", {})
        if isinstance(display, dict) and "show_seq_lines" in display:
            self._vars["show_seq_lines"].set(bool(display["show_seq_lines"]))
        if isinstance(display, dict) and "circle_radius" in display:
            try:
                self._circle_radius = max(0.5, float(display["circle_radius"]))
            except (TypeError, ValueError):
                pass
        if isinstance(display, dict):
            for key in (
                "summary_show_active",
                "summary_show_inputs",
                "summary_show_ces_pos",
                "summary_show_ces_neg",
                "video_summary_on_map",
            ):
                if key in display and key in self._vars:
                    self._vars[key].set(bool(display[key]))
        if isinstance(runtime, dict):
            for key in (
                "tick_ms",
                "max_iter",
                "seq_window",
                "avg_activity_window",
                "summary_depth",
                "video_summary_height",
            ):
                if key in runtime and key in self._vars:
                    self._vars[key].set(runtime[key])

    def _apply_legacy_params_config(self, params: dict) -> None:
        if not isinstance(params, dict):
            return
        for key, value in params.items():
            if key == "circle_radius":
                try:
                    self._circle_radius = max(0.5, float(value))
                except (TypeError, ValueError):
                    pass
            elif key in self._vars:
                try:
                    self._vars[key].set(value)
                except (tk.TclError, ValueError):
                    pass

    # ── Canvas placeholder renderers ──────────────────────────────────────────

    def _on_brain_resize(self, event: tk.Event) -> None:
        self._draw_brain()

    def _on_world_resize(self, event: tk.Event) -> None:
        self._draw_world()

    def _draw_world(self) -> None:
        c = self._world_canvas
        width = c.winfo_width()
        height = c.winfo_height()
        c.delete("all")
        if width <= 1 or height <= 1:
            return
        if not self._world_initialized:
            c.create_text(width // 2, height // 2,
                          text="World visualization", fill="#3d4451", font=("Helvetica", 14))
            return
        try:
            image = self._world_module.GetVisualization((width, height))
            params = self._world_module.GetParams()
        except (RuntimeError, ValueError) as exc:
            self._world_initialized = False
            c.create_text(width // 2, height // 2, text=str(exc), fill="#ef4444", font=("Helvetica", 11))
            return
        photo = tk.PhotoImage(width=image.width, height=image.height)
        rows = []
        for row in image.pixels:
            rows.append("{" + " ".join(f"#{r:02x}{g:02x}{b:02x}" for r, g, b in row) + "}")
        photo.put(" ".join(rows))
        self._world_photo = photo
        c.create_image(0, 0, image=photo, anchor="nw")
        c.create_text(
            12,
            10,
            text=f"x={float(params['x']):.3f}   velocity={float(params['velocity']):.3f}",
            fill="#d1d5db",
            font=("Courier", 10),
            anchor="nw",
        )

    # ── Brain rendering ───────────────────────────────────────────────────────

    def _draw_brain(self) -> None:
        c = self._brain_canvas
        W, H = c.winfo_width(), c.winfo_height()
        if W <= 1 or H <= 1:
            return
        c.delete("all")
        if self._brain is None:
            c.create_text(W // 2, H // 2, text="Brain visualization", fill="#3d4451", font=("Helvetica", 14))
            self._draw_brain_status_overlay(W, H)
            self._draw_brain_average()
            return

        # View transform: brain [0,1]² → canvas pixels
        strip_h = self._brain_map_summary_strip_height(H)
        map_h = max(2, H - strip_h)
        CW = W - 2 * _MARGIN
        CH = max(1.0, map_h - 2 * _MARGIN)
        vx, vy, vs = self._view_x, self._view_y, self._view_scale
        half_w, half_h = W / 2, map_h / 2

        def tc(px: float, py: float) -> tuple[float, float]:
            return half_w + (px - vx) * CW * vs, half_h + (py - vy) * CH * vs

        var = self._vars.get("show_seq_lines")
        if var and var.get():
            for i in range(len(self._positions) - 1):
                x0, y0 = tc(*self._positions[i])
                x1, y1 = tc(*self._positions[i + 1])
                c.create_line(x0, y0, x1, y1, fill="#2a2a2a", width=1)

        # Input / output links for the selected neuron (drawn behind neurons)
        sel = self._cas_neuron_idx
        neurons = self._brain.substrate.brain

        def source_link_color(source_idx: int) -> str:
            if source_idx < 0 or source_idx >= len(neurons):
                return "#4b5563"
            source = neurons[source_idx]
            if not source.active:
                return "#4b5563"
            if source.eq > 0.0:
                return "#22cc55"
            if source.eq < 0.0:
                return "#cc2222"
            return "#9ca3af"

        if sel is not None and sel < len(self._positions):
            in_links  = self._adj_in.get(sel, [])
            out_links = self._adj_out.get(sel, [])
            all_w = [abs(w) for _, w in in_links] + [abs(w) for _, w in out_links]
            max_w = max(all_w) if all_w else 1.0
            sx, sy = tc(*self._positions[sel])
            for src, w in in_links:
                ox, oy = tc(*self._positions[src])
                c.create_line(ox, oy, sx, sy, arrow=tk.LAST, arrowshape=(8, 10, 4),
                              fill=source_link_color(src), width=max(1.0, abs(w) / max_w * 5))
            for dst, w in out_links:
                dx, dy = tc(*self._positions[dst])
                c.create_line(sx, sy, dx, dy, arrow=tk.LAST, arrowshape=(8, 10, 4),
                              fill=source_link_color(sel), width=max(1.0, abs(w) / max_w * 5))

        # O(1) window-position lookup; brightness 10 % (oldest) → 100 % (newest)
        win_pos = {idx: wpos for wpos, idx in enumerate(self._seq_window)}
        M = len(self._seq_window)

        for i, ((px, py), neuron) in enumerate(zip(self._positions, neurons)):
            cx, cy = tc(px, py)
            # off-screen culling
            if cx < -50 or cx > W + 50 or cy < -50 or cy > map_h + 50:
                continue

            wpos = win_pos.get(i)
            if wpos is not None:
                bright = (10.0 + wpos * 90.0 / (M - 1)) / 100.0 if M > 1 else 1.0
                base = (0x22, 0xcc, 0x55) if neuron.eq >= 0.0 else (0xcc, 0x22, 0x22)
                win_color = f"#{int(base[0]*bright):02x}{int(base[1]*bright):02x}{int(base[2]*bright):02x}"
            else:
                win_color = None

            r = self._circle_radius
            if i < self._head_size:
                if i in self._input_indices:
                    color = "#74c7ff" if neuron.active else "#0b2447"
                elif win_color:
                    color = win_color
                elif neuron.active:
                    color = "#22cc55" if neuron.eq >= 0.0 else "#cc2222"
                else:
                    color = "#3a3a3a"
                fill = color if neuron.active else ""
                c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fill, outline=color, width=1)
            else:
                if i in self._input_indices:
                    color = "#74c7ff" if neuron.active else "#0b2447"
                elif win_color:
                    color = win_color
                elif neuron.active:
                    color = "#22cc55" if neuron.eq >= 0.0 else "#cc2222"
                else:
                    color = "#3a3a3a"
                fill = color if neuron.active else ""
                c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fill, outline=color, width=1)

        # Highlight rings drawn on top of neurons
        hi = self._highlight_neuron_idx
        if hi is not None and hi < len(self._positions):
            hx, hy = tc(*self._positions[hi])
            if -60 < hx < W + 60 and -60 < hy < map_h + 60:
                hr = min(max(self._circle_radius + 5, 8), 42.0)
                c.create_oval(hx - hr, hy - hr, hx + hr, hy + hr,
                              fill="", outline="#f59e0b", width=3)
        if sel is not None and sel < len(self._positions):
            sx, sy = tc(*self._positions[sel])
            if -60 < sx < W + 60 and -60 < sy < map_h + 60:
                hr = min(max(self._circle_radius + 3, 6), 40.0)
                c.create_oval(sx - hr, sy - hr, sx + hr, sy + hr,
                              fill="", outline="#ffffff", width=2)
        self._draw_brain_status_overlay(W, map_h)
        self._draw_activity_summary_on_brain_map(c, W, H)
        self._draw_brain_average()

    def _draw_brain_average(self, event=None) -> None:
        if not hasattr(self, "_brain_average_canvas"):
            return
        c = self._brain_average_canvas
        W, H = c.winfo_width(), c.winfo_height()
        if W <= 1 or H <= 1:
            return
        c.delete("all")
        if self._brain is None:
            c.create_text(W // 2, H // 2, text="Brain average activity", fill="#3d4451", font=("Helvetica", 14))
            return

        try:
            window = max(1, int(self._vars["avg_activity_window"].get()))
        except (tk.TclError, ValueError):
            window = 100
            self._vars["avg_activity_window"].set(window)

        CW = W - 2 * _MARGIN
        CH = H - 2 * _MARGIN
        vx, vy, vs = self._view_x, self._view_y, self._view_scale
        half_w, half_h = W / 2, H / 2

        def tc(px: float, py: float) -> tuple[float, float]:
            return half_w + (px - vx) * CW * vs, half_h + (py - vy) * CH * vs

        neurons = self._brain.substrate.brain
        for (px, py), neuron in zip(self._positions, neurons):
            cx, cy = tc(px, py)
            if cx < -50 or cx > W + 50 or cy < -50 or cy > H + 50:
                continue
            history = neuron.history[-window:]
            average = (
                sum(1 for entry in history if bool(entry.get("active", False))) / len(history)
                if history
                else 0.0
            )
            if average <= 0.0:
                color = "#2a2a2a"
            elif neuron.eq > 0.0:
                brightness = int(32 + average * 223)
                color = f"#00{brightness:02x}40"
            elif neuron.eq < 0.0:
                brightness = int(32 + average * 223)
                color = f"#{brightness:02x}2020"
            else:
                brightness = int(32 + average * 223)
                color = f"#{brightness:02x}{brightness:02x}{brightness:02x}"
            r = self._circle_radius
            c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=color, outline=color, width=1)

        c.create_text(
            12,
            10,
            text=f"Average activity over last {window} iterations",
            fill="#9fb8c8",
            font=("Courier", 10, "bold"),
            anchor="nw",
        )

    def _draw_brain_status_overlay(self, width: int, height: int) -> None:
        active = 0
        total = 0
        if self._brain is not None:
            neurons = self._brain.substrate.brain
            total = len(neurons)
            active = sum(1 for neuron in neurons if neuron.active)

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        brain_id = self._brain_yaml_path.stem if self._brain_yaml_path is not None else "unsaved"
        c = self._brain_canvas
        color = "#9fb8c8"
        font = ("Courier", 10, "bold")
        c.create_text(12, 10, text=f"Brain ID: {brain_id}", fill=color, font=font, anchor="nw")
        c.create_text(
            12,
            height - 12,
            text=f"ITER {self._iteration}",
            fill=color,
            font=font,
            anchor="sw",
        )
        c.create_text(
            width - 12,
            10,
            text=f"ACTIVE {active}/{total}",
            fill=color,
            font=font,
            anchor="ne",
        )
        c.create_text(width - 12, height - 12, text=now, fill=color, font=font, anchor="se")

    def _canvas_to_brain(self, canvas_x: float, canvas_y: float) -> tuple[float, float]:
        c = self._brain_canvas
        W, H = c.winfo_width(), c.winfo_height()
        CW = max(W - 2 * _MARGIN, 1)
        CH = max(H - 2 * _MARGIN, 1)
        return (
            self._view_x + (canvas_x - W / 2) / (CW * self._view_scale),
            self._view_y + (canvas_y - H / 2) / (CH * self._view_scale),
        )

    def _on_brain_scroll(self, event: tk.Event) -> None:
        factor = 1.12 if event.delta > 0 else 1 / 1.12
        bx, by = self._canvas_to_brain(event.x, event.y)
        self._view_scale = max(0.05, min(100.0, self._view_scale * factor))
        # keep the point under the cursor stationary
        bx2, by2 = self._canvas_to_brain(event.x, event.y)
        self._view_x += bx - bx2
        self._view_y += by - by2
        self._draw_brain()

    def _on_brain_drag_start(self, event: tk.Event) -> None:
        self._drag_start = (event.x, event.y)
        self._drag_moved = False

    def _on_brain_drag(self, event: tk.Event) -> None:
        if self._drag_start is None:
            return
        dx, dy = event.x - self._drag_start[0], event.y - self._drag_start[1]
        if abs(dx) > 3 or abs(dy) > 3:
            self._drag_moved = True
        c = self._brain_canvas
        W, H = c.winfo_width(), c.winfo_height()
        CW = max(W - 2 * _MARGIN, 1)
        CH = max(H - 2 * _MARGIN, 1)
        self._view_x -= dx / (CW * self._view_scale)
        self._view_y -= dy / (CH * self._view_scale)
        self._drag_start = (event.x, event.y)
        self._draw_brain()

    def _on_brain_drag_end(self, event: tk.Event) -> None:
        if not self._drag_moved:
            self._on_brain_click(event)
        self._drag_start = None
        self._drag_moved = False

    def _on_brain_click(self, event: tk.Event) -> None:
        """Single click — select neuron and show its info without changing state."""
        if not self._brain:
            return
        idx = self._nearest_neuron_at(event.x, event.y)
        if idx is None:
            self._clear_neuron_selection()
            return
        if self._cas_neuron_idx != idx:
            self._highlight_neuron_idx = None
            self._cas_charge.clear()
            self._cas_active.clear()
            self._cas_signal.clear()
            self._cas_neuron_idx = idx
            self._draw_brain()  # update link overlay for newly selected neuron
        self._draw_cas()
        self._update_neuron_panel(idx)
        neu = self._brain.substrate.brain[idx]
        ic, oc = self._neuron_counts(idx)
        self._neuron_info_label.config(text=(
            f"#{idx}   in={ic}  out={oc}   "
            f"active={neu.active}   eq={neu.eq:.3f}   charge={neu.charge:.3f}   "
            f"tiredness={neu.tiredness:.3f}   cumulative={neu.cumulative_signal:.3f}"
        ))

    def _on_brain_right_click(self, event: tk.Event) -> None:
        """Right-click — toggle clicked neuron's active state; selection unchanged."""
        if not self._brain:
            return
        idx = self._nearest_neuron_at(event.x, event.y)
        if idx is None:
            return
        neu = self._brain.substrate.brain[idx]
        self._set_neuron_runtime_active(idx, not neu.active)
        self._save_runtime_state()
        self._draw_brain()
        self._refresh_output_values()
        # If the toggled neuron is the currently selected one, refresh panel and status bar
        if self._cas_neuron_idx == idx:
            self._draw_cas()
            self._update_neuron_panel(idx)
            ic, oc = self._neuron_counts(idx)
            self._neuron_info_label.config(text=(
                f"#{idx}   in={ic}  out={oc}   "
                f"active={neu.active}   eq={neu.eq:.3f}   charge={neu.charge:.3f}   "
                f"tiredness={neu.tiredness:.3f}   cumulative={neu.cumulative_signal:.3f}"
            ))

    # ── Head sequence controls ────────────────────────────────────────────────

    def _neuron_counts(self, idx: int) -> tuple[int, int]:
        ic = self._in_counts[idx] if idx < len(self._in_counts) else 0
        oc = self._out_counts[idx] if idx < len(self._out_counts) else 0
        return ic, oc

    def _nearest_neuron_at(self, canvas_x: float, canvas_y: float) -> int | None:
        if not self._positions:
            return None
        c = self._brain_canvas
        W, H = c.winfo_width(), c.winfo_height()
        CW = W - 2 * _MARGIN
        CH = H - 2 * _MARGIN
        half_w, half_h = W / 2, H / 2
        vx, vy, vs = self._view_x, self._view_y, self._view_scale

        def canvas_pos(pos: tuple[float, float]) -> tuple[float, float]:
            px, py = pos
            return half_w + (px - vx) * CW * vs, half_h + (py - vy) * CH * vs

        idx, dist_sq = min(
            (
                (i, (cx - canvas_x) ** 2 + (cy - canvas_y) ** 2)
                for i, pos in enumerate(self._positions)
                for cx, cy in (canvas_pos(pos),)
            ),
            key=lambda item: item[1],
        )
        hit_radius = max(self._circle_radius + 4.0, 8.0)
        return idx if dist_sq <= hit_radius * hit_radius else None

    def _clear_neuron_selection(self) -> None:
        if self._cas_neuron_idx is None:
            return
        self._cas_neuron_idx = None
        self._highlight_neuron_idx = None
        self._cas_charge.clear()
        self._cas_active.clear()
        self._cas_signal.clear()
        self._neuron_info_label.config(text="")
        self._clear_neuron_panel()
        self._draw_brain()
        self._draw_cas()

    def _clear_neuron_panel(self) -> None:
        fields_panel = self._neuron_fields_panel
        fields_panel["header"].config(text="No neuron selected", foreground="gray")
        v = fields_panel["vals"]
        for key in (
            "index", "name", "pos", "inputs", "outputs", "layers", "hist_depth",
            "status", "signal", "trigger", "hist",
        ):
            self._set_neuron_label(v, key, "-")
        self._set_neuron_bool(v, "active", False)
        self._set_neuron_bool(v, "drop_next", False)
        for key in (
            "charge_max", "eq", "trig_flex", "charge", "charge_min", "recharge",
            "recharge_flex", "discharge_random", "cumul", "etd", "erchg",
            "cdschg", "tired",
        ):
            v[f"{key}_var"].set("")

        connectome_panel = self._neuron_connectome_panel
        connectome_panel["header"].config(text="No neuron selected", foreground="gray")
        tree = connectome_panel["tree"]
        tree.delete(*tree.get_children())
        connectome_panel["total_signal"].config(text="Total input signal:  -")

    def _set_neuron_info(self, idx: int) -> None:
        if not self._brain or idx >= len(self._brain.substrate.brain):
            return
        neu = self._brain.substrate.brain[idx]
        ic, oc = self._neuron_counts(idx)
        self._neuron_info_label.config(text=(
            f"#{idx}   in={ic}  out={oc}   "
            f"active={neu.active}   eq={neu.eq:.3f}   charge={neu.charge:.3f}   "
            f"tiredness={neu.tiredness:.3f}   cumulative={neu.cumulative_signal:.3f}"
        ))

    def _on_connectome_row_select(self, event: tk.Event) -> None:
        tree = event.widget
        selected = tree.selection()
        if not selected:
            self._highlight_neuron_idx = None
            self._draw_brain()
            return
        values = tree.item(selected[0], "values")
        try:
            self._highlight_neuron_idx = int(values[0])
        except (IndexError, TypeError, ValueError):
            self._highlight_neuron_idx = None
        self._draw_brain()

    def _on_connectome_row_double_click(self, event: tk.Event) -> None:
        if self._brain is None:
            return
        tree = event.widget
        item_id = tree.identify_row(event.y)
        if item_id:
            tree.selection_set(item_id)
            values = tree.item(item_id, "values")
        else:
            selected = tree.selection()
            if not selected:
                return
            values = tree.item(selected[0], "values")
        try:
            src_idx = int(values[0])
        except (IndexError, TypeError, ValueError):
            return
        if src_idx < 0 or src_idx >= len(self._brain.substrate.brain):
            return
        neuron = self._brain.substrate.brain[src_idx]
        self._set_neuron_runtime_active(src_idx, not neuron.active)
        self._highlight_neuron_idx = src_idx
        self._save_runtime_state()
        selected_idx = self._cas_neuron_idx
        if selected_idx is not None:
            self._update_neuron_panel(selected_idx)
            self._select_connectome_source(src_idx)
        self._draw_brain()
        self._draw_cas()
        self._refresh_output_values()

    def _select_connectome_source(self, src_idx: int) -> None:
        tree = self._neuron_connectome_panel["tree"]
        for item_id in tree.get_children():
            values = tree.item(item_id, "values")
            if values and str(values[0]) == str(src_idx):
                tree.selection_set(item_id)
                tree.focus(item_id)
                tree.see(item_id)
                return

    def _on_seq_start(self) -> None:
        if self._seq_running or not self._positions:
            return
        self._seq_running = True
        self._seq_tick()

    def _on_seq_stop(self) -> None:
        self._seq_running = False
        if self._seq_tick_id is not None:
            self.after_cancel(self._seq_tick_id)
            self._seq_tick_id = None

    def _on_seq_step(self) -> None:
        if not self._brain or self._seq_cursor >= len(self._positions):
            return
        self._activate_seq_neuron()

    def _on_seq_reset(self) -> None:
        self._on_seq_stop()
        self._seq_cursor = 0
        self._seq_window = []
        if self._brain:
            for neuron in self._brain.substrate.brain:
                neuron.active = False
            self._save_runtime_state()
        self._update_seq_label()
        self._draw_brain()

    def _activate_seq_neuron(self) -> None:
        win_size = int(self._vars["seq_window"].get())
        self._seq_window.append(self._seq_cursor)
        if len(self._seq_window) > win_size:
            self._seq_window = self._seq_window[-win_size:]
        in_window = set(self._seq_window)
        for i, neuron in enumerate(self._brain.substrate.brain):
            neuron.active = i in in_window
        self._seq_cursor += 1
        self._save_runtime_state()
        self._update_seq_label()
        self._draw_brain()

    def _seq_tick(self) -> None:
        if not self._seq_running:
            return
        if self._seq_cursor >= len(self._positions):
            self._seq_running = False
            return
        self._activate_seq_neuron()
        self._seq_tick_id = self.after(int(self._vars["tick_ms"].get()), self._seq_tick)

    def _update_seq_label(self) -> None:
        if self._seq_label is None:
            return
        total = len(self._positions)
        if total:
            self._seq_label.config(text=f"Step: {self._seq_cursor} / {total}")
        else:
            self._seq_label.config(text="Step: —")

    # ── Simulation callbacks (stubs) ──────────────────────────────────────────

    def _initialize_loaded_config(self, source: str) -> None:
        self._log(f"Auto-initializing loaded config ({source})")
        if not self._on_initialize():
            self._log(f"Auto-initialization stopped after brain init failure ({source})")
            return
        if not self._on_world_initialize():
            self._log(f"Auto-initialization stopped after world init failure ({source})")

    def _on_initialize_all(self) -> bool:
        if not self._on_validate_config():
            return False
        if not self._on_initialize():
            return False
        return self._on_world_initialize()

    def _on_world_initialize(self) -> bool:
        try:
            text = self._world_yaml_text()
            data = self._validate_world_yaml_text(text)
            module = self._world_module_for_config(data)
            module.Init(text)
        except (TypeError, ValueError) as exc:
            messagebox.showerror("World init", f"Invalid world YAML:\n{exc}")
            self._world_initialized = False
            self._world_first_process_pending = False
            self._world_status_label.config(text="Invalid YAML", foreground="red")
            self._log(f"World initialization failed: {exc}")
            self._draw_world()
            return False
        self._world_initialized = True
        self._world_first_process_pending = True
        self._select_world_module(module)
        self._world_status_label.config(text="Initialized", foreground="green")
        self._log(f"World initialized ({module.__name__})")
        self._validate_model_compatibility()
        self._draw_world()
        return True

    def _on_initialize(self) -> bool:
        try:
            cfg = self._read_brain_yaml()
            brain_id = _brain_id_from_config(cfg)
            brain_cfg = cfg.get("brain", cfg)
            if not isinstance(brain_cfg, dict):
                raise ValueError("brain must be a mapping.")

            target_n = self._yaml_optional_int(brain_cfg, "neurons", minimum=1)
            head_cfg = self._yaml_int(brain_cfg, "head_size", default=0, minimum=0)
            conns = self._yaml_int(
                brain_cfg, "connections_per_neuron", aliases=("connections",), default=10, minimum=0
            )
            max_syn = self._yaml_float(
                brain_cfg, "max_synapse_length", aliases=("max_synapse",), default=0.30, minimum=0.0
            )
            w_min = self._yaml_float(brain_cfg, "weight_min", default=0.0)
            w_max = self._yaml_float(brain_cfg, "weight_max", default=1.0)
            total_in = self._yaml_float(brain_cfg, "total_input", default=1000.0)
            number_of_layers = self._yaml_int(
                brain_cfg, "NUMBER_OF_LAYERS", aliases=("number_of_layers",), default=1, minimum=1
            )
            history_depth = self._yaml_int(
                brain_cfg, "HISTORY_DEPTH", aliases=("history_depth",), default=32, minimum=1
            )
            charge_max = self._yaml_float(
                brain_cfg, "CHARGE_MAX", aliases=("charge_max",), default=100.0, minimum=0.0
            )
            initialization = self._brain_initialization_config(brain_cfg, charge_max)
            seed_value = brain_cfg.get("seed")
            seed = None if seed_value in (None, "") else int(seed_value)
        except (TypeError, ValueError) as exc:
            messagebox.showerror("Init", f"Invalid brain YAML:\n{exc}")
            self._status_label.config(text="Invalid YAML", foreground="red")
            self._log(f"Brain initialization failed: {exc}")
            return False

        try:
            positions = self._assembly_positions(cfg, target_n)
            n = len(positions)
            head = min(head_cfg, n)
            brain = create_spatial_brain(
                positions,
                connections_per_neuron=conns,
                max_synapse_length=max_syn,
                weight_min=w_min,
                weight_max=w_max,
                total_input=total_in,
                head_count=head,
                seed=seed,
                number_of_layers=number_of_layers,
                history_depth=history_depth,
                charge_max=charge_max,
                default_charge=initialization["default_charge"],
                default_recharge=initialization["default_recharge"],
                default_eq_min=initialization["default_eq_min"],
                default_eq_max=initialization["default_eq_max"],
            )
            input_rng = random.Random(seed) if seed is not None else random.Random()
            input_indices, input_specs = self._initialize_inputs(brain, positions, cfg, n, input_rng)
            output_specs = self._initialize_outputs(cfg, n)
            body = Body.from_config(cfg.get(BODY_CONFIG_SECTION))
        except (TypeError, ValueError) as exc:
            messagebox.showerror("Init", f"Invalid brain YAML:\n{exc}")
            self._status_label.config(text="Invalid YAML", foreground="red")
            self._log(f"Brain initialization failed: {exc}")
            return False

        if input_indices:
            brain.substrate.connectome = [
                link for link in brain.substrate.connectome if link[1] not in input_indices
            ]
        in_counts = [0] * n
        out_counts = [0] * n
        adj_in: dict[int, list[tuple[int, float]]] = {}
        adj_out: dict[int, list[tuple[int, float]]] = {}
        for src_idx, dst_idx, w in brain.substrate.connectome:
            out_counts[src_idx] += 1
            in_counts[dst_idx] += 1
            adj_in.setdefault(dst_idx, []).append((src_idx, w))
            adj_out.setdefault(src_idx, []).append((dst_idx, w))
        self._positions = positions
        self._brain = brain
        self._brain_id = brain_id
        current_video_file = str(self._vars["video_file"].get()).strip()
        if not current_video_file or Path(current_video_file).stem.startswith("current_"):
            self._vars["video_file"].set(str(self._default_video_path()))
        self._in_counts = in_counts
        self._out_counts = out_counts
        self._input_indices = input_indices
        self._input_specs = input_specs
        self._output_specs = output_specs
        self._body = body
        self._last_active_input_indices = [[] for _ in brain.substrate.brain]
        self._input_value_vars = {}
        self._output_value_vars = {}
        self._adj_in = adj_in
        self._adj_out = adj_out
        self._head_size = head
        self._view_x, self._view_y, self._view_scale = 0.5, 0.5, 1.0
        self._on_seq_stop()
        self._seq_cursor = 0
        self._update_seq_label()
        self._act_history.clear()
        self._active_input_history.clear()
        self._ces_pos_history.clear()
        self._ces_neg_history.clear()
        self._last_active_input_count = 0
        self._cas_charge.clear()
        self._cas_active.clear()
        self._cas_signal.clear()
        self._cas_neuron_idx = None
        self._highlight_neuron_idx = None
        self._runtime_active_overrides.clear()
        self._neuron_info_label.config(text="")
        self._iteration = 0
        self._status_label.config(
            text=f"Initialized  ({n} neurons,  {self._head_size} head,  {len(input_indices)} inputs)",
            foreground="green",
        )
        self._log(
            f"Brain initialized ({brain_id}: {n} neurons, {self._head_size} head, "
            f"{len(input_indices)} inputs, {len(brain.substrate.connectome)} connections)"
        )
        self._start_logic_history()
        self._save_runtime_state()
        self._update_iteration_display()
        self._refresh_inputs_editor()
        self._draw_cas()
        self._draw_act_count()
        return True

    def _initialize_inputs(
        self,
        brain: Brain,
        positions: list[tuple[float, float]],
        cfg: dict,
        neuron_count: int,
        rng: random.Random,
    ) -> tuple[set[int], list[dict]]:
        raw_specs = cfg.get("inputs", [])
        if raw_specs is None:
            return set(), []
        if isinstance(raw_specs, dict):
            raw_specs = [{name: spec} for name, spec in raw_specs.items()]
        if not isinstance(raw_specs, list):
            raise ValueError("inputs must be a list or mapping.")

        input_indices: set[int] = set()
        input_specs: list[dict] = []
        neurons = brain.substrate.brain
        for raw_spec in raw_specs:
            name, spec = self._normalize_input_spec(raw_spec)
            center = self._yaml_int(spec, "center", minimum=0)
            radius = self._yaml_int(spec, "radius", minimum=0)
            number = self._yaml_int(spec, "number", minimum=0)
            eq_min = self._yaml_float(spec, "eq_min", default=0.0)
            eq_max = self._yaml_float(spec, "eq_max", default=0.0)
            value = self._yaml_float(spec, "value", aliases=("physical_value",), default=0.0)
            if center >= neuron_count:
                raise ValueError(f"inputs.{name}.center must be < neuron count")

            candidates = self._input_spot_candidates(positions, center, radius)
            chosen = self._choose_input_spot(candidates, center, number, rng)
            for offset, idx in enumerate(chosen):
                neurons[idx].eq = self._spread_value(eq_min, eq_max, offset, len(chosen))
                neurons[idx].charge = value
                neurons[idx].signal[0] = value
                neurons[idx].active = value > neurons[idx].trigger[0] + neurons[idx].trigger_flex + neurons[idx].eq
                input_indices.add(idx)
            input_specs.append({"name": name, "indices": chosen, "value": value})
        return input_indices, input_specs

    def _initialize_outputs(self, cfg: dict, neuron_count: int) -> list[dict]:
        raw_specs = cfg.get("outputs", [])
        if raw_specs is None:
            return []
        if isinstance(raw_specs, dict):
            raw_specs = [{name: spec} for name, spec in raw_specs.items()]
        if not isinstance(raw_specs, list):
            raise ValueError("outputs must be a list or mapping.")

        output_specs: list[dict] = []
        for raw_spec in raw_specs:
            name, spec = self._normalize_output_spec(raw_spec)
            indices = self._output_indices(spec)
            for idx in indices:
                if idx < 0 or idx >= neuron_count:
                    raise ValueError(f"outputs.{name} index must be in [0, {neuron_count - 1}]")
            output_specs.append({"name": name, "indices": indices})
        return output_specs

    def _assembly_positions(
        self,
        cfg: dict,
        target_count: int | None,
    ) -> list[tuple[float, float]]:
        raw_assembly = cfg.get("assembly")
        if raw_assembly is None:
            if target_count is None:
                raise ValueError("brain.neurons is required when assembly is not set.")
            return self._folding_positions("phc", target_count, [], {})
        if not isinstance(raw_assembly, list):
            raise ValueError("assembly must be a list.")

        positions: list[tuple[float, float]] = []
        for step_index, raw_step in enumerate(raw_assembly):
            method, count_spec, options = self._normalize_assembly_step(raw_step, step_index)
            count = self._resolve_assembly_count(count_spec, target_count, len(positions), step_index)
            if count <= 0:
                continue
            if self._folding_module(method) is not None:
                positions.extend(self._folding_positions(method, count, positions, options))
            elif method in {"straight", "stright"}:
                positions.extend(self._straight_positions(count, positions, options))
            else:
                raise ValueError(f"assembly.{step_index}: unsupported layout method {method!r}")

        if not positions:
            raise ValueError("assembly must create at least one neuron.")
        if target_count is not None and len(positions) != target_count:
            raise ValueError(
                f"assembly creates {len(positions)} neurons, but brain.neurons is {target_count}."
            )
        return self._fit_positions_to_unit(positions)

    def _normalize_assembly_step(self, raw_step, step_index: int) -> tuple[str, object, dict]:
        if not isinstance(raw_step, dict):
            raise ValueError(f"assembly.{step_index} must be a mapping.")
        options = self._assembly_params(raw_step.get("params", raw_step.get("options", {})), step_index)
        if "method" in raw_step:
            if "count" not in raw_step:
                raise ValueError(f"assembly.{step_index}.count is required.")
            method = str(raw_step["method"]).lower()
            return method, raw_step["count"], options

        method_keys = [key for key in raw_step if key not in {"options", "params", "count"}]
        if len(method_keys) != 1:
            raise ValueError(
                f"assembly.{step_index} must use method/count/params or contain exactly one layout method."
            )
        method = str(method_keys[0]).lower()
        count_spec = raw_step[method_keys[0]]
        if isinstance(count_spec, dict):
            merged = dict(count_spec)
            count_spec = merged.pop("count", merged.pop("neurons", None))
            merged.update(options)
            options = merged
        return method, count_spec, options

    def _assembly_params(self, raw_params, step_index: int) -> dict:
        if raw_params in (None, "", "default"):
            return {}
        if isinstance(raw_params, str) and raw_params.lower() == "default":
            return {}
        if not isinstance(raw_params, dict):
            raise ValueError(f"assembly.{step_index}.params must be a mapping or \"default\".")
        return dict(raw_params)

    def _resolve_assembly_count(
        self,
        count_spec,
        target_count: int | None,
        current_count: int,
        step_index: int,
    ) -> int:
        if isinstance(count_spec, str):
            text = count_spec.strip()
            if "," in text:
                text = text.split(",", 1)[0].strip()
            if text.upper() == "LAST":
                if target_count is None:
                    raise ValueError(f"assembly.{step_index}: LAST requires brain.neurons.")
                return max(target_count - current_count, 0)
            count_spec = text
        if count_spec is None:
            raise ValueError(f"assembly.{step_index}: missing neuron count.")
        count = int(count_spec)
        if count < 0:
            raise ValueError(f"assembly.{step_index}: neuron count must be >= 0.")
        return count

    def _folding_module(self, method: str):
        try:
            module = importlib.import_module(f"foldings.{method}")
        except ImportError:
            return None
        generator = getattr(module, "Generate", None)
        if not callable(generator):
            raise ValueError(f"foldings.{method} does not define Generate.")
        return module

    def _folding_positions(
        self,
        method: str,
        count: int,
        existing: list[tuple[float, float]],
        options: dict,
    ) -> list[tuple[float, float]]:
        module = self._folding_module(method)
        if module is None:
            raise ValueError(f"unsupported folding method {method!r}")
        ox, oy = self._assembly_origin(existing, options)
        min_x, max_x, min_y, max_y = self._assembly_space(options)
        direction = options.get("d", options.get("direction", "clockwise" if method == "spiral" else "center"))
        seed_value = options.get("R", options.get("seed", None))
        seed = None if seed_value in (None, "") else int(seed_value)
        generated = module.Generate(
            N=count,
            min_x=min_x,
            max_x=max_x,
            min_y=min_y,
            max_y=max_y,
            x=ox,
            y=oy,
            d=direction,
            R=seed,
            options=options,
        )
        return [(float(px), float(py)) for px, py in generated]

    def _straight_positions(
        self,
        count: int,
        existing: list[tuple[float, float]],
        options: dict,
    ) -> list[tuple[float, float]]:
        ox, oy = self._assembly_origin(existing, options)
        dx, dy = self._assembly_direction(options)
        spacing = self._assembly_spacing(options, count + len(existing))
        return [(ox + dx * spacing * (i + 1), oy + dy * spacing * (i + 1)) for i in range(count)]

    def _assembly_origin(
        self,
        existing: list[tuple[float, float]],
        options: dict,
    ) -> tuple[float, float]:
        raw = options.get("origin", options.get("start", "LAST"))
        if isinstance(raw, str) and raw.upper() == "LAST":
            return existing[-1] if existing else (0.5, 0.5)
        if isinstance(raw, (list, tuple)) and len(raw) == 2:
            return float(raw[0]), float(raw[1])
        if isinstance(raw, dict):
            return float(raw.get("x", 0.5)), float(raw.get("y", 0.5))
        return 0.5, 0.5

    def _assembly_space(self, options: dict) -> tuple[float, float, float, float]:
        raw = options.get("space")
        if isinstance(raw, dict):
            return (
                float(raw.get("min_x", 0.0)),
                float(raw.get("max_x", 1.0)),
                float(raw.get("min_y", 0.0)),
                float(raw.get("max_y", 1.0)),
            )
        return (
            float(options.get("min_x", 0.0)),
            float(options.get("max_x", 1.0)),
            float(options.get("min_y", 0.0)),
            float(options.get("max_y", 1.0)),
        )

    def _assembly_direction(self, options: dict) -> tuple[float, float]:
        raw = options.get("direction", "right")
        named = {
            "right": (1.0, 0.0),
            "left": (-1.0, 0.0),
            "down": (0.0, 1.0),
            "up": (0.0, -1.0),
        }
        if isinstance(raw, str):
            dx, dy = named.get(raw.lower(), named["right"])
        elif isinstance(raw, (list, tuple)) and len(raw) == 2:
            dx, dy = float(raw[0]), float(raw[1])
        elif isinstance(raw, dict):
            dx, dy = float(raw.get("x", 1.0)), float(raw.get("y", 0.0))
        else:
            dx, dy = 1.0, 0.0
        length = math.hypot(dx, dy)
        if length <= 1e-12:
            return 1.0, 0.0
        return dx / length, dy / length

    def _assembly_spacing(self, options: dict, count_hint: int) -> float:
        if "spacing" in options:
            return float(options["spacing"])
        side = max(math.ceil(math.sqrt(max(count_hint, 1))), 2)
        return 1.0 / (side - 1)

    def _fit_positions_to_unit(self, positions: list[tuple[float, float]]) -> list[tuple[float, float]]:
        xs = [x for x, _ in positions]
        ys = [y for _, y in positions]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        if 0.0 <= min_x <= max_x <= 1.0 and 0.0 <= min_y <= max_y <= 1.0:
            return positions
        width = max(max_x - min_x, 1e-12)
        height = max(max_y - min_y, 1e-12)
        scale = 0.96 / max(width, height)
        x_pad = (1.0 - width * scale) / 2.0
        y_pad = (1.0 - height * scale) / 2.0
        return [((x - min_x) * scale + x_pad, (y - min_y) * scale + y_pad) for x, y in positions]

    def _choose_input_spot(
        self,
        candidates: list[int],
        center: int,
        number: int,
        rng: random.Random,
    ) -> list[int]:
        if number <= 0 or not candidates:
            return []
        if number >= len(candidates):
            chosen = list(candidates)
            rng.shuffle(chosen)
            return chosen
        pool = [idx for idx in candidates if idx != center]
        chosen = [center] if center in candidates else []
        chosen.extend(rng.sample(pool, min(number - len(chosen), len(pool))))
        rng.shuffle(chosen)
        return chosen

    def _input_spot_candidates(
        self,
        positions: list[tuple[float, float]],
        center: int,
        radius: int,
    ) -> list[int]:
        grid_side = 1
        while grid_side * grid_side < len(positions):
            grid_side <<= 1
        scale = max(grid_side - 1, 1)
        cx, cy = positions[center]
        radius2 = radius * radius
        ranked: list[tuple[float, int]] = []
        for idx, (px, py) in enumerate(positions):
            dx = (px - cx) * scale
            dy = (py - cy) * scale
            d2 = dx * dx + dy * dy
            if d2 <= radius2:
                ranked.append((d2, idx))
        ranked.sort()
        return [idx for _, idx in ranked]

    def _normalize_input_spec(self, raw_spec) -> tuple[str, dict]:
        if not isinstance(raw_spec, dict):
            raise ValueError("each input must be a mapping.")
        if "name" in raw_spec:
            name = str(raw_spec.get("name") or "input")
            return name, raw_spec
        named_keys = [
            key for key, value in raw_spec.items()
            if isinstance(key, str) and key not in {
                "center", "radius", "number", "eq_min", "eq_max"
            } and value is None
        ]
        if len(named_keys) == 1:
            name = named_keys[0]
            spec = dict(raw_spec)
            spec.pop(name, None)
            spec["name"] = name
            return name, spec
        if len(raw_spec) == 1:
            name, spec = next(iter(raw_spec.items()))
            if isinstance(spec, dict):
                return str(name), spec
        raise ValueError("each input must have a name or be a single named mapping.")

    def _normalize_output_spec(self, raw_spec) -> tuple[str, dict]:
        if not isinstance(raw_spec, dict):
            raise ValueError("each output must be a mapping.")
        if "name" in raw_spec:
            name = str(raw_spec.get("name") or "output")
            return name, raw_spec
        if len(raw_spec) == 1:
            name, spec = next(iter(raw_spec.items()))
            if isinstance(spec, dict):
                return str(name), spec
            if isinstance(spec, (list, str)):
                return str(name), {"indices": spec}
        named_keys = [
            key for key, value in raw_spec.items()
            if isinstance(key, str) and isinstance(value, (list, str))
        ]
        if len(named_keys) == 1:
            name = named_keys[0]
            return name, {"indices": raw_spec[name]}
        raise ValueError("each output must have a name or be a single named mapping.")

    def _output_indices(self, spec: dict) -> list[int]:
        raw_indices = spec.get("indices", spec.get("actuators", spec.get("neurons", [])))
        if raw_indices is None:
            return []
        if isinstance(raw_indices, str):
            text = raw_indices.strip()
            if text.startswith("[") and text.endswith("]"):
                text = text[1:-1].strip()
            if not text:
                return []
            raw_indices = [item.strip() for item in text.split(",")]
        if not isinstance(raw_indices, list):
            raise ValueError("output indices must be a list.")
        return [int(idx) for idx in raw_indices]

    def _apply_input_value(self, input_name: str, *, redraw: bool = True) -> None:
        if self._brain is None:
            return
        spec = next((item for item in self._input_specs if item["name"] == input_name), None)
        if spec is None:
            return
        var = self._input_value_vars.get(input_name)
        if var is None:
            return
        try:
            value = float(var.get())
        except ValueError:
            var.set(str(spec.get("value", 0.0)))
            self._status_label.config(text=f"Invalid input value: {input_name}", foreground="red")
            return
        spec["value"] = value
        if self._body is None:
            self._log(f"Physical input translation skipped: body is not initialized")
            return
        mapping = self._body.mapping_for_target(input_name)
        if mapping is None:
            self._log(f"Physical input translation skipped: no body mapping for {input_name!r}")
            return
        translation = self._body.translate_value(mapping, value, spec)
        self._apply_body_translation(translation, redraw=redraw)

    def _apply_body_translation(self, translation: BodyTranslation, *, redraw: bool = True) -> None:
        if self._brain is None:
            return
        spec = next((item for item in self._input_specs if item["name"] == translation.target), None)
        if spec is None:
            return
        spec["value"] = translation.value
        neurons = self._brain.substrate.brain
        active_indices = set(translation.indices)
        positive_lines: list[str] = []
        negative_example: str | None = None
        negative_example_uses_valid_target = False
        valid_targets = 0
        became_active_count = 0
        for idx in spec["indices"]:
            if idx < len(neurons):
                valid_targets += 1
                neuron = neurons[idx]
                previous_active = neuron.active
                previous_status = list(neuron.status)
                previous_signal = list(neuron.signal)
                previous_charge = neuron.charge
                active = idx in active_indices
                neuron.resize_layers(self._brain.number_of_layers)
                neuron.charge = neuron.charge_max if active else 0.0
                if active:
                    threshold = neuron.trigger[0] + neuron.trigger_flex + neuron.eq
                    neuron.signal[0] = max(translation.value, neuron.charge, threshold + 1e-9, 1.0)
                    neuron.active = True
                    neuron.drop_charge_next_cycle = False
                else:
                    neuron.status = [False] * neuron.number_of_layers
                    neuron.signal[0] = 0.0
                detail = (
                    f"idx={idx} name={neuron.name!r} "
                    f"previous_active={previous_active} "
                    f"previous_status={previous_status} "
                    f"previous_signal={previous_signal} "
                    f"previous_charge={previous_charge:.6f} "
                    f"input_signal={neuron.signal[0]:.6f} "
                    f"charge={neuron.charge:.6f} "
                    f"charge_min={neuron.charge_min:.6f} "
                    f"charge_max={neuron.charge_max:.6f} "
                    f"trigger0={neuron.trigger[0]:.6f} "
                    f"trigger_flex={neuron.trigger_flex:.6f} "
                    f"eq={neuron.eq:.6f} "
                    f"active={neuron.active} "
                    f"status={neuron.status} "
                    f"drop_charge_next_cycle={neuron.drop_charge_next_cycle}"
                )
                if active and not previous_active:
                    became_active_count += 1
                    positive_lines.append(f"  activated neuron {detail}")
                elif negative_example is None:
                    reason = "already_active" if active else "not_activated"
                    negative_example = f"  negative example ({reason}) {detail}"
                    negative_example_uses_valid_target = True
            else:
                if negative_example is None:
                    negative_example = (
                        f"  negative example (out_of_range) "
                        f"idx={idx} skipped: out of range for {len(neurons)} neurons"
                    )
        lines = [
            (
                f"Physical input translation: input={translation.target!r} "
                f"source={translation.source!r} value={translation.value:.6f} "
                f"normalized={translation.normalized:.6f} "
                f"target_indices={len(spec['indices'])} active_count={translation.count} "
                f"active_indices={translation.indices} "
                f"valid_targets={valid_targets} became_active={became_active_count}"
            )
        ]
        lines.extend(positive_lines)
        if negative_example is not None:
            lines.append(negative_example)
        omitted = valid_targets - became_active_count - (1 if negative_example_uses_valid_target else 0)
        if omitted > 0:
            lines.append(
                f"  omitted inactive/already-active target details: {omitted}"
            )
        self._log("\n".join(lines))
        if redraw:
            self._save_runtime_state()
            self._draw_brain()
            self._refresh_output_values()

    def _apply_all_input_values(self) -> None:
        for spec in self._input_specs:
            self._apply_input_value(spec["name"], redraw=False)

    def _refresh_output_values(self) -> None:
        if self._brain is None:
            for var in self._output_value_vars.values():
                var.set("-")
            return
        neurons = self._brain.substrate.brain
        for spec in self._output_specs:
            indices = [idx for idx in spec["indices"] if idx < len(neurons)]
            active = sum(1 for idx in indices if neurons[idx].active)
            value = f"{active / len(indices):.3f}" if indices else "0.000"
            var = self._output_value_vars.get(spec["name"])
            if var is not None:
                var.set(value)

    def _brain_output_values(self) -> dict[str, float]:
        if self._brain is None:
            return {}
        neurons = self._brain.substrate.brain
        values: dict[str, float] = {}
        for spec in self._output_specs:
            indices = [idx for idx in spec["indices"] if idx < len(neurons)]
            active = sum(1 for idx in indices if neurons[idx].active)
            values[spec["name"]] = active / len(indices) if indices else 0.0
        return values

    def _world_interface_spec_names(self) -> tuple[list[str], list[str]]:
        try:
            world_cfg = self._validate_world_yaml_text(self._brain_yaml_text())
        except ValueError:
            return [], []
        inputs = [
            str(item.get("name", "")).strip()
            for item in world_cfg.get("inputs", [])
            if isinstance(item, dict) and str(item.get("name", "")).strip()
        ]
        raw_outputs = world_cfg.get("outputs", [])
        if isinstance(raw_outputs, dict):
            outputs = [str(name).strip() for name in raw_outputs if str(name).strip()]
        else:
            outputs = [
                str(item.get("name", "")).strip()
                for item in raw_outputs
                if isinstance(item, dict) and str(item.get("name", "")).strip()
            ]
        return inputs, outputs

    def _read_physical_model_values(self) -> dict[str, float] | None:
        if not self._world_initialized:
            return None
        input_names, output_names = self._world_interface_spec_names()
        if self._world_first_process_pending:
            world_inputs = None
            self._world_first_process_pending = False
        else:
            brain_outputs = self._brain_output_values()
            world_inputs = {name: brain_outputs.get(name, 0.0) for name in input_names}
        try:
            world_outputs = self._world_module.Process(world_inputs)
        except Exception as exc:
            self._world_initialized = False
            self._world_status_label.config(text="Process failed", foreground="red")
            self._log(f"World process failed: {exc}")
            self._draw_world()
            return None
        if not isinstance(world_outputs, dict):
            self._log(f"World process returned non-mapping outputs: {world_outputs!r}")
            return None
        logged_inputs = (
            "None"
            if world_inputs is None
            else ", ".join(f"{name}={world_inputs.get(name, 0.0):.6f}" for name in input_names)
        )
        logged_outputs = ", ".join(
            f"{name}={float(world_outputs.get(name, 0.0)):.6f}"
            for name in output_names
        )
        self._log(f"World process inputs: {logged_inputs}")
        self._log(f"World process outputs: {logged_outputs}")
        return {str(name): float(value) for name, value in world_outputs.items()}

    def _apply_physical_outputs_to_input_neurons(self, world_outputs: dict[str, float] | None) -> None:
        if world_outputs is None:
            self._apply_all_input_values()
            return
        body_translations: dict[str, BodyTranslation] = {}
        if self._body is not None:
            body_translations = self._body.translate(world_outputs, self._input_specs)
        for target, translation in body_translations.items():
            var = self._input_value_vars.get(target)
            if var is not None:
                var.set(f"{translation.value:.6f}")
            self._apply_body_translation(translation, redraw=False)
        if body_translations:
            self._log(
                "Body translations: "
                + "; ".join(
                    f"{target}: source={translation.source} value={translation.value:.6f} "
                    f"count={translation.count} indices={translation.indices}"
                    for target, translation in body_translations.items()
                )
            )

    def _read_brain_output_scalars(self) -> dict[str, float]:
        outputs = self._brain_output_values()
        self._refresh_output_values()
        if outputs:
            self._log(
                "Brain output scalars: "
                + ", ".join(f"{name}={value:.6f}" for name, value in outputs.items())
            )
        return outputs

    def _process_world_cycle(self) -> None:
        world_outputs = self._read_physical_model_values()
        self._apply_physical_outputs_to_input_neurons(world_outputs)
        self._draw_world()

    def _spread_value(self, min_value: float, max_value: float, offset: int, count: int) -> float:
        if count <= 1:
            return min_value
        return min_value + (max_value - min_value) * offset / (count - 1)

    def _yaml_value(self, cfg: dict, key: str, aliases: tuple[str, ...] = (), default=None):
        for name in (key, *aliases):
            if name in cfg:
                return cfg[name]
        if default is not None:
            return default
        raise ValueError(f"Missing required key: brain.{key}")

    def _yaml_int(
        self,
        cfg: dict,
        key: str,
        *,
        aliases: tuple[str, ...] = (),
        default=None,
        minimum: int | None = None,
    ) -> int:
        value = int(self._yaml_value(cfg, key, aliases, default))
        if minimum is not None and value < minimum:
            raise ValueError(f"brain.{key} must be >= {minimum}")
        return value

    def _yaml_float(
        self,
        cfg: dict,
        key: str,
        *,
        aliases: tuple[str, ...] = (),
        default=None,
        minimum: float | None = None,
    ) -> float:
        value = float(self._yaml_value(cfg, key, aliases, default))
        if minimum is not None and value < minimum:
            raise ValueError(f"brain.{key} must be >= {minimum}")
        return value

    def _yaml_optional_int(
        self,
        cfg: dict,
        key: str,
        *,
        aliases: tuple[str, ...] = (),
        minimum: int | None = None,
    ) -> int | None:
        for name in (key, *aliases):
            if name in cfg:
                value = cfg[name]
                if value in (None, ""):
                    return None
                parsed = int(value)
                if minimum is not None and parsed < minimum:
                    raise ValueError(f"brain.{key} must be >= {minimum}")
                return parsed
        return None

    def _start_video_recording(self) -> None:
        if self._video_recording:
            return
        try:
            fps = max(1, int(self._vars["video_fps"].get()))
        except (tk.TclError, ValueError):
            fps = 30
            self._vars["video_fps"].set(fps)
        output_path = self._resolve_video_output_path()
        frame_root = RUNTIME_DIR / f"{output_path.stem}_frames"
        if frame_root.exists():
            shutil.rmtree(frame_root)
        frame_root.mkdir(parents=True, exist_ok=True)
        self._video_recording = True
        self._video_frame_dir = frame_root
        self._video_output_path = output_path
        self._video_frame_count = 0
        self._log(f"Video recording started: {output_path} at {fps} FPS")

    def _record_video_frame(self) -> None:
        if not self._video_recording or self._video_frame_dir is None or self._brain is None:
            return
        try:
            self.update_idletasks()
            width = max(2, int(self._brain_canvas.winfo_width()))
            height = max(2, int(self._brain_canvas.winfo_height()))
            width -= width % 2
            height -= height % 2
            frame_path = self._video_frame_dir / f"frame_{self._video_frame_count:06d}.ppm"
            self._write_brain_map_ppm(frame_path, width, height)
            self._video_frame_count += 1
        except (OSError, ValueError, tk.TclError) as exc:
            self._log(f"Video frame capture failed: {exc}")

    def _finish_video_recording(self) -> None:
        frame_dir = self._video_frame_dir
        output_path = self._video_output_path
        frame_count = self._video_frame_count
        self._video_recording = False
        self._video_frame_dir = None
        self._video_output_path = None
        self._video_frame_count = 0
        if frame_dir is None or output_path is None:
            return
        if frame_count == 0:
            self._log("Video recording stopped: no frames captured")
            shutil.rmtree(frame_dir, ignore_errors=True)
            return
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            self._log(f"Video recording stopped: ffmpeg not found; frames kept in {frame_dir}")
            return
        try:
            fps = max(1, int(self._vars["video_fps"].get()))
        except (tk.TclError, ValueError):
            fps = 30
        command = [
            ffmpeg,
            "-y",
            "-framerate",
            str(fps),
            "-i",
            str(frame_dir / "frame_%06d.ppm"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            detail = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) and exc.stderr else str(exc)
            self._log(f"Video assembly failed: {detail}; frames kept in {frame_dir}")
            return
        shutil.rmtree(frame_dir, ignore_errors=True)
        self._log(f"Video saved {output_path} ({frame_count} frames)")

    def _write_brain_map_ppm(self, path: Path, width: int, height: int) -> None:
        if self._write_canvas_snapshot_ppm(path, width, height):
            return

        bg = (0x0d, 0x11, 0x17)
        pixels = bytearray(bg * (width * height))
        if self._brain is not None:
            neurons = self._brain.substrate.brain
            strip_h = self._brain_map_summary_strip_height(height)
            map_h = max(2, height - strip_h)
            cw = width - 2 * _MARGIN
            ch = max(1.0, map_h - 2 * _MARGIN)
            half_w, half_h = width / 2, map_h / 2

            def tc(px: float, py: float) -> tuple[float, float]:
                return (
                    half_w + (px - self._view_x) * cw * self._view_scale,
                    half_h + (py - self._view_y) * ch * self._view_scale,
                )

            radius = max(1, int(round(self._circle_radius)))
            for idx, ((px, py), neuron) in enumerate(zip(self._positions, neurons)):
                cx, cy = tc(px, py)
                if cx < -radius or cx >= width + radius or cy < -radius or cy >= map_h + radius:
                    continue
                if idx in self._input_indices:
                    color = (0x74, 0xc7, 0xff) if neuron.active else (0x0b, 0x24, 0x47)
                    fill = neuron.active
                elif neuron.active:
                    color = (0x22, 0xcc, 0x55) if neuron.eq >= 0.0 else (0xcc, 0x22, 0x22)
                    fill = True
                else:
                    color = (0x3a, 0x3a, 0x3a)
                    fill = False
                self._draw_ppm_circle(pixels, width, height, int(round(cx)), int(round(cy)), radius, color, fill)
        self._draw_ppm_activity_summary_overlay(pixels, width, height)
        with path.open("wb") as file:
            file.write(f"P6\n{width} {height}\n255\n".encode("ascii"))
            file.write(pixels)

    def _write_canvas_snapshot_ppm(self, path: Path, width: int, height: int) -> bool:
        try:
            import ctypes
            from ctypes import wintypes
        except ImportError:
            return False

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        hwnd = int(self._brain_canvas.winfo_id())
        src_dc = user32.GetDC(hwnd)
        if not src_dc:
            return False
        mem_dc = gdi32.CreateCompatibleDC(src_dc)
        bitmap = gdi32.CreateCompatibleBitmap(src_dc, width, height)
        if not mem_dc or not bitmap:
            if bitmap:
                gdi32.DeleteObject(bitmap)
            if mem_dc:
                gdi32.DeleteDC(mem_dc)
            user32.ReleaseDC(hwnd, src_dc)
            return False

        old_bitmap = gdi32.SelectObject(mem_dc, bitmap)
        success = False
        try:
            srccopy = 0x00CC0020
            if not gdi32.BitBlt(mem_dc, 0, 0, width, height, src_dc, 0, 0, srccopy):
                return False

            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ("biSize", wintypes.DWORD),
                    ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD),
                ]

            class BITMAPINFO(ctypes.Structure):
                _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 1)]

            row_stride = ((width * 3 + 3) // 4) * 4
            image_size = row_stride * height
            buffer = (ctypes.c_ubyte * image_size)()
            info = BITMAPINFO()
            info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            info.bmiHeader.biWidth = width
            info.bmiHeader.biHeight = -height
            info.bmiHeader.biPlanes = 1
            info.bmiHeader.biBitCount = 24
            info.bmiHeader.biCompression = 0
            info.bmiHeader.biSizeImage = image_size
            scan_lines = gdi32.GetDIBits(mem_dc, bitmap, 0, height, buffer, ctypes.byref(info), 0)
            if scan_lines != height:
                return False

            with path.open("wb") as file:
                file.write(f"P6\n{width} {height}\n255\n".encode("ascii"))
                for y in range(height):
                    row_start = y * row_stride
                    for x in range(width):
                        offset = row_start + x * 3
                        b, g, r = buffer[offset], buffer[offset + 1], buffer[offset + 2]
                        file.write(bytes((r, g, b)))
            success = True
            return True
        finally:
            gdi32.SelectObject(mem_dc, old_bitmap)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(mem_dc)
            user32.ReleaseDC(hwnd, src_dc)
            if not success:
                try:
                    path.unlink()
                except OSError:
                    pass

    def _draw_ppm_circle(
        self,
        pixels: bytearray,
        width: int,
        height: int,
        cx: int,
        cy: int,
        radius: int,
        color: tuple[int, int, int],
        fill: bool,
    ) -> None:
        radius2 = radius * radius
        inner2 = max(0, (radius - 1) * (radius - 1))
        for y in range(max(0, cy - radius), min(height, cy + radius + 1)):
            dy = y - cy
            for x in range(max(0, cx - radius), min(width, cx + radius + 1)):
                dx = x - cx
                d2 = dx * dx + dy * dy
                if d2 > radius2 or (not fill and d2 < inner2):
                    continue
                offset = (y * width + x) * 3
                pixels[offset:offset + 3] = bytes(color)

    def _draw_ppm_activity_summary_overlay(self, pixels: bytearray, width: int, height: int) -> None:
        if not bool(self._vars["video_summary_on_map"].get()):
            return
        overlay_h = self._brain_map_summary_strip_height(height)
        if overlay_h <= 0:
            return
        y0 = height - overlay_h
        bg = (0x0d, 0x11, 0x17)
        axis = (0x2a, 0x2a, 0x2a)
        for y in range(y0, height):
            for x in range(width):
                self._set_ppm_pixel(pixels, width, height, x, y, bg)

        series = self._activity_summary_series(self._summary_depth_value())
        values = [float(value) for data, _, _label in series for value in data]
        if not series or not values:
            return
        vmin = min(values)
        vmax = max(values)
        if vmin == vmax:
            vmin -= 0.5
            vmax += 0.5

        left = 42
        right = width - 6
        top = y0 + 4
        bottom = height - 4
        if right <= left or bottom <= top:
            return
        self._draw_ppm_line(pixels, width, height, left, top, left, bottom, axis)
        self._draw_ppm_line(pixels, width, height, left, bottom, right, bottom, axis)
        if vmin < 0.0 < vmax:
            zero_y = bottom - int(round((0.0 - vmin) / (vmax - vmin) * (bottom - top)))
            self._draw_ppm_line(pixels, width, height, left, zero_y, right, zero_y, (0x33, 0x41, 0x55))

        for data, color_hex, _label in series:
            vals = [float(value) for value in data]
            if len(vals) < 2:
                continue
            color = self._hex_to_rgb(color_hex)
            last_x = left
            last_y = bottom - int(round((vals[0] - vmin) / (vmax - vmin) * (bottom - top)))
            for i, value in enumerate(vals[1:], start=1):
                x = left + int(round(i * (right - left) / (len(vals) - 1)))
                y = bottom - int(round((value - vmin) / (vmax - vmin) * (bottom - top)))
                self._draw_ppm_line(pixels, width, height, last_x, last_y, x, y, color)
                last_x, last_y = x, y

    def _hex_to_rgb(self, color: str) -> tuple[int, int, int]:
        text = color.lstrip("#")
        return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)

    def _set_ppm_pixel(
        self,
        pixels: bytearray,
        width: int,
        height: int,
        x: int,
        y: int,
        color: tuple[int, int, int],
    ) -> None:
        if x < 0 or x >= width or y < 0 or y >= height:
            return
        offset = (y * width + x) * 3
        pixels[offset:offset + 3] = bytes(color)

    def _draw_ppm_line(
        self,
        pixels: bytearray,
        width: int,
        height: int,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        color: tuple[int, int, int],
    ) -> None:
        dx = abs(x1 - x0)
        sx = 1 if x0 < x1 else -1
        dy = -abs(y1 - y0)
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        x, y = x0, y0
        while True:
            self._set_ppm_pixel(pixels, width, height, x, y, color)
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x += sx
            if e2 <= dx:
                err += dx
                y += sy

    def _on_start(self) -> None:
        if self._running:
            return
        if bool(self._vars["record_video"].get()):
            self._start_video_recording()
        self._running = True
        self._log("Simulation started")
        self._tick()

    def _on_stop(self) -> None:
        was_running = self._running or self._tick_id is not None
        self._running = False
        if self._tick_id is not None:
            self.after_cancel(self._tick_id)
            self._tick_id = None
        if was_running:
            self._log("Simulation paused")
        if self._video_recording:
            self._finish_video_recording()

    def _on_step(self) -> None:
        if self._run_simulation_cycle():
            self._log(f"Simulation stepped to iteration {self._iteration}")

    def _run_simulation_cycle(self) -> bool:
        if not self._brain:
            return False
        self._iteration += 1

        # 1. Read values from physical model and update io table and input value vars
        world_outputs = self._read_physical_model_values()
        light_val = math.sin(self._iteration * 0.1) * 55 + 55
        hunger_val = (math.cos(self._iteration * 0.05) + 1) * 50
        world_outputs = {'velocity': 0.5, 'hunger': hunger_val, 'light': light_val }

        # 2. Apply input values to neurons (body translation and logging)
        self._apply_physical_outputs_to_input_neurons(world_outputs)

        # 3. Process brain with selected neuron log
        self._process_brain_with_selected_neuron_log()

        # 4. Read brain outputs and translate number neurons to scalars
        self._read_brain_output_scalars()

        # 5. Save runtime state (for potential rewinding)
        self._save_runtime_state()

        # 6. Record history (for potential rewinding and charts)
        self._record_history()

        # 7. Refresh charts (with new history)
        self._refresh_charts()

        # 8. Save detailed logic history
        self._append_logic_history()
        self._update_iteration_display()
        self._record_video_frame()
        if self._world_initialized:
            self._draw_world()
        return True

    def _on_reset(self) -> None:
        self._on_stop()
        self._iteration = 0
        self._update_iteration_display()
        self._save_runtime_state()
        self._log("Simulation reset")

    def _tick(self) -> None:
        if not self._running:
            return
        self._run_simulation_cycle()
        interval = int(self._vars["tick_ms"].get())
        self._tick_id = self.after(interval, self._tick)

    def _set_neuron_label(self, vals: dict, key: str, text: str) -> None:
        vals[key].config(text=text)

    def _set_neuron_bool(self, vals: dict, key: str, value: bool) -> None:
        vals[f"{key}_var"].set(value)

    def _set_neuron_entry(self, vals: dict, key: str, value: float) -> None:
        entry = vals[key]
        if self.focus_get() is entry:
            return
        vals[f"{key}_var"].set(f"{value:.6f}")

    def _selected_neuron(self):
        if not self._brain or self._cas_neuron_idx is None:
            return None
        if self._cas_neuron_idx >= len(self._brain.substrate.brain):
            return None
        return self._brain.substrate.brain[self._cas_neuron_idx]

    def _set_neuron_runtime_active(self, idx: int, active: bool) -> None:
        if self._brain is None or idx < 0 or idx >= len(self._brain.substrate.brain):
            return
        self._runtime_active_overrides[idx] = bool(active)
        self._apply_neuron_active_override(idx, bool(active))

    def _apply_runtime_active_overrides(self) -> None:
        if self._brain is None:
            return
        for idx, active in list(self._runtime_active_overrides.items()):
            if idx >= len(self._brain.substrate.brain):
                del self._runtime_active_overrides[idx]
                continue
            self._apply_neuron_active_override(idx, active)

    def _apply_neuron_active_override(self, idx: int, active: bool) -> None:
        neuron = self._brain.substrate.brain[idx]
        neuron.resize_layers(self._brain.number_of_layers)
        if active:
            neuron.status[0] = True
            threshold = neuron.trigger[0] + neuron.trigger_flex + neuron.eq
            forced_signal = max(neuron.signal[0], neuron.charge, threshold + 1e-9, 1.0)
            neuron.signal[0] = forced_signal
            neuron.charge = min(neuron.charge_max, max(neuron.charge, forced_signal))
        else:
            neuron.status = [False] * neuron.number_of_layers
            neuron.signal[0] = 0.0

    def _process_brain_with_selected_neuron_log(self) -> None:
        if self._brain is None:
            return
        self._apply_runtime_active_overrides()
        neurons = self._brain.substrate.brain
        self._last_active_input_count = sum(
            1
            for idx in self._input_indices
            if idx < len(neurons) and neurons[idx].active
        )
        self._update_last_active_input_indices()
        selected_idx = self._cas_neuron_idx
        if selected_idx is None or selected_idx >= len(self._brain.substrate.brain):
            self._brain.process()
            self._apply_runtime_active_overrides()
            return

        trace = self._selected_neuron_process_trace(selected_idx)
        self._brain.process()
        self._apply_runtime_active_overrides()
        self._log_selected_neuron_process_trace(selected_idx, trace)

    def _selected_neuron_process_trace(self, idx: int) -> dict:
        neurons = self._brain.substrate.brain
        neuron = neurons[idx]
        threshold = neuron.trigger[0] + neuron.trigger_flex + neuron.eq
        incoming_links = []
        total_signal = 0.0
        raw_total_signal = 0.0

        for src_idx, weight in self._adj_in.get(idx, []):
            src = neurons[src_idx]
            src_threshold = src.trigger[0] + src.trigger_flex + src.eq
            src_ready = src.active and not src.drop_charge_next_cycle
            raw_signal = src.signal[0] * weight
            signal = raw_signal if src_ready else 0.0
            raw_total_signal += raw_signal
            total_signal += signal
            incoming_links.append({
                "src": src_idx,
                "src_active": src.active,
                "src_status": list(src.status),
                "src_signal": list(src.signal),
                "src_charge": src.charge,
                "src_drop_charge_next_cycle": src.drop_charge_next_cycle,
                "src_eq": src.eq,
                "src_trigger": list(src.trigger),
                "src_trigger_flex": src.trigger_flex,
                "src_threshold": src_threshold,
                "src_ready": src_ready,
                "weight": weight,
                "raw_signal": raw_signal,
                "signal": signal,
            })

        charge_at_decision = neuron.charge
        recharging = neuron.drop_charge_next_cycle
        can_activate = not recharging and charge_at_decision >= neuron.charge_min
        active_after_signal = can_activate and total_signal > threshold
        recharge = max(0.0, neuron.recharge + neuron.recharge_flex)
        final_charge_estimate = (
            0.0
            if active_after_signal
            else min(neuron.charge_max, charge_at_decision + recharge)
        )
        final_drop_charge_next_cycle = (
            True
            if active_after_signal
            else recharging and final_charge_estimate < neuron.charge_max
        )
        final_tiredness_estimate = (
            neuron.tiredness + max(0.0, neuron.cyclic_discharge)
            if active_after_signal
            else max(0.0, neuron.tiredness - recharge)
        )

        return {
            "iteration": self._brain.iteration_idx,
            "pre_active": neuron.active,
            "pre_status": list(neuron.status),
            "pre_signal": list(neuron.signal),
            "pre_charge": neuron.charge,
            "pre_drop_charge_next_cycle": neuron.drop_charge_next_cycle,
            "pre_cumulative_signal": neuron.cumulative_signal,
            "pre_tiredness": neuron.tiredness,
            "eq": neuron.eq,
            "trigger": list(neuron.trigger),
            "trigger_flex": neuron.trigger_flex,
            "threshold": threshold,
            "charge_min": neuron.charge_min,
            "charge_max": neuron.charge_max,
            "recharge": neuron.recharge,
            "recharge_flex": neuron.recharge_flex,
            "cyclic_discharge": neuron.cyclic_discharge,
            "history_len": len(neuron.history_table),
            "incoming_links": incoming_links,
            "total_signal": total_signal,
            "raw_total_signal": raw_total_signal,
            "charge_at_decision": charge_at_decision,
            "recharging": recharging,
            "can_activate": can_activate,
            "active_after_signal": active_after_signal,
            "recharge": recharge,
            "final_charge_estimate": final_charge_estimate,
            "final_tiredness_estimate": final_tiredness_estimate,
            "final_drop_charge_next_cycle": final_drop_charge_next_cycle,
        }

    def _log_selected_neuron_process_trace(self, idx: int, trace: dict) -> None:
        neuron = self._brain.substrate.brain[idx]
        lines = [
            (
                f"Selected neuron #{idx} process trace "
                f"(brain iteration {trace['iteration']} -> {self._brain.iteration_idx})"
            ),
            (
                "  before: "
                f"active={trace['pre_active']} "
                f"status={trace['pre_status']} "
                f"signal={trace['pre_signal']} "
                f"charge={trace['pre_charge']:.6f} "
                f"drop_charge_next_cycle={trace['pre_drop_charge_next_cycle']} "
                f"cumulative_signal={trace['pre_cumulative_signal']:.6f} "
                f"tiredness={trace['pre_tiredness']:.6f} "
                f"history_len={trace['history_len']}"
            ),
            (
                "  threshold: "
                f"eq={trace['eq']:.6f} "
                f"trigger={trace['trigger']} "
                f"trigger_flex={trace['trigger_flex']:.6f} "
                f"threshold={trace['threshold']:.6f} "
                f"charge_min={trace['charge_min']:.6f} "
                f"charge_max={trace['charge_max']:.6f}"
            ),
            (
                "  incoming: "
                f"active_source_signal={trace['total_signal']:.6f} "
                f"raw_all_source_signal={trace['raw_total_signal']:.6f} "
                f"input_links={len(trace['incoming_links'])}"
            ),
        ]
        for link in trace["incoming_links"]:
            lines.append(
                "    link "
                f"src={link['src']} "
                f"src_active={link['src_active']} "
                f"src_status={link['src_status']} "
                f"src_signal={link['src_signal']} "
                f"src_charge={link['src_charge']:.6f} "
                f"src_drop_charge_next_cycle={link['src_drop_charge_next_cycle']} "
                f"src_eq={link['src_eq']:.6f} "
                f"src_trigger={link['src_trigger']} "
                f"src_trigger_flex={link['src_trigger_flex']:.6f} "
                f"src_threshold={link['src_threshold']:.6f} "
                f"src_ready={link['src_ready']} "
                f"weight={link['weight']:.6f} "
                f"raw_signal={link['raw_signal']:.6f} "
                f"applied_signal={link['signal']:.6f}"
            )
        lines.extend([
            (
                "  decision: "
                f"charge_at_decision={trace['charge_at_decision']:.6f} "
                f"recharging={trace['recharging']} "
                f"can_activate={trace['can_activate']} "
                f"active_after_signal={trace['active_after_signal']} "
                f"drop_charge_next_cycle_after={trace['final_drop_charge_next_cycle']} "
                f"recharge_applied={trace['recharge']:.6f}"
            ),
            (
                "  expected after: "
                f"charge={trace['final_charge_estimate']:.6f} "
                f"tiredness={trace['final_tiredness_estimate']:.6f}"
            ),
            (
                "  actual after: "
                f"active={neuron.active} "
                f"status={neuron.status} "
                f"signal={neuron.signal} "
                f"charge={neuron.charge:.6f} "
                f"drop_charge_next_cycle={neuron.drop_charge_next_cycle} "
                f"cumulative_signal={neuron.cumulative_signal:.6f} "
                f"tiredness={neuron.tiredness:.6f} "
                f"history_len={len(neuron.history_table)}"
            ),
        ])
        self._log("\n".join(lines))

    def _apply_selected_neuron_active(self) -> None:
        self._apply_selected_neuron_bool()

    def _apply_selected_neuron_bool(self) -> None:
        neuron = self._selected_neuron()
        if neuron is None:
            return
        vals = self._neuron_fields_panel["vals"]
        idx = self._cas_neuron_idx
        if idx is None:
            return
        self._set_neuron_runtime_active(idx, bool(vals["active_var"].get()))
        neuron.drop_charge_next_cycle = bool(vals["drop_next_var"].get())
        self._refresh_selected_neuron_after_edit()

    def _apply_selected_neuron_field(self, event: tk.Event) -> None:
        neuron = self._selected_neuron()
        if neuron is None:
            return
        field_map = {
            "charge_max": "charge_max",
            "eq": "eq",
            "trig_flex": "trigger_flex",
            "charge": "charge",
            "charge_min": "charge_min",
            "recharge": "recharge",
            "recharge_flex": "recharge_flex",
            "discharge_random": "discharge_random",
            "cumul": "cumulative_signal",
            "etd": "elastic_trigger_delta",
            "erchg": "elastic_recharge",
            "cdschg": "cyclic_discharge",
            "tired": "tiredness",
        }
        vals = self._neuron_fields_panel["vals"]
        for key, attr in field_map.items():
            if vals[key] is event.widget:
                try:
                    setattr(neuron, attr, float(vals[f"{key}_var"].get()))
                except ValueError:
                    vals[f"{key}_var"].set(f"{getattr(neuron, attr):.6f}")
                    self._status_label.config(text=f"Invalid value for {key}", foreground="red")
                    return
                self._refresh_selected_neuron_after_edit()
                return

    def _refresh_selected_neuron_after_edit(self) -> None:
        idx = self._cas_neuron_idx
        if idx is None:
            return
        self._save_runtime_state()
        self._draw_brain()
        self._draw_cas()
        self._update_neuron_panel(idx)
        self._set_neuron_info(idx)
        self._refresh_output_values()

    def _update_neuron_panel(self, idx: int) -> None:
        if not self._brain or idx >= len(self._brain.substrate.brain):
            return
        neu = self._brain.substrate.brain[idx]
        pos = self._positions[idx] if idx < len(self._positions) else (0.0, 0.0)
        ic  = self._in_counts[idx]  if idx < len(self._in_counts)  else 0
        oc  = self._out_counts[idx] if idx < len(self._out_counts) else 0

        neurons = self._brain.substrate.brain
        total_signal = 0.0
        link_rows = []
        for src, w in self._adj_in.get(idx, []):
            sn = neurons[src]
            threshold = sn.trigger[0] + sn.trigger_flex + sn.eq
            status = "ready" if sn.active else "idle"
            sig = sn.signal[0] * float(sn.active) * w
            total_signal += sig
            link_rows.append((
                src,
                status,
                str(sn.active),
                f"{sn.charge:.4f}",
                f"{threshold:.4f}",
                f"{w:.4f}",
                f"{sig:.4f}",
            ))

        fields_panel = self._neuron_fields_panel
        fields_panel["header"].config(
            text=f"Neuron  #{idx}",
            foreground="#22cc55" if neu.active else "#aaaaaa",
        )
        v = fields_panel["vals"]
        self._set_neuron_label(v, "index", str(idx))
        self._set_neuron_label(v, "name", neu.name)
        self._set_neuron_label(v, "pos", f"({pos[0]:.3f}, {pos[1]:.3f})")
        self._set_neuron_label(v, "inputs", str(ic))
        self._set_neuron_label(v, "outputs", str(oc))
        self._set_neuron_bool(v, "active", neu.active)
        self._set_neuron_bool(v, "drop_next", neu.drop_charge_next_cycle)
        self._set_neuron_label(v, "layers", str(neu.number_of_layers))
        self._set_neuron_label(v, "hist_depth", str(neu.history_depth))
        self._set_neuron_entry(v, "charge_max", neu.charge_max)
        self._set_neuron_label(v, "status", str(neu.status))
        self._set_neuron_label(v, "signal", str(neu.signal))
        self._set_neuron_label(v, "trigger", str(neu.trigger))
        self._set_neuron_entry(v, "eq", neu.eq)
        self._set_neuron_entry(v, "trig_flex", neu.trigger_flex)
        self._set_neuron_entry(v, "charge", neu.charge)
        self._set_neuron_entry(v, "charge_min", neu.charge_min)
        self._set_neuron_entry(v, "recharge", neu.recharge)
        self._set_neuron_entry(v, "recharge_flex", neu.recharge_flex)
        self._set_neuron_entry(v, "discharge_random", neu.discharge_random)
        self._set_neuron_entry(v, "cumul", neu.cumulative_signal)
        self._set_neuron_entry(v, "etd", neu.elastic_trigger_delta)
        self._set_neuron_entry(v, "erchg", neu.elastic_recharge)
        self._set_neuron_entry(v, "cdschg", neu.cyclic_discharge)
        self._set_neuron_entry(v, "tired", neu.tiredness)
        self._set_neuron_label(v, "hist", str(len(neu.history_table)))

        connectome_panel = self._neuron_connectome_panel
        connectome_panel["header"].config(
            text=f"Neuron  #{idx} input links ({ic})",
            foreground="#22cc55" if neu.active else "#aaaaaa",
        )
        tree = connectome_panel["tree"]
        tree.delete(*tree.get_children())
        for row in link_rows:
            tree.insert("", tk.END, values=row)
        connectome_panel["total_signal"].config(text=f"Total input signal:  {total_signal:.6f}")

    # ── Chart helpers ─────────────────────────────────────────────────────────

    def _record_history(self) -> None:
        neurons = self._brain.substrate.brain
        active_neurons = [n for n in neurons if n.active]
        active_count = len(active_neurons)
        self._act_history.append((active_count / len(neurons) * 100.0) if neurons else 0.0)
        self._active_input_history.append(float(self._last_active_input_count))
        self._ces_pos_history.append(sum(n.eq for n in active_neurons if n.eq > 0.0))
        self._ces_neg_history.append(sum(n.eq for n in active_neurons if n.eq < 0.0))
        if self._cas_neuron_idx is not None and self._cas_neuron_idx < len(neurons):
            n = neurons[self._cas_neuron_idx]
            self._cas_charge.append(n.charge)
            self._cas_active.append(float(n.active))
            self._cas_signal.append(n.cumulative_signal)

    def _refresh_charts(self) -> None:
        try:
            tab = self._bottom_nb.index(self._bottom_nb.select())
        except tk.TclError:
            return
        if tab == 1:
            self._draw_cas()
        elif tab == 2:
            self._draw_act_count()
        if self._cas_neuron_idx is not None:
            self._update_neuron_panel(self._cas_neuron_idx)

    def _plot(
        self,
        c: tk.Canvas,
        data: deque | list,
        color: str,
        label: str,
        x0: int, y0: int, w: int, h: int,
        *,
        y_min: float | None = None,
        y_max: float | None = None,
    ) -> None:
        ML, MR, MT, MB = 42, 6, 14, 12
        ax = x0 + ML
        ay0 = y0 + MT
        ay1 = y0 + h - MB
        pw = max(x0 + w - MR - ax, 1)
        ph = max(ay1 - ay0, 1)

        c.create_text(ax + 4, y0 + 2, text=label, fill=color, font=("Courier", 8), anchor="nw")
        c.create_line(ax, ay0, ax, ay1, fill="#2a2a2a", width=1)
        c.create_line(ax, ay1, ax + pw, ay1, fill="#2a2a2a", width=1)

        vals = list(data)
        N = len(vals)
        vmin = y_min if y_min is not None else (min(vals) if vals else 0.0)
        vmax = y_max if y_max is not None else (max(vals) if vals else 1.0)
        if vmin == vmax:
            vmin -= 0.5
            vmax += 0.5

        for frac, val in ((0.0, vmax), (0.5, (vmin + vmax) / 2), (1.0, vmin)):
            ty = ay0 + frac * ph
            c.create_line(ax - 3, ty, ax, ty, fill="#444", width=1)
            c.create_text(ax - 4, ty, text=f"{val:.3g}", fill="#555",
                          font=("Courier", 7), anchor="e")
            if 0.0 < frac < 1.0:
                c.create_line(ax, ty, ax + pw, ty, fill="#1c1c1c", width=1, dash=(2, 4))

        if N < 2:
            return
        pts = []
        for i, v in enumerate(vals):
            pts.append(ax + i * pw / (N - 1))
            pts.append(ay1 - (v - vmin) / (vmax - vmin) * ph)
        c.create_line(*pts, fill=color, width=1)

    def _summary_depth_value(self) -> int:
        try:
            return max(1, int(self._vars["summary_depth"].get()))
        except (tk.TclError, ValueError):
            depth = 1000
            self._vars["summary_depth"].set(depth)
            return depth

    def _video_summary_height_value(self) -> int:
        try:
            return max(10, int(self._vars["video_summary_height"].get()))
        except (tk.TclError, ValueError):
            height = 40
            self._vars["video_summary_height"].set(height)
            return height

    def _brain_map_summary_strip_height(self, canvas_height: int) -> int:
        if not bool(self._vars["video_summary_on_map"].get()):
            return 0
        return min(max(10, self._video_summary_height_value()), max(0, canvas_height - 4))

    def _activity_summary_series(self, depth: int) -> list[tuple[list[float], str, str]]:
        series: list[tuple[list[float], str, str]] = []
        if self._vars["summary_show_active"].get():
            series.append(([float(v) for v in list(self._act_history)[-depth:]], "#9ca3af", "Active count %"))
        if self._vars["summary_show_inputs"].get():
            series.append(([float(v) for v in list(self._active_input_history)[-depth:]], "#74c7ff", "Active input neurons"))
        if self._vars["summary_show_ces_pos"].get():
            series.append(([float(v) for v in list(self._ces_pos_history)[-depth:]], "#22cc55", "CES pos"))
        if self._vars["summary_show_ces_neg"].get():
            series.append(([float(v) for v in list(self._ces_neg_history)[-depth:]], "#ef4444", "CES neg"))
        return series

    def _draw_activity_summary_on_brain_map(self, c: tk.Canvas, width: int, height: int) -> None:
        if not bool(self._vars["video_summary_on_map"].get()):
            return
        overlay_h = self._brain_map_summary_strip_height(height)
        if overlay_h <= 0:
            return
        y0 = height - overlay_h
        c.create_rectangle(0, y0, width, height, fill="#0d1117", outline="#2a2a2a")
        self._plot_summary(c, self._activity_summary_series(self._summary_depth_value()), 0, y0, width, overlay_h)

    def _plot_summary(
        self,
        c: tk.Canvas,
        series: list[tuple[deque | list, str, str]],
        x0: int, y0: int, w: int, h: int,
    ) -> None:
        ML, MR, MT, MB = 42, 6, 18, 12
        ax = x0 + ML
        ay0 = y0 + MT
        ay1 = y0 + h - MB
        pw = max(x0 + w - MR - ax, 1)
        ph = max(ay1 - ay0, 1)

        c.create_line(ax, ay0, ax, ay1, fill="#2a2a2a", width=1)
        c.create_line(ax, ay1, ax + pw, ay1, fill="#2a2a2a", width=1)

        if not series:
            c.create_text(ax + 4, y0 + 2, text="No signals selected", fill="#555", font=("Courier", 8), anchor="nw")
            return

        values = [float(value) for data, _, _ in series for value in data]
        vmin = min(values) if values else 0.0
        vmax = max(values) if values else 1.0
        if vmin == vmax:
            vmin -= 0.5
            vmax += 0.5

        for frac, val in ((0.0, vmax), (0.5, (vmin + vmax) / 2), (1.0, vmin)):
            ty = ay0 + frac * ph
            c.create_line(ax - 3, ty, ax, ty, fill="#444", width=1)
            c.create_text(ax - 4, ty, text=f"{val:.3g}", fill="#555",
                          font=("Courier", 7), anchor="e")
            if 0.0 < frac < 1.0:
                c.create_line(ax, ty, ax + pw, ty, fill="#1c1c1c", width=1, dash=(2, 4))

        if vmin < 0.0 < vmax:
            zero_y = ay1 - (0.0 - vmin) / (vmax - vmin) * ph
            c.create_line(ax, zero_y, ax + pw, zero_y, fill="#334155", width=1)

        legend_x = ax + 4
        for _data, color, label in series:
            c.create_text(legend_x, y0 + 2, text=label, fill=color, font=("Courier", 8), anchor="nw")
            legend_x += max(90, len(label) * 8)

        for data, color, _label in series:
            vals = [float(value) for value in data]
            if len(vals) < 2:
                continue
            pts = []
            for i, value in enumerate(vals):
                pts.append(ax + i * pw / (len(vals) - 1))
                pts.append(ay1 - (value - vmin) / (vmax - vmin) * ph)
            c.create_line(*pts, fill=color, width=1)

    def _draw_cas(self, event=None) -> None:
        c = self._cas_canvas
        W, H = c.winfo_width(), c.winfo_height()
        if W <= 1 or H <= 1:
            return
        c.delete("all")
        if self._cas_neuron_idx is None:
            c.create_text(W // 2, H // 2, text="Click a neuron to view its dynamics",
                          fill="#3d4451", font=("Helvetica", 11))
            return
        hdr = 14
        c.create_text(W // 2, hdr // 2, text=f"Neuron  #{self._cas_neuron_idx}",
                      fill="#888", font=("Helvetica", 9))
        band = (H - hdr) // 3
        self._plot(c, self._cas_charge, "#4488ff", "Charge",
                   0, hdr,              W, band)
        self._plot(c, self._cas_active, "#22cc55", "Active",
                   0, hdr + band,       W, band, y_min=0.0, y_max=1.0)
        self._plot(c, self._cas_signal, "#ffcc22", "Cumul. signal",
                   0, hdr + 2 * band,  W, H - hdr - 2 * band)

    def _draw_act_count(self, event=None) -> None:
        c = self._act_canvas
        W, H = c.winfo_width(), c.winfo_height()
        if W <= 1 or H <= 1:
            return
        c.delete("all")
        self._plot_summary(c, self._activity_summary_series(self._summary_depth_value()), 0, 0, W, H)

    def _on_close(self) -> None:
        self._log("Application closing")
        self._on_stop()
        self._save_config(CONFIG_PATH)
        self.destroy()


def main() -> None:
    app = App()
    app.mainloop()
