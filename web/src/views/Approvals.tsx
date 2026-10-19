import React, { useState } from 'react'
import { api, errorText } from '../api'
import { useLoad } from '../hooks'
import { useAppStore } from '../store'
import type { Approval } from '../types'
import { Icon } from '../ui/Icon'
import { RiskPill, TargetPill } from '../ui/Pills'

export const ApprovalsView: React.FC = () => {
  const toast = useAppStore((s) => s.toast)
  const bump = useAppStore((s) => s.bump)

  const [tab, setTab] = useState<'pending' | 'history'>('pending')
  const [declineReason, setDeclineReason] = useState<Record<string, string>>({})
  const [decidingId, setDecidingId] = useState<string | null>(null)

  const url = tab === 'pending' ? '/api/approvals?status=pending' : '/api/approvals'
  const { data, loading, reload } = useLoad<{ approvals: Approval[] }>(url, 3000)
  const approvals = data?.approvals || []

  const handleDecide = async (approval: Approval, approve: boolean) => {
    setDecidingId(approval.id)
    try {
      await api.post(`/api/approvals/${approval.id}/decide`, {
        approve,
        payload_hash: approval.payload_hash,
        decline_reason: approve ? undefined : declineReason[approval.id] || 'Declined by user',
      })
      toast(approve ? 'Tool step approved' : 'Tool step declined', approve ? 'good' : 'warn')
      bump()
      await reload()
    } catch (err) {
      toast(`Decision failed: ${errorText(err)}`, 'bad')
    } finally {
      setDecidingId(null)
    }
  }

  return (
    <div className="view-container" style={{ padding: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <div>
          <h2 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--text-main)' }}>Security Approvals</h2>
          <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
            Review, authorize, or decline sensitive tool invocations before they execute on your laptop or DevBox.
          </p>
        </div>

        <div className="filter-tabs">
          <button
            type="button"
            className={`filter-tab ${tab === 'pending' ? 'active' : ''}`}
            onClick={() => setTab('pending')}
          >
            Pending
          </button>
          <button
            type="button"
            className={`filter-tab ${tab === 'history' ? 'active' : ''}`}
            onClick={() => setTab('history')}
          >
            History
          </button>
        </div>
      </div>

      {loading && approvals.length === 0 ? (
        <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
          Checking approval queue...
        </div>
      ) : approvals.length === 0 ? (
        <div className="card" style={{ padding: '48px', textAlign: 'center' }}>
          <Icon name="shield" size={36} style={{ color: 'var(--success)', margin: '0 auto 12px auto' }} />
          <h3 style={{ fontSize: '16px', fontWeight: 600 }}>Queue Clear</h3>
          <p style={{ fontSize: '13px', color: 'var(--text-muted)', margin: '6px 0 0 0' }}>
            No sensitive tool executions currently require approval.
          </p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {approvals.map((appr) => {
            const isDeciding = decidingId === appr.id
            return (
              <div
                key={appr.id}
                className="card"
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '14px',
                  borderLeft: '4px solid var(--warning)',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '8px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <RiskPill risk={appr.risk} />
                    <TargetPill target={appr.target} size="sm" />
                    <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '14px', color: 'var(--text-main)' }}>
                      {appr.tool}
                    </span>
                  </div>

                  <div style={{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
                    Task ID: {appr.task_id}
                  </div>
                </div>

                <div style={{ fontSize: '13px', color: 'var(--text-main)', lineHeight: 1.5 }}>
                  {appr.why}
                </div>

                {/* Payload args preview */}
                {appr.payload && Object.keys(appr.payload).length > 0 && (
                  <div
                    style={{
                      backgroundColor: 'var(--bg-input)',
                      border: '1px solid var(--border)',
                      borderRadius: 'var(--radius-sm)',
                      padding: '10px 14px',
                      fontFamily: 'var(--font-mono)',
                      fontSize: '12px',
                      overflowX: 'auto',
                    }}
                  >
                    <pre style={{ margin: 0 }}>{JSON.stringify(appr.payload, null, 2)}</pre>
                  </div>
                )}

                <div style={{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
                  Payload Hash: {appr.payload_hash}
                </div>

                {tab === 'pending' && (
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingTop: '10px', borderTop: '1px solid var(--border-subtle)', gap: '12px', flexWrap: 'wrap' }}>
                    <input
                      className="input"
                      style={{ flex: 1, minWidth: '220px', fontSize: '12px' }}
                      placeholder="Optional decline reason..."
                      value={declineReason[appr.id] || ''}
                      onChange={(e) => setDeclineReason({ ...declineReason, [appr.id]: e.target.value })}
                    />

                    <div style={{ display: 'flex', gap: '8px' }}>
                      <button
                        type="button"
                        onClick={() => handleDecide(appr, false)}
                        disabled={isDeciding}
                        className="btn btn-secondary btn-sm"
                      >
                        <Icon name="x" size={12} />
                        <span>Decline</span>
                      </button>

                      <button
                        type="button"
                        onClick={() => handleDecide(appr, true)}
                        disabled={isDeciding}
                        className="btn btn-primary btn-sm"
                      >
                        <Icon name="check" size={12} />
                        <span>{isDeciding ? 'Authorizing...' : 'Approve Execution'}</span>
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
