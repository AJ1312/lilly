import { useCallback, useState } from 'react'
import { useInterval, useLoad } from '../hooks'
import { Button } from './kit'

const EVERY_MS = 1500

/** A read-only picture of the agent's browser tab. Pictures are asked for only while this is open and the tab is visible. */
export function BrowserWatch({ taskId }: { taskId: string }) {
  const open = useLoad<{ tasks: { task_id: string; host: string }[] }>('/api/live', true)
  const [watching, setWatching] = useState(false)
  const [stamp, setStamp] = useState(0)
  const [failed, setFailed] = useState(false)
  const mine = open.data?.tasks.find((t) => t.task_id === taskId)
  useInterval(useCallback(() => { if (watching) setStamp((n) => n + 1) }, [watching]), EVERY_MS)
  if (!mine) return null
  return (
    <div className="watch">
      <Button small onClick={() => { setFailed(false); setWatching((w) => !w) }}>{watching ? 'Stop watching' : 'Watch browser'}</Button>
      {watching && (
        <figure className="watch-frame">
          {failed && <p className="hint">Nothing to show right now.</p>}
          <img hidden={failed} src={`/api/live/${encodeURIComponent(taskId)}/frame?n=${stamp}`} alt={`The agent's browser tab${mine.host ? ` on ${mine.host}` : ''} (read-only)`}
            onLoad={() => setFailed(false)} onError={() => setFailed(true)} />
          <figcaption className="hint">Read-only view of {mine.host || 'the page'}. You cannot click in it.</figcaption>
        </figure>
      )}
    </div>
  )
}
