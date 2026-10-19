import React from 'react'
import { useAppStore } from '../store'
import { Icon } from './Icon'

export const ToastContainer: React.FC = () => {
  const toasts = useAppStore((s) => s.toasts)
  const removeToast = useAppStore((s) => s.removeToast)

  if (toasts.length === 0) return null

  return (
    <div className="toast-container" aria-live="polite" role="status">
      {toasts.map((t) => {
        let iconName: 'check' | 'alert-triangle' | 'sparkles' = 'sparkles'
        if (t.kind === 'good') iconName = 'check'
        if (t.kind === 'warn' || t.kind === 'bad') iconName = 'alert-triangle'

        return (
          <div key={t.id} className={`toast ${t.kind || ''}`}>
            <Icon
              name={iconName}
              size={16}
              style={{
                color:
                  t.kind === 'good'
                    ? 'var(--success)'
                    : t.kind === 'bad'
                      ? 'var(--danger)'
                      : t.kind === 'warn'
                        ? 'var(--warning)'
                        : 'var(--primary)',
                flexShrink: 0,
              }}
            />
            <span style={{ flex: 1 }}>{t.text}</span>
            <button
              onClick={() => removeToast(t.id)}
              className="btn btn-ghost btn-sm btn-icon"
              style={{ padding: '2px', color: 'var(--text-muted)' }}
              type="button"
              aria-label="Dismiss toast"
            >
              <Icon name="x" size={14} />
            </button>
          </div>
        )
      })}
    </div>
  )
}
