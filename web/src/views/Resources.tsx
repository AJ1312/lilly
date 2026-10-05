import { useState } from 'react'
import { api, errorText } from '../api'
import { useInterval, useLoad } from '../hooks'
import { useApp } from '../store'
import type { Limits, Preset, Resources as ResourcesData, Settings } from '../types'
import { bytes, duration } from '../ui/format'
import { Button, ErrorNote, Field, PageHead, Pill, StatePill } from '../ui/kit'

function Meter({ label, percent, detail }: { label: string; percent: number; detail: string }) {
  const tone = percent >= 90 ? 'hot' : percent >= 75 ? 'warm' : 'cool'
  return (
    <div className="meter" role="group" aria-label={label}>
      <div className="meter-top"><span>{label}</span><strong>{Math.round(percent)}%</strong></div>
      <div className="meter-track" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(percent)} aria-label={label}>
        <span className={`meter-fill meter-${tone}`} style={{ width: `${Math.min(100, Math.max(2, percent))}%` }} />
      </div>
      <small>{detail}</small>
    </div>
  )
}

function LimitsCard({ limits, onSaved }: { limits: Limits; onSaved: () => void }) {
  const [draft, setDraft] = useState(limits)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const toast = useApp((s) => s.toast)
  const dirty = JSON.stringify(draft) !== JSON.stringify(limits)
  const num = (k: keyof Limits, lo: number, hi: number, label: string, hint: string, unit: string) => (
    <Field label={label} hint={hint}>
      {(id) => (
        <div className="with-unit">
          <input id={id} type="number" min={lo} max={hi} value={draft[k]} onChange={(e) => setDraft({ ...draft, [k]: Number.parseInt(e.target.value || String(lo), 10) })} />
          <span>{unit}</span>
        </div>
      )}
    </Field>
  )
  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      const current = (await api.get<{ settings: Settings }>('/api/settings')).settings
      await api.put('/api/settings', { ...current, limits: draft })
      toast('Limits applied')
      onSaved()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="panel">
      <h2>Limits</h2>
      <p className="hint">How much Lilly may do at once. Changes apply straight away, including to work already waiting in line.</p>
      <div className="grid-3">
        {num('max_running', 1, 8, 'Tasks at once', 'More wait in line.', 'tasks')}
        {num('lanes', 1, 8, 'Steps at once in one task', 'Only plain reads run side by side; anything that changes something runs alone.', 'steps')}
        {num('step_timeout_s', 10, 900, 'Longest single step', 'A slow model call or command is stopped after this.', 'seconds')}
        {num('task_minutes', 1, 240, 'Longest whole task', 'Then the task is stopped and marked failed.', 'minutes')}
        {num('local_unload_s', 0, 3600, 'Keep a local model loaded', 'After this long unused, an Ollama model leaves memory (0: right after each answer). Loading it again takes a few seconds.', 'seconds')}
      </div>
      <ErrorNote text={error} />
      <div className="row">
        <Button kind="primary" disabled={!dirty} busy={busy} onClick={() => void save()}>Apply limits</Button>
        {dirty && <Button onClick={() => setDraft(limits)}>Reset</Button>}
      </div>
    </section>
  )
}

function PresetCard({ onApplied }: { onApplied: () => void }) {
  const list = useLoad<{ presets: Preset[] }>('/api/presets')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const toast = useApp((s) => s.toast)
  const apply = async (name: string) => {
    setBusy(name)
    setError(null)
    try {
      await api.post('/api/presets', { name })
      toast(`Applied ${name}`)
      onApplied()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(null)
    }
  }
  return (
    <section className="panel">
      <h2>Presets</h2>
      <p className="hint">One-click starting points. They change only limits and idle times, never what Lilly is allowed to touch.</p>
      <ErrorNote text={error ?? list.error} />
      <div className="row">
        {list.data?.presets.map((p) => (
          <Button key={p.name} busy={busy === p.name} disabled={busy !== null} onClick={() => void apply(p.name)} title={p.summary}>{p.name}</Button>
        ))}
      </div>
    </section>
  )
}

