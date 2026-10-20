import React from 'react'
import { api, errorText } from '../api'
import { useLoad } from '../hooks'
import { useAppStore } from '../store'
import type { Resources } from '../types'
import { Icon } from '../ui/Icon'
import { StatePill } from '../ui/Pills'

export const ResourcesView: React.FC = () => {
  const toast = useAppStore((s) => s.toast)
  const bump = useAppStore((s) => s.bump)

  const { data, loading, reload } = useLoad<Resources>('/api/resources', 3000)

  const handleStopAll = async () => {
    try {
      await api.post('/api/stop')
      toast('Emergency stop executed', 'good')
      bump()
      await reload()
    } catch (err) {
      toast(`Failed to stop: ${errorText(err)}`, 'bad')
    }
  }

  const machine = data?.machine
  const lilly = data?.lilly
  const tasks = data?.tasks

  const formatBytes = (bytes?: number) => {
    if (!bytes) return '0 B'
    const mb = bytes / (1024 * 1024)
    if (mb >= 1024) return `${(mb / 1024).toFixed(2)} GB`
    return `${mb.toFixed(1)} MB`
  }

  return (
    <div className="view-container" style={{ padding: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <div>
          <h1 className="greeting-text">System Resources & Telemetry</h1>
          <div className="greeting-sub">
            Real-time CPU, RAM, disk utilization, running tasks, and Lilly engine process footprint.
          </div>
        </div>

        <div style={{ display: 'flex', gap: '8px' }}>
          <button onClick={() => reload()} className="btn btn-secondary btn-sm" type="button">
            <Icon name="refresh" size={12} />
            <span>Refresh</span>
          </button>

          {(tasks?.running || 0) > 0 && (
            <button onClick={handleStopAll} className="btn btn-danger btn-sm" type="button">
              <Icon name="stop" size={14} />
              <span>Emergency Stop All</span>
            </button>
          )}
        </div>
      </div>

      {loading && !data ? (
        <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
          Sampling host telemetry...
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {/* Machine Gauges */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '16px' }}>
            {/* CPU */}
            <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-dim)', textTransform: 'uppercase' }}>
                  Host CPU Usage
                </span>
                <Icon name="cpu" size={16} style={{ color: 'var(--primary)' }} />
              </div>
              <div style={{ fontSize: '28px', fontWeight: 700, color: 'var(--text-main)' }}>
                {machine?.cpu_percent ?? 0}%
              </div>
              <div style={{ height: '6px', width: '100%', backgroundColor: 'var(--bg-hover)', borderRadius: 'var(--radius-full)', overflow: 'hidden' }}>
                <div
                  style={{
                    height: '100%',
                    width: `${Math.min(machine?.cpu_percent ?? 0, 100)}%`,
                    backgroundColor: (machine?.cpu_percent ?? 0) > 85 ? 'var(--danger)' : 'var(--primary)',
                    transition: 'width var(--transition-normal)',
                  }}
                />
              </div>
            </div>

            {/* RAM */}
            <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-dim)', textTransform: 'uppercase' }}>
                  System Memory
                </span>
                <Icon name="cpu" size={16} style={{ color: 'var(--devbox-color)' }} />
              </div>
              <div style={{ fontSize: '28px', fontWeight: 700, color: 'var(--text-main)' }}>
                {machine?.memory?.percent ?? 0}%
              </div>
              <div style={{ height: '6px', width: '100%', backgroundColor: 'var(--bg-hover)', borderRadius: 'var(--radius-full)', overflow: 'hidden' }}>
                <div
                  style={{
                    height: '100%',
                    width: `${Math.min(machine?.memory?.percent ?? 0, 100)}%`,
                    backgroundColor: 'var(--devbox-color)',
                    transition: 'width var(--transition-normal)',
                  }}
                />
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                {formatBytes(machine?.memory?.total)} total
              </div>
            </div>

            {/* Disk */}
            <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-dim)', textTransform: 'uppercase' }}>
                  Disk Space
                </span>
                <Icon name="database" size={16} style={{ color: 'var(--success)' }} />
              </div>
              <div style={{ fontSize: '28px', fontWeight: 700, color: 'var(--text-main)' }}>
                {formatBytes(machine?.disk?.free)}
              </div>
              <div style={{ height: '6px', width: '100%', backgroundColor: 'var(--bg-hover)', borderRadius: 'var(--radius-full)', overflow: 'hidden' }}>
                <div
                  style={{
                    height: '100%',
                    width: `${Math.min(machine?.disk?.percent ?? 0, 100)}%`,
                    backgroundColor: 'var(--success)',
                    transition: 'width var(--transition-normal)',
                  }}
                />
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                Free of {formatBytes(machine?.disk?.total)} total
              </div>
            </div>

            {/* Active Tasks in flight */}
            <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-dim)', textTransform: 'uppercase' }}>
                  Tasks In Flight
                </span>
                <Icon name="tasks" size={16} style={{ color: 'var(--warning)' }} />
              </div>
              <div style={{ fontSize: '28px', fontWeight: 700, color: 'var(--text-main)' }}>
                {tasks?.running ?? 0}
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                {tasks?.queued ?? 0} queued, {tasks?.waiting_approval ?? 0} pending approval
              </div>
            </div>
          </div>

          {/* Lilly Engine Process Details */}
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: 600 }}>Lilly Engine Footprint</h3>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px' }}>
              <div className="card card-subtle">
                <div style={{ fontSize: '11px', color: 'var(--text-dim)' }}>Process PID</div>
                <div style={{ fontWeight: 600, fontSize: '14px', fontFamily: 'var(--font-mono)', marginTop: '2px' }}>
                  {lilly?.pid ?? '—'}
                </div>
              </div>

              <div className="card card-subtle">
                <div style={{ fontSize: '11px', color: 'var(--text-dim)' }}>Engine Memory (RSS)</div>
                <div style={{ fontWeight: 600, fontSize: '14px', fontFamily: 'var(--font-mono)', marginTop: '2px' }}>
                  {formatBytes(lilly?.memory_bytes)}
                </div>
              </div>

              <div className="card card-subtle">
                <div style={{ fontSize: '11px', color: 'var(--text-dim)' }}>SQLite Database</div>
                <div style={{ fontWeight: 600, fontSize: '14px', fontFamily: 'var(--font-mono)', marginTop: '2px' }}>
                  {formatBytes(lilly?.database_bytes)}
                </div>
              </div>

              <div className="card card-subtle">
                <div style={{ fontSize: '11px', color: 'var(--text-dim)' }}>Thread Count</div>
                <div style={{ fontWeight: 600, fontSize: '14px', fontFamily: 'var(--font-mono)', marginTop: '2px' }}>
                  {lilly?.threads ?? '—'}
                </div>
              </div>
            </div>
          </div>

          {/* Top Running Processes */}
          {machine?.top_processes && machine.top_processes.length > 0 && (
            <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <h3 style={{ fontSize: '15px', fontWeight: 600 }}>Top Host Processes</h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                {machine.top_processes.map((proc, idx) => (
                  <div
                    key={idx}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '6px 12px',
                      borderRadius: 'var(--radius-xs)',
                      backgroundColor: 'var(--bg-card-subtle)',
                      fontSize: '12px',
                      fontFamily: 'var(--font-mono)',
                    }}
                  >
                    <span>{proc.name}</span>
                    <span style={{ color: 'var(--text-muted)' }}>
                      PID: {proc.pid} | RAM: {proc.memory_percent ?? 0}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Live active tasks list */}
          {tasks?.live && tasks.live.length > 0 && (
            <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <h3 style={{ fontSize: '15px', fontWeight: 600 }}>Active Tasks Running in Engine</h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {tasks.live.map((t) => (
                  <div
                    key={t.id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '8px 12px',
                      borderRadius: 'var(--radius-xs)',
                      backgroundColor: 'var(--bg-input)',
                      border: '1px solid var(--border-subtle)',
                      fontSize: '13px',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <StatePill state={t.state} />
                      <span style={{ fontWeight: 500 }}>{t.goal}</span>
                    </div>

                    <button
                      type="button"
                      onClick={async () => {
                        try {
                          await api.post(`/api/tasks/${t.id}/cancel`)
                          toast('Cancelled task', 'warn')
                          bump()
                          await reload()
                        } catch (e) {
                          toast(`Error: ${errorText(e)}`, 'bad')
                        }
                      }}
                      className="btn btn-danger btn-sm"
                    >
                      <Icon name="x" size={12} />
                      <span>Cancel</span>
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
