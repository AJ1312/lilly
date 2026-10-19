import React from 'react'
import type { ExecutionTarget, TaskState, TaskOutcome } from '../types'
import { Icon } from './Icon'

export const TargetPill: React.FC<{ target?: ExecutionTarget | null; size?: 'sm' | 'md' }> = ({
  target = 'host',
  size = 'md',
}) => {
  const isHost = target !== 'devbox'
  return (
    <span
      className={`pill ${isHost ? 'pill-host' : 'pill-devbox'} ${size === 'sm' ? 'btn-sm' : ''}`}
      title={isHost ? 'Runs on this Laptop (Host OS)' : 'Runs in isolated DevBox container'}
    >
      <Icon name={isHost ? 'laptop' : 'cloud'} size={12} />
      <span>{isHost ? 'Host' : 'DevBox'}</span>
    </span>
  )
}

export const StatePill: React.FC<{ state: TaskState }> = ({ state }) => {
  let cls = 'pill-state-running'
  let label = state.toLowerCase()

  switch (state) {
    case 'DONE':
      cls = 'pill-state-done'
      label = 'done'
      break
    case 'FAILED':
    case 'CANCELLED':
    case 'EXPIRED':
      cls = 'pill-state-failed'
      label = state.toLowerCase()
      break
    case 'WAITING_APPROVAL':
      cls = 'pill-state-waiting'
      label = 'approval'
      break
    case 'PLANNING':
    case 'RUNNING':
    case 'VERIFYING':
      cls = 'pill-state-running'
      label = state.toLowerCase()
      break
    case 'PENDING':
      cls = 'card-subtle'
      label = 'pending'
      break
  }

  return <span className={`pill ${cls}`}>{label}</span>
}

export const OutcomePill: React.FC<{ outcome?: TaskOutcome | null }> = ({ outcome }) => {
  if (!outcome) return null
  let cls = 'pill-state-done'
  if (outcome === 'blocked' || outcome === 'needs_user') {
    cls = 'pill-state-waiting'
  }

  return <span className={`pill ${cls}`}>{outcome}</span>
}

export const RiskPill: React.FC<{ risk?: 'R0' | 'R1' | 'R2' | string }> = ({ risk = 'R0' }) => {
  let cls = 'pill-risk-r0'
  let label = 'Low (R0)'
  if (risk === 'R1') {
    cls = 'pill-risk-r1'
    label = 'Medium (R1)'
  } else if (risk === 'R2') {
    cls = 'pill-risk-r2'
    label = 'High Risk (R2)'
  }

  return (
    <span className={`pill ${cls}`}>
      <Icon name="shield" size={11} />
      <span>{label}</span>
    </span>
  )
}
