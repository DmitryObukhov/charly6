<template>
  <div class="emotion-wrap">
    <div style="position: relative; height: 340px;">
      <canvas ref="canvasRef" />
    </div>
    <div class="emotion-values">
      <div style="text-align: right">
        <div class="label pain-label">PAIN</div>
        <div class="value pain-val">{{ worldState.feelings.pain.toLocaleString() }}</div>
      </div>
      <div>
        <div class="label pleasure-label">PLEASURE</div>
        <div class="value pleasure-val">{{ worldState.feelings.pleasure.toLocaleString() }}</div>
      </div>
    </div>
    <div class="upd">updates: {{ count }}</div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { Chart, ScatterController, LinearScale, PointElement, LineElement, Tooltip } from 'chart.js'
import { worldState } from '../simulation/worldState'

Chart.register(ScatterController, LinearScale, PointElement, LineElement, Tooltip)

const canvasRef = ref<HTMLCanvasElement>()
const count = ref(0)
let chart: Chart | null = null
const MAX_POINTS = 10
const data: { x: number; y: number }[] = []

onMounted(() => {
  chart = new Chart(canvasRef.value!, {
    type: 'scatter',
    data: {
      datasets: [{
        data,
        backgroundColor: (ctx: any) => {
          const i = ctx.dataIndex
          const total = ctx.dataset.data.length
          if (i === total - 1) return '#ffffff'
          const alpha = 0.05 + 0.45 * (i / Math.max(total - 1, 1))
          return `rgba(0,255,136,${alpha.toFixed(2)})`
        },
        pointRadius: (ctx: any) => {
          const i = ctx.dataIndex
          const total = ctx.dataset.data.length
          if (i === total - 1) return 8
          return 1 + 2 * (i / Math.max(total - 1, 1))
        },
        showLine: true,
        borderColor: (ctx: any) => {
          const i = ctx.dataIndex
          const total = ctx.dataset.data.length
          const alpha = 0.05 + 0.5 * (i / Math.max(total - 1, 1))
          return `rgba(0,255,136,${alpha.toFixed(2)})`
        },
        borderWidth: 1,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: { legend: { display: false } },
      scales: {
        x: {
          min: -200000,
          max: 0,
          position: 'bottom',
          title: {
            display: true,
            text: 'pain',
            color: '#ff4444',
            font: { family: 'Courier New', size: 11 }
          },
          ticks: {
            color: '#4a8a4a',
            maxTicksLimit: 6,
            callback: (v) => Number(v).toLocaleString()
          },
          grid: { color: 'rgba(0,255,136,0.15)' },
          border: { color: '#1a5a1a', width: 1 },
        },
        y: {
          min: 0,
          max: 200000,
          position: 'right',
          title: {
            display: true,
            text: 'pleasure',
            color: '#00ff88',
            font: { family: 'Courier New', size: 11 }
          },
          ticks: {
            color: '#4a8a4a',
            maxTicksLimit: 6,
            callback: (v) => Number(v).toLocaleString()
          },
          grid: { color: 'rgba(0,255,136,0.15)' },
          border: { color: '#1a5a1a', width: 1 },
        }
      }
    }
  })
})

onUnmounted(() => chart?.destroy())

watch([() => worldState.feelings.pleasure, () => worldState.feelings.pain], ([pleasure, pain]) => {
  data.push({
    x: Math.max(-200000, Math.min(0, pain)),
    y: Math.max(0, Math.min(200000, pleasure)),
  })
  if (data.length > MAX_POINTS) data.shift()
  chart?.update('none')
  count.value++
})
</script>

<style scoped>
.emotion-wrap {
  background: #050a05;
  border: 1px solid #1a3a1a;
  border-radius: 8px;
  padding: 16px;
  width: 360px;
  font-family: 'Courier New', monospace;
}
.emotion-values { display: flex; justify-content: space-between; margin-top: 12px; }
.label { font-size: 11px; margin-bottom: 2px; }
.pleasure-label { color: #4a8a4a; }
.pain-label { color: #8a4a4a; }
.value { font-size: 22px; font-weight: 700; }
.pleasure-val { color: #00ff88; }
.pain-val { color: #ff4444; }
.upd { color: #2a5a2a; font-size: 11px; margin-top: 8px; }
</style>