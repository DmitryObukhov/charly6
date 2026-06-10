"""
CharlieWorm 2D physical world plugin for charly6.

Bridges Vue 3 2D simulation ↔ charly6 brain via WebSocket on port 8765.

Public API (stable, never change signatures):
    Init, GetDefaultConfig, Validate, Process,
    GetParams, SetParam, SetParams, GetVisualization

Architecture:
    - WebSocket server runs in a daemon thread (asyncio event loop)
    - Process() is called every 100ms by Tkinter main thread
    - sensor_buffer: written by WebSocket thread, read by Process()
    - motor_buffer: written by Process(), read by WebSocket thread
    - wallImpact is peak-held: max value since last Process() call, then reset

Inbound  (Vue → bridge): { "sensors": { lightLux, wallImpactForce, foodSmell, waterSmell } }
Outbound (bridge → Vue): { "actuators": { direction, strength }, "feelings": { pleasure, pain } }
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass
from typing import Any

import yaml

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lightweight Image type (matches linear.py — no PIL dependency)
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Normalisation constants — keep in sync with Vue constants.ts
# ---------------------------------------------------------------------------

LUX_MAX    = 100.0  # lightLux (lux)
IMPACT_MAX = 0.1    # wallImpactForce (newtons)

# ---------------------------------------------------------------------------
# Shared state between WebSocket thread and Process() (Tkinter thread)
# ---------------------------------------------------------------------------

# Written by WebSocket thread, read by Process()
_sensor_buffer: dict[str, float] = {
    'foodSmell':  0.0,
    'waterSmell': 0.0,
    'lightLux':   0.0,
    'wallImpact': 0.0,
}
_peak_impact: float = 0.0

# Written by Process(), read by WebSocket thread
_motor_buffer: dict[str, Any] = {
    'direction': 'move_n',
    'strength':  0.0,
    'pleasure':  0,
    'pain':      0,
}

_ws_thread: threading.Thread | None = None
_ws_loop:   asyncio.AbstractEventLoop | None = None
_clients:   set = set()
_initialized: bool = False

# ---------------------------------------------------------------------------
# Default config
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG = """\
world:
  base: worlds/charlie_worm.py
  host: localhost
  port: 8765
  input_validation: missing_as_zero

objects:
  - name: agent
    shape: circle
    mass: 0.02
    radius: 8.0
    position: [0.0]
    velocity: [0.0]
    restitution: 0.6

inputs:
  - name: move_n
    min: 0.0
    max: 1.0
  - name: move_ne
    min: 0.0
    max: 1.0
  - name: move_e
    min: 0.0
    max: 1.0
  - name: move_se
    min: 0.0
    max: 1.0
  - name: move_s
    min: 0.0
    max: 1.0
  - name: move_sw
    min: 0.0
    max: 1.0
  - name: move_w
    min: 0.0
    max: 1.0
  - name: move_nw
    min: 0.0
    max: 1.0

outputs:
  foodSmell: foodSmell
  waterSmell: waterSmell
  lightLux: lightLux
  wallImpact: wallImpact
