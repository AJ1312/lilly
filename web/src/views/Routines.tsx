import React, { useState } from 'react'
import { api, errorText } from '../api'
import { useLoad } from '../hooks'
import { useAppStore } from '../store'
import type { Routine, Playbook, ExecutionTarget, Agent, Schedule } from '../types'
import { Icon } from '../ui/Icon'
import { TargetPill } from '../ui/Pills'
import { Modal } from '../ui/Modal'

const DAYS_OF_WEEK = [
  { label: 'Mon', value: 0 },
  { label: 'Tue', value: 1 },
  { label: 'Wed', value: 2 },
  { label: 'Thu', value: 3 },
  { label: 'Fri', value: 4 },
  { label: 'Sat', value: 5 },
  { label: 'Sun', value: 6 },
]

export const RoutinesView: React.FC = () => {
  const toast = useAppStore((s) => s.toast)
  const bump = useAppStore((s) => s.bump)

  const [activeTab, setActiveTab] = useState<'routines' | 'playbooks'>('routines')

  // Routines data
  const { data: routinesData, loading: loadingRoutines, reload: reloadRoutines } =
    useLoad<{ routines: Routine[] }>('/api/routines')
  const routines = routinesData?.routines || []

  // Playbooks data
  const { data: playbooksData, loading: loadingPlaybooks, reload: reloadPlaybooks } =
    useLoad<{ playbooks: Playbook[] }>('/api/playbooks')
  const playbooks = playbooksData?.playbooks || []

  // Agents data for selection
  const { data: agentsData } = useLoad<{ agents: Agent[] }>('/api/agents')
  const agents = agentsData?.agents || []

  // Routine modal state
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [goal, setGoal] = useState('')
  const [scheduleKind, setScheduleKind] = useState<'every' | 'at'>('every')
  const [everyMinutes, setEveryMinutes] = useState(60)
  const [atTime, setAtTime] = useState('09:00')
  const [selectedDays, setSelectedDays] = useState<number[]>([0, 1, 2, 3, 4])
  const [target, setTarget] = useState<ExecutionTarget>('host')
  const [agentId, setAgentId] = useState<string>('')
  const [playbookId, setPlaybookId] = useState<string>('')
  const [saving, setSaving] = useState(false)

  // Playbook modal state
  const [playbookModalOpen, setPlaybookModalOpen] = useState(false)
  const [pbName, setPbName] = useState('')
  const [pbSignature, setPbSignature] = useState('')
  const [pbDescription, setPbDescription] = useState('')
  const [pbTarget, setPbTarget] = useState<ExecutionTarget>('host')
  const [savingPb, setSavingPb] = useState(false)

  const openCreateRoutine = () => {
    setEditingId(null)
    setTitle('')
    setGoal('')
    setScheduleKind('every')
    setEveryMinutes(60)
    setAtTime('09:00')
    setSelectedDays([0, 1, 2, 3, 4])
    setTarget('host')
    setAgentId('')
    setPlaybookId('')
    setModalOpen(true)
  }

  const openEditRoutine = (routine: Routine) => {
    setEditingId(routine.id)
    setTitle(routine.name)
    setGoal(routine.goal)
    setTarget(routine.target || 'host')
    setAgentId(routine.agent_id || '')
    setPlaybookId(routine.playbook_id || '')

    if (routine.schedule && routine.schedule.kind === 'at') {
      setScheduleKind('at')
      setAtTime(routine.schedule.at || '09:00')
      setSelectedDays(routine.schedule.days || [0, 1, 2, 3, 4])
    } else {
      setScheduleKind('every')
      setEveryMinutes(routine.schedule?.every_minutes ? Math.max(5, routine.schedule.every_minutes) : 60)
    }
    setModalOpen(true)
  }

  const toggleDay = (day: number) => {
    if (selectedDays.includes(day)) {
      if (selectedDays.length > 1) {
        setSelectedDays(selectedDays.filter((d) => d !== day))
      }
    } else {
      setSelectedDays([...selectedDays, day].sort())
    }
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

  const handleDeleteRoutine = async (id: string) => {
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
      const schedule: Schedule =
        scheduleKind === 'every'
          ? { kind: 'every', every_minutes: Math.max(5, Math.floor(everyMinutes)) }
          : { kind: 'at', at: atTime || '09:00', days: selectedDays }

      const payload: Record<string, unknown> = {
        name: title.trim(),
        goal: goal.trim(),
        target,
        schedule,
        agent_id: agentId || null,
        playbook_id: playbookId || null,
        enabled: true,
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

  const openCreatePlaybook = () => {
    setPbName('')
    setPbSignature('')
    setPbDescription('')
    setPbTarget('host')
    setPlaybookModalOpen(true)
  }

  const handleSavePlaybook = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!pbName.trim()) return

    setSavingPb(true)
    try {
      await api.post('/api/playbooks', {
        name: pbName.trim(),
        task_signature: pbSignature.trim() || pbName.trim().toLowerCase().replace(/\s+/g, '_'),
        description: pbDescription.trim(),
        target: pbTarget,
        steps: [],
      })
      toast('Playbook created', 'good')
      setPlaybookModalOpen(false)
      bump()
      await reloadPlaybooks()
    } catch (err) {
      toast(`Failed to create playbook: ${errorText(err)}`, 'bad')
    } finally {
      setSavingPb(false)
    }
  }

  const handleDeletePlaybook = async (id: string) => {
    if (!confirm('Are you sure you want to delete this playbook?')) return
    try {
      await api.delete(`/api/playbooks/${id}`)
      toast('Playbook deleted', 'good')
      bump()
      await reloadPlaybooks()
    } catch (err) {
      toast(`Failed to delete playbook: ${errorText(err)}`, 'bad')
    }
  }

  return (
    <div className="view-container" style={{ padding: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <div>
          <h1 className="greeting-text">Routines & Playbooks</h1>
          <div className="greeting-sub">
            Automated background workflows, periodic system checks, and multi-agent playbooks.
          </div>
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

          {activeTab === 'routines' ? (
            <button onClick={openCreateRoutine} className="btn btn-primary btn-sm" type="button">
              <Icon name="plus" size={14} />
              <span>New Routine</span>
            </button>
          ) : (
            <button onClick={openCreatePlaybook} className="btn btn-primary btn-sm" type="button">
              <Icon name="plus" size={14} />
              <span>New Playbook</span>
            </button>
          )}
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
              <button onClick={openCreateRoutine} className="btn btn-primary btn-sm" type="button">
                Schedule First Routine
              </button>
            </div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: '16px' }}>
              {routines.map((r) => {
                const assignedAgent = agents.find((a) => a.id === r.agent_id)
                const assignedPlaybook = playbooks.find((p) => p.id === r.playbook_id)

                return (
                  <div key={r.id} className="card" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                      <div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <h3 style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-main)' }}>{r.name}</h3>
                          <TargetPill target={r.target} size="sm" />
                        </div>
                        <div style={{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', marginTop: '2px' }}>
                          {r.when || 'Schedule'}
                          {assignedAgent && ` • ${assignedAgent.name}`}
                          {assignedPlaybook && ` • Playbook: ${assignedPlaybook.name}`}
                        </div>
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <button
                          onClick={() => openEditRoutine(r)}
                          className="btn btn-ghost btn-sm btn-icon"
                          type="button"
                          title="Edit routine"
                        >
                          <Icon name="sliders" size={14} />
                        </button>

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
                          onClick={() => handleDeleteRoutine(r.id)}
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
                )
              })}
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
              <p style={{ fontSize: '13px', color: 'var(--text-muted)', margin: '6px 0 16px 0' }}>
                Playbooks orchestrate complex sequential workflows between multiple specialist agents.
              </p>
              <button onClick={openCreatePlaybook} className="btn btn-primary btn-sm" type="button">
                Create First Playbook
              </button>
            </div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '16px' }}>
              {playbooks.map((pb) => (
                <div key={pb.id} className="card" style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div>
                      <div style={{ fontWeight: 600, fontSize: '15px', color: 'var(--text-main)' }}>{pb.name}</div>
                      <div style={{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', marginTop: '2px' }}>
                        {pb.task_signature}
                      </div>
                    </div>
                    <button
                      onClick={() => handleDeletePlaybook(pb.id)}
                      className="btn btn-ghost btn-sm btn-icon"
                      type="button"
                      title="Delete playbook"
                    >
                      <Icon name="trash" size={14} />
                    </button>
                  </div>
                  <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                    {pb.description || 'No description'}
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 'auto', paddingTop: '8px', borderTop: '1px solid var(--border-subtle)' }}>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                      v{pb.version} • {pb.success_count} runs
                    </div>
                    <TargetPill target={pb.target} size="sm" />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Routine Creator / Editor Modal */}
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

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
            <div>
              <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
                Specialist Agent (Optional)
              </label>
              <select
                className="select"
                value={agentId}
                onChange={(e) => setAgentId(e.target.value)}
              >
                <option value="">Auto Specialist</option>
                {agents.map((ag) => (
                  <option key={ag.id} value={ag.id}>
                    {ag.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
                Playbook (Optional)
              </label>
              <select
                className="select"
                value={playbookId}
                onChange={(e) => setPlaybookId(e.target.value)}
              >
                <option value="">No Playbook</option>
                {playbooks.map((pb) => (
                  <option key={pb.id} value={pb.id}>
                    {pb.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '6px' }}>
              Schedule Type
            </label>
            <div style={{ display: 'flex', gap: '12px', marginBottom: '8px' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', cursor: 'pointer' }}>
                <input
                  type="radio"
                  name="scheduleKind"
                  checked={scheduleKind === 'every'}
                  onChange={() => setScheduleKind('every')}
                />
                <span>Every N Minutes</span>
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', cursor: 'pointer' }}>
                <input
                  type="radio"
                  name="scheduleKind"
                  checked={scheduleKind === 'at'}
                  onChange={() => setScheduleKind('at')}
                />
                <span>Specific Time & Weekdays</span>
              </label>
            </div>

            {scheduleKind === 'every' ? (
              <div>
                <label style={{ display: 'block', fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>
                  Interval in minutes (minimum 5 minutes)
                </label>
                <input
                  type="number"
                  min="5"
                  step="1"
                  className="input"
                  value={everyMinutes}
                  onChange={(e) => setEveryMinutes(Math.max(5, Number(e.target.value)))}
                  placeholder="e.g. 60"
                  required
                />
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>
                    Run time (HH:MM 24-hour)
                  </label>
                  <input
                    type="time"
                    className="input"
                    value={atTime}
                    onChange={(e) => setAtTime(e.target.value)}
                    required
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '11px', color: 'var(--text-muted)', marginBottom: '6px' }}>
                    Active Days
                  </label>
                  <div style={{ display: 'flex', gap: '6px' }}>
                    {DAYS_OF_WEEK.map((d) => {
                      const isSelected = selectedDays.includes(d.value)
                      return (
                        <button
                          key={d.value}
                          type="button"
                          onClick={() => toggleDay(d.value)}
                          className={`btn btn-sm ${isSelected ? 'btn-primary' : 'btn-ghost'}`}
                          style={{ minWidth: '40px', padding: '4px 8px' }}
                        >
                          {d.label}
                        </button>
                      )
                    })}
                  </div>
                </div>
              </div>
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
                <span>DevBox (Sandbox Container)</span>
              </label>
            </div>
          </div>
        </form>
      </Modal>

      {/* Playbook Creator Modal */}
      <Modal
        isOpen={playbookModalOpen}
        onClose={() => setPlaybookModalOpen(false)}
        title="Create Playbook"
        footer={
          <>
            <button type="button" onClick={() => setPlaybookModalOpen(false)} className="btn btn-secondary">
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSavePlaybook}
              disabled={!pbName.trim() || savingPb}
              className="btn btn-primary"
            >
              <span>{savingPb ? 'Creating...' : 'Create Playbook'}</span>
            </button>
          </>
        }
      >
        <form onSubmit={handleSavePlaybook} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
              Playbook Name
            </label>
            <input
              className="input"
              value={pbName}
              onChange={(e) => setPbName(e.target.value)}
              placeholder="e.g. Full Release Verification"
              required
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
              Task Signature
            </label>
            <input
              className="input"
              value={pbSignature}
              onChange={(e) => setPbSignature(e.target.value)}
              placeholder="e.g. release_verification"
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
              Description
            </label>
            <textarea
              className="textarea"
              rows={3}
              value={pbDescription}
              onChange={(e) => setPbDescription(e.target.value)}
              placeholder="Describe the multi-step or multi-agent playbook workflow..."
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '6px' }}>
              Target Environment
            </label>
            <div style={{ display: 'flex', gap: '12px' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', cursor: 'pointer' }}>
                <input
                  type="radio"
                  name="pbTarget"
                  checked={pbTarget === 'host'}
                  onChange={() => setPbTarget('host')}
                />
                <span>Host</span>
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', cursor: 'pointer' }}>
                <input
                  type="radio"
                  name="pbTarget"
                  checked={pbTarget === 'devbox'}
                  onChange={() => setPbTarget('devbox')}
                />
                <span>DevBox</span>
              </label>
            </div>
          </div>
        </form>
      </Modal>
    </div>
  )
}
