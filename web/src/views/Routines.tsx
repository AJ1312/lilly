import { useCallback, useState } from 'react'
import { api, errorText } from '../api'
import { useInterval, useLoad } from '../hooks'
import { useApp } from '../store'
import type { Agent, Routine, Schedule } from '../types'
import { STATE_LABEL, ago, when } from '../ui/format'
import { Button, Confirm, Dialog, Empty, ErrorNote, Field, IconButton, PageHead, Pill, Segmented, Switch } from '../ui/kit'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const WEEKDAYS = [0, 1, 2, 3, 4]
const UNITS = [{ value: 1, label: 'minutes' }, { value: 60, label: 'hours' }, { value: 1440, label: 'days' }] as const

interface Draft {
  name: string
  goal: string
  agent_id: string
  kind: 'at' | 'every'
  at: string
  days: number[]
  amount: number
  unit: number
}

function toDraft(r: Routine | null): Draft {
  const base: Draft = { name: '', goal: '', agent_id: '', kind: 'at', at: '08:30', days: WEEKDAYS, amount: 1, unit: 60 }
  if (!r) return base
  const common = { ...base, name: r.name, goal: r.goal, agent_id: r.agent_id ?? '' }
  if (r.schedule.kind === 'at') return { ...common, kind: 'at', at: r.schedule.at, days: r.schedule.days }
  const n = r.schedule.every_minutes
  const unit = n % 1440 === 0 ? 1440 : n % 60 === 0 ? 60 : 1
  return { ...common, kind: 'every', amount: n / unit, unit }
}

function toSchedule(d: Draft): Schedule {
  return d.kind === 'at' ? { kind: 'at', at: d.at, days: d.days } : { kind: 'every', every_minutes: d.amount * d.unit }
}

