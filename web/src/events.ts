import { useAppStore } from './store'
import { api } from './api'

export interface LiveEventPayload {
  task_id?: string
  step_id?: string
  tool?: string
  status?: string
  state?: string
  outcome?: string
  reason?: string
  thought?: string
  layer?: string
  message?: string
  actor?: string
  ts?: number
  [key: string]: unknown
}

export interface LiveEvent {
  event: string
  data: LiveEventPayload
}

class EventBus {
  private source: EventSource | null = null
  private retryTimeout = 1000
  private maxTimeout = 15000
  private stopped = false

  public start() {
    this.stopped = false
    this.connect()
  }

  public stop() {
    this.stopped = true
    if (this.source) {
      this.source.close()
      this.source = null
    }
    useAppStore.getState().setLiveConnected(false)
  }

  private connect() {
    if (this.stopped) return

    try {
      this.source = new EventSource('/api/events', { withCredentials: true })

      this.source.onopen = () => {
        useAppStore.getState().setLiveConnected(true)
        this.retryTimeout = 1000
        void this.refreshCounts()
      }

      this.source.onmessage = (e) => {
        try {
          const raw = JSON.parse(e.data)
          this.handleEvent(raw.event || 'message', raw.data || raw)
        } catch {
          // ignore malformed ping
        }
      }

      this.source.onerror = () => {
        useAppStore.getState().setLiveConnected(false)
        if (this.source) {
          this.source.close()
          this.source = null
        }
        if (!this.stopped) {
          setTimeout(() => this.connect(), this.retryTimeout)
          this.retryTimeout = Math.min(this.retryTimeout * 1.5, this.maxTimeout)
        }
      }
    } catch {
      useAppStore.getState().setLiveConnected(false)
    }
  }

  private handleEvent(type: string, data: LiveEventPayload) {
    const store = useAppStore.getState()

    // Dispatch global store bump so current views refresh their data
    store.bump()

    if (type === 'approval_needed') {
      store.toast(`Approval needed: ${data.tool || 'sensitive step'}`, 'warn')
      void this.refreshCounts()
    } else if (type === 'approval_decided') {
      void this.refreshCounts()
    } else if (type === 'task_created') {
      void this.refreshCounts()
    } else if (type === 'state' && data.state === 'DONE') {
      if (data.outcome === 'success') {
        store.toast('Task completed successfully', 'good')
      } else if (data.outcome === 'blocked' || data.outcome === 'partial') {
        store.toast(`Task finished: ${data.outcome}`, 'warn')
      }
      void this.refreshCounts()
    } else if (type === 'state' && data.state === 'FAILED') {
      store.toast(`Task failed: ${data.reason || 'error'}`, 'bad')
      void this.refreshCounts()
    }
  }

  public async refreshCounts() {
    try {
      const approvals = await api.get<{ approvals: unknown[] }>('/api/approvals')
      useAppStore.getState().setPendingApprovals(approvals.approvals?.length || 0)

      const tasks = await api.get<{ tasks: Array<{ state: string }> }>('/api/tasks?limit=50')
      const running = tasks.tasks.filter((t) =>
        ['PENDING', 'PLANNING', 'RUNNING', 'WAITING_APPROVAL', 'VERIFYING'].includes(t.state)
      ).length
      useAppStore.getState().setRunningTasks(running)
    } catch {
      // offline or unauth
    }
  }
}

export const liveEvents = new EventBus()
