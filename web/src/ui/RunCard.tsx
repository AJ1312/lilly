import { BrowserWatch } from './BrowserWatch'
import { useState } from 'react'
import { api } from '../api'
import { useLoad } from '../hooks'
import { useApp } from '../store'
import { LIVE_STATES, type PlanStep, type Step, type TaskDetail, type Verdict } from '../types'
import { ApprovalCard } from './ApprovalCard'
import { TOOL_LABEL } from './format'
import { Icon } from './Icon'
import { Button, ErrorNote, Pill, StatePill } from './kit'

const VERDICT: Record<Verdict, { text: string; tone: 'ok' | 'warn' | 'bad' }> = {
  ALLOW: { text: 'runs on its own', tone: 'ok' },
  NEEDS_APPROVAL: { text: 'asks you first', tone: 'warn' },
  DENY: { text: 'blocked by policy', tone: 'bad' },
}

/** The plan entry for a step. A step of a second attempt is stored as "s1.2"; the plan names it "s1". */
const planOf = (plan: PlanStep[], stepId: string): PlanStep | undefined => plan.find((p) => p.id === stepId.replace(/\.\d+$/, ''))

export function StepNode({ step, plan }: { step: Step; plan?: PlanStep }) {
  const [open, setOpen] = useState(false)
  const label = TOOL_LABEL[step.tool] ?? step.tool
  const tone = step.status === 'done' ? 'ok' : step.status === 'failed' ? 'bad' : step.status === 'waiting' ? 'warn' : step.status === 'skipped' ? 'mute' : 'live'
  return (
    <li className={`stem-node stem-${tone}`}>
      <span className="leaf" aria-hidden="true" />
      <button type="button" className="stem-head" aria-expanded={open} onClick={() => setOpen(!open)}>
        <strong>{label}</strong>
        <span className="stem-status">{step.status}{step.untrusted ? ' · from the web' : ''}</span>
        <Icon name={open ? 'up' : 'down'} size={15} />
      </button>
      {plan && (
        <p className="stem-plan">
          {plan.expect && <span>{plan.expect}</span>}
          {plan.deps.length > 0 && <span>after {plan.deps.join(', ')}</span>}
          <Pill tone={VERDICT[plan.verdict].tone}>{VERDICT[plan.verdict].text}</Pill>
        </p>
      )}
      {step.error && <p className="stem-error">{step.error}</p>}
      {open && (
        <div className="stem-body">
          <p className="mini-title">What it was asked</p>
          <pre>{JSON.stringify(step.args, null, 2)}</pre>
          {step.output && (
            <>
              <p className="mini-title">What came back ({step.label.toLowerCase()})</p>
              <pre>{step.output.slice(0, 4000)}{step.output.length > 4000 ? '\n…' : ''}</pre>
            </>
          )}
        </div>
      )}
    </li>
  )
}

/** The reply as it is being written. Only shown while the task runs; the finished answer replaces it. */
function Writing({ taskId }: { taskId: string }) {
  const text = useApp((s) => s.streams[taskId])
  if (!text) return null
  return (
    <>
      <span className="sr-only" role="status">Writing the reply</span>
      <p className="run-writing" aria-hidden="true">{text}</p>
    </>
  )
}

/** One task inside a conversation: its progress, any approval it is waiting on, and how it did the work. */
export function RunCard({ taskId, initialState }: { taskId: string; initialState: string }) {
  const live = LIVE_STATES.includes(initialState as never)
  const detail = useLoad<TaskDetail>(`/api/tasks/${taskId}`, live)
  const bump = useApp((s) => s.bump)
  const [error, setError] = useState<string | null>(null)
  const d = detail.data
  if (!d) return <ErrorNote text={detail.error} />
  const { task, steps, approvals, plan_steps: plan } = d
  const isLive = LIVE_STATES.includes(task.state)
  if (task.state === 'DONE' && steps.length === 0 && approvals.length === 0) return null // a plain answer needs no card

  const stop = async () => {
    try {
      await api.post(`/api/tasks/${taskId}/cancel`)
      bump()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not stop')
    }
  }

  return (
    <section className="run" aria-label="Task progress">
      <header className="run-head">
        <StatePill state={task.state} />
        {task.skill && <span className="tag">skill: {task.skill}</span>}
        {task.label !== 'PUBLIC' && <span className="tag tag-private"><Icon name="lock" size={12} /> used private data</span>}
        {task.tainted && <span className="tag tag-warn">read web content</span>}
        {isLive && <Button small icon="stop" onClick={() => void stop()}>Stop</Button>}
      </header>
      {task.plan?.reasoning && isLive && <p className="run-reasoning">{task.plan.reasoning}</p>}
      {approvals.map((a) => <ApprovalCard key={a.id} approval={a} />)}
      {task.error && !isLive && <p className="run-error" role="alert">{task.error}</p>}
      {steps.length > 0 && (
        <details open={isLive} className="run-steps">
          <summary>{steps.length} step{steps.length === 1 ? '' : 's'}</summary>
          <ol className="stem">{steps.map((s) => <StepNode key={s.id} step={s} plan={planOf(plan, s.id)} />)}</ol>
        </details>
      )}
      {isLive && <Writing taskId={taskId} />}
      {isLive && <BrowserWatch taskId={taskId} />}
      <ErrorNote text={error} />
    </section>
  )
}
