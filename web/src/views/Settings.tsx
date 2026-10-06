import { useState } from 'react'
import { api, errorText } from '../api'
import { useLoad } from '../hooks'
import { useApp, type ThemePref } from '../store'
import { APPROVAL_MODES, MODES, type BrowserMode, type SystemInfo } from '../types'
import { Button, ErrorNote, Field, IconButton, PageHead, Segmented, Switch } from '../ui/kit'
import { ago, bytes, duration } from '../ui/format'
import { ChatAppsSection } from './ChatAppsSection'
import { DecisionsSection } from './DecisionsSection'
import { DevboxSection } from './DevboxSection'
import { McpSection } from './McpSection'
import { ModelsSection } from './ModelsSection'
import { SecuritySection } from './SecuritySection'
import { useSettingsDraft, type SettingsDraft } from './settingsDraft'

const SECTIONS = [
  { id: 'general', label: 'General' },
  { id: 'models', label: 'Models & keys' },
  { id: 'connections', label: 'Connections' },
  { id: 'chat', label: 'Chat apps' },
  { id: 'devbox', label: 'Devbox' },
  { id: 'quick', label: 'Quick decisions' },
  { id: 'privacy', label: 'Privacy & access' },
  { id: 'security', label: 'Security' },
  { id: 'data', label: 'Your data' },
  { id: 'about', label: 'About' },
] as const

const MODULES: { id: string; label: string; hint: string }[] = [
  { id: 'files', label: 'Files', hint: 'Let agents read and organise files in the folders you share.' },
  { id: 'web', label: 'Web', hint: 'Let agents search the web and read pages. Web content is always treated as untrusted.' },
  { id: 'memory', label: 'Memory', hint: 'Let agents remember short facts about you.' },
  { id: 'notes', label: 'Notes', hint: 'Let agents search and read your notes, and propose new ones. Nothing is saved until you have read it and approved.' },
  { id: 'skills', label: 'Skills', hint: 'Ready-made routines such as research and file organiser.' },
  { id: 'browser', label: 'Browser', hint: 'Let agents open pages in their own separate browser (your installed Chrome, Chromium, Edge or Brave, with an empty profile that holds none of your sign-ins). Page text is always treated as untrusted. Choose below how much it may do without asking.' },
  { id: 'devbox', label: 'Devbox', hint: 'Let agents you allow run commands and code in a sealed container: no network, and it can only see the one folder you share with it. Set it up under Devbox.' },
  { id: 'computer', label: 'Computer control', hint: 'Let agents you allow open links and apps, control the pointer and keyboard, and run commands in a shared folder. MANUAL asks, AUTO permits policy-safe actions, and OFF suppresses prompts without bypassing policy.' },
]

function General({ d }: { d: SettingsDraft }) {
  const theme = useApp((s) => s.theme)
  const setTheme = useApp((s) => s.setTheme)
  if (!d.current) return null
  const s = d.current
  return (
    <div className="stack">
      <div className="field">
        <span className="label">Appearance</span>
        <Segmented<ThemePref> label="Appearance" value={theme} onChange={setTheme} options={[{ value: 'system', label: 'Match my device' }, { value: 'light', label: 'Light' }, { value: 'dark', label: 'Dark' }]} />
        <p className="hint">Saved in this browser only.</p>
      </div>
      <div className="field">
        <span className="label">Approval mode</span>
        <Segmented
          label="Approval mode"
          value={s.approval_mode}
          onChange={(v) => d.edit((x) => ({ ...x, approval_mode: v }))}
          options={APPROVAL_MODES.map((m) => ({ value: m.value, label: m.name, hint: m.blurb }))}
        />
        <p className="hint">OFF never bypasses policy, permissions, sandboxing, or hard denials.</p>
      </div>
      <div className="field">
        <span className="label">Default freedom for new chats</span>
        <Segmented
          label="Default mode"
          value={s.default_mode}
          onChange={(v) => d.edit((x) => ({ ...x, default_mode: v }))}
          options={MODES.map((m) => ({ value: m.key, label: m.name, hint: m.blurb }))}
        />
        <p className="hint">{MODES.find((m) => m.key === s.default_mode)?.blurb} An agent can set its own mode.</p>
      </div>
      <Switch label="Keep this computer awake while Lilly works" hint="macOS only. Lilly holds the Mac awake just while a task runs, or always when this is on." checked={s.stay_awake} onChange={(v) => d.edit((x) => ({ ...x, stay_awake: v }))} />
    </div>
  )
}

