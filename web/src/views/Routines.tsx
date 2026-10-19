import React, { useState } from 'react'
import { api, errorText } from '../api'
import { useLoad } from '../hooks'
import { useAppStore } from '../store'
import type { Routine, Playbook, ExecutionTarget } from '../types'
import { Icon } from '../ui/Icon'
import { TargetPill } from '../ui/Pills'
import { Modal } from '../ui/Modal'

export const RoutinesView: React.FC = () => {
  const toast = useAppStore((s) => s.toast)
  const bump = useAppStore((s) => s.bump)

  const [activeTab, setActiveTab] = useState<'routines' | 'playbooks'>('routines')

  // Routines data
  const { data: routinesData, loading: loadingRoutines, reload: reloadRoutines } =
    useLoad<{ routines: Routine[] }>('/api/routines')
  const routines = routinesData?.routines || []

  // Playbooks data
  const { data: playbooksData, loading: loadingPlaybooks } =
    useLoad<{ playbooks: Playbook[] }>('/api/playbooks')
  const playbooks = playbooksData?.playbooks || []

  // Create routine modal
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [goal, setGoal] = useState('')
  const [scheduleType, setScheduleType] = useState<'cron' | 'interval'>('interval')
  const [cron, setCron] = useState('0 9 * * *')
  const [intervalMins, setIntervalMins] = useState(60)
  const [target, setTarget] = useState<ExecutionTarget>('host')
  const [saving, setSaving] = useState(false)

  const openCreate = () => {
    setEditingId(null)
    setTitle('')
    setGoal('')
    setScheduleType('interval')
    setCron('0 9 * * *')
    setIntervalMins(60)
    setTarget('host')
    setModalOpen(true)
  }

  const handleToggleEnabled = async (routine: Routine) => {
    try {
      await api.patch(`/api/routines/${routine.id}`, { enabled: !routine.enabled })
      toast(routine.enabled ? 'Routine paused' : 'Routine enabled', 'good')
      bump()
      await reloadRoutines()
    } catch (err) {
      toast(`Failed to toggle: ${errorText(err)}`, 'bad')
    }
  }

  const handleRunNow = async (id: string) => {
    try {
      await api.post(`/api/routines/${id}/run`)
      toast('Routine triggered immediately', 'good')
      bump()
    } catch (err) {
      toast(`Trigger failed: ${errorText(err)}`, 'bad')
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Are you sure you want to delete this routine?')) return
    try {
      await api.delete(`/api/routines/${id}`)
      toast('Routine deleted', 'good')
      bump()
      await reloadRoutines()
    } catch (err) {
      toast(`Failed to delete: ${errorText(err)}`, 'bad')
    }
  }

  const handleSaveRoutine = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim() || !goal.trim()) return

    setSaving(true)
    try {
      const payload: Record<string, unknown> = {
        name: title.trim(),
        goal: goal.trim(),
        target,
        enabled: true,
      }
      if (scheduleType === 'cron') {
        payload.cron = cron.trim()
      } else {
        payload.interval_s = intervalMins * 60
      }

      if (editingId) {
        await api.patch(`/api/routines/${editingId}`, payload)
        toast('Routine updated', 'good')
      } else {
        await api.post('/api/routines', payload)
        toast('Routine created', 'good')
      }
      setModalOpen(false)
      bump()
      await reloadRoutines()
    } catch (err) {
      toast(`Failed to save routine: ${errorText(err)}`, 'bad')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="view-container" style={{ padding: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <div>
          <h2 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--text-main)' }}>Routines & Playbooks</h2>
          <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
            Automated background workflows, periodic system checks, and multi-agent playbooks.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '8px' }}>
          <div className="filter-tabs">
            <button
              type="button"
              className={`filter-tab ${activeTab === 'routines' ? 'active' : ''}`}
              onClick={() => setActiveTab('routines')}
            >
              Routines ({routines.length})
            </button>
            <button
              type="button"
              className={`filter-tab ${activeTab === 'playbooks' ? 'active' : ''}`}
              onClick={() => setActiveTab('playbooks')}
            >
              Playbooks ({playbooks.length})
            </button>
          </div>

          <button onClick={openCreate} className="btn btn-primary btn-sm" type="button">
            <Icon name="plus" size={14} />
            <span>New Routine</span>
          </button>
        </div>
      </div>

      {activeTab === 'routines' ? (
        <div>
          {loadingRoutines && routines.length === 0 ? (
            <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
              Loading routines...
            </div>
          ) : routines.length === 0 ? (
            <div className="card" style={{ padding: '48px', textAlign: 'center' }}>
              <Icon name="routines" size={36} style={{ color: 'var(--text-dim)', margin: '0 auto 12px auto' }} />
              <h3 style={{ fontSize: '16px', fontWeight: 600 }}>No recurring routines configured</h3>
              <p style={{ fontSize: '13px', color: 'var(--text-muted)', margin: '6px 0 16px 0' }}>
                Automate periodic tasks like repository health audits, disk checks, or daily summaries.
              </p>
              <button onClick={openCreate} className="btn btn-primary btn-sm" type="button">
                Schedule First Routine
              </button>
            </div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: '16px' }}>
              {routines.map((r) => (
                <div key={r.id} className="card" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <h3 style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-main)' }}>{r.name}</h3>
                        <TargetPill target={r.target} size="sm" />
                      </div>
                      <div style={{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', marginTop: '2px' }}>
                        {r.when || 'Schedule'}
                      </div>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <button
                        onClick={() => handleToggleEnabled(r)}
                        className={`btn btn-sm ${r.enabled ? 'btn-secondary' : 'btn-ghost'}`}
                        type="button"
                        title={r.enabled ? 'Pause routine' : 'Enable routine'}
                      >
                        <Icon name={r.enabled ? 'pause' : 'play'} size={12} />
                        <span>{r.enabled ? 'Active' : 'Paused'}</span>
                      </button>

                      <button
                        onClick={() => handleDelete(r.id)}
                        className="btn btn-ghost btn-sm btn-icon"
                        type="button"
                        title="Delete routine"
                      >
                        <Icon name="trash" size={14} />
                      </button>
                    </div>
                  </div>

                  <div style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.5, flex: 1 }}>
                    {r.goal}
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: '8px', borderTop: '1px solid var(--border-subtle)', marginTop: 'auto' }}>
                    <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                      Last run: {r.last_run ? new Date(r.last_run * 1000).toLocaleString() : 'Never'}
                    </span>

                    <button
                      type="button"
                      onClick={() => handleRunNow(r.id)}
                      className="btn btn-primary btn-sm"
                    >
                      <Icon name="play" size={12} />
                      <span>Run Now</span>
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        /* Playbooks view */
        <div>
          {loadingPlaybooks && playbooks.length === 0 ? (
            <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
              Loading playbooks...
            </div>
          ) : playbooks.length === 0 ? (
            <div className="card" style={{ padding: '48px', textAlign: 'center' }}>
              <Icon name="sparkles" size={36} style={{ color: 'var(--text-dim)', margin: '0 auto 12px auto' }} />
              <h3 style={{ fontSize: '16px', fontWeight: 600 }}>No multi-agent playbooks</h3>
              <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
                Playbooks orchestrate complex sequential workflows between multiple specialist agents.
              </p>
            </div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '16px' }}>
              {playbooks.map((pb) => (
                <div key={pb.id} className="card" style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  <div style={{ fontWeight: 600, fontSize: '15px', color: 'var(--text-main)' }}>{pb.name}</div>
                  <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>{pb.description}</div>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                    Version {pb.version} • Successes: {pb.success_count}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Routine Creator Modal */}
      <Modal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editingId ? 'Edit Routine' : 'Create Routine'}
        footer={
          <>
            <button type="button" onClick={() => setModalOpen(false)} className="btn btn-secondary">
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSaveRoutine}
              disabled={!title.trim() || !goal.trim() || saving}
              className="btn btn-primary"
            >
              <span>{saving ? 'Saving...' : 'Save Routine'}</span>
            </button>
          </>
        }
      >
        <form onSubmit={handleSaveRoutine} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
              Title
            </label>
            <input
              className="input"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Daily Workspace Health Audit"
              required
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
              Task Goal / Prompt
            </label>
            <textarea
              className="textarea"
              rows={3}
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              placeholder="e.g. Run tests, verify git status, and summarize warnings..."
              required
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '6px' }}>
              Schedule Type
            </label>
            <div style={{ display: 'flex', gap: '12px', marginBottom: '8px' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', cursor: 'pointer' }}>
                <input
                  type="radio"
                  name="scheduleType"
                  checked={scheduleType === 'interval'}
                  onChange={() => setScheduleType('interval')}
                />
                <span>Interval (Minutes)</span>
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', cursor: 'pointer' }}>
                <input
                  type="radio"
                  name="scheduleType"
                  checked={scheduleType === 'cron'}
                  onChange={() => setScheduleType('cron')}
                />
                <span>Cron Expression</span>
              </label>
            </div>

            {scheduleType === 'interval' ? (
              <input
                type="number"
                min="1"
                className="input"
                value={intervalMins}
                onChange={(e) => setIntervalMins(Number(e.target.value))}
                placeholder="Minutes between runs (e.g. 60)"
              />
            ) : (
              <input
                className="input"
                value={cron}
                onChange={(e) => setCron(e.target.value)}
                placeholder="0 9 * * *"
              />
            )}
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '6px' }}>
              Execution Target
            </label>
            <div style={{ display: 'flex', gap: '12px' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', cursor: 'pointer' }}>
                <input
                  type="radio"
                  name="routineTarget"
                  checked={target === 'host'}
                  onChange={() => setTarget('host')}
                />
                <span>Host (This Laptop)</span>
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', cursor: 'pointer' }}>
                <input
                  type="radio"
                  name="routineTarget"
                  checked={target === 'devbox'}
                  onChange={() => setTarget('devbox')}
                />
                <span>DevBox (Container)</span>
              </label>
            </div>
          </div>
        </form>
      </Modal>
    </div>
  )
}
