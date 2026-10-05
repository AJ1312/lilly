import { useState } from 'react'
import { api, errorText } from '../api'
import { useLoad } from '../hooks'
import { useApp } from '../store'
import { LIVE_STATES, type LilEvent, type Task, type TaskDetail } from '../types'
import { StepNode } from '../ui/RunCard'
import { Button, Empty, ErrorNote, PageHead, Segmented, StatePill } from '../ui/kit'
import { ago, clock } from '../ui/format'

type Filter = 'all' | 'live' | 'problems'

function TaskList({ go }: { go: (h: string) => void }) {
  const [filter, setFilter] = useState<Filter>('all')
  const states = filter === 'live' ? LIVE_STATES.join(',') : filter === 'problems' ? 'FAILED,EXPIRED,CANCELLED' : ''
  const list = useLoad<{ tasks: Task[] }>(`/api/tasks?limit=100${states ? `&state=${states}` : ''}`, true)
  return (
    <div className="page">
      <PageHead title="Activity" sub="Everything Lilly has done, with a tamper-evident record of each task." />
      <Segmented
        label="Filter"
        value={filter}
        onChange={setFilter}
        options={[{ value: 'all', label: 'All' }, { value: 'live', label: 'Running' }, { value: 'problems', label: 'Stopped or failed' }]}
      />
      <ErrorNote text={list.error} />
      {list.data?.tasks.length === 0 && <Empty title="Nothing here yet">Tasks you start in Talk appear here.</Empty>}
      <ul className="ledger ledger-tasks">
        {list.data?.tasks.map((t) => (
          <li key={t.id}>
            <button type="button" className="row-button" onClick={() => go(`/activity/${t.id}`)}>
              <strong>{t.goal.slice(0, 120)}</strong>
              <span className="row-meta"><StatePill state={t.state} /> <span className="hint">{ago(t.created_at)}</span></span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

function TaskDetailView({ id, go }: { id: string; go: (h: string) => void }) {
  const detail = useLoad<TaskDetail>(`/api/tasks/${id}`, true)
  const events = useLoad<{ events: LilEvent[] }>(`/api/tasks/${id}/events?limit=500`, true)
  const [intact, setIntact] = useState<boolean | null>(null)
  const toast = useApp((s) => s.toast)
  const d = detail.data

  const verify = async () => {
    try {
      setIntact((await api.get<{ intact: boolean }>(`/api/tasks/${id}/verify`)).intact)
    } catch (e) {
      toast(errorText(e), 'bad')
    }
  }

  if (!d) return <div className="page"><ErrorNote text={detail.error} /></div>
  return (
    <div className="page">
      <PageHead
        title={d.task.goal.slice(0, 90)}
        sub={`Started ${ago(d.task.created_at)}`}
        actions={<Button icon="chevron" onClick={() => go('/activity')}>All activity</Button>}
      />
      <div className="facts">
        <StatePill state={d.task.state} />
        <span className="tag">mode {['locked', 'ask', 'open'][d.task.mode]}</span>
        <span className="tag">data seen: {d.task.label.toLowerCase()}</span>
        {d.task.tainted && <span className="tag tag-warn">read web content</span>}
        {d.task.pinned_model && <span className="tag">model: {d.task.pinned_model}</span>}
      </div>
      {d.task.error && <p className="run-error">{d.task.error}</p>}
      {d.task.answer && <section><h2 className="section-title">Answer</h2><p className="prose pre-wrap">{d.task.answer}</p></section>}
      {d.steps.length > 0 && <section><h2 className="section-title">Steps</h2><ol className="stem">{d.steps.map((s) => <StepNode key={s.id} step={s} />)}</ol></section>}
      <section>
        <div className="row between">
          <h2 className="section-title">Record</h2>
          <div className="row">
            {intact !== null && <span className={intact ? 'ok-text' : 'bad-text'}>{intact ? 'Record is intact' : 'Record was altered'}</span>}
            <Button small icon="shield" onClick={() => void verify()}>Verify record</Button>
          </div>
        </div>
        <ol className="events">
          {events.data?.events.map((e) => (
            <li key={e.seq}>
              <time>{clock(e.at)}</time>
              <strong>{e.kind}</strong>
              <code>{JSON.stringify(e.payload).slice(0, 220)}</code>
            </li>
          ))}
        </ol>
      </section>
    </div>
  )
}

export function Activity({ taskId, go }: { taskId: string | null; go: (h: string) => void }) {
  return taskId ? <TaskDetailView id={taskId} go={go} /> : <TaskList go={go} />
}