"""

_config: dict = {}

# ---------------------------------------------------------------------------
# WebSocket server (runs in daemon thread)
# ---------------------------------------------------------------------------

def _ingest_sensors(raw: dict) -> None:
    global _peak_impact
    _sensor_buffer['foodSmell']  = min(1.0, max(0.0, float(raw.get('foodSmell',  0.0))))
    _sensor_buffer['waterSmell'] = min(1.0, max(0.0, float(raw.get('waterSmell', 0.0))))
    _sensor_buffer['lightLux']   = min(1.0, float(raw.get('lightLux', 0.0)) / LUX_MAX)
    impact = min(1.0, float(raw.get('wallImpactForce', 0.0)) / IMPACT_MAX)
    if impact > _peak_impact:
        _peak_impact = impact
    _sensor_buffer['wallImpact'] = _peak_impact


def _dominant_direction(outputs: dict[str, float]) -> tuple[str, float]:
    if not outputs:
        return 'move_n', 0.0
    best = max(outputs, key=outputs.get)
    return best, round(float(outputs[best]), 4)


async def _ws_handler(websocket) -> None:
    _clients.add(websocket)
    log.info(f'[charlie_worm] Vue connected ({len(_clients)} clients)')
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                _ingest_sensors(data.get('sensors', {}))
            except (json.JSONDecodeError, ValueError):
                pass
    except Exception:
        pass
    finally:
        _clients.discard(websocket)
        log.info(f'[charlie_worm] Vue disconnected ({len(_clients)} clients)')


async def _ws_broadcast_loop() -> None:
    global _clients, _motor_buffer
    """Broadcast motor_buffer to all connected clients every 100ms."""
    while True:
        await asyncio.sleep(0.1)
        if not _clients:
            continue
        msg = json.dumps({
            'actuators': {
                'direction': _motor_buffer['direction'],
                'strength':  _motor_buffer['strength'],
            },
            'feelings': {
                'pleasure': _motor_buffer['pleasure'],
                'pain':     _motor_buffer['pain'],
            },
        })
        dead = set()
        for ws in list(_clients):
            try:
                await ws.send(msg)
            except Exception:
                dead.add(ws)
        _clients -= dead


async def _ws_serve(host: str, port: int) -> None:
    try:
        import websockets
    except ImportError:
        log.error('[charlie_worm] websockets not installed: pip install websockets')
        return

    async with websockets.serve(_ws_handler, host, port):
        log.info(f'[charlie_worm] WebSocket server: ws://{host}:{port}')
        await _ws_broadcast_loop()


def _start_ws_thread(host: str, port: int) -> None:
    global _ws_thread, _ws_loop
    if _ws_thread and _ws_thread.is_alive():
        return
    _ws_loop = asyncio.new_event_loop()

    def run() -> None:
        asyncio.set_event_loop(_ws_loop)
        _ws_loop.run_until_complete(_ws_serve(host, port))

    _ws_thread = threading.Thread(target=run, daemon=True, name='charlie_worm_ws')
    _ws_thread.start()

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def Init(config_yaml: str) -> None:
    global _config, _initialized, _peak_impact
    _config = yaml.safe_load(config_yaml) or {}
    # Handle both flat config and combined brain+world YAML
    # When called from app.py, config is the physical_world section content
    # When called standalone, config is the flat world config
    world_cfg = _config.get('physical_world', _config)
    world = world_cfg.get('world', _config.get('world', {}))
    host = world.get('host', 'localhost')
    port = int(world.get('port', 8765))
    log.info(f'[2d_world] Init called, world config: host={host}, port={port}')

    # Reset buffers
    for k in _sensor_buffer:
        _sensor_buffer[k] = 0.0
    _peak_impact = 0.0
    _motor_buffer.update({'direction': 'move_n', 'strength': 0.0, 'pleasure': 0, 'pain': 0})

    _start_ws_thread(host, port)
    _initialized = True
    log.info(f'[charlie_worm] Init complete, WebSocket on ws://{host}:{port}')


def GetDefaultConfig() -> str:
    return _DEFAULT_CONFIG


def Validate(config_yaml: str) -> tuple[bool, list[str]]:
    try:
        cfg = yaml.safe_load(config_yaml) or {}
        if not isinstance(cfg, dict):
            return False, ['YAML root must be a mapping']
        # Accept both flat and nested under physical_world
        world_cfg = cfg.get('physical_world', cfg)
        world = world_cfg.get('world', {})
        port = world.get('port', 8765)
        if not isinstance(port, int) or not (1024 <= port <= 65535):
            return False, [f'world.port must be integer 1024-65535, got {port!r}']
        return True, []
    except Exception as exc:
        return False, [str(exc)]


def Process(inputs: dict[str, float] | None) -> dict[str, float]:
    """
    Called every 100ms by Tkinter main thread.
    inputs:  8 motor values from brain (move_n/ne/e/se/s/sw/w/nw)
    returns: 4 sensor values to brain (foodSmell/waterSmell/lightLux/wallImpact)
    """
    global _peak_impact

    if not _initialized:
        return {'foodSmell': 0.0, 'waterSmell': 0.0, 'lightLux': 0.0, 'wallImpact': 0.0}

    # Read motor outputs from brain → store in motor_buffer for WebSocket broadcast
    if inputs:
        direction, strength = _dominant_direction(inputs)
        _motor_buffer['direction'] = direction
        _motor_buffer['strength']  = strength

    # Reset wallImpact peak after brain reads it
    result = dict(_sensor_buffer)
    _peak_impact = 0.0
    _sensor_buffer['wallImpact'] = 0.0

    return result


def GetParams() -> dict[str, str]:
    world = _config.get('world', {})
    return {
        'host': str(world.get('host', 'localhost')),
        'port': str(world.get('port', 8765)),
        'connected_clients': str(len(_clients)),
        'x': '0.0',
        'velocity': '0.0',
        'foodSmell':  f"{_sensor_buffer['foodSmell']:.3f}",
        'waterSmell': f"{_sensor_buffer['waterSmell']:.3f}",
        'lightLux':   f"{_sensor_buffer['lightLux']:.3f}",
        'wallImpact': f"{_sensor_buffer['wallImpact']:.3f}",
    }


def SetParam(name: str, value: str) -> None:
    SetParams({name: value})


def SetParams(params: dict[str, str]) -> None:
    world = _config.setdefault('world', {})
    if 'port' in params:
        world['port'] = int(params['port'])
    if 'host' in params:
        world['host'] = params['host']


def GetVisualization(size: tuple[int, int]) -> Image:
    """Return a minimal placeholder image — Vue canvas is the real visualization."""
    width, height = max(1, size[0]), max(1, size[1])
    bg = (17, 24, 39)
    pixels = [[bg for _ in range(width)] for _ in range(height)]

    # Draw connected client count as green dot
    if _clients:
        cx, cy = width // 2, height // 2
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                if dx*dx + dy*dy <= 16:
                    x, y = cx+dx, cy+dy
                    if 0 <= x < width and 0 <= y < height:
                        pixels[y][x] = (34, 197, 94)

    return Image(width=width, height=height, pixels=pixels)
