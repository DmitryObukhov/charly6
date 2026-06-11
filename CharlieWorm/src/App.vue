<script setup lang="ts">
import { onMounted } from 'vue' 
import { charlySocket } from './services/socketService'
import SimulationCanvas from './components/SimulationCanvas.vue'
import SensorPanel from './components/SensorPanel.vue'
import EmotionChart from './components/EmotionChart.vue'
import { FIELD_HEIGHT } from './simulation/constants'

const layoutStyle = { '--field-height': `${FIELD_HEIGHT}px` }
onMounted(() => {
  charlySocket.connect() // Запускаем сокет один раз
})
</script>

<template>
  <div class="app-container" :style="layoutStyle">
    <h1>Charlie Worm Simulation</h1>
    <div class="outer-layout">
      <!-- существующая конструкция — не трогаем -->
      <div class="main-layout">
        <SimulationCanvas />
        <SensorPanel />
      </div>
      <!-- диаграмма справа, отдельно -->
      <EmotionChart />
    </div>
  </div>
</template>

<style scoped>
.app-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 20px;
}

h1 {
  margin-bottom: 20px;
  color: #333;
}

.outer-layout {
  display: flex;
  flex-direction: row;
  align-items: flex-start;
  gap: 16px;
}

.main-layout {
  display: flex;
  flex-direction: row;
  align-items: stretch;
  height: var(--field-height);
  min-height: var(--field-height);
}

.main-layout > :first-child {
  flex-shrink: 0;
}

.main-layout > :last-child {
  flex-shrink: 0;
  min-height: 0;
}
</style>