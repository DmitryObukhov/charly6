import { reactive } from 'vue'

/**
 * Shared reactive world state for simulation and AI integration.
 * All values represent physical quantities (SI where applicable).
 */
export const worldState = reactive({
  sensors: {
    /** Illuminance at worm head in lux (inverse square law from point source) */
    lightLux: 0,
    /** Magnitude of wall impact force in newtons (impulse approximation) */
    wallImpactForce: 0,
    /** Dimensionless water smell intensity at worm head in [0,1] */
    waterSmell: 0,
    /** Dimensionless food smell intensity at worm head in [0,1] */
    foodSmell: 0,
  },
  physics: {
    /** Worm speed in m/s (magnitude of velocity). Position (x,y) is not exposed to the agent. */
    wormVelocity: 0,
  },
  actuators: {
    direction: 'move_n' as string,
    strength: 0,
  },
  simulation: {
    /** Increments every frame. Used for backend sync. */
    stepCount: 0,
    /** Pause/resume simulation. */
    isRunning: true,
  },
  
  feelings: {         
    pleasure: 0,       // ← приходит от реального esp Чарли
    pain: 0,           // ← приходит от реального esn Чарли
  },
})
