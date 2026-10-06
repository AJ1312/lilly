import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, configureApi, errorText } from './api'
import { useHash } from './hooks'
import { NAV } from './nav'
import { useApp } from './store'
import { Companion } from './ui/Companion'
import { Icon, Petals } from './ui/Icon'
import { Palette } from './ui/Palette'
import { Button, Confirm, ErrorNote, Field, Toasts } from './ui/kit'
import { FirstRunWizard } from './ui/FirstRunWizard'
import { Activity } from './views/Activity'
import { Agents } from './views/Agents'
import { Approvals } from './views/Approvals'
import { Memory } from './views/Memory'
import { Notes } from './views/Notes'
import { Resources } from './views/Resources'
import { Routines } from './views/Routines'
import { Settings } from './views/Settings'
import { Workspace } from './views/Workspace'

interface Session { signed_in: boolean; csrf?: string }

type LiveMessage = { type: 'text'; task_id: string; text: string } | { type: 'task'; task_id: string; state: string } | { type: 'computer'; task_id: string; frame_id: string; changed: boolean } | { type: 'other' }
const FINISHED = ['DONE', 'FAILED', 'CANCELLED', 'EXPIRED']
const RETRY_MIN_MS = 1000
const RETRY_MAX_MS = 30000

function parseLive(raw: string): LiveMessage | null {
  try {
    const m = JSON.parse(raw) as Record<string, unknown>
    if (m.type === 'text' && typeof m.task_id === 'string' && typeof m.text === 'string') return { type: 'text', task_id: m.task_id, text: m.text }
    if (m.type === 'task' && typeof m.task_id === 'string' && typeof m.state === 'string') return { type: 'task', task_id: m.task_id, state: m.state }
    if (m.type === 'computer' && typeof m.task_id === 'string' && typeof m.frame_id === 'string' && typeof m.changed === 'boolean') return { type: 'computer', task_id: m.task_id, frame_id: m.frame_id, changed: m.changed }
    return { type: 'other' }
  } catch {
    return null
  }
}

function SignIn({ onDone }: { onDone: (csrf: string) => void }) {
  const [token, setToken] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    try {
      const r = await api.post<{ csrf: string }>('/api/login', { token })
      onDone(r.csrf)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <main className="signin">
      <form onSubmit={(e) => void submit(e)}>
        <span className="signin-mark"><Petals size={64} /></span>
        <h1>Lilly</h1>
        <p className="sub">A private assistant that lives on your computer.</p>
        <Field label="Access token" hint="On the computer running Lilly, open a terminal and run `lilly open`, or `lilly token` to see it.">
          {(id) => <input id={id} type="password" autoComplete="current-password" value={token} onChange={(e) => setToken(e.target.value)} autoFocus />}
        </Field>
        <ErrorNote text={error} />
        <Button type="submit" kind="primary" busy={busy} disabled={!token.trim()}>Sign in</Button>
      </form>
    </main>
  )
}


function Shell() {
  const [hash, go] = useHash()
  const [, section, rest] = hash.split('/')
  const pending = useApp((s) => s.pending)
  const live = useApp((s) => s.live)
  const theme = useApp((s) => s.theme)
  const setTheme = useApp((s) => s.setTheme)
  const toast = useApp((s) => s.toast)
  const [stopAsk, setStopAsk] = useState(false)
  const [jump, setJump] = useState(false)
  const [wizard, setWizard] = useState(() => localStorage.getItem('lilly.firstRunComplete') !== '2.0')
  const dark = theme === 'dark' || (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)

  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setJump((open) => !open) }
    }
    window.addEventListener('keydown', on)
    return () => window.removeEventListener('keydown', on)
  }, [])

  const here = NAV.find((n) => n.path === (section ?? 'talk'))?.label ?? 'Lilly'
  useEffect(() => { document.title = `${pending > 0 ? `(${pending}) ` : ''}${here} · Lilly` }, [here, pending])

  useEffect(() => { // on a phone the bar scrolls sideways: keep the open view in sight
    document.getElementById(`nav-${section ?? 'talk'}`)?.scrollIntoView({ inline: 'center', block: 'nearest' })
  }, [section])

  const view = (() => {
    switch (section) {
      case 'approvals': return <Approvals />
      case 'activity': return <Activity taskId={rest ?? null} go={go} />
      case 'notes': return <Notes />
      case 'memory': return <Memory />
      case 'agents': return <Agents />
      case 'routines': return <Routines />
      case 'resources': return <Resources />
      case 'settings': return <Settings section={rest ?? 'general'} go={go} />
      default: return <Workspace />
    }
  })()

  return (
    <div className="shell">
      <button type="button" className="skip" onClick={() => document.getElementById('main')?.focus()}>Skip to content</button>
      <nav className="rail" aria-label="Main">
        <a className="brand" href="#/talk"><Petals size={26} /><span>Lilly</span></a>
        <button type="button" className="rail-search" onClick={() => setJump(true)} aria-keyshortcuts="Control+K Meta+K">
          <Icon name="search" size={15} /><span>Jump to…</span><kbd>{/Mac|iPhone|iPad/.test(navigator.userAgent) ? '⌘K' : 'Ctrl K'}</kbd>
        </button>
        <ul>
          {NAV.map((n) => (
            <li key={n.path}>
              <a id={`nav-${n.path}`} href={`#/${n.path}`} aria-current={(section ?? 'talk') === n.path ? 'page' : undefined}>
                <Icon name={n.icon} />
                <span>{n.label}</span>
                {n.path === 'approvals' && pending > 0 && <span className="badge" aria-label={`${pending} waiting`}>{pending}</span>}
              </a>
            </li>
          ))}
        </ul>
        <Companion go={go} />
        <div className="rail-foot">
          <span className={`live ${live ? 'live-on' : ''}`}><span className="dot" aria-hidden="true" />{live ? 'Live' : 'Reconnecting…'}</span>
          <button type="button" className="icon-btn" aria-label={dark ? 'Switch to light theme' : 'Switch to dark theme'} onClick={() => setTheme(dark ? 'light' : 'dark')}>
            <Icon name={dark ? 'sun' : 'moon'} />
          </button>
          <button type="button" className="kill" onClick={() => setStopAsk(true)}><Icon name="stop" size={15} /> Stop all</button>
        </div>
      </nav>
      <main className="stage" id="main" tabIndex={-1}>{view}</main>
      {jump && (
        <Palette
          go={go}
          onClose={() => setJump(false)}
          actions={[
            { id: 'new', label: 'New chat', icon: 'plus', run: () => go('/talk') },
            { id: 'theme', label: dark ? 'Switch to light theme' : 'Switch to dark theme', icon: dark ? 'sun' : 'moon', run: () => setTheme(dark ? 'light' : 'dark') },
            { id: 'stop', label: 'Stop all tasks…', icon: 'stop', run: () => setStopAsk(true) },
          ]}
        />
      )}
      {stopAsk && (
        <Confirm
          title="Stop everything?"
          danger
          confirm="Stop all tasks"
          body="Every running or waiting task is cancelled right away. Nothing is lost, and you can start again straight after."
          onClose={() => setStopAsk(false)}
          onConfirm={() => {
            api.post<{ stopped: number }>('/api/stop').then((r) => toast(r.stopped ? `Stopped ${r.stopped} task(s)` : 'Nothing was running')).catch((e: unknown) => toast(errorText(e), 'bad'))
          }}
        />
      )}
      {wizard && <FirstRunWizard onDone={() => setWizard(false)} />}
    </div>
  )
}