function RoutineDialog({ routine, agents, onClose, onSaved }: { routine: Routine | null; agents: Agent[]; onClose: () => void; onSaved: () => void }) {
  const [d, setD] = useState<Draft>(() => toDraft(routine))
  const [error, setError] = useState<string | null>(null)
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD({ ...d, [k]: v })
  const toggleDay = (i: number) => set('days', d.days.includes(i) ? d.days.filter((x) => x !== i) : [...d.days, i].sort())
  const ready = d.name.trim() !== '' && d.goal.trim() !== '' && (d.kind === 'every' ? d.amount >= 1 : d.days.length > 0 && d.at !== '')
  const save = async () => {
    const body = { name: d.name, goal: d.goal, agent_id: d.agent_id || null, schedule: toSchedule(d) }
    try {
      if (routine) await api.patch(`/api/routines/${routine.id}`, body)
      else await api.post('/api/routines', body)
      onSaved()
    } catch (e) {
      setError(errorText(e))
    }
  }
  return (
    <Dialog
      wide
      title={routine ? 'Edit routine' : 'New routine'}
      onClose={onClose}
      footer={<><Button onClick={onClose}>Cancel</Button><Button kind="primary" disabled={!ready} onClick={() => void save()}>Save</Button></>}
    >
      <Field label="Name">{(id) => <input id={id} value={d.name} maxLength={80} placeholder="Morning brief" onChange={(e) => set('name', e.target.value)} />}</Field>
      <Field label="What should Lilly do?" hint="Write it as you would in a chat. It runs the same way, with the same approvals.">
        {(id) => <textarea id={id} rows={4} value={d.goal} maxLength={4000} placeholder="Read my notes from yesterday and list what I should follow up on today." onChange={(e) => set('goal', e.target.value)} />}
      </Field>
      <Field label="Who does it?" hint="The agent's permissions decide what the routine may touch. Anything that needs approval waits for you in Approvals.">
        {(id) => (
          <select id={id} value={d.agent_id} onChange={(e) => set('agent_id', e.target.value)}>
            <option value="">Default assistant</option>
            {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        )}
      </Field>
      <div className="field">
        <span className="label">When</span>
        <Segmented label="Kind of schedule" value={d.kind} onChange={(v) => set('kind', v)} options={[{ value: 'at', label: 'At a time' }, { value: 'every', label: 'Repeating' }]} />
      </div>
      {d.kind === 'at' ? (
        <>
          <Field label="Time" hint="Your computer's local time.">{(id) => <input id={id} type="time" value={d.at} onChange={(e) => set('at', e.target.value)} />}</Field>
          <div className="field">
            <span className="label">Days</span>
            <div className="day-row" role="group" aria-label="Days">
              {DAYS.map((name, i) => (
                <button key={name} type="button" aria-pressed={d.days.includes(i)} className={`day-chip${d.days.includes(i) ? ' on' : ''}`} onClick={() => toggleDay(i)}>{name}</button>
              ))}
            </div>
          </div>
        </>
      ) : (
        <div className="field">
          <span className="label">Repeat every</span>
          <div className="row">
            <input aria-label="How many" type="number" min={1} className="num" value={d.amount} onChange={(e) => set('amount', Math.max(1, Math.floor(Number(e.target.value) || 1)))} />
            <select aria-label="Unit" value={d.unit} onChange={(e) => set('unit', Number(e.target.value))}>
              {UNITS.map((u) => <option key={u.value} value={u.value}>{u.label}</option>)}
            </select>
          </div>
          <p className="hint">At least every 5 minutes.</p>
        </div>
      )}
      <ErrorNote text={error} />
    </Dialog>
  )
}

const capitalise = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

function status(r: Routine): { tone: 'ok' | 'warn' | 'bad' | 'mute'; text: string } {
  if (!r.enabled) return { tone: 'warn', text: capitalise(r.pause_reason ?? 'paused') }
  if (r.last_state === 'running') return { tone: 'ok', text: 'Running now' }
  return { tone: 'ok', text: r.next_run ? `Next ${when(r.next_run)}` : 'Waiting' }
}

export function Routines() {
  const list = useLoad<{ routines: Routine[] }>('/api/routines', true)
  const team = useLoad<{ agents: Agent[] }>('/api/agents')
  // A run's result is recorded by the scheduler, which raises no live event: look while a routine is scheduled or running.
  const scheduled = list.data?.routines.some((r) => r.enabled || r.last_state === 'running') ?? false
  const reload = list.reload
  const poll = useCallback(() => { if (scheduled) reload() }, [scheduled, reload])
  useInterval(poll, 5000)
  const [editing, setEditing] = useState<Routine | 'new' | null>(null)
  const [removing, setRemoving] = useState<Routine | null>(null)
  const toast = useApp((s) => s.toast)
  const agents = team.data?.agents ?? []
  const fail = (e: unknown) => toast(errorText(e), 'bad')

  const toggle = (r: Routine) => api.patch(`/api/routines/${r.id}`, { enabled: !r.enabled }).then(list.reload).catch(fail)
  const runNow = (r: Routine) => api.post(`/api/routines/${r.id}/run`, {}).then(() => { toast(`${r.name} started`); list.reload() }).catch(fail)

  return (
    <div className="page">
      <PageHead
        title="Routines"
        sub="Requests Lilly runs on a schedule while it is open. Each run is a normal task: it follows the same rules and waits for your approval when it needs it."
        actions={<Button kind="primary" icon="plus" onClick={() => setEditing('new')}>New routine</Button>}
      />
      <ErrorNote text={list.error} />
      {list.data?.routines.length === 0 && (
        <Empty title="No routines yet">Try “Every weekday at 08:30, summarise my notes from yesterday”, or “Every 2 hours, check which programs use the most memory”. Stop all pauses every routine.</Empty>
      )}
      <ul className="routines">
        {list.data?.routines.map((r) => {
          const s = status(r)
          return (
            <li key={r.id} className={`routine${r.enabled ? '' : ' paused'}`}>
              <div className="row between">
                <h3>{r.name}</h3>
                <div className="row">
                  <Button small icon="play" disabled={r.last_state === 'running'} onClick={() => void runNow(r)}>Run now</Button>
                  <IconButton icon="edit" label={`Edit ${r.name}`} onClick={() => setEditing(r)} />
                  <IconButton icon="trash" label={`Delete ${r.name}`} kind="danger" onClick={() => setRemoving(r)} />
                </div>
              </div>
              <p className="clamp">{r.goal}</p>
              <div className="row wrap">
                <Pill tone="mute">{r.when}</Pill>
                <Pill tone={s.tone}>{s.text}</Pill>
                {r.last_run !== null && r.last_state && r.last_state !== 'running' && (
                  <a className="pill pill-mute" href={r.last_task_id ? `#/activity/${r.last_task_id}` : undefined}>
                    Last run {ago(r.last_run)}: {STATE_LABEL[r.last_state.toUpperCase()] ?? r.last_state}
                  </a>
                )}
              </div>
              {r.last_error && r.last_state === 'failed' && <p className="hint">{r.last_error}</p>}
              <Switch label={r.enabled ? 'On' : 'Paused'} checked={r.enabled} onChange={() => void toggle(r)} />
            </li>
          )
        })}
      </ul>
      {editing && (
        <RoutineDialog routine={editing === 'new' ? null : editing} agents={agents} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); list.reload() }} />
      )}
      {removing && (
        <Confirm
          title={`Delete ${removing.name}?`}
          danger
          confirm="Delete"
          body="Runs it already did stay in Activity."
          onClose={() => setRemoving(null)}
          onConfirm={() => { api.del(`/api/routines/${removing.id}`).then(list.reload).catch(fail) }}
        />
      )}
    </div>
  )
}