function RootsEditor({ d }: { d: SettingsDraft }) {
  const [path, setPath] = useState('')
  if (!d.current) return null
  const roots = d.current.file_roots
  const add = () => {
    const p = path.trim()
    if (p && !roots.includes(p)) d.edit((s) => ({ ...s, file_roots: [...s.file_roots, p] }))
    setPath('')
  }
  return (
    <div className="field">
      <span className="label">Folders Lilly may work in</span>
      <p className="hint">Agents can only touch files inside these folders, in every mode. Choose specific folders, not your whole home folder. Lilly's own data folder and credential folders such as .ssh are always off limits.</p>
      <ul className="path-list">
        {roots.length === 0 && <li className="hint">None yet, so no agent can use files.</li>}
        {roots.map((r) => (
          <li key={r}><code>{r}</code><IconButton icon="trash" label={`Stop sharing ${r}`} kind="danger" onClick={() => d.edit((s) => ({ ...s, file_roots: s.file_roots.filter((x) => x !== r) }))} /></li>
        ))}
      </ul>
      <form className="inline-form" onSubmit={(e) => { e.preventDefault(); add() }}>
        <label className="sr-only" htmlFor="new-root">Folder path</label>
        <input id="new-root" placeholder="/Users/you/Documents/Lilly" value={path} onChange={(e) => setPath(e.target.value)} />
        <Button type="submit" icon="plus" disabled={!path.trim()}>Share folder</Button>
      </form>
    </div>
  )
}

const parseHosts = (raw: string) => raw.split('\n').map((h) => h.trim().toLowerCase()).filter(Boolean)

/** The sites as typed, one per line. The draft always holds the parsed list; the text keeps its blank lines until the field is left. */
function HostsInput({ id, hosts, onChange }: { id: string; hosts: string[]; onChange: (hosts: string[]) => void }) {
  const [raw, setRaw] = useState(hosts.join('\n'))
  const clean = hosts.join('\n')
  if (parseHosts(raw).join('\n') !== clean) setRaw(clean) // the draft changed from outside, such as Discard
  return <textarea id={id} rows={3} value={raw} onChange={(e) => { setRaw(e.target.value); onChange(parseHosts(e.target.value)) }} onBlur={() => setRaw(clean)} />
}

function BrowserCard({ d }: { d: SettingsDraft }) {
  if (!d.current) return null
  const b = d.current.browser
  const set = (change: Partial<typeof b>) => d.edit((x) => ({ ...x, browser: { ...x.browser, ...change } }))
  return (
    <div className="field">
      <span className="label">What the browser may do without asking</span>
      <Segmented<BrowserMode>
        label="Browser approvals"
        value={b.mode}
        onChange={(v) => set({ mode: v })}
        options={[
          { value: 'ask_every', label: 'Ask every time', hint: 'Every click, key press and typed text asks first.' },
          { value: 'ask_risky', label: 'Ask for risky things', hint: 'Plain clicking goes ahead. Anything that could send, buy, delete or sign in, and every form submit, asks.' },
          { value: 'allowlist', label: 'Trusted sites only', hint: 'Everything goes ahead on the sites you list, and asks anywhere else.' },
        ]}
      />
      {b.mode === 'allowlist' && (
        <Field label="Trusted sites" hint="One site per line, like example.com. Its subdomains count too.">
          {(id) => <HostsInput id={id} hosts={b.allow_hosts} onChange={(allow_hosts) => set({ allow_hosts })} />}
        </Field>
      )}
      <p className="hint">Whatever you choose, the agent never types passwords or card numbers, never uploads or downloads files, and only opens public web addresses. Anything it learns from a page still makes later changes ask you.</p>
      <Field label="Actions per task" hint="Clicks, key presses and typed texts one task may make.">
        {(id) => <input id={id} type="number" min={1} max={500} value={b.max_actions} onChange={(e) => set({ max_actions: Number(e.target.value) })} />}
      </Field>
    </div>
  )
}

