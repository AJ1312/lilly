import React, { useState, useEffect } from 'react'
import { useAppStore } from '../store'
import { AgentPet, type PetState } from './AgentPet'
import { Icon } from './Icon'
import { useLoad } from '../hooks'
import { api } from '../api'
import type { Task, Agent, Settings } from '../types'

export const CompanionWidget: React.FC = () => {
  const [minimized, setMinimized] = useState(false)
  const [activeTask, setActiveTask] = useState<Task | null>(null)
  const [activeAgent, setActiveAgent] = useState<Agent | null>(null)
  const setSection = useAppStore((s) => s.setSection)
  const runningTasksCount = useAppStore((s) => s.runningTasksCount)
  const pendingApprovalsCount = useAppStore((s) => s.pendingApprovalsCount)

  // Fetch running task info if tasks are active
  useEffect(() => {
    let active = true
    if (runningTasksCount > 0) {
      api
        .get<{ tasks: Task[] }>('/api/tasks?state=RUNNING,PLANNING,VERIFYING&limit=1')
        .then((res) => {
          if (active && res.tasks && res.tasks[0]) {
            setActiveTask(res.tasks[0])
            if (res.tasks[0].agent_id) {
              api
                .get<{ agents: Agent[] }>('/api/agents')
                .then((agRes) => {
                  const ag = agRes.agents?.find((a) => a.id === res.tasks[0].agent_id)
                  if (active && ag) setActiveAgent(ag)
                })
                .catch(() => {})
            }
          }
        })
        .catch(() => {})
    } else {
      setActiveTask(null)
    }

    return () => {
      active = false
    }
  }, [runningTasksCount])

  // Load autonomy & approval mode settings
  const { data: settingsData } = useLoad<{ settings: Settings }>('/api/settings', 6000)
  const approvalMode = settingsData?.settings?.approval_mode || 'MANUAL'

  // Derive pet state from real agent activity
  let petState: PetState = 'idle'
  let currentThought =
    approvalMode === 'OFF'
      ? 'Off mode: all agentic tasks stopped, ready for conversational chat.'
      : approvalMode === 'AUTO'
      ? 'Auto mode: ready to move without asking permission.'
      : 'Ask mode: ready to assist; I will ask for permission before acting.'

  if (pendingApprovalsCount > 0) {
    petState = 'approval'
    currentThought = `${pendingApprovalsCount} security approval request requires your review!`
  } else if (activeTask) {
    if (activeTask.state === 'PLANNING') {
      petState = 'thinking'
      currentThought = `Planning steps for: "${activeTask.goal.slice(0, 48)}..."`
    } else {
      petState = 'working'
      currentThought = `Executing: "${activeTask.goal.slice(0, 52)}..."`
    }
  }

  const species = activeAgent?.pet || 'lily'
  const look = activeAgent?.look || { accessory: 'none', eyes: 'round', blush: true }
  const agentName = activeAgent?.name || 'Lilly'

  if (minimized) {
    return (
      <button
        type="button"
        onClick={() => setMinimized(false)}
        className="btn"
        style={{
          position: 'fixed',
          bottom: '24px',
          right: '24px',
          zIndex: 90,
          borderRadius: 'var(--radius-full)',
          padding: '6px 14px',
          backgroundColor: 'var(--bg-card)',
          border: '1px solid var(--border)',
          boxShadow: 'var(--shadow-lg)',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          cursor: 'pointer',
        }}
        title="Open AI Companion"
      >
        <AgentPet
          species={species}
          look={look}
          state={petState}
          size={24}
          interactive={false}
        />
        <span style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-main)' }}>
          {agentName}
        </span>
        {petState !== 'idle' && (
          <span
            style={{
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              backgroundColor:
                petState === 'approval'
                  ? 'var(--warning)'
                  : petState === 'working'
                  ? 'var(--accent-lime)'
                  : 'var(--primary)',
            }}
          />
        )}
      </button>
    )
  }

  return (
    <div className="companion-dock" style={{ zIndex: 90 }}>
      {/* Live Thought Bubble */}
      <div className="companion-pill-bubble">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ fontSize: '10px', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--text-dim)' }}>
              {agentName} • {petState}
            </span>
            <span
              style={{
                fontSize: '9px',
                fontWeight: 700,
                padding: '1px 5px',
                borderRadius: '8px',
                backgroundColor:
                  approvalMode === 'AUTO'
                    ? 'var(--primary-subtle)'
                    : approvalMode === 'MANUAL'
                    ? 'var(--warning-subtle)'
                    : 'var(--bg-subtle)',
                color:
                  approvalMode === 'AUTO'
                    ? 'var(--primary)'
                    : approvalMode === 'MANUAL'
                    ? 'var(--warning-text)'
                    : 'var(--text-muted)',
              }}
            >
              {approvalMode === 'AUTO' ? 'Auto' : approvalMode === 'MANUAL' ? 'Ask' : 'Off'}
            </span>
          </div>
          <button
            type="button"
            onClick={() => setMinimized(true)}
            className="btn btn-ghost"
            style={{ padding: '2px', height: 'auto', minWidth: 'auto', color: 'var(--text-muted)' }}
            title="Minimize companion"
          >
            <Icon name="x" size={11} />
          </button>
        </div>

        <div style={{ fontSize: '12px', color: 'var(--text-main)', marginBottom: '8px' }}>
          {currentThought}
        </div>

        {pendingApprovalsCount > 0 ? (
          <button
            type="button"
            onClick={() => setSection('approvals')}
            className="btn btn-warning btn-sm"
            style={{ width: '100%', fontSize: '11px', padding: '4px 8px' }}
          >
            <Icon name="shield" size={12} />
            <span>Review Approvals</span>
          </button>
        ) : activeTask ? (
          <button
            type="button"
            onClick={() => setSection('workspace')}
            className="btn btn-secondary btn-sm"
            style={{ width: '100%', fontSize: '11px', padding: '4px 8px' }}
          >
            <Icon name="tasks" size={12} />
            <span>Inspect Task</span>
          </button>
        ) : null}
      </div>

      {/* Full Body Character */}
      <div style={{ position: 'relative' }}>
        <AgentPet
          species={species}
          look={look}
          state={petState}
          size={78}
          agentName={agentName}
          currentThought={currentThought}
          interactive={true}
          onAction={(act) => {
            if (act === 'talk') setSection('talk')
          }}
        />
      </div>
    </div>
  )
}