export function Resources() {
  const res = useLoad<ResourcesData>('/api/resources')
  const toast = useApp((s) => s.toast)
  const reload = res.reload
  useInterval(reload, 5000)
  const d = res.data

  const stop = async (id: string) => {
    try {
      await api.post(`/api/tasks/${id}/cancel`)
      reload()
    } catch (e) {
      toast(errorText(e), 'bad')
    }
  }

  return (
    <div className="page">
      <PageHead title="Resources" sub="What this computer is doing, what Lilly is using, and how much work Lilly is allowed to take on." />
      <ErrorNote text={res.error} />
      {d && (
        <>
          <section className="panel">
            <h2>This computer</h2>
            <div className="meters">
              <Meter label="Processor" percent={d.machine.cpu_percent} detail="across all cores" />
              <Meter label="Memory" percent={d.machine.memory.percent} detail={`${bytes(d.machine.memory.total - d.machine.memory.available)} of ${bytes(d.machine.memory.total)} in use`} />
              <Meter label="Disk" percent={d.machine.disk.percent} detail={`${bytes(d.machine.disk.free)} free`} />
            </div>
            <details className="procs">
              <summary>Heaviest programs</summary>
              <table>
                <thead><tr><th scope="col">Program</th><th scope="col">Memory</th></tr></thead>
                <tbody>{d.machine.top_processes.map((p) => <tr key={p.pid}><td>{p.name}</td><td>{p.memory_percent}%</td></tr>)}</tbody>
              </table>
              <p className="hint">To close one, ask Lilly (with an agent that may control this computer). You approve the exact program first.</p>
            </details>
          </section>

          <section className="panel">
            <h2>Work in progress</h2>
            <div className="counts">
              <div><strong>{d.tasks.running}</strong><span>running</span></div>
              <div><strong>{d.tasks.queued}</strong><span>in line</span></div>
              <div><strong>{d.tasks.waiting_approval}</strong><span>waiting for you</span></div>
              {d.stay_awake_active && <Pill tone="live">keeping the computer awake</Pill>}
            </div>
            {d.tasks.live.length === 0 ? <p className="hint">Nothing is running.</p> : (
              <ul className="plain-list">
                {d.tasks.live.map((t) => (
                  <li key={t.id} className="live-task">
                    <StatePill state={t.state} />
                    <span className="clamp1">{t.goal}</span>
                    <Button small icon="stop" onClick={() => void stop(t.id)}>Stop</Button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <PresetCard onApplied={reload} />
          <LimitsCard key={JSON.stringify(d.limits)} limits={d.limits} onSaved={reload} />

          <section className="panel">
            <h2>Lilly itself</h2>
            <dl className="facts">
              <div><dt>Memory</dt><dd>{bytes(d.lilly.memory_bytes)}</dd></div>
              <div><dt>Processor</dt><dd>{d.lilly.cpu_percent}%</dd></div>
              <div><dt>Threads</dt><dd>{d.lilly.threads}</dd></div>
              <div><dt>Database</dt><dd>{bytes(d.lilly.database_bytes)}</dd></div>
              <div><dt>Backups</dt><dd>{bytes(d.lilly.backups_bytes)}</dd></div>
              <div><dt>Logs</dt><dd>{bytes(d.lilly.logs_bytes)}</dd></div>
            </dl>
          </section>

          <section className="panel">
            <h2>Models</h2>
            <p className="hint">Free tiers have limits. Counts reset by the schedule you set for each model.</p>
            <ul className="quota-list">
              {d.models.map((m) => (
                <li key={m.name}>
                  <div className="row between">
                    <strong>{m.name}</strong>
                    <span className="row">
                      {!m.enabled && <Pill>off</Pill>}
                      {m.enabled && !m.has_key && <Pill tone="warn">no key</Pill>}
                      {m.breaker !== 'closed' && <Pill tone="bad">{m.breaker === 'open' ? 'paused after errors' : 'checking'}</Pill>}
                    </span>
                  </div>
                  <div className="quota">
                    <span>{m.rpm ? `${m.minute_used ?? 0} / ${m.rpm} per minute` : 'no per-minute limit set'}</span>
                    <span>{m.rpd ? `${m.day_used ?? 0} / ${m.rpd} today${m.resets_in_s ? `, resets in ${duration(m.resets_in_s)}` : ''}` : 'no daily limit set'}</span>
                    <span className="hint">{m.calls} calls, {m.tokens_in.toLocaleString()} tokens in, {m.tokens_out.toLocaleString()} out since Lilly started</span>
                  </div>
                  {m.last_error && <p className="stem-error">{m.last_error}</p>}
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  )
}
