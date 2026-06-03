"""Linear physical world with a single left/right agent coordinate.

The public API in this module is intentionally function-based so different
world modules can be loaded with the same external contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml


@dataclass(slots=True)
class Image:
    width: int
    height: int
    pixels: list[list[tuple[int, int, int]]]

    def get_pixel(self, x: int, y: int) -> tuple[int, int, int]:
        return self.pixels[y][x]

    def to_ppm(self) -> bytes:
        header = f"P6\n{self.width} {self.height}\n255\n".encode("ascii")
        body = bytearray()
        for row in self.pixels:
            for r, g, b in row:
                body.extend((r, g, b))
        return header + bytes(body)


@dataclass(slots=True)
class InputMapping:
    name: str
    min_value: float
    max_value: float

    def physical_value(self, normalized: float) -> float:
        return self.min_value + normalized * (self.max_value - self.min_value)


@dataclass(slots=True)
class OutputMapping:
    name: str
    source: str
    min_value: float | None = None
    max_value: float | None = None


@dataclass(slots=True)
class WorldState:
    x: float
    velocity: float
    stomach_content: float
    time: float = 0.0
    step: int = 0


@dataclass(slots=True)
class WorldConfig:
    dt: float
    input_validation: str
    max_steps: int | None
    x_min: float
    x_max: float
    mass: float
    drag: float
    restitution: float
    initial_x: float
    initial_velocity: float
    initial_stomach_content: float
    stomach_decay: float
    light_x: float
    light_brightness: float
    inputs: dict[str, InputMapping]
    outputs: list[OutputMapping]


_DEFAULT_CONFIG = """\
world:
  base: worlds/linear.py
  dt: 0.1
  seed: 42
  input_validation: strict
  max_steps: null
  dimensions: 2
  bounds:
    x: [-10.0, 10.0]
    y: [0.0, 1.0]
  drag: 0.05

objects:
  - name: agent
    shape: triangle
    mass: 1.0
    radius: 0.5
    position: [0.0]
    velocity: [0.0]
    restitution: 0.2
    stomach_content: 10.0
  - name: light
    x: 5.0
    brightness: 10.0

inputs:
  - name: left_motor
    min: 0.0
    max: 10.0
  - name: right_motor
    min: 0.0
    max: 10.0

outputs:
  velocity: velocity
  hunger: hunger
  light: lightness
