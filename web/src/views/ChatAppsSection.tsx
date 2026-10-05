import { useCallback, useState } from 'react'
import { api, errorText } from '../api'
import { useInterval, useLoad } from '../hooks'
import { useApp } from '../store'
import type { Agent, BridgeStatus } from '../types'
import { ago } from '../ui/format'
import { Button, Confirm, ErrorNote, Field, Pill, Switch } from '../ui/kit'
import type { SettingsDraft } from './settingsDraft'

const PAIR_WINDOW = 'Send this code to your bot in a private chat within 10 minutes.'

export function ChatAppsSection({ d }: { d: SettingsDraft }) {
  const status = useLoad<{ telegram: BridgeStatus }>('/api/bridges')
  const agents = useLoad<{ agents: Agent[] }>('/api/agents')
  const toast = useApp((s) => s.toast)
  const [token, setToken] = useState('')
  const [code, setCode] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [removeToken, setRemoveToken] = useState(false)
  const s = status.data?.telegram
  const reload = status.reload
  const waiting = s?.pairing_until != null   // the server reports null once the code has run out
  // While a code is open, look for the new link now and then; a hidden tab does nothing.
  useInterval(useCallback(() => { if (waiting && !document.hidden) reload() }, [waiting, reload]), 3000)

  const act = async (run: () => Promise<unknown>, done?: string) => {
    setBusy(true)
    try {
      await run()
      setError(null)
      reload()
      if (done) toast(done)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  const b = d.current?.bridges
  if (!s || !b) return <ErrorNote text={status.error ?? d.loadError} />
  const chatAgents = (agents.data?.agents ?? []).filter((a) => a.chat_allowed)

  return (
    <div className="stack">
      <p className="hint">Talk to Lilly from Telegram. Lilly only asks Telegram for messages (nothing connects in to this computer). Only accounts you link with a one-time code can talk to it, and what comes in from chat is treated as outside text.</p>
      <ErrorNote text={error ?? s.error} />
      <section className="card stack" aria-labelledby="tg-h">
        <h3 id="tg-h">Telegram {s.bot && <span className="hint">@{s.bot}</span>} {s.running ? <Pill tone="ok">listening</Pill> : <Pill>stopped</Pill>}</h3>
        {!s.token_set ? (
          <form className="stack" onSubmit={(e) => { e.preventDefault(); void act(async () => { await api.put('/api/bridges/telegram/token', { token }); setToken('') }, 'Bot connected') }}>
            <Field label="Bot token" hint="Make a bot with @BotFather in Telegram and paste its token here. It is kept in your key store and never shown again.">
              {(id) => <input id={id} type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} />}
            </Field>
            <div className="row"><Button type="submit" busy={busy} disabled={!token.trim()}>Connect bot</Button></div>
          </form>
        ) : (
          <div className="row">
            <Button onClick={() => void act(async () => { const r = await api.post<{ code: string }>('/api/bridges/telegram/pairing'); setCode(r.code) })} busy={busy}>Link a Telegram account</Button>
            <Button kind="danger" onClick={() => setRemoveToken(true)}>Remove bot</Button>
          </div>
        )}
        {waiting && code && <p role="status"><strong className="pair-code">{code}</strong> <span className="hint">{PAIR_WINDOW}</span></p>}
        <h4>Linked accounts</h4>
        {s.identities.length === 0 && <p className="hint">No one is linked yet. Strangers who message the bot get no reply.</p>}
        <ul className="plain-list">
          {s.identities.map((i) => (
            <li key={i.user_id} className="row-between">
              <span>{i.label} <span className="hint">linked {ago(i.paired_at)}</span></span>
              <Button kind="danger" onClick={() => void act(() => api.del(`/api/bridges/telegram/identities/${i.user_id}`), 'Unlinked')}>Unlink</Button>
            </li>
          ))}
        </ul>
      </section>
      <section className="card stack" aria-labelledby="tg-set">
        <h3 id="tg-set">How chat behaves</h3>
        <Switch label="Answer messages from linked accounts" checked={b.enabled} onChange={(v) => d.edit((x) => ({ ...x, bridges: { ...x.bridges, enabled: v } }))} />
        <Field label="Agent that answers" hint={chatAgents.length === 0 ? 'No agent is reachable from chat yet. Turn on “Reachable from chat apps” on an agent first.' : undefined}>
          {(id) => (
            <select id={id} value={b.agent_id ?? ''} onChange={(e) => d.edit((x) => ({ ...x, bridges: { ...x.bridges, agent_id: e.target.value || null } }))}>
              <option value="">Choose an agent…</option>
              {chatAgents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          )}
        </Field>
        <Switch label="Send private answers to chat" hint="Off: an answer that used personal data stays in the Lilly app and chat only says it is ready." checked={b.private_replies} onChange={(v) => d.edit((x) => ({ ...x, bridges: { ...x.bridges, private_replies: v } }))} />
        <Field label="Messages per minute, per person">
          {(id) => <input id={id} type="number" min={1} max={30} value={b.per_minute} onChange={(e) => d.edit((x) => ({ ...x, bridges: { ...x.bridges, per_minute: Number(e.target.value) } }))} />}
        </Field>
        <Field label="Longest message accepted (characters)">
          {(id) => <input id={id} type="number" min={100} max={4000} step={100} value={b.max_chars} onChange={(e) => d.edit((x) => ({ ...x, bridges: { ...x.bridges, max_chars: Number(e.target.value) } }))} />}
        </Field>
      </section>
      {removeToken && (
        <Confirm title="Remove the bot?" body="Lilly stops listening and forgets the token. Linked accounts stay on the list for if you add a bot again." confirm="Remove" danger
          onConfirm={() => { setRemoveToken(false); setCode(null); void act(() => api.del('/api/bridges/telegram/token'), 'Bot removed') }} onClose={() => setRemoveToken(false)} />
      )}
    </div>
  )
}
