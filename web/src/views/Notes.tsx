import React, { useState, useEffect, useMemo } from 'react'
import { api, errorText } from '../api'
import { useLoad } from '../hooks'
import { useAppStore } from '../store'
import type { Space, NotePage } from '../types'
import { Icon } from '../ui/Icon'
import { Markdown } from '../ui/Markdown'
import { Modal } from '../ui/Modal'

export const NotesView: React.FC = () => {
  const toast = useAppStore((s) => s.toast)
  const bump = useAppStore((s) => s.bump)

  // 1. Spaces list
  const { data: spacesData, loading: loadingSpaces, reload: reloadSpaces } =
    useLoad<{ spaces: Space[] }>('/api/spaces')
  const spaces = useMemo(() => spacesData?.spaces || [], [spacesData])

  const [selectedSpaceId, setSelectedSpaceId] = useState<string | null>(null)
  const [selectedPageId, setSelectedPageId] = useState<string | null>(null)

  // Default to first space once loaded
  useEffect(() => {
    if (!selectedSpaceId && spaces.length > 0) {
      setSelectedSpaceId(spaces[0].id)
    }
  }, [spaces, selectedSpaceId])

  // 2. Pages list for selected space
  const pagesUrl = selectedSpaceId ? `/api/spaces/${selectedSpaceId}/pages` : null
  const { data: pagesData, loading: loadingPages, reload: reloadPages } =
    useLoad<{ pages: NotePage[] }>(pagesUrl || '')
  const pages = useMemo(() => pagesData?.pages || [], [pagesData])

  // Default to first page once pages loaded
  useEffect(() => {
    if (pages.length > 0 && (!selectedPageId || !pages.some((p) => p.id === selectedPageId))) {
      setSelectedPageId(pages[0].id)
    } else if (pages.length === 0) {
      setSelectedPageId(null)
    }
  }, [pages, selectedPageId])

  // 3. Active page details
  const [activePage, setActivePage] = useState<NotePage | null>(null)
  const [loadingActivePage, setLoadingActivePage] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [editContent, setEditContent] = useState('')
  const [savingPage, setSavingPage] = useState(false)

  // Modals
  const [spaceModalOpen, setSpaceModalOpen] = useState(false)
  const [newSpaceName, setNewSpaceName] = useState('')
  const [newSpaceDesc, setNewSpaceDesc] = useState('')
  const [creatingSpace, setCreatingSpace] = useState(false)

  const [pageModalOpen, setPageModalOpen] = useState(false)
  const [newPageTitle, setNewPageTitle] = useState('')
  const [newPageContent, setNewPageContent] = useState('')
  const [creatingPage, setCreatingPage] = useState(false)

  // Fetch full page content when selectedPageId changes
  useEffect(() => {
    if (!selectedSpaceId || !selectedPageId) {
      setActivePage(null)
      setIsEditing(false)
      return
    }

    let active = true
    setLoadingActivePage(true)
    api
      .get<{ page: NotePage }>(`/api/spaces/${selectedSpaceId}/pages/${selectedPageId}`)
      .then((res) => {
        if (!active) return
        setActivePage(res.page)
        setEditTitle(res.page.title)
        setEditContent(res.page.content)
      })
      .catch((err) => {
        if (!active) return
        toast(`Error loading note: ${errorText(err)}`, 'bad')
      })
      .finally(() => {
        if (active) setLoadingActivePage(false)
      })

    return () => {
      active = false
    }
  }, [selectedSpaceId, selectedPageId, toast])

  const handleCreateSpace = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newSpaceName.trim()) return

    setCreatingSpace(true)
    try {
      const res = await api.post<{ space: Space }>('/api/spaces', {
        name: newSpaceName.trim(),
        description: newSpaceDesc.trim(),
      })
      toast('Workspace space created', 'good')
      setSpaceModalOpen(false)
      setNewSpaceName('')
      setNewSpaceDesc('')
      bump()
      await reloadSpaces()
      setSelectedSpaceId(res.space.id)
    } catch (err) {
      toast(`Failed to create space: ${errorText(err)}`, 'bad')
    } finally {
      setCreatingSpace(false)
    }
  }

  const handleDeleteSpace = async (spaceId: string) => {
    if (!confirm('Are you sure you want to delete this space and all its notes?')) return
    try {
      await api.delete(`/api/spaces/${spaceId}`)
      toast('Space deleted', 'good')
      bump()
      if (selectedSpaceId === spaceId) {
        setSelectedSpaceId(null)
        setSelectedPageId(null)
      }
      await reloadSpaces()
    } catch (err) {
      toast(`Failed to delete space: ${errorText(err)}`, 'bad')
    }
  }

  const handleCreatePage = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedSpaceId || !newPageTitle.trim()) return

    setCreatingPage(true)
    try {
      const res = await api.post<{ page: NotePage }>(`/api/spaces/${selectedSpaceId}/pages`, {
        title: newPageTitle.trim(),
        content: newPageContent.trim(),
      })
      toast('Note page created', 'good')
      setPageModalOpen(false)
      setNewPageTitle('')
      setNewPageContent('')
      bump()
      await reloadPages()
      setSelectedPageId(res.page.id)
    } catch (err) {
      toast(`Failed to create note: ${errorText(err)}`, 'bad')
    } finally {
      setCreatingPage(false)
    }
  }

  const handleSavePage = async () => {
    if (!selectedSpaceId || !selectedPageId || !editTitle.trim()) return

    setSavingPage(true)
    try {
      const res = await api.put<{ page: NotePage }>(
        `/api/spaces/${selectedSpaceId}/pages/${selectedPageId}`,
        {
          title: editTitle.trim(),
          content: editContent,
        }
      )
      toast('Note saved', 'good')
      setActivePage(res.page)
      setIsEditing(false)
      bump()
      await reloadPages()
    } catch (err) {
      toast(`Failed to save note: ${errorText(err)}`, 'bad')
    } finally {
      setSavingPage(false)
    }
  }

  const handleDeletePage = async (pageId: string) => {
    if (!selectedSpaceId || !confirm('Are you sure you want to delete this note?')) return
    try {
      await api.delete(`/api/spaces/${selectedSpaceId}/pages/${pageId}`)
      toast('Note deleted', 'good')
      bump()
      if (selectedPageId === pageId) {
        setSelectedPageId(null)
      }
      await reloadPages()
    } catch (err) {
      toast(`Failed to delete note: ${errorText(err)}`, 'bad')
    }
  }

  return (
    <div className="view-container" style={{ padding: '24px', height: 'calc(100vh - 48px)', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
        <div>
          <h1 className="greeting-text">Spaces & Notes</h1>
          <div className="greeting-sub">
            Organize project documentation, operational runbooks, and agent workspace notes.
          </div>
        </div>

        <div style={{ display: 'flex', gap: '8px' }}>
          <button onClick={() => setSpaceModalOpen(true)} className="btn btn-secondary btn-sm" type="button">
            <Icon name="plus" size={13} />
            <span>New Space</span>
          </button>
          {selectedSpaceId && (
            <button onClick={() => setPageModalOpen(true)} className="btn btn-primary btn-sm" type="button">
              <Icon name="plus" size={13} />
              <span>New Note</span>
            </button>
          )}
        </div>
      </div>

      {loadingSpaces && spaces.length === 0 ? (
        <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
          Loading spaces...
        </div>
      ) : spaces.length === 0 ? (
        <div className="card" style={{ padding: '48px', textAlign: 'center', margin: 'auto 0' }}>
          <Icon name="file-text" size={36} style={{ color: 'var(--text-dim)', margin: '0 auto 12px auto' }} />
          <h3 style={{ fontSize: '16px', fontWeight: 600 }}>No spaces created yet</h3>
          <p style={{ fontSize: '13px', color: 'var(--text-muted)', margin: '6px 0 16px 0' }}>
            Spaces group related note pages, runbooks, and documentation for your projects.
          </p>
          <button onClick={() => setSpaceModalOpen(true)} className="btn btn-primary btn-sm" type="button">
            Create First Space
          </button>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '220px 260px 1fr', gap: '16px', flex: 1, minHeight: 0 }}>
          {/* Column 1: Spaces List */}
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '6px', overflowY: 'auto', padding: '12px' }}>
            <div style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', padding: '4px 6px', marginBottom: '4px' }}>
              Spaces
            </div>
            {spaces.map((sp) => (
              <div
                key={sp.id}
                onClick={() => setSelectedSpaceId(sp.id)}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '8px 10px',
                  borderRadius: 'var(--radius-sm)',
                  cursor: 'pointer',
                  backgroundColor: selectedSpaceId === sp.id ? 'var(--primary-subtle)' : 'transparent',
                  color: selectedSpaceId === sp.id ? 'var(--primary)' : 'var(--text-main)',
                  fontWeight: selectedSpaceId === sp.id ? 600 : 500,
                  fontSize: '13px',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflow: 'hidden' }}>
                  <Icon name="database" size={14} />
                  <span style={{ textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>{sp.name}</span>
                </div>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    handleDeleteSpace(sp.id)
                  }}
                  className="btn btn-ghost btn-sm"
                  style={{ padding: '2px', opacity: 0.6 }}
                  title="Delete space"
                >
                  <Icon name="trash" size={11} />
                </button>
              </div>
            ))}
          </div>

          {/* Column 2: Note Pages in selected space */}
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '6px', overflowY: 'auto', padding: '12px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 6px', marginBottom: '4px' }}>
              <span style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                Pages ({pages.length})
              </span>
              <button
                type="button"
                onClick={() => setPageModalOpen(true)}
                className="btn btn-ghost btn-sm"
                style={{ padding: '2px 6px', fontSize: '11px' }}
                title="Add note"
              >
                <Icon name="plus" size={11} />
              </button>
            </div>

            {loadingPages && pages.length === 0 ? (
              <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '12px' }}>
                Loading notes...
              </div>
            ) : pages.length === 0 ? (
              <div style={{ padding: '24px 12px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '12px' }}>
                No notes in this space yet.
              </div>
            ) : (
              pages.map((p) => (
                <div
                  key={p.id}
                  onClick={() => setSelectedPageId(p.id)}
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '2px',
                    padding: '8px 10px',
                    borderRadius: 'var(--radius-sm)',
                    cursor: 'pointer',
                    backgroundColor: selectedPageId === p.id ? 'var(--primary-subtle)' : 'transparent',
                    border: selectedPageId === p.id ? '1px solid var(--primary-border)' : '1px solid transparent',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: '13px', fontWeight: 600, color: selectedPageId === p.id ? 'var(--primary)' : 'var(--text-main)' }}>
                      {p.title}
                    </span>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation()
                        handleDeletePage(p.id)
                      }}
                      className="btn btn-ghost btn-sm"
                      style={{ padding: '2px', opacity: 0.6 }}
                      title="Delete note"
                    >
                      <Icon name="trash" size={11} />
                    </button>
                  </div>
                  <span style={{ fontSize: '10px', color: 'var(--text-dim)' }}>
                    {new Date(p.updated_at * 1000).toLocaleDateString()}
                  </span>
                </div>
              ))
            )}
          </div>

          {/* Column 3: Note Content Preview & Editor */}
          <div className="card" style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden', padding: '16px' }}>
            {loadingActivePage ? (
              <div style={{ margin: 'auto', color: 'var(--text-muted)' }}>Loading note content...</div>
            ) : !activePage ? (
              <div style={{ margin: 'auto', textAlign: 'center', color: 'var(--text-muted)' }}>
                Select or create a note page to view its contents.
              </div>
            ) : isEditing ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', height: '100%' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <input
                    className="input"
                    value={editTitle}
                    onChange={(e) => setEditTitle(e.target.value)}
                    style={{ fontSize: '16px', fontWeight: 600 }}
                    placeholder="Note title..."
                  />
                  <div style={{ display: 'flex', gap: '6px', marginLeft: '12px' }}>
                    <button
                      type="button"
                      onClick={() => setIsEditing(false)}
                      className="btn btn-secondary btn-sm"
                      disabled={savingPage}
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      onClick={handleSavePage}
                      className="btn btn-primary btn-sm"
                      disabled={savingPage || !editTitle.trim()}
                    >
                      <span>{savingPage ? 'Saving...' : 'Save Changes'}</span>
                    </button>
                  </div>
                </div>

                <textarea
                  className="textarea"
                  value={editContent}
                  onChange={(e) => setEditContent(e.target.value)}
                  style={{ flex: 1, fontFamily: 'var(--font-mono)', fontSize: '13px', resize: 'none' }}
                  placeholder="Markdown note content..."
                />
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', paddingBottom: '12px', borderBottom: '1px solid var(--border-subtle)', marginBottom: '14px' }}>
                  <div>
                    <h1 style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-main)', marginBottom: '4px' }}>
                      {activePage.title}
                    </h1>
                    <div style={{ fontSize: '11px', color: 'var(--text-dim)' }}>
                      Last updated: {new Date(activePage.updated_at * 1000).toLocaleString()}
                    </div>
                  </div>

                  <button
                    type="button"
                    onClick={() => setIsEditing(true)}
                    className="btn btn-secondary btn-sm"
                  >
                    <Icon name="sliders" size={13} />
                    <span>Edit Note</span>
                  </button>
                </div>

                <div style={{ flex: 1, overflowY: 'auto' }}>
                  <Markdown content={activePage.content || '*Empty note.*'} />
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* New Space Modal */}
      <Modal
        isOpen={spaceModalOpen}
        onClose={() => setSpaceModalOpen(false)}
        title="Create New Space"
        footer={
          <>
            <button type="button" onClick={() => setSpaceModalOpen(false)} className="btn btn-secondary">
              Cancel
            </button>
            <button
              type="button"
              onClick={handleCreateSpace}
              disabled={!newSpaceName.trim() || creatingSpace}
              className="btn btn-primary"
            >
              <span>{creatingSpace ? 'Creating...' : 'Create Space'}</span>
            </button>
          </>
        }
      >
        <form onSubmit={handleCreateSpace} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
              Space Name
            </label>
            <input
              className="input"
              value={newSpaceName}
              onChange={(e) => setNewSpaceName(e.target.value)}
              placeholder="e.g. Project Apollo, Backend Architecture"
              required
            />
          </div>
          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
              Description (Optional)
            </label>
            <textarea
              className="textarea"
              rows={3}
              value={newSpaceDesc}
              onChange={(e) => setNewSpaceDesc(e.target.value)}
              placeholder="What documentation and notes live in this space?"
            />
          </div>
        </form>
      </Modal>

      {/* New Page Modal */}
      <Modal
        isOpen={pageModalOpen}
        onClose={() => setPageModalOpen(false)}
        title="Create New Note Page"
        footer={
          <>
            <button type="button" onClick={() => setPageModalOpen(false)} className="btn btn-secondary">
              Cancel
            </button>
            <button
              type="button"
              onClick={handleCreatePage}
              disabled={!newPageTitle.trim() || creatingPage}
              className="btn btn-primary"
            >
              <span>{creatingPage ? 'Creating...' : 'Create Note'}</span>
            </button>
          </>
        }
      >
        <form onSubmit={handleCreatePage} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
              Title
            </label>
            <input
              className="input"
              value={newPageTitle}
              onChange={(e) => setNewPageTitle(e.target.value)}
              placeholder="e.g. Deployment Runbook, Onboarding Notes"
              required
            />
          </div>
          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
              Initial Content (Markdown supported)
            </label>
            <textarea
              className="textarea"
              rows={6}
              value={newPageContent}
              onChange={(e) => setNewPageContent(e.target.value)}
              placeholder="# Heading&#10;&#10;Write initial notes here..."
            />
          </div>
        </form>
      </Modal>
    </div>
  )
}