"""

_config: WorldConfig | None = None
_state: WorldState | None = None


def Init(config_yaml: str) -> None:
    """Initialize the world from YAML and reset all simulation state."""
    global _config, _state
    cfg = _parse_config(config_yaml)
    _config = cfg
    _state = WorldState(
        x=_clamp(cfg.initial_x, cfg.x_min, cfg.x_max),
        velocity=cfg.initial_velocity,
        stomach_content=_clamp(cfg.initial_stomach_content, 0.0, 10.0),
    )


def GetDefaultConfig() -> str:
    """Return a valid default YAML configuration."""
    return _DEFAULT_CONFIG


def Process(inputs: dict[str, float]) -> dict[str, float]:
    """Advance the world by one step and return observable values."""
    cfg, state = _require_initialized()
    normalized = _validate_inputs(inputs, cfg)
    if cfg.max_steps is not None and state.step >= cfg.max_steps:
        return _collect_outputs(cfg, state)

    left_force = cfg.inputs["left_motor"].physical_value(normalized["left_motor"])
    right_force = cfg.inputs["right_motor"].physical_value(normalized["right_motor"])
    force = right_force - left_force
    drag_force = -state.velocity * cfg.drag
    acceleration = (force + drag_force) / cfg.mass

    state.velocity += acceleration * cfg.dt
    state.x += state.velocity * cfg.dt
    state.stomach_content = max(0.0, state.stomach_content - cfg.stomach_decay * cfg.dt)
    _resolve_bounds(cfg, state)
    state.time += cfg.dt
    state.step += 1
    return _collect_outputs(cfg, state)


def GetParams() -> dict[str, str]:
    """Return editable internal parameters as strings."""
    cfg, state = _require_initialized()
    return {
        "dt": str(cfg.dt),
        "input_validation": cfg.input_validation,
        "max_steps": "" if cfg.max_steps is None else str(cfg.max_steps),
        "x_min": str(cfg.x_min),
        "x_max": str(cfg.x_max),
        "mass": str(cfg.mass),
        "drag": str(cfg.drag),
        "restitution": str(cfg.restitution),
        "stomach_decay": str(cfg.stomach_decay),
        "light_x": str(cfg.light_x),
        "light_brightness": str(cfg.light_brightness),
        "x": str(state.x),
        "velocity": str(state.velocity),
        "stomach_content": str(state.stomach_content),
        "time": str(state.time),
        "step": str(state.step),
    }


def SetParam(name: str, value: str) -> None:
    """Set one editable world parameter."""
    SetParams({name: value})


def SetParams(params: dict[str, str]) -> None:
    """Set multiple editable world parameters."""
    global _config
    cfg, state = _require_initialized()
    values = GetParams()
    values.update(params)
    next_config = WorldConfig(
        dt=_positive_float(values["dt"], "dt"),
        input_validation=_validation_mode(values["input_validation"]),
        max_steps=_optional_nonnegative_int(values["max_steps"], "max_steps"),
        x_min=float(values["x_min"]),
        x_max=float(values["x_max"]),
        mass=_positive_float(values["mass"], "mass"),
        drag=max(0.0, float(values["drag"])),
        restitution=_bounded_float(values["restitution"], "restitution", 0.0, 1.0),
        initial_stomach_content=cfg.initial_stomach_content,
        stomach_decay=max(0.0, float(values["stomach_decay"])),
        light_x=float(values["light_x"]),
        light_brightness=max(0.0, float(values["light_brightness"])),
        initial_x=cfg.initial_x,
        initial_velocity=cfg.initial_velocity,
        inputs=cfg.inputs,
        outputs=cfg.outputs,
    )
    if next_config.x_min >= next_config.x_max:
        raise ValueError("x_min must be smaller than x_max")
    state.x = _clamp(float(values["x"]), next_config.x_min, next_config.x_max)
    state.velocity = float(values["velocity"])
    state.stomach_content = _clamp(float(values["stomach_content"]), 0.0, 10.0)
    state.time = max(0.0, float(values["time"]))
    state.step = _optional_nonnegative_int(values["step"], "step") or 0
    _config = next_config


def GetVisualization(size: tuple[int, int]) -> Image:
    """Return a raster visualization of the current world state."""
    cfg, state = _require_initialized()
    width, height = size
    if width <= 0 or height <= 0:
        raise ValueError("size must contain positive width and height")

    pixels = [[(17, 24, 39) for _ in range(width)] for _ in range(height)]
    mid_y = max(0, min(height - 1, height // 2))
    for x in range(width):
        pixels[mid_y][x] = (75, 85, 99)

    light_x = _world_to_pixel(cfg.light_x, cfg.x_min, cfg.x_max, width)
    _draw_light(pixels, light_x, mid_y)
    agent_x = _world_to_pixel(state.x, cfg.x_min, cfg.x_max, width)
    _draw_agent(pixels, agent_x, mid_y)
    return Image(width=width, height=height, pixels=pixels)


def _parse_config(config_yaml: str) -> WorldConfig:
    raw = yaml.safe_load(config_yaml) if config_yaml.strip() else {}
    if not isinstance(raw, dict):
        raise ValueError("YAML root must be a mapping")

    world = _mapping(raw.get("world", {}), "world")
    simulation = _mapping(raw.get("simulation", {}), "simulation") if "simulation" in raw else world
    bounds = _mapping(world.get("bounds", {}), "world.bounds")
    x_bounds = _number_pair(bounds.get("x", [-10.0, 10.0]), "world.bounds.x")
    if x_bounds[0] >= x_bounds[1]:
        raise ValueError("world.bounds.x minimum must be smaller than maximum")

    objects = raw.get("objects", [])
    agent = _find_object(objects, "agent", required=True)
    light = _find_object(objects, "light", required=True)
    inputs = _parse_inputs(raw.get("inputs", []))
    for required in ("left_motor", "right_motor"):
        if required not in inputs:
            raise ValueError(f"inputs must include {required!r}")
    light_x = float(light["x"]) if "x" in light else _first_number(light.get("position", [5.0]), "light.position")

    return WorldConfig(
        dt=_positive_float(simulation.get("dt", 0.1), "world.dt"),
        input_validation=_validation_mode(simulation.get("input_validation", "strict")),
        max_steps=_optional_nonnegative_int(simulation.get("max_steps"), "world.max_steps"),
        x_min=x_bounds[0],
        x_max=x_bounds[1],
        mass=_positive_float(agent.get("mass", 1.0), "agent.mass"),
        drag=max(0.0, float(world.get("drag", world.get("air_resistance", 0.0)))),
        restitution=_bounded_float(agent.get("restitution", 0.0), "agent.restitution", 0.0, 1.0),
        initial_x=_first_number(agent.get("position", [0.0]), "agent.position"),
        initial_velocity=_first_number(agent.get("velocity", [0.0]), "agent.velocity"),
        initial_stomach_content=_bounded_float(agent.get("stomach_content", 10.0), "agent.stomach_content", 0.0, 10.0),
        stomach_decay=max(0.0, float(agent.get("stomach_decay", 0.02))),
        light_x=light_x,
        light_brightness=max(0.0, float(light.get("brightness", 10.0))),
        inputs=inputs,
        outputs=_parse_outputs(raw.get("outputs", [])),
    )


def _parse_inputs(raw_inputs: Any) -> dict[str, InputMapping]:
    if not isinstance(raw_inputs, list):
        raise ValueError("inputs must be a list")
    mappings: dict[str, InputMapping] = {}
    for idx, raw in enumerate(raw_inputs):
        item = _mapping(raw, f"inputs.{idx}")
        name = str(item.get("name", "")).strip()
        if not name:
            raise ValueError(f"inputs.{idx}.name is required")
        mappings[name] = InputMapping(
            name=name,
            min_value=float(item.get("min", 0.0)),
            max_value=float(item.get("max", 1.0)),
        )
    return mappings


def _parse_outputs(raw_outputs: Any) -> list[OutputMapping]:
    if raw_outputs is None:
        return []
    outputs: list[OutputMapping] = []
    valid_sources = {
        "x",
        "velocity",
        "time",
        "step",
        "left_wall",
        "right_wall",
        "stomach_content",
        "hunger",
        "lightness",
        "light",
    }
    if isinstance(raw_outputs, dict):
        items = [
            {
                "name": name,
                "source": source,
            }
            for name, source in raw_outputs.items()
        ]
    elif isinstance(raw_outputs, list):
        items = raw_outputs
    else:
        raise ValueError("outputs must be a mapping or list")
    for idx, raw in enumerate(items):
        item = _mapping(raw, f"outputs.{idx}")
        name = str(item.get("name", "")).strip()
        source = str(item.get("source", name)).strip()
        if not name:
            raise ValueError(f"outputs.{idx}.name is required")
        if source not in valid_sources:
            raise ValueError(f"outputs.{name} has unknown source {source!r}")
        min_value = None if item.get("min") is None else float(item["min"])
        max_value = None if item.get("max") is None else float(item["max"])
        outputs.append(OutputMapping(name=name, source=source, min_value=min_value, max_value=max_value))
    return outputs


def _validate_inputs(inputs: dict[str, float], cfg: WorldConfig) -> dict[str, float]:
    if not isinstance(inputs, dict):
        raise ValueError("inputs must be a dictionary")

    result: dict[str, float] = {}
    for name in cfg.inputs:
        if name not in inputs:
            if cfg.input_validation == "missing_as_zero":
                value = 0.0
            else:
                raise ValueError(f"missing input: {name}")
        else:
            value = inputs[name]
        if not isinstance(value, (int, float)):
            raise ValueError(f"input {name} must be numeric")
        parsed = float(value)
        if cfg.input_validation == "clamp":
            parsed = _clamp(parsed, 0.0, 1.0)
        elif parsed < 0.0 or parsed > 1.0:
            raise ValueError(f"input {name} must be in range [0.0, 1.0]")
        result[name] = parsed
    return result


def _resolve_bounds(cfg: WorldConfig, state: WorldState) -> None:
    if state.x < cfg.x_min:
        state.x = cfg.x_min
        if state.velocity < 0.0:
            state.velocity = -state.velocity * cfg.restitution
    elif state.x > cfg.x_max:
        state.x = cfg.x_max
        if state.velocity > 0.0:
            state.velocity = -state.velocity * cfg.restitution


def _collect_outputs(cfg: WorldConfig, state: WorldState) -> dict[str, float]:
    if not cfg.outputs:
        return {"x": state.x, "velocity": state.velocity}
    lightness = _lightness_at_agent(cfg, state)
    values = {
        "x": state.x,
        "velocity": state.velocity,
        "stomach_content": state.stomach_content,
        "hunger": 10.0 - state.stomach_content,
        "lightness": lightness,
        "light": lightness,
        "time": state.time,
        "step": float(state.step),
        "left_wall": float(state.x <= cfg.x_min),
        "right_wall": float(state.x >= cfg.x_max),
    }
    output: dict[str, float] = {}
    for mapping in cfg.outputs:
        value = values[mapping.source]
        if mapping.min_value is not None and mapping.max_value is not None:
            value = _normalize(value, mapping.min_value, mapping.max_value)
        output[mapping.name] = float(value)
    return output


def _require_initialized() -> tuple[WorldConfig, WorldState]:
    if _config is None or _state is None:
        raise RuntimeError("Init must be called before using the world")
    return _config, _state


def _lightness_at_agent(cfg: WorldConfig, state: WorldState) -> float:
    distance = abs(state.x - cfg.light_x)
    return cfg.light_brightness / (1.0 + distance)


def _find_object(raw_objects: Any, name: str, *, required: bool) -> dict:
    if not isinstance(raw_objects, list):
        raise ValueError("objects must be a list")
    for raw in raw_objects:
        item = _mapping(raw, "objects[]")
        if item.get("name") == name:
            return item
    if required:
        raise ValueError(f"objects must include {name!r}")
    return {}


def _mapping(value: Any, name: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping")
    return value


def _number_pair(value: Any, name: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{name} must be a two-item list")
    return float(value[0]), float(value[1])


def _first_number(value: Any, name: str) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, list) and value:
        return float(value[0])
    raise ValueError(f"{name} must contain at least one number")


def _positive_float(value: Any, name: str) -> float:
    parsed = float(value)
    if parsed <= 0.0:
        raise ValueError(f"{name} must be > 0")
    return parsed


def _bounded_float(value: Any, name: str, min_value: float, max_value: float) -> float:
    parsed = float(value)
    if parsed < min_value or parsed > max_value:
        raise ValueError(f"{name} must be in range [{min_value}, {max_value}]")
    return parsed


def _optional_nonnegative_int(value: Any, name: str) -> int | None:
    if value in (None, ""):
        return None
    parsed = int(value)
    if parsed < 0:
        raise ValueError(f"{name} must be >= 0")
    return parsed


def _validation_mode(value: Any) -> str:
    mode = str(value)
    allowed = {"strict", "clamp", "missing_as_zero"}
    if mode not in allowed:
        raise ValueError(f"input_validation must be one of {sorted(allowed)}")
    return mode


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def _normalize(value: float, min_value: float, max_value: float) -> float:
    if min_value == max_value:
        raise ValueError("output min and max cannot be equal")
    return (value - min_value) / (max_value - min_value)


def _world_to_pixel(x: float, x_min: float, x_max: float, width: int) -> int:
    if width == 1:
        return 0
    ratio = _clamp((x - x_min) / (x_max - x_min), 0.0, 1.0)
    return int(round(ratio * (width - 1)))


def _draw_agent(pixels: list[list[tuple[int, int, int]]], center_x: int, base_y: int) -> None:
    height = len(pixels)
    width = len(pixels[0]) if height else 0
    color = (34, 197, 94)
    for dy in range(-5, 6):
        y = base_y + dy
        if y < 0 or y >= height:
            continue
        span = max(1, 6 - abs(dy))
        for dx in range(-span, span + 1):
            x = center_x + dx
            if 0 <= x < width:
                pixels[y][x] = color


def _draw_light(pixels: list[list[tuple[int, int, int]]], center_x: int, base_y: int) -> None:
    height = len(pixels)
    width = len(pixels[0]) if height else 0
    center_y = max(0, base_y - 14)
    color = (250, 204, 21)
    for dy in range(-4, 5):
        y = center_y + dy
        if y < 0 or y >= height:
            continue
        span = max(1, 4 - abs(dy))
        for dx in range(-span, span + 1):
            x = center_x + dx
            if 0 <= x < width:
                pixels[y][x] = color


if __name__ == "__main__":
    config = GetDefaultConfig()
    Init(config)
    for _ in range(5):
        print(Process({"left_motor": 0.0, "right_motor": 1.0}))
