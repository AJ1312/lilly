import { useState } from 'react'
import { api, errorText } from '../api'
import { useLoad } from '../hooks'
import { useApp } from '../store'
import { APPROVAL_MODES, LIVE_STATES, type Settings, type Task, type TaskDetail } from '../types'
import { Icon } from '../ui/Icon'
import { Markdown } from '../ui/Markdown'
import { RunCard } from '../ui/RunCard'
import { Button, ErrorNote, Segmented, StatePill } from '../ui/kit'
import { ago } from '../ui/format'

const statusLabel: Record<string, string> = {
  PENDING: 'Queued', PLANNING: 'Planning', RUNNING: 'Working', WAITING_APPROVAL: 'Waiting',
  VERIFYING: 'Verifying', DONE: 'Complete', FAILED: 'Failed', CANCELLED: 'Stopped', EXPIRED: 'Expired',
}

function TaskComposer({ onCreated }: { onCreated: (task: Task) => void }) {
  const [goal, setGoal] = useState('')
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
      const result = await api.post<{ task: Task }>('/api/tasks', { goal: goal.trim() })
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
    <section className="task-composer" aria-label="New task">
      <textarea value={goal} rows={3} maxLength={4000} placeholder="What should Lilly get done?" aria-label="Task description"
        onChange={(event) => setGoal(event.target.value)} onKeyDown={(event) => {
          if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) { event.preventDefault(); void submit() }
        }} />
      <div className="task-composer-approval">
        <span className="label">Approval</span>
        <Segmented
          label="Approval mode for tasks"
          value={approvalMode}
          onChange={(value) => void changeApprovalMode(value)}
          options={APPROVAL_MODES.map((mode) => ({ value: mode.value, label: mode.name, hint: mode.blurb }))}
        />
        <span className="hint">{APPROVAL_MODES.find((mode) => mode.value === approvalMode)?.blurb}</span>
      </div>
      <ErrorNote text={approvalError} />
      <div className="task-composer-footer"><span className="hint">Lilly will plan, act, verify, and keep you posted.</span><Button kind="primary" icon="arrow-right" busy={busy} disabled={!goal.trim()} onClick={() => void submit()}>Start task</Button></div>
      <ErrorNote text={error} />
    </section>
  )
}

function TaskRow({ task, selected, onSelect }: { task: Task; selected: boolean; onSelect: () => void }) {
  return <button type="button" className={`workspace-task${selected ? ' selected' : ''}`} onClick={onSelect}>
    <span className="task-row-icon"><Icon name={LIVE_STATES.includes(task.state) ? 'loader' : task.state === 'DONE' ? 'check' : 'activity'} size={15} /></span>
    <span className="task-row-copy"><strong>{task.goal.slice(0, 90)}</strong><small>{statusLabel[task.state] ?? task.state} · {ago(task.updated_at)}</small></span>
    <StatePill state={task.state} />
  </button>
}

function ActiveTask({ task, onBack }: { task: Task; onBack: () => void }) {
  const detail = useLoad<TaskDetail>(`/api/tasks/${task.id}`, true)
  const d = detail.data
  if (!d) return <main className="workspace-main"><ErrorNote text={detail.error} /></main>
  const reply = d.task.answer
  return <main className="workspace-main">
    <header className="workspace-task-head">
      <button type="button" className="workspace-back" onClick={onBack}><Icon name="chevron" size={15} /> All tasks</button>
      <div className="workspace-title-line"><div><p className="eyebrow">Task</p><h1>{d.task.goal}</h1></div><StatePill state={d.task.state} /></div>
      <div className="workspace-meta"><span>{statusLabel[d.task.state] ?? d.task.state}</span><span>Started {ago(d.task.created_at)}</span>{d.task.tainted && <span>External content</span>}</div>
    </header>
    <section className="task-timeline"><div className="timeline-dot active" /><div><p className="timeline-label">{statusLabel[d.task.state] ?? 'Working'}</p><p className="timeline-copy">{d.task.state === 'DONE' ? 'Lilly finished and verified this task.' : 'Lilly is working through the task and will verify the result.'}</p></div></section>
    <RunCard taskId={task.id} initialState={task.state} />
    {reply && <section className="workspace-result"><p className="eyebrow">Result</p><Markdown text={reply} /></section>}
    {d.task.error && <p className="run-error" role="alert">{d.task.error}</p>}
    <details className="advanced-trace"><summary>Advanced trace</summary><p className="hint">Steps, policy decisions and verification details are available in the task record.</p><a href={`#/activity/${task.id}`}>Open full task record</a></details>
  </main>
}

export function Workspace() {
  const tick = useApp((state) => state.tick)
  const [selected, setSelected] = useState<Task | null>(null)
  const tasks = useLoad<{ tasks: Task[] }>('/api/tasks?limit=80', true)
  const active = selected ? tasks.data?.tasks.find((task) => task.id === selected.id) ?? selected : null
  return <div className="workspace">
    <aside className="workspace-sidebar" aria-label="Task workspace">
      <div className="workspace-sidebar-head"><div><p className="eyebrow">Workspace</p><h2>What Lilly is doing</h2></div><span className="workspace-live"><i />Live</span></div>
      <TaskComposer onCreated={(task) => { setSelected(task); tasks.reload() }} />
      <div className="workspace-section-head"><span>Tasks</span><span className="hint">{tasks.data?.tasks.length ?? 0}</span></div>
      <div className="workspace-task-list">{tasks.data?.tasks.map((task) => <TaskRow key={task.id} task={task} selected={selected?.id === task.id} onSelect={() => setSelected(task)} />)}{tasks.data?.tasks.length === 0 && <p className="workspace-empty">No tasks yet. Give Lilly a job to begin.</p>}</div>
      <a className="workspace-settings" href="#/settings"><Icon name="settings" size={15} /> Settings</a>
    </aside>
    {active ? <ActiveTask task={active} onBack={() => setSelected(null)} /> : <main className="workspace-main workspace-blank"><div className="workspace-blank-mark"><Icon name="spark" size={20} /></div><p className="eyebrow">Ready when you are</p><h1>Give Lilly a job.</h1><p>Tasks stay here while Lilly works. You can follow progress, handle approvals, and inspect the result without leaving the workspace.</p><div className="workspace-shortcuts"><span><kbd>⌘</kbd><kbd>Enter</kbd> start task</span><span><kbd>⌘</kbd><kbd>K</kbd> command palette</span></div></main>}
    <span className="sr-only" aria-live="polite">Workspace updated {tick}</span>
  </div>
}
