import { worldState } from '../simulation/worldState'

class CharlySocketService {
  private ws: WebSocket | null = null
  private url = 'ws://127.0.0.1:8765'
  private reconnectTimer: any = null

  connect() {
    if (this.ws?.readyState === WebSocket.OPEN) return

    console.log('[Socket] Попытка подключения...')
    this.ws = new WebSocket(this.url)

    this.ws.onopen = () => {
      console.log('[Socket] ✅ Соединение установлено')
      if (this.reconnectTimer) clearInterval(this.reconnectTimer)
    }

    this.ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      
      // Обновляем состояние ГЛОБАЛЬНО
      if (data.feelings) {
        worldState.feelings.pleasure = data.feelings.pleasure
        worldState.feelings.pain = data.feelings.pain
      }
      if (data.actuators) {
        worldState.actuators.direction = data.actuators.direction ?? 'move_n'
        worldState.actuators.strength  = data.actuators.strength  ?? 0
    }
    }

    this.ws.onclose = () => {
      console.warn('[Socket] ❌ Потеряно соединение. Реконнект через 2 сек...')
      this.reconnectTimer = setTimeout(() => this.connect(), 2000)
    }
  }

send(payload: any) {
  if (this.ws?.readyState === WebSocket.OPEN) {
    this.ws.send(JSON.stringify(payload))
  }
  }
}

export const charlySocket = new CharlySocketService()