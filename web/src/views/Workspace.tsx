import { useState } from 'react'
import { api, errorText } from '../api'
import { useLoad } from '../hooks'
import { useApp } from '../store'
import {
  APPROVAL_MODES,
  EXECUTION_TARGETS,
  LIVE_STATES,
  REQUEST_INTENTS,
  type ExecutionTarget,
  type RequestIntent,
  type Settings,
  type Task,
  type TaskDetail,
} from '../types'
import { Icon } from '../ui/Icon'
import { Markdown } from '../ui/Markdown'
import { RunCard } from '../ui/RunCard'
import { Button, ErrorNote, OutcomePill, Segmented, StatePill, TargetPill } from '../ui/kit'
import { ago } from '../ui/format'

const statusLabel: Record<string, string> = {
  PENDING: 'Queued', PLANNING: 'Planning', RUNNING: 'Working', WAITING_APPROVAL: 'Waiting',
  VERIFYING: 'Verifying', DONE: 'Complete', FAILED: 'Failed', CANCELLED: 'Stopped', EXPIRED: 'Expired',
}

function TaskComposer({ onCreated, conversationId = null }: { onCreated: (task: Task) => void; conversationId?: string | null }) {
  const [goal, setGoal] = useState('')
  const [intent, setIntent] = useState<RequestIntent>('AUTO')
  const [target, setTarget] = useState<ExecutionTarget>('host')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [approvalBusy, setApprovalBusy] = useState(false)
  const [approvalError, setApprovalError] = useState<string | null>(null)
  const settings = useLoad<{ settings: Settings; problems: string[] }>('/api/settings')
  const approvalMode = settings.data?.settings.approval_mode ?? 'MANUAL'

  const submit = async () => {
    if (!goal.trim() || busy) return
    setBusy(true); setError(null)
    try {
      const result = await api.post<{ task: Task }>('/api/tasks', {
        goal: goal.trim(),
        conversation_id: conversationId || undefined,
        intent: intent === 'AUTO' ? undefined : intent,
        target,
      })
      setGoal(''); onCreated(result.task)
    } catch (err) { setError(errorText(err)) } finally { setBusy(false) }
  }

  const changeApprovalMode = async (mode: Settings['approval_mode']) => {
    if (!settings.data || mode === approvalMode || approvalBusy) return
    setApprovalBusy(true); setApprovalError(null)
    try {
      settings.replace(await api.put('/api/settings', { ...settings.data.settings, approval_mode: mode }))
    } catch (err) { setApprovalError(errorText(err)) } finally { setApprovalBusy(false) }
  }

  return (
    <section className="task-composer" aria-label={conversationId ? 'Continue task' : 'New task'}>
      <textarea
        value={goal}
        rows={3}
        maxLength={4000}
        placeholder={conversationId ? 'Continue this task with more context…' : 'What should Lilly get done?'}
        aria-label="Task description"
        onChange={(event) => setGoal(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
            event.preventDefault(); void submit()
          }
        }}
      />
      <div className="task-composer-target">
        <span className="label">Target</span>
        <Segmented
          label="Execution target"
          value={target}
          onChange={(value) => setTarget(value as ExecutionTarget)}
          options={EXECUTION_TARGETS.map((t) => ({ value: t.value, label: t.label, hint: t.hint }))}
        />
        <span className="hint">{EXECUTION_TARGETS.find((t) => t.value === target)?.hint}</span>
      </div>
      <div className="task-composer-approval">
        <span className="label">Approval (global default)</span>
        <Segmented
          label="Approval mode for tasks"
          value={approvalMode}
          onChange={(value) => void changeApprovalMode(value)}
          options={APPROVAL_MODES.map((mode) => ({ value: mode.value, label: mode.name, hint: mode.blurb }))}
        />
        <span className="hint">{APPROVAL_MODES.find((mode) => mode.value === approvalMode)?.blurb}</span>
      </div>
      <div className="task-composer-mode">
        <label htmlFor="workspace-intent">Request mode</label>
        <select id="workspace-intent" aria-label="Request mode" value={intent} onChange={(event) => setIntent(event.target.value as RequestIntent)}>
          {REQUEST_INTENTS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
      </div>
      <ErrorNote text={approvalError} />
      <div className="task-composer-footer">
        <span className="hint">Lilly will plan, act, verify, and keep you posted.</span>
        <Button kind="primary" icon="arrow-right" busy={busy} disabled={!goal.trim()} onClick={() => void submit()}>
          {conversationId ? 'Continue task' : 'Start task'}
        </Button>
      </div>
      <ErrorNote text={error} />
    </section>
  )
}