function Privacy({ d }: { d: SettingsDraft }) {
  if (!d.current) return null
  const s = d.current
  const toggle = (id: string, on: boolean) => d.edit((x) => ({ ...x, modules: on ? [...x.modules, id] : x.modules.filter((m) => m !== id) }))
  return (
    <div className="stack">
      <RootsEditor d={d} />
      <fieldset className="stack">
        <legend className="label">What Lilly can use</legend>
        {MODULES.map((m) => <Switch key={m.id} label={m.label} hint={m.hint} checked={s.modules.includes(m.id)} onChange={(v) => toggle(m.id, v)} />)}
      </fieldset>
      {s.modules.includes('browser') && <BrowserCard d={d} />}
      <div className="field">
        <span className="label">Web search</span>
        <Segmented label="Search engine" value={s.search.engine} onChange={(v) => d.edit((x) => ({ ...x, search: { ...x.search, engine: v } }))} options={[{ value: 'duckduckgo', label: 'DuckDuckGo' }, { value: 'brave', label: 'Brave (needs a key)' }, { value: 'searxng', label: 'SearXNG (your own)' }]} />
        {s.search.engine === 'searxng' && (
          <Field label="SearXNG address">{(id) => <input id={id} placeholder="https://search.example.org" value={s.search.searxng_url ?? ''} onChange={(e) => d.edit((x) => ({ ...x, search: { ...x.search, searxng_url: e.target.value.trim() || null } }))} />}</Field>
        )}
        {s.search.engine === 'brave' && <p className="hint">Add your Brave key under Models &amp; keys after saving.</p>}
      </div>
    </div>
  )
}

function DataSection({ d }: { d: SettingsDraft }) {
  const info = useLoad<SystemInfo>('/api/system')
  const toast = useApp((s) => s.toast)
  const [busy, setBusy] = useState<string | null>(null)
  const run = async (name: string, fn: () => Promise<string>) => {
    setBusy(name)
    try {
      toast(await fn())
      info.reload()
    } catch (e) {
      toast(errorText(e), 'bad')
    } finally {
      setBusy(null)
    }
  }
  if (!d.current) return null
  const m = info.data?.maintenance
  return (
    <div className="stack">
      <Field label="Keep finished tasks for (days)" hint="Older finished tasks are removed; a small tamper-evident stub remains. 0 keeps everything.">
        {(id) => <input id={id} type="number" min={0} max={3650} value={d.current?.retention_days ?? 90} onChange={(e) => d.edit((x) => ({ ...x, retention_days: Number.parseInt(e.target.value || '0', 10) }))} />}
      </Field>
      <div className="field">
        <span className="label">Backup</span>
        <p className="hint">{m?.last_backup ? `Last backup ${ago(m.last_backup)} (${m.last_backup_file})${m.integrity_ok === false ? ', but the integrity check failed' : ''}.` : 'No backup yet this session. Lilly backs up once a day while it runs and keeps the newest seven.'}</p>
        <div className="row">
          <Button icon="download" busy={busy === 'backup'} onClick={() => void run('backup', async () => `Backed up as ${(await api.post<{ file: string }>('/api/data/backup')).file}`)}>Back up now</Button>
          <Button busy={busy === 'prune'} onClick={() => void run('prune', async () => `Removed ${(await api.post<{ removed: number }>('/api/data/prune')).removed} old task(s)`)}>Clean up old tasks now</Button>
        </div>
      </div>
      <div className="field">
        <span className="label">Export</span>
        <p className="hint">Conversations, memory, agents and notes as one JSON file. API keys are never included.</p>
        <a className="btn btn-plain" href="/api/data/export" download="lilly-export.json"><span>Download everything</span></a>
      </div>
      {info.data && <p className="hint">Your data lives in <code>{info.data.home}</code> on this computer.</p>}
    </div>
  )
}

