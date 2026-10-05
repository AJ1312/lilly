import { useCallback, useEffect, useState } from 'react'
import { api, errorText } from '../api'
import { useInterval, useLoad } from '../hooks'
import { useApp } from '../store'
import type { DevboxSettings, DevboxStatus } from '../types'
import { Button, Confirm, ErrorNote, Field, Pill } from '../ui/kit'
import type { SettingsDraft } from './settingsDraft'

const STATE_TEXT: Record<DevboxStatus['state'], string> = {
  unavailable: 'Docker or Podman not found',
  missing: 'not created yet (it starts when first needed)',
  stopped: 'asleep (wakes in about a second)',
  running: 'running',
}

export function DevboxSection({ d }: { d: SettingsDraft }) {
  const status = useLoad<DevboxStatus>('/api/devbox')
  const toast = useApp((s) => s.toast)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirm, setConfirm] = useState(false)
  const s = status.data
  const reload = status.reload
  useInterval(useCallback(() => { if (s?.preparing) reload() }, [s?.preparing, reload]), 2000)
  const saves = d.saves
  useEffect(() => { if (saves > 0) reload() }, [saves, reload]) // the folder check depends on the saved settings
  const b = d.current?.devbox
  if (!s || !b) return <ErrorNote text={status.error ?? d.loadError} />

  const act = async (run: () => Promise<unknown>, done: string) => {
    setBusy(true)
    try {
      await run()
      setError(null)
      reload()
      toast(done)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  const set = (patch: Partial<DevboxSettings>) => d.edit((x) => ({ ...x, devbox: { ...x.devbox, ...patch } }))
  const num = (key: 'cpus' | 'memory_mb' | 'pids' | 'idle_stop_s' | 'destroy_after_s' | 'command_timeout_s', label: string, unit: string, hint?: string, step = 1) => (
    <Field label={label} hint={hint}>
      {(id) => (
        <div className="with-unit">
          <input id={id} type="number" step={step} value={b[key]} onChange={(e) => set({ [key]: Number(e.target.value) })} />
          <span>{unit}</span>
        </div>
      )}
    </Field>
  )

  return (
    <div className="stack">
      <p className="hint">A sealed container where an agent can run commands and code. It has no network, cannot see anything on this computer except the one folder you share, and is capped on CPU, memory and processes. It starts when a task needs it, sleeps when idle, and is removed after a longer quiet spell. Switch the Devbox module on under General, and allow “files” for the agents that may use it.</p>
      <ErrorNote text={error} />
      <section className="card stack" aria-labelledby="dv-status">
        <h3 id="dv-status">Status</h3>
        <p>
          {s.engine ? <>Engine: <strong>{s.engine}</strong></> : <Pill tone="warn">No Docker or Podman found</Pill>} · Box: {STATE_TEXT[s.state]} · Image {s.image}: {s.image_ready ? <Pill tone="ok">downloaded</Pill> : <Pill>not downloaded</Pill>}
        </p>
        <ErrorNote text={s.prepare_error} />
        <div className="row">
          <Button onClick={() => void act(() => api.post('/api/devbox/prepare'), 'Downloading the image')} busy={busy || s.preparing} disabled={!s.engine || s.image_ready}>{s.preparing ? 'Downloading…' : 'Download image'}</Button>
          <Button kind="danger" onClick={() => setConfirm(true)} disabled={s.state === 'missing' || s.state === 'unavailable'}>Reset box</Button>
        </div>
      </section>
      <section className="card stack" aria-labelledby="dv-set">
        <h3 id="dv-set">Settings</h3>
        <Field label="Shared folder" hint={s.folder_problem ?? 'Everything in this folder can be read, changed or deleted by commands in the box. Use a folder made for this, inside a folder you have shared with Lilly.'} wide>
          {(id) => <input id={id} value={b.shared_folder} placeholder="/Users/you/Documents/devbox" onChange={(e) => set({ shared_folder: e.target.value })} />}
        </Field>
        <Field label="Engine">
          {(id) => (
            <select id={id} value={b.runtime} onChange={(e) => set({ runtime: e.target.value as DevboxSettings['runtime'] })}>
              <option value="auto">Whichever is installed</option>
              <option value="docker">Docker</option>
              <option value="podman">Podman</option>
            </select>
          )}
        </Field>
        <Field label="Image" hint="Downloaded once, by you, with the button above.">
          {(id) => <input id={id} value={b.image} onChange={(e) => set({ image: e.target.value })} />}
        </Field>
        <div className="grid-3">
          {num('cpus', 'CPU', 'cores', undefined, 0.25)}
          {num('memory_mb', 'Memory', 'MB')}
          {num('pids', 'Processes', 'at most')}
          {num('command_timeout_s', 'Longest command', 'seconds', 'Then it is stopped and the box is reset.')}
          {num('idle_stop_s', 'Sleep when idle after', 'seconds', 'A sleeping box wakes in about a second.')}
          {num('destroy_after_s', 'Remove after', 'seconds', 'Files in the shared folder are kept.')}
        </div>
        <p className="hint">Changes apply when you save, and the box is rebuilt the next time it is used.</p>
      </section>
      {confirm && (
        <Confirm title="Reset the box?" body="Anything running in it stops and the box is removed. Files in the shared folder stay." confirm="Reset" danger
          onConfirm={() => { setConfirm(false); void act(() => api.del('/api/devbox'), 'Box removed') }} onClose={() => setConfirm(false)} />
      )}
    </div>
  )
}
