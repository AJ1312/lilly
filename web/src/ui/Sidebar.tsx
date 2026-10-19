import React from 'react'
import { useAppStore, type NavSection } from '../store'
import { Icon, type IconName } from './Icon'
import { api, errorText } from '../api'

import { LillyLogo } from './LillyLogo'

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
    { id: 'talk', label: 'Talk & Assist', icon: 'chat' },
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

  return (
    <aside className={`rail ${collapsed ? 'collapsed' : ''}`} aria-label="Main Navigation">
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
        <div className="sidebar-header">
          <div className="brand-wrapper" onClick={() => setSection('talk')} title="Lilly AI Workspace">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <LillyLogo size={collapsed ? 26 : 28} />
            </div>
            {!collapsed && (
              <div>
                <span className="brand-title">Lilly</span>
                <div style={{ fontSize: '10px', color: 'var(--text-dim)', fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                  AI Workspace
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Navigation list */}
        <nav style={{ flex: 1, overflowY: 'auto' }}>
          <ul className="nav-list">
            {navItems.map((item) => {
              const active = currentSection === item.id
              return (
                <li key={item.id}>
                  <button
                    type="button"
                    className={`nav-link ${active ? 'active' : ''}`}
                    onClick={() => setSection(item.id)}
                    title={collapsed ? item.label : undefined}
                  >
                    <Icon name={item.icon} size={18} />
                    {!collapsed && <span>{item.label}</span>}
                    {!collapsed && item.badge !== undefined && (
                      <span className="nav-link-badge">
                        {item.badge}
                      </span>
                    )}
                  </button>
                </li>
              )
            })}
          </ul>
        </nav>

        {/* Footer info & Controls */}
        <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: '12px', marginTop: 'auto' }}>
          {!collapsed ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '11px', color: 'var(--text-muted)' }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span
                    style={{
                      width: '7px',
                      height: '7px',
                      borderRadius: '50%',
                      backgroundColor: liveConnected ? 'var(--success)' : 'var(--danger)',
                    }}
                  />
                  {liveConnected ? 'Live sync' : 'Offline'}
                </span>
                <button
                  type="button"
                  onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
                  className="btn btn-ghost btn-sm"
                  style={{ padding: '2px 8px', fontSize: '11px' }}
                >
                  <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={12} />
                  <span>{theme === 'dark' ? 'Light' : 'Dark'}</span>
                </button>
              </div>

              {runningTasks > 0 && (
                <button
                  type="button"
                  onClick={handleStopAll}
                  className="btn btn-danger btn-sm"
                  style={{ width: '100%', fontSize: '11px' }}
                >
                  <Icon name="stop" size={12} />
                  <span>Stop All ({runningTasks})</span>
                </button>
              )}
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
              <span
                style={{
                  width: '8px',
                  height: '8px',
                  borderRadius: '50%',
                  backgroundColor: liveConnected ? 'var(--success)' : 'var(--danger)',
                }}
                title={liveConnected ? 'SSE Live Connected' : 'Offline'}
              />
              <button
                type="button"
                onClick={toggleSidebar}
                className="btn btn-ghost btn-sm"
                style={{ padding: '4px' }}
                title="Expand Navigation"
              >
                <Icon name="chevron-right" size={14} />
              </button>
            </div>
          )}
        </div>
      </div>
    </aside>
  )
}
