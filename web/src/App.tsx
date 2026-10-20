import React, { useEffect } from 'react'
import { useAppStore, type NavSection } from './store'
import { liveEvents } from './events'
import { useKeyCombo } from './hooks'
import { Sidebar } from './ui/Sidebar'
import { CommandPalette } from './ui/CommandPalette'
import { ToastContainer } from './ui/Toast'
import { TalkView } from './views/Talk'
import { WorkspaceView } from './views/Workspace'
import { AgentsView } from './views/Agents'
import { MemoryView } from './views/Memory'
import { NotesView } from './views/Notes'
import { SkillsView } from './views/Skills'
import { RoutinesView } from './views/Routines'
import { ApprovalsView } from './views/Approvals'
import { ActivityView } from './views/Activity'
import { ModelsView } from './views/Models'
import { SettingsView } from './views/Settings'
import { ResourcesView } from './views/Resources'
import { CompanionWidget } from './ui/CompanionWidget'

export const App: React.FC = () => {
  const section = useAppStore((s) => s.section)
  const setSection = useAppStore((s) => s.setSection)
  const setCommandPalette = useAppStore((s) => s.setCommandPalette)

  // Start SSE stream on mount
  useEffect(() => {
    liveEvents.start()
    return () => {
      liveEvents.stop()
    }
  }, [])

  // Sync hash routing
  useEffect(() => {
    const handleHash = () => {
      const hash = window.location.hash.replace(/^#\/?/, '').toLowerCase()
      const valid: NavSection[] = [
        'talk',
        'workspace',
        'agents',
        'memory',
        'notes',
        'skills',
        'routines',
        'approvals',
        'activity',
        'models',
        'settings',
        'resources',
      ]
      if (valid.includes(hash as NavSection)) {
        setSection(hash as NavSection)
      }
    }

    handleHash()
    window.addEventListener('hashchange', handleHash)
    return () => window.removeEventListener('hashchange', handleHash)
  }, [setSection])

  // Update URL hash when section changes
  useEffect(() => {
    if (window.location.hash !== `#/${section}`) {
      window.history.replaceState(null, '', `#/${section}`)
    }
  }, [section])

  // Cmd+K / Ctrl+K shortcut
  useKeyCombo('k', true, () => {
    setCommandPalette(true)
  })

  const renderView = () => {
    switch (section) {
      case 'talk':
        return <TalkView />
      case 'workspace':
        return <WorkspaceView />
      case 'agents':
        return <AgentsView />
      case 'memory':
        return <MemoryView />
      case 'notes':
        return <NotesView />
      case 'skills':
        return <SkillsView />
      case 'routines':
        return <RoutinesView />
      case 'approvals':
        return <ApprovalsView />
      case 'activity':
        return <ActivityView />
      case 'models':
        return <ModelsView />
      case 'settings':
        return <SettingsView />
      case 'resources':
        return <ResourcesView />
      default:
        return <TalkView />
    }
  }

  return (
    <div className="app-shell">
      <Sidebar />
      <main className="app-main" id="main-content">
        {renderView()}
      </main>
      <CompanionWidget />
      <CommandPalette />
      <ToastContainer />
    </div>
  )
}
