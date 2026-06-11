<template>
  <aside class="sensor-panel">
    <h2 class="title">Charlie's Senses</h2>

    <section class="sensor-section">
      <label class="sensor-label">🔆 Light (illuminance)</label>
      <div class="progress-wrap">
        <div
          class="progress-bar light-bar"
          :style="lightBarStyle"
        />
      </div>
      <span class="sensor-value">{{ formatLux(worldState.sensors.lightLux) }}</span>
    </section>


    <section class="sensor-section">
      <label class="sensor-label">💥 Wall impact force</label>
      <div class="progress-wrap">
        <div
          class="progress-bar wall-bar"
          :style="forceBarStyle"
        />
      </div>
      <span class="sensor-value">{{ formatForce(worldState.sensors.wallImpactForce) }}</span>
    </section>
 <div class="sensor-divider"></div>
 

    <section class="sensor-section">
      <label class="sensor-label">🍎 Food smell</label>
      <div class="progress-wrap">
        <div
          class="progress-bar food-bar"
          :style="foodBarStyle"
        />
      </div>
      <span class="sensor-value">{{ formatFood(worldState.sensors.foodSmell) }}</span>
    </section>

    <section class="sensor-section">
      <label class="sensor-label">💧 Water smell</label>
      <div class="progress-wrap">
        <div
          class="progress-bar water-bar"
          :style="waterBarStyle"
        />
      </div>
      <span class="sensor-value">{{ formatWater(worldState.sensors.waterSmell) }}</span>
    </section>
  </aside>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { worldState } from '../simulation/worldState'

/** Display scale for light bar (lux). Bar fill is min(1, lightLux / MAX). */
const LIGHT_BAR_MAX_LUX = 500

/** Display scale for force bar (N). Bar fill is min(1, force / MAX). */
const FORCE_BAR_MAX_N = 1

/** Water smell is already normalized [0,1]; bar is just 0–100%. */
const WATER_BAR_MAX = 1

const FOOD_MAX_MGM3 = 50
/** Food smell is already normalized [0,1]; bar is 0–100%. */
const FOOD_BAR_MAX = 1

const lightBarStyle = computed(() => ({
  width: `${Math.min(1, worldState.sensors.lightLux / LIGHT_BAR_MAX_LUX) * 100}%`,
}))

const forceBarStyle = computed(() => ({
  width: `${Math.min(1, worldState.sensors.wallImpactForce / FORCE_BAR_MAX_N) * 100}%`,
}))

const waterBarStyle = computed(() => ({
  width: `${Math.min(1, worldState.sensors.waterSmell / WATER_BAR_MAX) * 100}%`,
}))

const foodBarStyle = computed(() => ({
  width: `${Math.min(1, worldState.sensors.foodSmell / FOOD_BAR_MAX) * 100}%`,
}))


function formatLux(lux: number): string {
  if (lux >= 1000) return `${(lux / 1000).toFixed(2)} klux`
  return `${lux.toFixed(1)} lux`
}

function formatForce(force: number): string {
  if (force < 0.001) return '0 N'
  if (force >= 1) return `${force.toFixed(2)} N`
  return `${(force * 1000).toFixed(1)} mN`
}

function formatWater(value: number): string {
  const clamped = Math.max(0, Math.min(1, value))
  return `${(clamped * 10).toFixed(1)} mg/L`
}

function formatFood(value: number): string {
  const clamped = Math.max(0, Math.min(1, value))
  const mgPerM3 = clamped * FOOD_MAX_MGM3
  return `${mgPerM3.toFixed(1)} mg/m³`
}
</script>

<style scoped>
.sensor-panel {
  width: 250px;
  height: 100%;
  min-height: 0;
  background:#8D6E63;
  padding: 1rem 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  overflow-y: auto;
  box-sizing: border-box;
  position: relative;
  overflow: hidden;
}

.sensor-panel > * {
  position: relative;
  z-index: 1;
}
.sensor-panel::before {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 220px;

background-color:#1a0a06;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='36'%3E%3Crect x='2.5' y='2.5' width='18' height='10' fill='%238D6E63'/%3E%3Crect x='2.5' y='14.5' width='18' height='10' fill='%238D6E63'/%3E%3Crect x='-8.5' y='26.5' width='18' height='10' fill='%238D6E63'/%3E%3Crect x='12' y='26' width='18' height='10' fill='%238D6E63'/%3E%3C/svg%3E");

mask-image: radial-gradient(ellipse 100% 100% at 50% 0%, transparent 50%, black 100%);
-webkit-mask-image: radial-gradient(ellipse 100% 100% at 50% 0%, transparent 50%, black 100%);
  pointer-events: none;
  z-index: 0;
}

.title {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
  color: #eaeaea;
}

.sensor-section {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.sensor-label {
  font-size: 0.85rem;
  color: #b0b0b0;
}

.progress-wrap {
  height: 1.25rem;
  background: #0d0d14;
  border-radius: 4px;
  overflow: hidden;
}

.progress-bar {
  height: 100%;
  border-radius: 4px;
  transition: width 0.1s ease;
}

.light-bar {
  background: linear-gradient(to right, #1a1a00, #ffff00);
}

.wall-bar {
  background: linear-gradient(to right, #1a0000, #c62828);
}

.water-bar {
  background: linear-gradient(to right, #001a2e, #29B6F6);
}

.food-bar {
  background: linear-gradient(to right, #330000, #FF5722);
}

.sensor-value {
  font-size: 0.9rem;
  color: #ddd;
}

.sensor-divider {
  height: 1px;
  margin: 0.25rem 0.5rem;
  background: rgba(0, 0, 0, 0.35);
  border-radius: 999px;
}

.sensor-group-label {
  margin: 0.1rem 0.5rem 0.35rem;
  font-size: 0.75rem;
  font-weight: 500;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: #b0b0b0;
}

.placeholder-bar {
  padding: 0.5rem 0.6rem;
  background: #2a2a3e;
  border-radius: 4px;
  font-size: 0.8rem;
  color: #666;
}
</style>
