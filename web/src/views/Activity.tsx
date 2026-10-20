import React, { useState } from 'react'
import { api, errorText } from '../api'
import { useLoad } from '../hooks'
import { useAppStore } from '../store'
import type { DecisionLog } from '../types'
import { Icon } from '../ui/Icon'

export const ActivityView: React.FC = () => {
  const toast = useAppStore((s) => s.toast)
  const bump = useAppStore((s) => s.bump)

  const [kindFilter, setKindFilter] = useState<string>('all')

  const url = kindFilter === 'all' ? '/api/decisions' : `/api/decisions?kind=${kindFilter}`
  const { data, loading, reload } = useLoad<{ decisions: DecisionLog[]; summary?: any[] }>(url, 4000)
  const decisions = data?.decisions || []
  const summary = data?.summary || []

  const handleMarkOutcome = async (logId: number, outcome: string) => {
    try {
      await api.post(`/api/decisions/${logId}/outcome`, { outcome })
      toast(`Marked decision outcome as ${outcome}`, 'good')
      bump()
      await reload()
    } catch (err) {
      toast(`Failed to mark outcome: ${errorText(err)}`, 'bad')
    }
  }

  return (
    <div className="view-container" style={{ padding: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <div>
          <h1 className="greeting-text">Activity & Decision Log</h1>
          <div className="greeting-sub">
            Audit trail of classifier choices, routing judgements, and grounding decisions.
          </div>
        </div>

        <div className="filter-tabs">
          {['all', 'reply_check', 'intent', 'risk', 'tool_pick'].map((k) => (
            <button
              key={k}
              type="button"
              className={`filter-tab ${kindFilter === k ? 'active' : ''}`}
              onClick={() => setKindFilter(k)}
            >
              {k.replace('_', ' ')}
            </button>
          ))}
        </div>
      </div>

      {/* Summary KPI cards */}
      {summary.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '12px', marginBottom: '20px' }}>
          {summary.map((s, idx) => (
            <div key={idx} className="card card-subtle">
              <div style={{ fontSize: '11px', color: 'var(--text-dim)', textTransform: 'uppercase', fontWeight: 600 }}>
                {s.kind || 'Kind'}
              </div>
              <div style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-main)', marginTop: '4px' }}>
                {s.count ?? 0}
              </div>
            </div>
          ))}
        </div>
      )}

      {loading && decisions.length === 0 ? (
        <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
          Loading activity log...
        </div>
      ) : decisions.length === 0 ? (
        <div className="card" style={{ padding: '48px', textAlign: 'center' }}>
          <Icon name="activity" size={36} style={{ color: 'var(--text-dim)', margin: '0 auto 12px auto' }} />
          <h3 style={{ fontSize: '16px', fontWeight: 600 }}>No decisions recorded yet</h3>
          <p style={{ fontSize: '13px', color: 'var(--text-muted)', margin: '6px 0 0 0' }}>
            Decision logs will populate automatically as tasks and routing checks are processed.
          </p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          {decisions.map((dec) => (
            <div key={dec.id} className="card" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span
                    style={{
                      fontSize: '11px',
                      fontFamily: 'var(--font-mono)',
                      fontWeight: 600,
                      backgroundColor: 'var(--primary-subtle)',
                      color: 'var(--primary)',
                      padding: '2px 8px',
                      borderRadius: 'var(--radius-xs)',
                    }}
                  >
                    {dec.kind}
                  </span>
                  <span style={{ fontWeight: 600, fontSize: '13px', color: 'var(--text-main)' }}>
                    Choice: {dec.choice}
                  </span>
                </div>

                <div style={{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
                  {new Date(dec.created_at * 1000).toLocaleTimeString()}
                </div>
              </div>

              {dec.prompt && (
                <div style={{ fontSize: '12px', color: 'var(--text-secondary)', backgroundColor: 'var(--bg-input)', padding: '8px 12px', borderRadius: 'var(--radius-xs)', maxHeight: '80px', overflowY: 'auto' }}>
                  {dec.prompt}
                </div>
              )}

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: '6px', borderTop: '1px solid var(--border-subtle)' }}>
                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                  Outcome: <strong>{dec.outcome || 'uncalibrated'}</strong>
                </span>

                <div style={{ display: 'flex', gap: '4px' }}>
                  {['correct', 'incorrect'].map((opt) => (
                    <button
                      key={opt}
                      type="button"
                      onClick={() => handleMarkOutcome(dec.id, opt)}
                      className={`btn btn-sm ${dec.outcome === opt ? 'btn-primary' : 'btn-ghost'}`}
                      style={{ fontSize: '11px', padding: '2px 8px' }}
                    >
                      {opt === 'correct' ? <Icon name="check" size={10} /> : <Icon name="x" size={10} />}
                      <span>{opt}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
