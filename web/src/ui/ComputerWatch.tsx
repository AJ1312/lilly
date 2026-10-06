import { useApp } from '../store'
import { useLoad } from '../hooks'

interface ComputerState {
  frame_id: string
  app: string | null
  window: string | null
  screenshot: string | null
  elements: { role: string; name: string; description: string }[]
  dom: { url?: string; title?: string } | null
  devbox: { state?: string } | null
}

export function ComputerWatch({ taskId }: { taskId: string }) {
  const tick = useApp((s) => s.tick)
  const state = useLoad<ComputerState>(`/api/computer/${taskId}`, true)
  const frame = state.data
  if (!frame) return null
  return (
    <section className="computer-watch" aria-label="Computer state">
      <div className="row between">
        <strong>Computer</strong>
        <span className="hint">{frame.app ?? 'Desktop'}{frame.window ? ` · ${frame.window}` : ''}</span>
      </div>
      {frame.screenshot && <img src={`/api/computer/${taskId}/screenshot?v=${tick}`} alt={`Current screen in ${frame.app ?? 'the desktop'}`} />}
      <div className="facts">
        <span className="tag">frame {frame.frame_id.slice(-8)}</span>
        <span className="tag">{frame.elements.length} AX elements</span>
        {frame.dom?.url && <span className="tag">DOM {frame.dom.url}</span>}
        {frame.devbox?.state && <span className="tag">DevBox {frame.devbox.state}</span>}
      </div>
    </section>
  )
}
