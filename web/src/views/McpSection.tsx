import { useState } from 'react'
import { api, errorText } from '../api'
import { useLoad } from '../hooks'
import { useApp } from '../store'
import type { McpReview, McpRisk, McpServer } from '../types'
import { ago } from '../ui/format'
import { KeyDialog } from '../ui/KeyDialog'
import { Button, Confirm, Dialog, Empty, ErrorNote, Field, IconButton, Pill, Segmented, Switch } from '../ui/kit'

const RISKS: { value: McpRisk | 'NO'; label: string; hint: string }[] = [
  { value: 'NO', label: 'Not allowed', hint: 'Lilly never offers this tool.' },
  { value: 'R0', label: 'Reads only', hint: 'Looks things up and changes nothing.' },
  { value: 'R1', label: 'Changes things', hint: 'Makes changes that can be undone.' },
  { value: 'R2', label: 'Reaches outside', hint: 'Sends, deletes or changes things that cannot be undone.' },
]

const STATE_TONE = { running: 'ok', starting: 'live', stopped: 'mute', failed: 'bad', changed: 'bad' } as const
const STATE_TEXT = { running: 'running', starting: 'starting', stopped: 'idle', failed: 'failed', changed: 'tools changed: review again' } as const

interface Form {
  name: string
  command: string
  args: string
  env: string
  secrets: string
  data_label: 'PUBLIC' | 'PERSONAL'
  idle_minutes: string
  enabled: boolean
}

const BLANK: Form = { name: '', command: '', args: '', env: '', secrets: '', data_label: 'PERSONAL', idle_minutes: '10', enabled: true }

function toForm(s: McpServer): Form {
  return {
    name: s.name, command: s.command, args: s.args.join('\n'),
    env: Object.entries(s.env).map(([k, v]) => `${k}=${v}`).join('\n'),
    secrets: s.secret_vars.map((v) => v.var).join('\n'),
    data_label: s.data_label, idle_minutes: String(Math.round(s.idle_stop_s / 60)), enabled: s.enabled,
  }
}

function lines(text: string): string[] {
  return text.split('\n').map((l) => l.trim()).filter(Boolean)
}

function toBody(f: Form): Record<string, unknown> {
  const env: Record<string, string> = {}
  for (const l of lines(f.env)) {
    const i = l.indexOf('=')
    if (i > 0) env[l.slice(0, i).trim()] = l.slice(i + 1)
  }
  const minutes = Number.parseFloat(f.idle_minutes)
  return {
    name: f.name.trim(), command: f.command.trim(), args: f.args.split('\n').map((a) => a.replace(/\r$/, '')).filter((a) => a !== ''),
    env, secret_vars: lines(f.secrets), data_label: f.data_label, enabled: f.enabled,
    idle_stop_s: Number.isFinite(minutes) ? Math.round(minutes * 60) : 600,
  }
}

