# Charlie Worm — 2D Physical World Simulator

## 1. Project Overview

This project is a **2D physical world simulator** for **Charlie** — an AI worm agent driven by a neural network.

- **Frontend only:** Vue 3 + Vite + TypeScript + Konva.js (canvas rendering).
- **Backend** connects via WebSocket (not yet implemented). The frontend exposes reactive state for an external agent to read sensors and write actuator commands.

---

## 2. Quick Start

```bash
npm install
npm run dev
```

---

## 3. Project Structure

| Path | Description |
|------|-------------|
| `src/components/SimulationCanvas.vue` | Main canvas: physics, collisions, light/water/food, sensors, worm and obstacle rendering |
| `src/components/SensorPanel.vue` | Real-time sensor display (light, wall impact, water smell, food smell) |
| `src/simulation/worldState.ts` | Shared reactive state between canvas and panel (and future backend) |
| `src/simulation/constants.ts` | Field dimensions, wall thickness |
| `src/simulation/physics/collision.ts` | Circle/rect collision, circle/circle, Liang–Barsky ray casting for light blocking |

---

## 4. Sensor Data (`worldState`)

All sensor values are written by the simulation each frame and can be read by the panel or backend.

| Field | Description |
|-------|-------------|
| `worldState.sensors.lightLux` | Illuminance at the worm head (lux). Inverse-square from the lamp; set to 0 when a wall blocks line of sight. |
| `worldState.sensors.wallImpactForce` | Magnitude of impact force (N) when the worm hits a wall or the lamp. |
| `worldState.sensors.waterSmell` | Water smell intensity at the worm head, in [0, 1]. Falls off with distance; reduced by internal walls. |
| `worldState.sensors.foodSmell` | Food smell intensity at the worm head, in [0, 1]. Same falloff and wall attenuation as water. |
| `worldState.physics.wormVelocity` | Worm speed in m/s (magnitude). Position (x, y) is **not** exposed to the agent. |

---
## 5. Connecting External Agent (Backend)

- **Backend is connected** via `bridge.py` (WebSocket on port 8765).
- Worm movement is controlled by Charly's real motor neuron outputs (`move_up` → `actuators.left`, `move_down` → `actuators.right`).
- Emotion chart shows Charly's real internal state: `esp` (pleasure) and `esn` (pain) — not computed from sensors.
- `worldState.feelings.pleasure` and `worldState.feelings.pain` are written by the bridge, not the frontend.

### What the frontend sends to bridge (every frame):
```json
{
  "sensors": {
    "lightLux": 355.5,
    "wallImpactForce": 0,
    "waterSmell": 0.33,
    "foodSmell": 0.55
  }
}
```

### What the bridge sends back (from real Charly output):
```json
{
  "actuators": { "left": 0.83, "right": 0.85 },
  "feelings":  { "pleasure": 0.12, "pain": 0.04 }
}
```

### worldState fields written by bridge:
| Field | Source |
|-------|--------|
| `worldState.actuators.left` | `move_up` neuron zone firing rate |
| `worldState.actuators.right` | `move_down` neuron zone firing rate |
| `worldState.feelings.pleasure` | Charly's `esp` (cumulative positive emotional state) |
| `worldState.feelings.pain` | Charly's `esn` (cumulative negative emotional state) |


## 6. Git Branches

| Branch | Description |
|--------|-------------|
| `main` | Stable |
| `sensor-panel` | Head only + sensor panel |
| `food-water` | Food and water sources ← **current** |
