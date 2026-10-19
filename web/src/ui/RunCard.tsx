import React, { useState, useEffect } from 'react'
import type { Task, StepRecord, TaskThought } from '../types'
import { TargetPill, StatePill, OutcomePill } from './Pills'
import { Icon } from './Icon'
import { api, errorText } from '../api'
import { useAppStore } from '../store'

interface RunCardProps {
  task: Task
  steps?: StepRecord[]
  thoughts?: TaskThought[]
  onSelect?: () => void
}

export const RunCard: React.FC<RunCardProps> = ({ task, steps = [], thoughts = [], onSelect }) => {
  const toast = useAppStore((s) => s.toast)
  const [cancelling, setCancelling] = useState(false)
  const [screenUrl, setScreenUrl] = useState<string | null>(null)
  const isRunning = task.state === 'RUNNING' || task.state === 'PLANNING' || task.state === 'VERIFYING'

  // Poll screenshot for active tasks that might be doing computer control or devbox actions
  useEffect(() => {
    if (!isRunning) {
      setScreenUrl(null)
      return
    }

    const interval = setInterval(() => {
      setScreenUrl(`/api/live/${task.id}/frame?t=${Date.now()}`)
    }, 2000)

    return () => clearInterval(interval)
  }, [task.id, isRunning])

  const handleCancel = async (e: React.MouseEvent) => {
    e.stopPropagation()
    setCancelling(true)
    try {
      await api.post(`/api/tasks/${task.id}/cancel`)
      toast('Task cancellation requested', 'warn')
    } catch (err) {
      toast(`Cancel failed: ${errorText(err)}`, 'bad')
    } finally {
      setCancelling(false)
    }
  }

  return (
    <div
      className="card"
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '12px',
        cursor: onSelect ? 'pointer' : 'default',
        transition: 'all var(--transition-fast)',
      }}
      onClick={onSelect}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '8px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
          <StatePill state={task.state} />
          <TargetPill target={task.target} size="sm" />
          <OutcomePill outcome={task.outcome} />
          {task.duration_s !== undefined && (
            <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
              {task.duration_s.toFixed(1)}s
            </span>
          )}
        </div>

        {isRunning && (
          <button
            onClick={handleCancel}
            disabled={cancelling}
            className="btn btn-danger btn-sm"
            type="button"
            title="Cancel task"
          >
            <Icon name="x" size={12} />
            <span>{cancelling ? 'Stopping...' : 'Cancel'}</span>
          </button>
        )}
      </div>

      <div style={{ fontWeight: 600, fontSize: '14px', color: 'var(--text-main)', lineHeight: 1.4 }}>
        {task.goal}
      </div>

      {/* Screen Preview if active */}
      {screenUrl && isRunning && (
        <div
          style={{
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border)',
            overflow: 'hidden',
            backgroundColor: '#000',
            maxHeight: '180px',
            position: 'relative',
          }}
        >
          <img
            src={screenUrl}
            alt="Live Screen Stream"
            style={{ width: '100%', height: 'auto', display: 'block' }}
            onError={() => setScreenUrl(null)}
          />
          <div
            style={{
              position: 'absolute',
              bottom: 6,
              left: 6,
              padding: '2px 6px',
              borderRadius: 'var(--radius-xs)',
              backgroundColor: 'rgba(0,0,0,0.7)',
              color: '#fff',
              fontSize: '10px',
              fontFamily: 'var(--font-mono)',
            }}
          >
            Live Screen Feed
          </div>
        </div>
      )}

      {/* Thoughts trace */}
      {thoughts.length > 0 && (
        <div className="thought-stream">
          {thoughts.slice(-3).map((th, idx) => (
            <div key={idx} className="thought-line">
              <span style={{ color: 'var(--primary)', fontWeight: 600 }}>[{th.layer}]</span>
              <span>{th.text}</span>
            </div>
          ))}
        </div>
      )}

      {/* Steps overview */}
      {steps.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginTop: '4px' }}>
          <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-dim)', textTransform: 'uppercase' }}>
            Steps ({steps.length})
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
            {steps.slice(-4).map((st) => (
              <div
                key={st.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '4px 8px',
                  backgroundColor: 'var(--bg-card-subtle)',
                  borderRadius: 'var(--radius-xs)',
                  fontSize: '12px',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontFamily: 'var(--font-mono)' }}>
                  <Icon
                    name={
                      st.status === 'success'
                        ? 'check'
                        : st.status === 'failed'
                          ? 'x'
                          : st.status === 'running'
                            ? 'refresh'
                            : 'terminal'
                    }
                    size={12}
                    style={{
                      color:
                        st.status === 'success'
                          ? 'var(--success)'
                          : st.status === 'failed'
                            ? 'var(--danger)'
                            : 'var(--primary)',
                    }}
                  />
                  <span>{st.tool}</span>
                </div>
                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                  {st.duration_s ? `${st.duration_s.toFixed(2)}s` : st.status}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {task.error && (
        <div
          style={{
            padding: '8px 12px',
            borderRadius: 'var(--radius-sm)',
            backgroundColor: 'var(--danger-subtle)',
            border: '1px solid var(--danger-border)',
            color: 'var(--danger-text)',
            fontSize: '12px',
          }}
        >
          {task.error}
        </div>
      )}
    </div>
  )
}