function TaskRow({ task, selected, onSelect }: { task: Task; selected: boolean; onSelect: () => void }) {
  const isTerminal = !LIVE_STATES.includes(task.state)
  return (
    <button type="button" className={`workspace-task${selected ? ' selected' : ''}`} onClick={onSelect}>
      <span className="task-row-icon">
        <Icon name={LIVE_STATES.includes(task.state) ? 'loader' : task.state === 'DONE' ? 'check' : 'activity'} size={15} />
      </span>
      <span className="task-row-copy">
        <strong>{task.goal.slice(0, 90)}</strong>
        <small>{statusLabel[task.state] ?? task.state} · {ago(task.updated_at)}</small>
      </span>
      <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
        <TargetPill target={task.target} />
        {isTerminal && task.outcome && <OutcomePill outcome={task.outcome} reason={task.outcome_reason} />}
        <StatePill state={task.state} />
      </div>
    </button>
  )
}

function ActiveTask({ task, onBack, onContinue }: { task: Task; onBack: () => void; onContinue: (task: Task) => void }) {
  const detail = useLoad<TaskDetail>(`/api/tasks/${task.id}`, true)
  const d = detail.data
  if (!d) return <main className="workspace-main"><ErrorNote text={detail.error} /></main>
  const reply = d.task.answer

  const timelineCopy = () => {
    if (d.task.state !== 'DONE') {
      if (d.task.state === 'FAILED') return d.task.error || 'The task failed.'
      if (d.task.state === 'CANCELLED') return 'The task was stopped.'
      if (d.task.state === 'WAITING_APPROVAL') return 'Awaiting your approval.'
      return 'Lilly is working through the task and will verify the result.'
    }
    if (d.task.outcome === 'success') return 'Lilly finished and verified this task.'
    if (d.task.outcome === 'partial') return 'Lilly partially completed this task; some requested actions were unmet.'
    if (d.task.outcome === 'needs_user') return 'Lilly paused for your input or choice to continue.'
    if (d.task.outcome === 'blocked') return 'This task was blocked by platform capability or policy.'
    return 'Lilly finished the task (result not independently verified).'
  }

  return (
    <main className="workspace-main">
      <header className="workspace-task-head">
        <button type="button" className="workspace-back" onClick={onBack}>
          <Icon name="chevron" size={15} /> All tasks
        </button>
        <div className="workspace-title-line">
          <div><p className="eyebrow">Task</p><h1>{d.task.goal}</h1></div>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <TargetPill target={d.task.target} />
            {d.task.outcome && <OutcomePill outcome={d.task.outcome} reason={d.task.outcome_reason} />}
            <StatePill state={d.task.state} />
          </div>
        </div>
        <div className="workspace-meta">
          <span>{statusLabel[d.task.state] ?? d.task.state}</span>
          <span>Target: {d.task.target === 'devbox' ? 'Isolated DevBox' : 'This laptop'}</span>
          <span>Started {ago(d.task.created_at)}</span>
          {d.task.tainted && <span>External content</span>}
        </div>
      </header>
      <section className="task-timeline">
        <div className="timeline-dot active" />
        <div>
          <p className="timeline-label">{statusLabel[d.task.state] ?? 'Working'}</p>
          <p className="timeline-copy">{timelineCopy()}</p>
        </div>
      </section>
      <RunCard taskId={task.id} initialState={task.state} />
      {reply && <section className="workspace-result"><p className="eyebrow">Result</p><Markdown text={reply} /></section>}
      {d.task.state === 'DONE' && (!d.task.outcome || d.task.outcome === 'success') && (
        <div style={{ display: 'flex', gap: '8px', margin: '12px 0', alignItems: 'center' }}>
          <Button
            icon="bookmark"
            onClick={async () => {
              try {
                await api.post('/api/playbooks', {
                  name: d.task.goal.slice(0, 48),
                  description: d.task.goal,
                  task_signature: d.task.goal,
                  target: d.task.target || 'host',
                  provenance_task_id: d.task.id,
                  steps: [],
                })
                alert('Saved workflow to Playbooks!')
              } catch (e) {
                alert('Could not save playbook: ' + String(e))
              }
            }}
          >
            Remember workflow
          </Button>
          <a
            className="btn btn-secondary"
            href={`#/routines?goal=${encodeURIComponent(d.task.goal)}&target=${encodeURIComponent(d.task.target || 'host')}`}
            style={{ textDecoration: 'none', display: 'inline-flex', alignItems: 'center' }}
          >
            Schedule daily…
          </a>
        </div>
      )}
      {d.task.error && <p className="run-error" role="alert">{d.task.error}</p>}
      <TaskComposer conversationId={d.task.conversation_id} onCreated={(next) => { onContinue(next) }} />
      <details className="advanced-trace">
        <summary>Advanced trace</summary>
        <p className="hint">Steps, policy decisions and verification details are available in the task record.</p>
        <a href={`#/activity/${task.id}`}>Open full task record</a>
      </details>
    </main>
  )
}

