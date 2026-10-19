import React from 'react'
import { useAppStore, type NavSection } from '../store'
import { Icon, type IconName } from './Icon'
import { LillyMascot } from './LillyMascot'
import { api, errorText } from '../api'

interface NavEntry {
  id: NavSection
  label: string
  icon: IconName
  badge?: number
  badgeWarn?: boolean
}

export const Sidebar: React.FC = () => {
  const currentSection = useAppStore((s) => s.section)
  const setSection = useAppStore((s) => s.setSection)
  const collapsed = useAppStore((s) => s.sidebarCollapsed)
  const toggleSidebar = useAppStore((s) => s.toggleSidebar)
  const pendingApprovals = useAppStore((s) => s.pendingApprovalsCount)
  const runningTasks = useAppStore((s) => s.runningTasksCount)
  const liveConnected = useAppStore((s) => s.liveConnected)
  const theme = useAppStore((s) => s.theme)
  const setTheme = useAppStore((s) => s.setTheme)
  const toast = useAppStore((s) => s.toast)

  const navItems: NavEntry[] = [
    { id: 'talk', label: 'Talk', icon: 'chat' },
    {
      id: 'workspace',
      label: 'Workspace',
      icon: 'tasks',
      badge: runningTasks > 0 ? runningTasks : undefined,
    },
    { id: 'agents', label: 'Agents', icon: 'agents' },
    { id: 'memory', label: 'Memory', icon: 'memory' },
    { id: 'skills', label: 'Skills', icon: 'skills' },
    { id: 'routines', label: 'Routines', icon: 'routines' },
    {
      id: 'approvals',
      label: 'Approvals',
      icon: 'approvals',
      badge: pendingApprovals > 0 ? pendingApprovals : undefined,
      badgeWarn: true,
    },
    { id: 'activity', label: 'Activity', icon: 'activity' },
    { id: 'models', label: 'Models', icon: 'models' },
    { id: 'settings', label: 'Settings', icon: 'settings' },
    { id: 'resources', label: 'Resources', icon: 'resources' },
  ]

  const handleStopAll = async () => {
    try {
      await api.post('/api/stop')
      toast('Emergency stop executed', 'good')
    } catch (e) {
      toast(`Stop failed: ${errorText(e)}`, 'bad')
    }
  }

  const toggleTheme = () => {
    if (theme === 'dark') setTheme('light')
    else setTheme('dark')
  }

  return (
    <aside className={`rail ${collapsed ? 'collapsed' : ''}`} aria-label="Main Navigation">
      <div>
        <div className="sidebar-header">
          <div className="brand-wrapper" onClick={() => setSection('talk')} title="Click to talk with Lilly">
            <LillyMascot
              size={collapsed ? 36 : 42}
              look={{ hue: 250, eyes: 'happy', accessory: 'none', blush: true }}
              interactive
              state={runningTasks > 0 ? 'thinking' : 'idle'}
            />
            {!collapsed && (
              <div>
                <span className="brand-title">Lilly</span>
                <div style={{ fontSize: '10px', color: 'var(--text-dim)', fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                  Agent Workspace
                </div>
              </div>
            )}
          </div>
          <button
            onClick={toggleSidebar}
            className="btn btn-ghost btn-sm btn-icon"
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            type="button"
          >
            <Icon name={collapsed ? 'chevron-right' : 'chevron-left'} size={14} />
          </button>
        </div>

        <nav className="sidebar-nav">
          {!collapsed && <div className="nav-section-label">Navigation</div>}
          {navItems.map((item) => {
            const isActive = currentSection === item.id
            return (
              <button
                key={item.id}
                onClick={() => setSection(item.id)}
                className={`nav-item ${isActive ? 'active' : ''}`}
                title={item.label}
                type="button"
              >
                <div className="nav-item-icon">
                  <Icon name={item.icon} size={16} />
                </div>
                {!collapsed && <span className="nav-item-label">{item.label}</span>}
                {!collapsed && item.badge !== undefined && (
                  <span
                    className={`nav-badge ${item.badgeWarn ? 'nav-badge-warn' : 'nav-badge-info'}`}
                  >
                    {item.badge}
                  </span>
                )}
              </button>
            )
          })}
        </nav>
      </div>

      <div className="sidebar-footer">
        {/* Live SSE status */}
        <div className="live-indicator" title={liveConnected ? 'Live stream connected to Lilly engine' : 'Connecting to live events stream...'}>
          <div className={`live-dot ${liveConnected ? 'connected' : ''}`} />
          {!collapsed && (
            <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: 600 }}>
              {liveConnected ? 'Live Engine' : 'Reconnecting...'}
            </span>
          )}
        </div>

        {/* Action buttons */}
        <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
          <button
            onClick={toggleTheme}
            className="btn btn-ghost btn-sm"
            style={{ flex: 1, justifyContent: collapsed ? 'center' : 'flex-start' }}
            title={`Switch theme (currently ${theme})`}
            type="button"
          >
            <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={14} />
            {!collapsed && <span>{theme === 'dark' ? 'Light' : 'Dark'}</span>}
          </button>

          {runningTasks > 0 && (
            <button
              onClick={handleStopAll}
              className="btn btn-danger btn-sm btn-icon"
              title="Emergency stop active tasks"
              type="button"
            >
              <Icon name="stop" size={14} />
            </button>
          )}
        </div>
      </div>
    </aside>
  )
}
