import React, { useState, useEffect, useRef } from 'react'
import { useAppStore } from '../store'
import { Icon, type IconName } from './Icon'
import { api, errorText } from '../api'

interface CommandItem {
  id: string
  title: string
  subtitle?: string
  icon: IconName
  category: 'Navigation' | 'Actions' | 'Theme'
  action: () => void | Promise<void>
}

export const CommandPalette: React.FC = () => {
  const isOpen = useAppStore((s) => s.commandPaletteOpen)
  const setOpen = useAppStore((s) => s.setCommandPalette)
  const setSection = useAppStore((s) => s.setSection)
  const setTheme = useAppStore((s) => s.setTheme)
  const toast = useAppStore((s) => s.toast)

  const [query, setQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  const items: CommandItem[] = [
    // Navigation
    {
      id: 'nav-talk',
      title: 'Talk with Lilly',
      subtitle: 'Conversational assistant, live streaming, tasks',
      icon: 'chat',
      category: 'Navigation',
      action: () => setSection('talk'),
    },
    {
      id: 'nav-workspace',
      title: 'Workspace / Tasks',
      subtitle: 'Task center, execution traces, artifacts',
      icon: 'tasks',
      category: 'Navigation',
      action: () => setSection('workspace'),
    },
    {
      id: 'nav-agents',
      title: 'Agents Studio',
      subtitle: 'Manage specialist personas, capabilities, and system instructions',
      icon: 'agents',
      category: 'Navigation',
      action: () => setSection('agents'),
    },
    {
      id: 'nav-memory',
      title: 'Memory Bank',
      subtitle: 'Curated knowledge, user facts, constraints',
      icon: 'memory',
      category: 'Navigation',
      action: () => setSection('memory'),
    },
    {
      id: 'nav-skills',
      title: 'Skills Catalog',
      subtitle: 'System & custom skills, schemas, execution',
      icon: 'skills',
      category: 'Navigation',
      action: () => setSection('skills'),
    },
    {
      id: 'nav-routines',
      title: 'Routines & Playbooks',
      subtitle: 'Schedules, recurring workflows, multi-agent',
      icon: 'routines',
      category: 'Navigation',
      action: () => setSection('routines'),
    },
    {
      id: 'nav-approvals',
      title: 'Approvals Queue',
      subtitle: 'Review pending security and tool approvals',
      icon: 'approvals',
      category: 'Navigation',
      action: () => setSection('approvals'),
    },
    {
      id: 'nav-activity',
      title: 'Activity Log',
      subtitle: 'Real-time timeline, security audit trail',
      icon: 'activity',
      category: 'Navigation',
      action: () => setSection('activity'),
    },
    {
      id: 'nav-models',
      title: 'Models & API Keys',
      subtitle: 'Configure LLM providers, test connections',
      icon: 'models',
      category: 'Navigation',
      action: () => setSection('models'),
    },
    {
      id: 'nav-settings',
      title: 'Settings',
      subtitle: 'DevBox, MCP servers, privacy, policy',
      icon: 'settings',
      category: 'Navigation',
      action: () => setSection('settings'),
    },
    {
      id: 'nav-resources',
      title: 'System Resources',
      subtitle: 'Live CPU, memory, disk, active processes',
      icon: 'resources',
      category: 'Navigation',
      action: () => setSection('resources'),
    },

    // Actions
    {
      id: 'action-stop-all',
      title: 'Emergency Stop All Tasks',
      subtitle: 'Immediately cancel all active and queued executions',
      icon: 'stop',
      category: 'Actions',
      action: async () => {
        try {
          await api.post('/api/stop')
          toast('Emergency stop signal sent to engine', 'good')
        } catch (e) {
          toast(`Failed to stop: ${errorText(e)}`, 'bad')
        }
      },
    },
    {
      id: 'action-revoke-all',
      title: 'Revoke All Runtime Permissions',
      subtitle: 'Instantly revoke all granted tool grants and file root access',
      icon: 'shield',
      category: 'Actions',
      action: async () => {
        try {
          await api.post('/api/permissions/revoke-all')
          toast('All runtime permissions have been revoked', 'warn')
        } catch (e) {
          toast(`Failed to revoke: ${errorText(e)}`, 'bad')
        }
      },
    },

    // Theme
    {
      id: 'theme-dark',
      title: 'Theme: Dark',
      subtitle: 'Switch interface to dark mode',
      icon: 'moon',
      category: 'Theme',
      action: () => setTheme('dark'),
    },
    {
      id: 'theme-light',
      title: 'Theme: Light',
      subtitle: 'Switch interface to light mode',
      icon: 'sun',
      category: 'Theme',
      action: () => setTheme('light'),
    },
    {
      id: 'theme-system',
      title: 'Theme: System',
      subtitle: 'Match system preference',
      icon: 'sparkles',
      category: 'Theme',
      action: () => setTheme('system'),
    },
  ]

  const filtered = items.filter(
    (item) =>
      item.title.toLowerCase().includes(query.toLowerCase()) ||
      item.subtitle?.toLowerCase().includes(query.toLowerCase()) ||
      item.category.toLowerCase().includes(query.toLowerCase())
  )

  useEffect(() => {
    if (isOpen) {
      setQuery('')
      setSelectedIndex(0)
      const t = setTimeout(() => inputRef.current?.focus(), 50)
      return () => clearTimeout(t)
    }
  }, [isOpen])

  if (!isOpen) return null

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      setOpen(false)
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIndex((prev) => (prev + 1) % (filtered.length || 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex((prev) => (prev - 1 + filtered.length) % (filtered.length || 1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const item = filtered[selectedIndex]
      if (item) {
        void item.action()
        setOpen(false)
      }
    }
  }

  return (
    <div
      className="dialog"
      onClick={(e) => {
        if (e.target === e.currentTarget) setOpen(false)
      }}
    >
      <div className="dialog-content" onKeyDown={handleKeyDown}>
        <div className="command-palette-input-wrap">
          <Icon name="search" size={18} style={{ color: 'var(--text-muted)' }} />
          <input
            ref={inputRef}
            className="command-palette-input"
            placeholder="Type a command or search..."
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setSelectedIndex(0)
            }}
          />
          <kbd className="kbd-badge">esc</kbd>
        </div>

        <div className="command-palette-list">
          {filtered.length === 0 ? (
            <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)' }}>
              No commands found for &ldquo;{query}&rdquo;
            </div>
          ) : (
            filtered.map((item, idx) => (
              <div
                key={item.id}
                className={`command-palette-item ${idx === selectedIndex ? 'active' : ''}`}
                onClick={() => {
                  void item.action()
                  setOpen(false)
                }}
                onMouseEnter={() => setSelectedIndex(idx)}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <Icon name={item.icon} size={16} />
                  <div>
                    <div style={{ fontWeight: 500 }}>{item.title}</div>
                    {item.subtitle && (
                      <div
                        style={{
                          fontSize: '11px',
                          opacity: 0.8,
                          marginTop: '2px',
                        }}
                      >
                        {item.subtitle}
                      </div>
                    )}
                  </div>
                </div>
                <span
                  style={{
                    fontSize: '11px',
                    opacity: 0.7,
                    textTransform: 'uppercase',
                    letterSpacing: '0.04em',
                  }}
                >
                  {item.category}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
