import { describe, it, expect, beforeEach } from 'vitest'
import { useAppStore } from './store'

describe('useAppStore and Navigation', () => {
  beforeEach(() => {
    useAppStore.setState({
      section: 'talk',
      subSection: null,
      theme: 'light',
      commandPaletteOpen: false,
      sidebarCollapsed: false,
      pendingApprovalsCount: 0,
      runningTasksCount: 0,
      liveConnected: false,
      toasts: [],
      selectedTaskId: null,
      selectedThreadId: null,
    })
  })

  it('initializes on talk section', () => {
    const state = useAppStore.getState()
    expect(state.section).toBe('talk')
    expect(state.commandPaletteOpen).toBe(false)
  })

  it('updates sections cleanly', () => {
    const { setSection } = useAppStore.getState()
    setSection('workspace')
    expect(useAppStore.getState().section).toBe('workspace')

    setSection('models')
    expect(useAppStore.getState().section).toBe('models')

    setSection('settings')
    expect(useAppStore.getState().section).toBe('settings')
  })

  it('toggles command palette', () => {
    const { setCommandPalette } = useAppStore.getState()
    setCommandPalette(true)
    expect(useAppStore.getState().commandPaletteOpen).toBe(true)

    setCommandPalette(false)
    expect(useAppStore.getState().commandPaletteOpen).toBe(false)
  })

  it('dispatches and clears toasts', () => {
    const { toast, removeToast } = useAppStore.getState()
    toast('Task created', 'good')

    const toasts = useAppStore.getState().toasts
    expect(toasts.length).toBe(1)
    expect(toasts[0].text).toBe('Task created')
    expect(toasts[0].kind).toBe('good')

    removeToast(toasts[0].id)
    expect(useAppStore.getState().toasts.length).toBe(0)
  })

  it('tracks pending approvals count', () => {
    const { setPendingApprovals } = useAppStore.getState()
    setPendingApprovals(3)
    expect(useAppStore.getState().pendingApprovalsCount).toBe(3)
  })

  it('updates themes', () => {
    const { setTheme } = useAppStore.getState()
    setTheme('dark')
    expect(useAppStore.getState().theme).toBe('dark')
  })
})
