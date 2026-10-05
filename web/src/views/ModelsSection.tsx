import { useState } from 'react'
import { api, errorText } from '../api'
import { useLoad } from '../hooks'
import { useApp } from '../store'
import type { KeyInfo, ModelSpec, ModelStatus, OllamaCheck } from '../types'
import { Button, Confirm, Dialog, Field, IconButton, Pill, Segmented, Switch } from '../ui/kit'
import { KeyDialog } from '../ui/KeyDialog'
import type { SettingsDraft } from './settingsDraft'

const PROVIDERS = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'mistral', label: 'Mistral' },
  { value: 'openrouter', label: 'OpenRouter' },
  { value: 'gemini', label: 'Google Gemini' },
  { value: 'ollama', label: 'Ollama (on this computer)' },
] as const

const BLANK: ModelSpec = {
  name: '', provider: 'mistral', model_id: '', local: false, enabled: true, caps: ['JSON'], max_label: 'PUBLIC',
  rpm: null, rpd: null, tz: 'America/Los_Angeles', key_ref: null, private_access: 'ask', trains: true, base_url: null, quick: false,
}

function numberOrNull(v: string): number | null {
  const n = Number.parseInt(v, 10)
  return Number.isFinite(n) && n > 0 ? n : null
}

function ModelDialog({ initial, onClose, onSave }: { initial: ModelSpec | null; onClose: () => void; onSave: (m: ModelSpec) => void }) {
  const [m, setM] = useState<ModelSpec>(initial ?? BLANK)
  const set = <K extends keyof ModelSpec>(k: K, v: ModelSpec[K]) => setM({ ...m, [k]: v })
  const hasCap = (c: string) => m.caps.includes(c)
  const toggleCap = (c: string, on: boolean) => set('caps', on ? [...m.caps, c] : m.caps.filter((x) => x !== c))
  const valid = /^[a-z0-9][a-z0-9._-]{0,47}$/.test(m.name) && m.model_id.trim() !== ''
  return (
    <Dialog
      wide
      title={initial ? `Edit ${initial.name}` : 'Add a model'}
      onClose={onClose}
      footer={<><Button onClick={onClose}>Cancel</Button><Button kind="primary" disabled={!valid} onClick={() => onSave({ ...m, max_label: m.local ? m.max_label : 'PUBLIC', trains: m.local ? false : m.trains })}>Done</Button></>}
    >
      <div className="grid-2">
        <Field label="Name" hint="Lowercase letters, numbers, dots, dashes.">
          {(id) => <input id={id} value={m.name} disabled={initial !== null} onChange={(e) => set('name', e.target.value.toLowerCase())} />}
        </Field>
        <Field label="Provider">
          {(id) => (
            <select id={id} value={m.provider} onChange={(e) => setM({ ...m, provider: e.target.value, local: e.target.value === 'ollama' ? true : m.local })}>
              {PROVIDERS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
            </select>
          )}
        </Field>
        <Field label="Model id" hint="Exactly as the provider names it.">{(id) => <input id={id} value={m.model_id} onChange={(e) => set('model_id', e.target.value)} />}</Field>
        <Field label="Server address (optional)" hint="Only for a provider on another address, such as Ollama on a different port.">
          {(id) => <input id={id} value={m.base_url ?? ''} placeholder="http://127.0.0.1:11434" onChange={(e) => set('base_url', e.target.value.trim() || null)} />}
        </Field>
        <Field label="Requests per minute" hint="From your provider's console. Leave empty for no limit.">
          {(id) => <input id={id} inputMode="numeric" value={m.rpm ?? ''} onChange={(e) => set('rpm', numberOrNull(e.target.value))} />}
        </Field>
        <Field label="Requests per day" hint="Lilly stops before your daily free quota runs out.">
          {(id) => <input id={id} inputMode="numeric" value={m.rpd ?? ''} onChange={(e) => set('rpd', numberOrNull(e.target.value))} />}
        </Field>
        <Field label="Daily limit resets in time zone">{(id) => <input id={id} value={m.tz} onChange={(e) => set('tz', e.target.value)} />}</Field>
        <Field label="Key name (optional)" hint="Lets two models share one saved key.">{(id) => <input id={id} value={m.key_ref ?? ''} placeholder={m.provider} onChange={(e) => set('key_ref', e.target.value.trim() || null)} />}</Field>
      </div>
      <Switch label="Runs on this computer" hint="Nothing goes over the internet. The address must be this computer or a private network (for example 192.168.x.x or Tailscale)." checked={m.local} onChange={(v) => setM({ ...m, local: v, trains: v ? false : m.trains, max_label: v ? m.max_label : 'PUBLIC' })} />
      {m.local && (
        <div className="field">
          <span className="label">Most private data it may always see</span>
          <Segmented label="Standing access" value={m.max_label} onChange={(v) => set('max_label', v)} options={[{ value: 'PUBLIC', label: 'Public only' }, { value: 'PERSONAL', label: 'Personal too' }]} />
        </div>
      )}
      <Switch label="Use first for quick steps" hint="Small, simple jobs (a short summary, a yes/no) try this model before the others, which saves quota on your stronger models. Planning always uses your normal order." checked={m.quick} onChange={(v) => set('quick', v)} />
      {!m.local && <Switch label="May train on or show your inputs" hint="Free tiers often do. Lilly then asks you before sending anything private." checked={m.trains} onChange={(v) => set('trains', v)} />}
      <div className="field">
        <span className="label">Private data</span>
        <Segmented label="Private data" value={m.private_access} onChange={(v) => set('private_access', v)} options={[{ value: 'ask', label: 'May ask me first' }, { value: 'never', label: 'Never send' }]} />
      </div>
      <Switch label="Reliable structured output" hint="Needed for planning. Turn off for small models that cannot do it." checked={hasCap('JSON')} onChange={(v) => toggleCap('JSON', v)} />
      <Switch label="Long documents" hint="Can read very long inputs." checked={hasCap('LONG_CONTEXT')} onChange={(v) => toggleCap('LONG_CONTEXT', v)} />
    </Dialog>
  )
}

function OllamaDialog({ name, onClose, onPick }: { name: string; onClose: () => void; onPick: (modelId: string) => void }) {
  const check = useLoad<OllamaCheck>(`/api/models/${name}/ollama`)
  const c = check.data
  return (
    <Dialog title="Ollama on this computer" onClose={onClose} footer={<><Button onClick={check.reload}>Check again</Button><Button kind="primary" onClick={onClose}>Close</Button></>}>
      {check.loading && !c && <p className="prose">Checking…</p>}
      {c && <p className={`callout ${c.reachable && c.model_ready !== false ? '' : 'callout-warn'}`} role="status">{c.message}</p>}
      {check.error && <p className="callout callout-warn" role="alert">{check.error}</p>}
      {c && c.reachable && (
        <div className="stack">
          <span className="label">Installed models{c.version ? ` (Ollama ${c.version})` : ''}</span>
          {c.models.length === 0 && <p className="hint">None yet. Install one with: ollama pull llama3.2</p>}
          <div className="row wrap">{c.models.map((m) => <Button key={m} small onClick={() => { onPick(m); onClose() }}>{m}</Button>)}</div>
          {c.models.length > 0 && <p className="hint">Choose one to use it for this model. Save your changes afterwards.</p>}
        </div>
      )}
    </Dialog>
  )
}

export function ModelsSection({ d }: { d: SettingsDraft }) {
  const status = useLoad<{ models: ModelStatus[] }>('/api/models', true)
  const keys = useLoad<{ store: { kind: string; secure: boolean }; keys: KeyInfo[] }>('/api/keys')
  const [editing, setEditing] = useState<ModelSpec | 'new' | null>(null)
  const [keyFor, setKeyFor] = useState<string | null>(null)
  const [removing, setRemoving] = useState<string | null>(null)
  const [testing, setTesting] = useState<string | null>(null)
  const [ollama, setOllama] = useState<string | null>(null)
  const toast = useApp((s) => s.toast)
  if (!d.current) return null
  const models = d.current.models
  const stat = (name: string) => status.data?.models.find((s) => s.name === name)
  const hasKey = (ref: string) => keys.data?.keys.find((k) => k.ref === ref)?.present ?? false

  const move = (i: number, by: number) => d.edit((s) => {
    const next = [...s.models]
    const [item] = next.splice(i, 1)
    next.splice(i + by, 0, item)
    return { ...s, models: next }
  })
  const replace = (name: string, change: (m: ModelSpec) => ModelSpec) => d.edit((s) => ({ ...s, models: s.models.map((m) => (m.name === name ? change(m) : m)) }))

  const test = async (name: string) => {
    setTesting(name)
    try {
      const r = await api.post<{ ok: boolean; error?: string; latency_ms?: number }>(`/api/models/${name}/test`)
      toast(r.ok ? `${name} works (${r.latency_ms} ms)` : `${name}: ${r.error ?? 'failed'}`, r.ok ? 'ok' : 'bad')
      status.reload()
    } catch (e) {
      toast(errorText(e), 'bad')
    } finally {
      setTesting(null)
    }
  }

  return (
    <div className="stack">
      <p className="prose">Lilly tries your models from the top. If one is busy, over its limits or down, it moves to the next. Reorder them to change who goes first.</p>
      {keys.data && !keys.data.store.secure && (
        <p className="callout callout-warn" role="note">
          No system keychain was found, so keys are kept in a private file (readable only by you). That is weaker than a keychain: anything running as you could read it.
        </p>
      )}
      <ul className="model-list">
        {models.map((m, i) => {
          const s = stat(m.name)
          const ref = m.key_ref ?? m.provider
          const needsKey = !m.local
          const ready = !needsKey || hasKey(ref)
          return (
            <li key={m.name} className={`model${m.enabled ? '' : ' model-off'}`}>
              <div className="model-order">
                <IconButton icon="up" label={`Move ${m.name} up`} disabled={i === 0} onClick={() => move(i, -1)} />
                <span aria-hidden="true" className="model-rank">{i + 1}</span>
                <IconButton icon="down" label={`Move ${m.name} down`} disabled={i === models.length - 1} onClick={() => move(i, 1)} />
              </div>
              <div className="model-main">
                <div className="row wrap">
                  <strong>{m.name}</strong>
                  <span className="hint">{m.provider} · {m.model_id}</span>
                </div>
                <div className="row wrap">
                  {m.local ? <Pill tone="ok">on this computer</Pill> : <Pill tone={ready ? 'ok' : 'warn'}>{ready ? 'key saved' : 'needs a key'}</Pill>}
                  {s && s.breaker !== 'closed' && <Pill tone="bad">{s.breaker}</Pill>}
                  {s?.last_error && <Pill tone="bad">{s.last_error}</Pill>}
                  {s && s.rpd !== null && <Pill>{s.day_used}/{s.rpd} today</Pill>}
                  {s && s.rpm !== null && <Pill>{s.minute_used}/{s.rpm} per min</Pill>}
                  {s?.suggested_rpm != null && (
                    <Button small title="This provider refused calls after about this many in a minute" onClick={() => replace(m.name, (x) => ({ ...x, rpm: s.suggested_rpm }))}>
                      Limit it to {s.suggested_rpm} per minute?
                    </Button>
                  )}
                  {s?.suggested_rpd != null && (
                    <Button small title="This provider refused calls after about this many in a day" onClick={() => replace(m.name, (x) => ({ ...x, rpd: s.suggested_rpd }))}>
                      Limit it to {s.suggested_rpd} per day?
                    </Button>
                  )}
                  {!m.local && m.trains && <Pill tone="warn">may train on inputs</Pill>}
                </div>
              </div>
              <div className="model-actions">
                <Switch label={`Use ${m.name}`} checked={m.enabled} onChange={(v) => replace(m.name, (x) => ({ ...x, enabled: v }))} />
                <div className="row wrap">
                  {needsKey && <Button small icon="key" disabled={d.dirty} title={d.dirty ? 'Save your changes first' : undefined} onClick={() => setKeyFor(ref)}>Key</Button>}
                  <Button small busy={testing === m.name} disabled={d.dirty} title={d.dirty ? 'Save your changes first' : undefined} onClick={() => void test(m.name)}>Test</Button>
                  {m.provider === 'ollama' && <Button small disabled={d.dirty} title={d.dirty ? 'Save your changes first' : undefined} onClick={() => setOllama(m.name)}>Check Ollama</Button>}
                  <Button small icon="edit" onClick={() => setEditing(m)}>Edit</Button>
                  <IconButton icon="trash" label={`Remove ${m.name}`} kind="danger" onClick={() => setRemoving(m.name)} />
                </div>
              </div>
            </li>
          )
        })}
      </ul>
      <div><Button icon="plus" onClick={() => setEditing('new')}>Add a model</Button></div>
      {editing && (
        <ModelDialog
          initial={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
          onSave={(m) => {
            if (editing === 'new') d.edit((s) => ({ ...s, models: s.models.some((x) => x.name === m.name) ? s.models : [...s.models, m] }))
            else replace(m.name, () => m)
            setEditing(null)
          }}
        />
      )}
      {ollama && <OllamaDialog name={ollama} onClose={() => setOllama(null)} onPick={(id) => replace(ollama, (x) => ({ ...x, model_id: id }))} />}
      {keyFor && <KeyDialog refName={keyFor} present={hasKey(keyFor)} onClose={() => setKeyFor(null)} onChanged={() => { keys.reload(); status.reload() }} />}
      {removing && (
        <Confirm
          title={`Remove ${removing}?`}
          danger
          confirm="Remove"
          body="It is removed when you save. Its saved key stays in your keychain until you delete it."
          onClose={() => setRemoving(null)}
          onConfirm={() => d.edit((s) => ({ ...s, models: s.models.filter((m) => m.name !== removing) }))}
        />
      )}
    </div>
  )
}