export function Workspace() {
  const tick = useApp((state) => state.tick)
  const [selected, setSelected] = useState<Task | null>(null)
  const [search, setSearch] = useState('')
  const queryParam = search.trim() ? `&q=${encodeURIComponent(search.trim())}` : ''
  const tasks = useLoad<{ tasks: Task[]; total?: number }>(`/api/tasks?limit=50${queryParam}`, true)
  const active = selected ? tasks.data?.tasks.find((task) => task.id === selected.id) ?? selected : null

  const taskCountDisplay = () => {
    if (!tasks.data) return '0'
    if (tasks.data.total !== undefined && tasks.data.total !== tasks.data.tasks.length) {
      return `${tasks.data.tasks.length} of ${tasks.data.total}`
    }
    return `${tasks.data.tasks.length}`
  }

  return (
    <div className="workspace">
      <aside className="workspace-sidebar" aria-label="Task workspace">
        <div className="workspace-sidebar-head">
          <div><p className="eyebrow">Workspace</p><h2>What Lilly is doing</h2></div>
          <span className="workspace-live"><i />Live</span>
        </div>
        <TaskComposer onCreated={(task) => { setSelected(task); tasks.reload() }} />
        <div className="workspace-section-head">
          <span>Tasks</span>
          <span className="hint">{taskCountDisplay()}</span>
        </div>
        <div style={{ padding: '0 12px 8px' }}>
          <input
            type="search"
            placeholder="Search tasks…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ width: '100%', padding: '6px 10px', fontSize: '13px', borderRadius: '6px', border: '1px solid var(--border)' }}
            aria-label="Filter tasks by goal"
          />
        </div>
        <div className="workspace-task-list">
          {tasks.data?.tasks.map((task) => (
            <TaskRow key={task.id} task={task} selected={selected?.id === task.id} onSelect={() => setSelected(task)} />
          ))}
          {tasks.data?.tasks.length === 0 && (
            <p className="workspace-empty">{search ? 'No matching tasks.' : 'No tasks yet. Give Lilly a job to begin.'}</p>
          )}
        </div>
        <a className="workspace-settings" href="#/settings"><Icon name="settings" size={15} /> Settings</a>
      </aside>
      {active ? (
        <ActiveTask task={active} onBack={() => setSelected(null)} onContinue={(task) => { setSelected(task); tasks.reload() }} />
      ) : (
        <main className="workspace-main workspace-blank">
          <div className="workspace-blank-mark"><Icon name="spark" size={20} /></div>
          <p className="eyebrow">Ready when you are</p>
          <h1>Give Lilly a job.</h1>
          <p>Tasks stay here while Lilly works. You can follow progress, handle approvals, and inspect the result without leaving the workspace.</p>
          <div className="workspace-shortcuts">
            <span><kbd>⌘</kbd><kbd>Enter</kbd> start task</span>
            <span><kbd>⌘</kbd><kbd>K</kbd> command palette</span>
          </div>
        </main>
      )}
      <span className="sr-only" aria-live="polite">Workspace updated {tick}</span>
    </div>
  )
}
