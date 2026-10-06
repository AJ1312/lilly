import { Pill } from './kit'

const ADVICE = 'Laya, a small model that runs on this computer, judged this reply against your request and the agent’s instructions. This is advice only: the reply was not changed or held back, and Laya can be wrong.'

/** A warning under a reply that Laya thought drifted from the request. Nothing is shown when it was not asked, was only watching, or had no answer. `watch` keeps it fresh, because the check lands after the reply. */
export function ReplyCheck({ verdict }: { verdict: 'follows' | 'drifts' | null | undefined }) {
  if (verdict !== 'drifts') return null
  return (
    <p className="hint">
      <Pill tone="warn" title={ADVICE}>Laya thinks this may not follow your instructions</Pill>
    </p>
  )
}
