import { useEffect, useState } from 'react'
import { useLoad } from '../hooks'
import { LIVE_STATES, type Agent, type Task } from '../types'
import { Pet, type PetState } from './Pet'

const DONE_SHOW_S = 8 // how long the pet keeps showing how the last task ended

const CAPTION: Record<PetState, string> = {
  idle: 'Ready when you are',
  thinking: 'Working on it…',
  waiting: 'Needs your OK',
  done: 'All done',
  error: 'Hit a snag',
}

/** The pet of the agent that is working right now, showing what is happening. Click to see what needs you. */
export function Companion({ go }: { go: (hash: string) => void }) {
  const recent = useLoad<{ tasks: Task[] }>('/api/tasks?limit=5', true)
  const agents = useLoad<{ agents: Agent[] }>('/api/agents')
  const [now, setNow] = useState(() => Date.now() / 1000)
  const finishedAt = recent.data?.tasks[0]?.finished_at ?? null
  useEffect(() => {
    if (finishedAt === null) return
    // One timeout, for the rest of the window in which this task counts as just ended.
    const left = Math.max(0, DONE_SHOW_S - (Date.now() / 1000 - finishedAt))
    const id = setTimeout(() => setNow(Date.now() / 1000), left * 1000)
    return () => clearTimeout(id)
  }, [finishedAt])

  const tasks = recent.data?.tasks ?? []
  const waiting = tasks.find((t) => t.state === 'WAITING_APPROVAL')
  const busy = tasks.find((t) => LIVE_STATES.includes(t.state))
  const last = tasks[0]
  const justEnded = last && last.finished_at !== null && now - last.finished_at < DONE_SHOW_S ? last : undefined

  let state: PetState = 'idle'
  let subject: Task | undefined
  if (waiting) { state = 'waiting'; subject = waiting }
  else if (busy) { state = 'thinking'; subject = busy }
  else if (justEnded) {
    state = justEnded.state === 'DONE' ? 'done' : justEnded.state === 'FAILED' || justEnded.state === 'EXPIRED' ? 'error' : 'idle'
    subject = justEnded
  }
  const agent = agents.data?.agents.find((a) => a.id === subject?.agent_id)

  return (
    <button type="button" className="companion" onClick={() => go(waiting ? '/approvals' : '/talk')} aria-label={`${CAPTION[state]}. Open ${waiting ? 'approvals' : 'talk'}`}>
      <Pet id={agent?.pet ?? 'lily'} look={agent?.look} state={state} size={64} />
      <span className="companion-text" aria-live="polite">{CAPTION[state]}</span>
    </button>
  )
}
