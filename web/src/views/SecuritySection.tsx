import { useState } from 'react'
import { api, configureApi, errorText } from '../api'
import { useApp } from '../store'
import { Button, Confirm, Dialog, Field, IconButton } from '../ui/kit'
import type { SettingsDraft } from './settingsDraft'

type Pending = 'everywhere' | 'token' | 'stop' | 'permissions' | null

export function SecuritySection({ d }: { d: SettingsDraft }) {
  const toast = useApp((s) => s.toast)
  const setAuth = useApp((s) => s.setAuth)
  const [ask, setAsk] = useState<Pending>(null)
  const [newToken, setNewToken] = useState<string | null>(null)
  const [host, setHost] = useState('')

  const act = async (fn: () => Promise<void>) => {
    try {
      await fn()
    } catch (e) {
      toast(errorText(e), 'bad')
    }
  }

  const signOut = () => act(async () => {
    await api.post('/api/logout')
    setAuth('out')
  })
  const everywhere = () => act(async () => {
    const r = await api.post<{ csrf: string }>('/api/session/revoke-all')
    configureApi(r.csrf, () => setAuth('out'))
    toast('Every other browser is signed out')
  })
  const replaceToken = () => act(async () => {
    const r = await api.post<{ csrf: string; token: string }>('/api/session/token')
    configureApi(r.csrf, () => setAuth('out'))
    setNewToken(r.token)
  })
  const stop = () => act(async () => {
    const r = await api.post<{ stopped: number }>('/api/stop')
    toast(r.stopped ? `Stopped ${r.stopped} task(s)` : 'Nothing was running')
  })
  const permissions = () => act(async () => {
    const r = await api.post<{ revoked: number }>('/api/permissions/revoke-all')
    toast(r.revoked ? `Withdrew ${r.revoked} model permission(s)` : 'No model permissions were active')
  })

  if (!d.current) return null
  const hosts = d.current.network.allowed_hosts
  const addHost = () => {
    const h = host.trim().toLowerCase()
    if (h && !hosts.includes(h)) d.edit((s) => ({ ...s, network: { allowed_hosts: [...hosts, h] } }))
    setHost('')
  }

  return (
    <div className="stack">
      <div className="field">
        <span className="label">Signed in on this browser</span>
        <p className="hint">Lilly only answers requests that carry your sign-in. Sessions last 30 days.</p>
        <div className="row wrap">
          <Button icon="lock" onClick={() => void signOut()}>Sign out</Button>
          <Button onClick={() => setAsk('everywhere')}>Sign out everywhere else</Button>
          <Button onClick={() => setAsk('token')}>Replace access token</Button>
        </div>
      </div>
      <div className="field">
        <span className="label">Emergency controls</span>
        <div className="row wrap">
          <Button kind="danger" icon="stop" onClick={() => setAsk('stop')}>Stop everything now</Button>
          <Button onClick={() => setAsk('permissions')}>Withdraw model permissions</Button>
        </div>
        <p className="hint">Stopping cancels every running task within a second. Lilly keeps working normally afterwards. Model permissions you granted for private data are also forgotten whenever Lilly restarts.</p>
      </div>
      <div className="field">
        <span className="label">Reaching Lilly from your phone</span>
        <p className="hint">Lilly only listens on this computer. To use it from your phone, put it behind <strong>Tailscale Serve</strong> (private to your devices) and add that address here so Lilly will answer to it. Never expose it to the public internet.</p>
        <ul className="path-list">
          {hosts.map((h) => <li key={h}><code>{h}</code><IconButton icon="trash" label={`Remove ${h}`} kind="danger" onClick={() => d.edit((s) => ({ ...s, network: { allowed_hosts: hosts.filter((x) => x !== h) } }))} /></li>)}
        </ul>
        <form className="inline-form" onSubmit={(e) => { e.preventDefault(); addHost() }}>
          <label className="sr-only" htmlFor="new-host">Host name</label>
          <input id="new-host" placeholder="my-mac.tail1234.ts.net" value={host} onChange={(e) => setHost(e.target.value)} />
          <Button type="submit" disabled={!host.trim()}>Allow this address</Button>
        </form>
      </div>

      {ask === 'everywhere' && <Confirm title="Sign out everywhere else?" confirm="Sign out others" body="Every other browser and device must sign in again. This one stays signed in." onClose={() => setAsk(null)} onConfirm={() => void everywhere()} />}
      {ask === 'token' && <Confirm title="Replace the access token?" confirm="Replace token" danger body="A new token is created and shown once. The old one stops working and every other browser is signed out." onClose={() => setAsk(null)} onConfirm={() => void replaceToken()} />}
      {ask === 'stop' && <Confirm title="Stop everything?" confirm="Stop all tasks" danger body="Every running or waiting task is cancelled." onClose={() => setAsk(null)} onConfirm={() => void stop()} />}
      {ask === 'permissions' && <Confirm title="Withdraw model permissions?" confirm="Withdraw" body="Models you allowed to see private data for a task lose that permission immediately." onClose={() => setAsk(null)} onConfirm={() => void permissions()} />}
      {newToken && (
        <Dialog title="Your new access token" onClose={() => setNewToken(null)} footer={<Button kind="primary" onClick={() => setNewToken(null)}>I have saved it</Button>}>
          <p className="prose">This is shown once. You can also read it any time on this computer with <code>lilly token</code>.</p>
          <Field label="Access token">{(id) => <input id={id} readOnly value={newToken} onFocus={(e) => e.currentTarget.select()} />}</Field>
        </Dialog>
      )}
    </div>
  )
}
