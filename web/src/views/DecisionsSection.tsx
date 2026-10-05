import { api, errorText } from '../api'
import { useLoad } from '../hooks'
import { useApp } from '../store'
import type { DecisionKind, DecisionRow, DeciderSummary } from '../types'
import { ago } from '../ui/format'
import { Button, ErrorNote, Switch } from '../ui/kit'
import { LayaSetup } from './LayaSetup'
import type { SettingsDraft } from './settingsDraft'

const KINDS: { id: DecisionKind; label: string; hint: string }[] = [
  { id: 'tools', label: 'Choosing tools to show the planner', hint: 'Fewer tools in the prompt means fewer tokens. If nothing is sure, the whole list is shown.' },
  { id: 'loop', label: 'Stopping a run that goes round in circles', hint: 'Spots repeated steps. If unsure, nothing is stopped.' },
  { id: 'instructions', label: 'Spotting orders hidden in data', hint: 'Can only add caution: text that reads like orders is treated as outside text.' },
  { id: 'pick', label: 'Picking from a short list', hint: 'An app, a page element, a result. If unsure, you are asked.' },
]

function Summary({ rows }: { rows: DeciderSummary[] }) {
  if (rows.length === 0) return <p className="hint">Nothing has been decided yet. Rows appear here as Lilly works.</p>
  return (
    <table className="decide-table">
      <thead><tr><th scope="col">Question</th><th scope="col">Decider</th><th scope="col">Asked</th><th scope="col">Answered</th><th scope="col">Right</th><th scope="col">Wrong</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={`${r.kind}-${r.decider ?? 'none'}`}>
            <td>{r.kind}</td><td>{r.decider ?? 'nobody was sure'}</td><td>{r.decisions}</td><td>{r.answered}{r.shadow ? ` (${r.shadow} shadow)` : ''}</td><td>{r.accepted}</td><td>{r.corrected}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Recent({ rows, reload }: { rows: DecisionRow[]; reload: () => void }) {
  const toast = useApp((s) => s.toast)
  const mark = async (id: number, outcome: 'accepted' | 'corrected') => {
    try {
      await api.post(`/api/decisions/${id}/outcome`, { outcome })
      reload()
    } catch (e) {
      toast(errorText(e), 'bad')
    }
  }
  if (rows.length === 0) return null
  return (
    <ul className="plain-list">
      {rows.slice(0, 8).map((r) => (
        <li key={r.id} className="row-between">
          <span><strong>{r.kind}</strong> · {r.decider ?? 'no decider'} → {r.choice ?? 'no decision'}{r.confidence !== null ? ` (${Math.round(r.confidence * 100)}%)` : ''}{r.shadow ? ' · shadow' : ''} <span className="hint">{ago(r.ts)}</span></span>
          {r.choice !== null && (
            <span className="row">
              <Button small disabled={r.outcome === 'accepted'} onClick={() => void mark(r.id, 'accepted')}>Right</Button>
              <Button small disabled={r.outcome === 'corrected'} onClick={() => void mark(r.id, 'corrected')}>Wrong</Button>
            </span>
          )}
        </li>
      ))}
    </ul>
  )
}

export function DecisionsSection({ d }: { d: SettingsDraft }) {
  const log = useLoad<{ decisions: DecisionRow[]; summary: DeciderSummary[] }>('/api/decisions?limit=20', true)
  if (!d.current) return null
  const cfg = d.current.decisions
  const edit = (patch: Partial<typeof cfg>) => d.edit((x) => ({ ...x, decisions: { ...x.decisions, ...patch } }))
  const editKind = (k: DecisionKind, patch: Partial<typeof cfg.tools>) => edit({ [k]: { ...cfg[k], ...patch } })
  return (
    <div className="stack">
      <p className="hint">Small, quick helpers settle narrow questions before a language model is asked, which saves tokens and time. They can only make Lilly more careful; they can never allow an action or skip an approval.</p>
      <Switch label="Use quick deciders" hint="Off means every question goes to the language model." checked={cfg.enabled} onChange={(v) => edit({ enabled: v })} />
      {cfg.enabled && (
        <fieldset className="stack">
          <legend className="label">Each question</legend>
          {KINDS.map((k) => (
            <div key={k.id} className="stack">
              <Switch label={k.label} hint={k.hint} checked={cfg[k.id].enabled} onChange={(v) => editKind(k.id, { enabled: v })} />
              {cfg[k.id].enabled && <Switch label="Watch only" hint="Run it and record what it would have said, without using the answer." checked={cfg[k.id].shadow} onChange={(v) => editKind(k.id, { shadow: v })} />}
            </div>
          ))}
        </fieldset>
      )}
      <LayaSetup d={d} />
      <section className="stack" aria-labelledby="dec-log">
        <h3 id="dec-log">How they are doing</h3>
        <ErrorNote text={log.error} />
        <Summary rows={log.data?.summary ?? []} />
        <Recent rows={log.data?.decisions ?? []} reload={log.reload} />
      </section>
    </div>
  )
}