function ServerDialog({ initial, onClose, onSaved }: { initial: McpServer | null; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState<Form>(initial ? toForm(initial) : BLANK)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const toast = useApp((s) => s.toast)
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF({ ...f, [k]: v })
  const save = async () => {
    setBusy(true)
    try {
      await api.post('/api/mcp', toBody(f))
      toast(initial ? 'Server updated' : 'Server added. Review its tools next.')
      onSaved()
      onClose()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog
      wide
      title={initial ? `Edit ${initial.name}` : 'Add a connection'}
      onClose={onClose}
      footer={<><Button onClick={onClose}>Cancel</Button><Button kind="primary" busy={busy} disabled={!f.name.trim() || !f.command.trim()} onClick={() => void save()}>Save</Button></>}
    >
      <p className="prose">An MCP server is a program that gives Lilly extra tools. It runs on this computer with only the settings below, and you choose which of its tools Lilly may use. It runs as you, so it can read your files and use the network: add only programs you trust.</p>
      {initial && <p className="callout callout-warn" role="note">Changing how a server starts withdraws your approval of its tools. You will review them again.</p>}
      <div className="grid-2">
        <Field label="Name" hint="Lowercase letters, numbers, dashes.">{(id) => <input id={id} value={f.name} disabled={initial !== null} onChange={(e) => set('name', e.target.value.toLowerCase())} />}</Field>
        <Field label="Program" hint="For example npx, uvx or a full path.">{(id) => <input id={id} value={f.command} onChange={(e) => set('command', e.target.value)} />}</Field>
        <Field label="Arguments" hint="One per line.">{(id) => <textarea id={id} rows={4} value={f.args} onChange={(e) => set('args', e.target.value)} />}</Field>
        <Field label="Settings" hint="NAME=value, one per line. Not for passwords.">{(id) => <textarea id={id} rows={4} value={f.env} onChange={(e) => set('env', e.target.value)} />}</Field>
        <Field label="Secret variables" hint="Names only, one per line. You paste each value next, and it goes to your keychain.">{(id) => <textarea id={id} rows={3} value={f.secrets} onChange={(e) => set('secrets', e.target.value)} />}</Field>
        <Field label="Stop when unused for (minutes)" hint="It starts again when needed.">{(id) => <input id={id} inputMode="numeric" value={f.idle_minutes} onChange={(e) => set('idle_minutes', e.target.value)} />}</Field>
      </div>
      <div className="field">
        <span className="label">What it returns</span>
        <Segmented label="Data label" value={f.data_label} onChange={(v) => set('data_label', v)} options={[{ value: 'PERSONAL', label: 'Personal', hint: 'Lilly asks before a cloud model sees it.' }, { value: 'PUBLIC', label: 'Public', hint: 'Treated like web pages.' }]} />
      </div>
      <Switch label="Use this server" checked={f.enabled} onChange={(v) => set('enabled', v)} />
      <ErrorNote text={error} />
    </Dialog>
  )
}

function ReviewDialog({ server, onClose, onApproved }: { server: McpServer; onClose: () => void; onApproved: () => void }) {
  const [review, setReview] = useState<McpReview | null>(null)
  const [choice, setChoice] = useState<Record<string, McpRisk | 'NO'>>({})
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const toast = useApp((s) => s.toast)
  const previous = Object.fromEntries(server.approved_tools.map((t) => [t.name, t.risk]))

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const r = await api.post<McpReview>(`/api/mcp/${server.name}/review`)
      setReview(r)
      setChoice(Object.fromEntries(r.tools.map((t) => [t.name, previous[t.name] ?? 'NO'])))
    } catch (e) {
      setError(errorText(e))
    } finally {
      setLoading(false)
    }
  }
  const chosen = Object.entries(choice).filter(([, v]) => v !== 'NO')
  const approve = async () => {
    if (!review) return
    setBusy(true)
    try {
      await api.post(`/api/mcp/${server.name}/approve`, { fingerprint: review.fingerprint, risks: Object.fromEntries(chosen) })
      toast(`${chosen.length} tool(s) approved`)
      onApproved()
      onClose()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog
      wide
      title={`Tools from ${server.name}`}
      onClose={onClose}
      footer={<><Button onClick={onClose}>Close</Button>{review && <Button kind="primary" busy={busy} disabled={chosen.length === 0} onClick={() => void approve()}>Approve {chosen.length} tool(s)</Button>}</>}
    >
      {!review && (
        <>
          <p className="prose">Lilly will start this program once and ask it which tools it offers. Nothing is approved by looking.</p>
          <div><Button kind="primary" busy={loading} onClick={() => void load()}>Start and list tools</Button></div>
        </>
      )}
      {review && (
        <div className="stack">
          <p className="prose">The descriptions below come from the server, so read them as claims, not facts. Choose what each tool may do. If the server later offers a different set, Lilly stops using it until you review again.</p>
          {review.tools.length === 0 && <Empty title="This server offers no tools" />}
          <ul className="model-list">
            {review.tools.map((t) => (
              <li key={t.name} className="model">
                <div className="model-main">
                  <strong>{t.name}</strong>
                  <p className="hint">{t.description || 'No description.'}</p>
                  <Segmented label={`Permission for ${t.name}`} value={choice[t.name] ?? 'NO'} onChange={(v) => setChoice({ ...choice, [t.name]: v })} options={RISKS.map((r) => ({ value: r.value, label: r.label, hint: r.hint }))} />
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
      <ErrorNote text={error} />
    </Dialog>
  )
}

export function McpSection() {
  const list = useLoad<{ servers: McpServer[] }>('/api/mcp', true)
  const [editing, setEditing] = useState<McpServer | 'new' | null>(null)
  const [reviewing, setReviewing] = useState<McpServer | null>(null)
  const [removing, setRemoving] = useState<string | null>(null)
  const [secret, setSecret] = useState<{ ref: string; present: boolean } | null>(null)
  const toast = useApp((s) => s.toast)
  const servers = list.data?.servers ?? []

  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn()
      list.reload()
    } catch (e) {
      toast(errorText(e), 'bad')
    }
  }

  return (
    <div className="stack">
      <p className="prose">Connect extra tools through MCP servers. Each one runs only on this computer, starts when needed, stops when idle, and can use only the tools you approve. Every call that reaches outside still asks you first.</p>
      <ErrorNote text={list.error} />
      {servers.length === 0 && !list.loading && <Empty title="No connections yet">Add an MCP server to give Lilly more tools.</Empty>}
      <ul className="model-list">
        {servers.map((s) => {
          const missing = s.secret_vars.filter((v) => !v.present)
          return (
            <li key={s.name} className={`model${s.enabled ? '' : ' model-off'}`}>
              <div className="model-main">
                <div className="row wrap">
                  <strong>{s.name}</strong>
                  <span className="hint">{[s.command, ...s.args].join(' ').slice(0, 80)}</span>
                </div>
                <div className="row wrap">
                  <Pill tone={STATE_TONE[s.state]}>{STATE_TEXT[s.state]}</Pill>
                  <Pill tone={s.approved ? 'ok' : 'warn'}>{s.approved ? `${s.approved_tools.length} tool(s) approved` : 'tools not reviewed'}</Pill>
                  {missing.length > 0 && <Pill tone="warn">needs {missing.map((m) => m.var).join(', ')}</Pill>}
                  {s.last_used && <Pill>used {ago(s.last_used)}</Pill>}
                </div>
                {s.error && <p className="hint">{s.error}</p>}
              </div>
              <div className="model-actions">
                <Switch label={`Use ${s.name}`} checked={s.enabled} onChange={(v) => void act(() => api.patch(`/api/mcp/${s.name}`, { enabled: v }))} />
                <div className="row wrap">
                  {s.secret_vars.map((v) => <Button key={v.ref} small icon="key" onClick={() => setSecret({ ref: v.ref, present: v.present })}>{v.var}</Button>)}
                  <Button small onClick={() => setReviewing(s)}>{s.approved ? 'Tools' : 'Review tools'}</Button>
                  <Button small icon="edit" onClick={() => setEditing(s)}>Edit</Button>
                  <IconButton icon="trash" label={`Remove ${s.name}`} kind="danger" onClick={() => setRemoving(s.name)} />
                </div>
              </div>
            </li>
          )
        })}
      </ul>
      <div><Button icon="plus" onClick={() => setEditing('new')}>Add a connection</Button></div>
      {editing && <ServerDialog initial={editing === 'new' ? null : editing} onClose={() => setEditing(null)} onSaved={list.reload} />}
      {reviewing && <ReviewDialog server={reviewing} onClose={() => setReviewing(null)} onApproved={list.reload} />}
      {secret && <KeyDialog refName={secret.ref} present={secret.present} title="Secret value" onClose={() => setSecret(null)} onChanged={list.reload} />}
      {removing && (
        <Confirm
          title={`Remove ${removing}?`}
          danger
          confirm="Remove"
          body="Its approval and saved secret values are deleted. The program itself is not touched."
          onClose={() => setRemoving(null)}
          onConfirm={() => void act(() => api.del(`/api/mcp/${removing}`))}
        />
      )}
    </div>
  )
}
