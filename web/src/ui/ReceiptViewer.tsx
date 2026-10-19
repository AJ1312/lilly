import React, { useState, useEffect } from 'react'
import { api, errorText } from '../api'
import { Modal } from './Modal'
import { Icon } from './Icon'

interface ReceiptViewerProps {
  taskId: string | null
  onClose: () => void
}

export const ReceiptViewer: React.FC<ReceiptViewerProps> = ({ taskId, onClose }) => {
  const [loading, setLoading] = useState(false)
  const [receipt, setReceipt] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!taskId) {
      setReceipt(null)
      return
    }

    setLoading(true)
    setError(null)
    api
      .get<Record<string, unknown>>(`/api/tasks/${taskId}/receipt`)
      .then((res) => setReceipt(res))
      .catch((err) => setError(errorText(err)))
      .finally(() => setLoading(false))
  }, [taskId])

  if (!taskId) return null

  return (
    <Modal
      isOpen={Boolean(taskId)}
      onClose={onClose}
      title="Task Verification Receipt"
      maxWidth={620}
      footer={
        <button onClick={onClose} className="btn btn-secondary" type="button">
          Close
        </button>
      }
    >
      {loading ? (
        <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)' }}>
          Loading cryptographic verification receipt...
        </div>
      ) : error ? (
        <div
          style={{
            padding: '12px 16px',
            backgroundColor: 'var(--danger-subtle)',
            border: '1px solid var(--danger-border)',
            borderRadius: 'var(--radius-sm)',
            color: 'var(--danger-text)',
            fontSize: '13px',
          }}
        >
          {error}
        </div>
      ) : receipt ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '10px 14px',
              backgroundColor: 'var(--success-subtle)',
              border: '1px solid var(--success-border)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--success-text)',
              fontSize: '13px',
              fontWeight: 500,
            }}
          >
            <Icon name="check" size={16} />
            <span>Cryptographic receipt verified for Task {taskId}</span>
          </div>

          <div
            style={{
              backgroundColor: 'var(--bg-input)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)',
              padding: '12px',
              fontFamily: 'var(--font-mono)',
              fontSize: '12px',
              overflowX: 'auto',
              maxHeight: '360px',
            }}
          >
            <pre style={{ margin: 0 }}>{JSON.stringify(receipt, null, 2)}</pre>
          </div>
        </div>
      ) : (
        <div style={{ color: 'var(--text-muted)', textAlign: 'center', padding: '24px' }}>
          No receipt data found.
        </div>
      )}
    </Modal>
  )
}