export default function App() {
  const auth = useApp((s) => s.auth)
  const setAuth = useApp((s) => s.setAuth)
  const bump = useApp((s) => s.bump)
  const setLive = useApp((s) => s.setLive)
  const setPending = useApp((s) => s.setPending)
  const setStream = useApp((s) => s.setStream)
  const clearStream = useApp((s) => s.clearStream)

  useEffect(() => {
    api.get<Session>('/api/session').then((s) => {
      if (s.signed_in && s.csrf) configureApi(s.csrf, () => setAuth('out'))
      setAuth(s.signed_in ? 'in' : 'out')
    }).catch(() => setAuth('out'))
  }, [setAuth])

  const refreshPending = useCallback(() => {
    api.get<{ approvals: unknown[] }>('/api/approvals?status=pending').then((r) => setPending(r.approvals.length)).catch(() => {})
  }, [setPending])

  useEffect(() => {
    if (auth !== 'in') return
    // Every (throttled) change report also refreshes the badge, so a burst of events asks once.
    const unsubscribe = useApp.subscribe((s, prev) => { if (s.tick !== prev.tick) refreshPending() })
    let source: EventSource | undefined
    let retry: ReturnType<typeof setTimeout> | undefined
    let wait = RETRY_MIN_MS
    let missed = false // something changed while this tab was hidden
    const reconnectLater = () => { retry = setTimeout(connect, wait); wait = Math.min(wait * 2, RETRY_MAX_MS) }
    const connect = () => {
      const es = new EventSource('/api/events')
      source = es
      es.onopen = () => { wait = RETRY_MIN_MS; setLive(true); bump() } // whatever happened while we were away, look again
      es.onerror = () => {
        setLive(false)
        if (es.readyState !== EventSource.CLOSED) return // the browser is reconnecting by itself
        es.close() // the server refused the stream: find out why before trying again
        api.get<Session>('/api/session').then((s) => { if (s.signed_in) reconnectLater(); else setAuth('out') }).catch(reconnectLater)
      }
      es.onmessage = (e: MessageEvent<string>) => {
        const m = parseLive(e.data)
        if (m?.type === 'text') { setStream(m.task_id, m.text); return } // text as it is written: show it, reload nothing
        if (m?.type === 'task' && FINISHED.includes(m.state)) clearStream(m.task_id)
        if (document.hidden) missed = true
        else bump()
      }
    }
    connect()
    const onVisible = () => { if (!document.hidden && missed) { missed = false; bump() } }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      document.removeEventListener('visibilitychange', onVisible)
      unsubscribe()
      clearTimeout(retry)
      source?.close()
      setLive(false)
    }
  }, [auth, bump, setAuth, setLive, refreshPending, setStream, clearStream])

  if (auth === 'loading') return <div className="boot"><Petals size={48} /></div>
  return (
    <>
      {auth === 'out' ? <SignIn onDone={(csrf) => { configureApi(csrf, () => setAuth('out')); setAuth('in') }} /> : <Shell />}
      <Toasts />
    </>
  )
}
