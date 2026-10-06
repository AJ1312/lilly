import { useState } from 'react'
import { api, errorText } from '../api'
import { useApp } from '../store'
import type { Approval } from '../types'
import { Button, ErrorNote } from './kit'
import { TOOL_LABEL } from './format'

function pretty(v: unknown): string {
  return JSON.stringify(v, null, 2)
}

/** Shows exactly what Lilly is asking permission for. The decision is bound to this exact request. */
export function ApprovalCard({ approval, onDone }: { approval: Approval; onDone?: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const models = approval.kind === 'model' ? ((approval.payload?.models as string[] | undefined) ?? []) : []
  const questionChoices = approval.kind === 'question' ? ((approval.payload?.choices as string[] | undefined) ?? []) : []
  const [choice, setChoice] = useState(models[0] ?? questionChoices[0] ?? '')
  const bump = useApp((s) => s.bump)
  const [shownAt] = useState(() => Date.now() / 1000)

  const decide = async (approve: boolean) => {
    setBusy(true)
    setError(null)
    try {
      await api.post(`/api/approvals/${approval.id}/decide`, {
        approve,
        payload_hash: approval.payload_hash,
        choice: approval.kind === 'model' || approval.kind === 'question' ? choice : undefined,
      })
      bump()
      onDone?.()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  const tool = approval.kind === 'step' ? String(approval.payload?.tool ?? '') : ''
  const note = tool === 'notes.write' ? (approval.payload?.args as Record<string, unknown> | undefined) : undefined
  const expires = Math.max(0, Math.round(approval.expires_at - shownAt))
  return (
    <section className="approval" aria-label="Approval needed">
      <p className="approval-kicker">{approval.kind === 'model' ? 'Sharing needs your OK' : approval.kind === 'question' ? 'Lilly needs an answer' : 'Needs your OK'}</p>
      <h3>{approval.kind === 'step' ? (TOOL_LABEL[tool] ?? tool) : approval.summary}</h3>
      {approval.kind === 'step' && <p className="approval-why">{String(approval.payload?.why ?? approval.summary)}</p>}
      {approval.kind === 'model' ? (
        <fieldset className="choices">
          <legend>Which model may see {String(approval.payload?.label ?? 'private').toLowerCase()} data for this task? (one hour, this task only)</legend>
          {models.map((m) => (
            <label key={m} className="choice">
              <input type="radio" name={`m-${approval.id}`} checked={choice === m} onChange={() => setChoice(m)} />
              <span>{m}</span>
            </label>
          ))}
        </fieldset>
      ) : approval.kind === 'question' ? (
        <fieldset className="choices">
          <legend>{String(approval.payload?.question ?? approval.summary)}</legend>
          {questionChoices.length > 0 ? questionChoices.map((item) => (
            <label key={item} className="choice">
              <input type="radio" name={`q-${approval.id}`} checked={choice === item} onChange={() => setChoice(item)} />
              <span>{item}</span>
            </label>
          )) : (
            <input aria-label="Answer" value={choice} onChange={(event) => setChoice(event.target.value)} />
          )}
        </fieldset>
      ) : note ? (
        <div>
          <p>
            <strong>{String(note.title ?? 'Same title')}</strong>
            {note.id ? ' · replaces the whole note' : ` · new note in ${String(note.space ?? '')}`}
          </p>
          <pre>{String(note.content ?? '')}</pre>
        </div>
      ) : (
        <details className="approval-details">
          <summary>Exactly what will run</summary>
          <pre>{pretty(approval.payload?.args ?? approval.payload)}</pre>
        </details>
      )}
      <ErrorNote text={error} />
      <div className="approval-actions">
        <Button kind="primary" icon="check" busy={busy} onClick={() => void decide(true)}>Approve</Button>
        <Button icon="x" busy={busy} onClick={() => void decide(false)}>Decline</Button>
        <span className="hint">Expires in about {expires < 90 ? `${expires} s` : `${Math.round(expires / 60)} min`}</span>
      </div>
    </section>
  )
}
