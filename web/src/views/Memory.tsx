import React, { useState } from 'react'
import { api, errorText } from '../api'
import { useLoad, useDebounce } from '../hooks'
import { useAppStore } from '../store'
import type { Memory } from '../types'
import { Icon } from '../ui/Icon'
import { Modal } from '../ui/Modal'

export const MemoryView: React.FC = () => {
  const toast = useAppStore((s) => s.toast)
  const bump = useAppStore((s) => s.bump)

  const [search, setSearch] = useState('')
  const debouncedSearch = useDebounce(search, 250)
  const [categoryFilter, setCategoryFilter] = useState<string>('all')

  const { data, loading, reload } = useLoad<{ memory: Memory[] }>('/api/memory')
  const allItems = data?.memory || []

  // Add/Edit modal
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [memoryText, setMemoryText] = useState('')
  const [memoryCategory, setMemoryCategory] = useState('general')
  const [saving, setSaving] = useState(false)

  const getItemText = (item: Memory): string => item.text || item.fact || ''
  const getItemCategory = (item: Memory): string => item.category || (item.tags && item.tags[0]) || 'general'

  const filtered = allItems.filter((item) => {
    const text = getItemText(item)
    const cat = getItemCategory(item)
    const matchesSearch = text.toLowerCase().includes(debouncedSearch.toLowerCase())
    const matchesCat = categoryFilter === 'all' || cat === categoryFilter
    return matchesSearch && matchesCat
  })

  const openAdd = () => {
    setEditingId(null)
    setMemoryText('')
    setMemoryCategory('general')
    setModalOpen(true)
  }

  const openEdit = (item: Memory) => {
    setEditingId(item.id)
    setMemoryText(getItemText(item))
    setMemoryCategory(getItemCategory(item))
    setModalOpen(true)
  }

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!memoryText.trim()) return

    setSaving(true)
    try {
      const payload = {
        fact: memoryText.trim(),
        text: memoryText.trim(),
        category: memoryCategory,
        tags: [memoryCategory],
      }
      if (editingId) {
        await api.patch(`/api/memory/${editingId}`, payload)
        toast('Memory updated', 'good')
      } else {
        await api.post('/api/memory', payload)
        toast('Memory saved to knowledge bank', 'good')
      }
      setModalOpen(false)
      bump()
      await reload()
    } catch (err) {
      toast(`Failed to save memory: ${errorText(err)}`, 'bad')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Are you sure you want to forget this memory item?')) return
    try {
      await api.delete(`/api/memory/${id}`)
      toast('Memory item deleted', 'good')
      bump()
      await reload()
    } catch (err) {
      toast(`Failed to delete: ${errorText(err)}`, 'bad')
    }
  }

  const handleClearAll = async () => {
    if (!confirm('DANGER: Are you sure you want to clear ALL stored memories? This cannot be undone.')) return
    try {
      await api.post('/api/memory/clear')
      toast('All memories cleared', 'warn')
      bump()
      await reload()
    } catch (err) {
      toast(`Failed to clear: ${errorText(err)}`, 'bad')
    }
  }

  return (
    <div className="view-container" style={{ padding: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <div>
          <h1 className="greeting-text">Memory Bank</h1>
          <div className="greeting-sub">
            Curated long-term memory, project guidelines, user preferences, and operational constraints.
          </div>
        </div>

        <div style={{ display: 'flex', gap: '8px' }}>
          {allItems.length > 0 && (
            <button onClick={handleClearAll} className="btn btn-secondary btn-sm" type="button">
              <Icon name="trash" size={14} />
              <span>Clear All</span>
            </button>
          )}
          <button onClick={openAdd} className="btn btn-primary btn-sm" type="button">
            <Icon name="plus" size={14} />
            <span>Add Memory</span>
          </button>
        </div>
      </div>

      {/* Search & Filter Bar */}
      <div style={{ display: 'flex', gap: '12px', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap' }}>
        <div style={{ position: 'relative', flex: 1, minWidth: '240px', maxWidth: '360px' }}>
          <Icon
            name="search"
            size={14}
            style={{ position: 'absolute', left: '10px', top: '10px', color: 'var(--text-muted)' }}
          />
          <input
            className="input"
            style={{ paddingLeft: '30px', fontSize: '12px' }}
            placeholder="Search remembered facts..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <div className="filter-tabs">
          {['all', 'general', 'preference', 'project', 'constraint'].map((cat) => (
            <button
              key={cat}
              type="button"
              className={`filter-tab ${categoryFilter === cat ? 'active' : ''}`}
              onClick={() => setCategoryFilter(cat)}
            >
              {cat.charAt(0).toUpperCase() + cat.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Memory items grid */}
      {loading && allItems.length === 0 ? (
        <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
          Loading stored memory...
        </div>
      ) : filtered.length === 0 ? (
        <div className="card" style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
          No memories found matching your search.
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '12px' }}>
          {filtered.map((item) => {
            const text = getItemText(item)
            const cat = getItemCategory(item)
            const timestamp = item.created_at || item.at || 0

            return (
              <div key={item.id} className="card" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span
                    style={{
                      fontSize: '10px',
                      fontWeight: 700,
                      textTransform: 'uppercase',
                      letterSpacing: '0.06em',
                      color: 'var(--primary)',
                      backgroundColor: 'var(--primary-subtle)',
                      padding: '2px 6px',
                      borderRadius: 'var(--radius-xs)',
                    }}
                  >
                    {cat}
                  </span>

                  <div style={{ display: 'flex', gap: '4px' }}>
                    <button
                      onClick={() => openEdit(item)}
                      className="btn btn-ghost btn-sm btn-icon"
                      type="button"
                      title="Edit memory"
                    >
                      <Icon name="sliders" size={13} />
                    </button>
                    <button
                      onClick={() => handleDelete(item.id)}
                      className="btn btn-ghost btn-sm btn-icon"
                      type="button"
                      title="Delete memory"
                    >
                      <Icon name="trash" size={13} />
                    </button>
                  </div>
                </div>

                <div style={{ fontSize: '13px', color: 'var(--text-main)', lineHeight: 1.5 }}>
                  {text}
                </div>

                <div style={{ fontSize: '11px', color: 'var(--text-dim)', marginTop: 'auto', paddingTop: '6px' }}>
                  {new Date(timestamp * 1000).toLocaleDateString()}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Add / Edit Dialog */}
      <Modal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editingId ? 'Edit Memory' : 'Add Memory'}
        footer={
          <>
            <button type="button" onClick={() => setModalOpen(false)} className="btn btn-secondary">
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={!memoryText.trim() || saving}
              className="btn btn-primary"
            >
              <span>{saving ? 'Saving...' : 'Save'}</span>
            </button>
          </>
        }
      >
        <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
              Category
            </label>
            <select
              className="select"
              value={memoryCategory}
              onChange={(e) => setMemoryCategory(e.target.value)}
            >
              <option value="general">General Fact</option>
              <option value="preference">User Preference</option>
              <option value="project">Project Architecture</option>
              <option value="constraint">Security / System Constraint</option>
            </select>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
              Memory Statement
            </label>
            <textarea
              className="textarea"
              rows={4}
              value={memoryText}
              onChange={(e) => setMemoryText(e.target.value)}
              placeholder="e.g. Always write tests with pytest and verify ResourceWarnings are zero..."
              required
            />
          </div>
        </form>
      </Modal>
    </div>
  )
}