function About() {
  const info = useLoad<SystemInfo>('/api/system')
  const i = info.data
  if (!i) return <ErrorNote text={info.error} />
  return (
    <div className="stack">
      <dl className="facts-grid">
        <div><dt>Lilly</dt><dd>version {i.version}</dd></div>
        <div><dt>Running for</dt><dd>{duration(i.uptime_s)}</dd></div>
        <div><dt>Working on</dt><dd>{i.running_tasks} task(s), {i.pending_approvals} waiting for you</dd></div>
        <div><dt>Keys are kept in</dt><dd>{i.key_store.kind === 'keychain' ? 'your system keychain' : i.key_store.kind === 'file' ? 'a private file (no keychain found)' : i.key_store.kind}</dd></div>
        <div><dt>This computer</dt><dd>{i.platform}</dd></div>
        <div><dt>Processor</dt><dd>{i.stats.cpu_percent}% busy</dd></div>
        <div><dt>Memory</dt><dd>{bytes(i.stats.memory.available)} free of {bytes(i.stats.memory.total)}</dd></div>
        <div><dt>Disk</dt><dd>{bytes(i.stats.disk.free)} free of {bytes(i.stats.disk.total)}</dd></div>
        <div><dt>Python</dt><dd>{i.python}</dd></div>
        <div><dt>Awake</dt><dd>{i.stay_awake_active ? 'holding the Mac awake' : 'not holding'}</dd></div>
      </dl>
    </div>
  )
}

function SaveBar({ d }: { d: SettingsDraft }) {
  if (!d.dirty && !d.error) return null
  return (
    <div className="savebar" role="region" aria-label="Unsaved settings">
      <span>{d.dirty ? 'You have unsaved changes.' : ''}</span>
      <ErrorNote text={d.error} />
      <Button onClick={d.revert}>Discard</Button>
      <Button kind="primary" busy={d.saving} disabled={!d.dirty} onClick={() => void d.save()}>Save changes</Button>
    </div>
  )
}

export function Settings({ section, go }: { section: string; go: (h: string) => void }) {
  const d = useSettingsDraft()
  const active = SECTIONS.find((s) => s.id === section) ?? SECTIONS[0]
  return (
    <div className="page page-wide">
      <PageHead title="Settings" sub="Everything Lilly does is controlled here." />
      <ErrorNote text={d.loadError} />
      {d.problems.length > 0 && (
        <div className="callout callout-warn" role="alert">
          <strong>Your settings file had problems, so defaults are shown. Saving replaces the file with what you see here.</strong>
          <ul>{d.problems.map((p) => <li key={p}>{p}</li>)}</ul>
        </div>
      )}
      <div className="settings">
        <nav className="settings-nav" aria-label="Settings sections">
          {SECTIONS.map((s) => (
            <a key={s.id} href={`#/settings/${s.id}`} aria-current={s.id === active.id ? 'page' : undefined} onClick={(e) => { e.preventDefault(); go(`/settings/${s.id}`) }}>{s.label}</a>
          ))}
        </nav>
        <section className="settings-body" aria-labelledby="settings-h">
          <h2 id="settings-h">{active.label}</h2>
          {active.id === 'general' && <General d={d} />}
          {active.id === 'models' && <ModelsSection d={d} />}
          {active.id === 'connections' && <McpSection />}
          {active.id === 'chat' && <ChatAppsSection d={d} />}
          {active.id === 'devbox' && <DevboxSection d={d} />}
          {active.id === 'quick' && <DecisionsSection d={d} />}
          {active.id === 'privacy' && <Privacy d={d} />}
          {active.id === 'security' && <SecuritySection d={d} />}
          {active.id === 'data' && <DataSection d={d} />}
          {active.id === 'about' && <About />}
        </section>
      </div>
      <SaveBar d={d} />
    </div>
  )
}
