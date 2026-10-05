import { useLoad } from '../hooks'
import type { Approval } from '../types'
import { ApprovalCard } from '../ui/ApprovalCard'
import { Empty, ErrorNote, PageHead, Pill } from '../ui/kit'
import { ago } from '../ui/format'

export function Approvals() {
  const pending = useLoad<{ approvals: Approval[] }>('/api/approvals?status=pending', true)
  const history = useLoad<{ approvals: Approval[] }>('/api/approvals?limit=30', true)
  const waiting = pending.data?.approvals ?? []
  const past = (history.data?.approvals ?? []).filter((a) => a.status !== 'pending')
  return (
    <div className="page">
      <PageHead title="Approvals" sub="Anything Lilly wants to do that changes something or shares private data waits here for you." />
      <ErrorNote text={pending.error} />
      <section aria-label="Waiting for you" className="stack">
        {waiting.length === 0 && <Empty title="Nothing is waiting">When Lilly needs your OK, it shows up here and in the conversation.</Empty>}
        {waiting.map((a) => <ApprovalCard key={a.id} approval={a} />)}
      </section>
      {past.length > 0 && (
        <section aria-label="Recent decisions">
          <h2 className="section-title">Recent decisions</h2>
          <ul className="ledger">
            {past.map((a) => (
              <li key={a.id}>
                <span>{a.summary}</span>
                <Pill tone={a.status === 'approved' ? 'ok' : a.status === 'denied' ? 'bad' : 'mute'}>{a.status}</Pill>
                <span className="hint">{ago(a.decided_at ?? a.created_at)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
