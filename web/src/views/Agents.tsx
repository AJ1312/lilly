import React, { useState } from 'react'
import { api, errorText } from '../api'
import { useLoad } from '../hooks'
import { useAppStore } from '../store'
import type { Agent, ModelStatus } from '../types'
import { Icon } from '../ui/Icon'
import { Modal } from '../ui/Modal'
import { Markdown } from '../ui/Markdown'
import { AgentPet } from '../ui/AgentPet'

const PASTEL_THEMES = ['peach', 'lime', 'periwinkle', 'mint', 'lilac'] as const
const PET_SPECIES_OPTIONS = [
  { id: 'lily', name: 'Lily Fairy', hint: 'Graceful botanical guide' },
  { id: 'pip', name: 'Pip Bird', hint: 'Speedy bouncy automator' },
  { id: 'mochi', name: 'Mochi Cat', hint: 'Analytical coding feline' },
  { id: 'bao', name: 'Bao Panda', hint: 'Gentle memory guardian' },
  { id: 'fern', name: 'Fern Sprout', hint: 'Curious research explorer' },
  { id: 'juno', name: 'Juno Fox', hint: 'Sharp terminal hacker' },
  { id: 'otto', name: 'Otto Otter', hint: 'Playful problem solver' },
  { id: 'wisp', name: 'Wisp Spirit', hint: 'Ethereal background watcher' },
] as const

export const AgentsView: React.FC = () => {
  const toast = useAppStore((s) => s.toast)
  const bump = useAppStore((s) => s.bump)

  const { data, loading, reload } = useLoad<{ agents: Agent[] }>('/api/agents')
  const agents = data?.agents || []

  const { data: modelsData } = useLoad<{ models: ModelStatus[] }>('/api/models')
  const availableModels = modelsData?.models || []

  const [promptPreview, setPromptPreview] = useState<string | null>(null)
  const [editorOpen, setEditorOpen] = useState(false)
  const [isEditingExisting, setIsEditingExisting] = useState(false)

  // Form fields
  const [agentId, setAgentId] = useState('')
  const [name, setName] = useState('')
  const [instructions, setInstructions] = useState('')
  const [pinnedModel, setPinnedModel] = useState('')
  const [mode, setMode] = useState<number>(1)
  const [researchAllowed, setResearchAllowed] = useState(true)
  const [memoryAllowed, setMemoryAllowed] = useState(true)
  const [filesAllowed, setFilesAllowed] = useState(true)
  const [computerAllowed, setComputerAllowed] = useState(false)
  const [chatAllowed, setChatAllowed] = useState(true)
  const [saving, setSaving] = useState(false)

  // Pet companion customizer state
  const [petSpecies, setPetSpecies] = useState<string>('lily')
  const [petAccessory, setPetAccessory] = useState<'none' | 'bow' | 'glasses' | 'hat' | 'scarf' | 'crown' | 'headphones'>('none')
  const [petEyes, setPetEyes] = useState<'round' | 'sparkle' | 'sleepy'>('round')
  const [petBlush, setPetBlush] = useState<boolean>(true)
  const [petHue, setPetHue] = useState<number | null>(null)

  const openCreate = () => {
    setIsEditingExisting(false)
    setAgentId(`agent_${Date.now()}`)
    setName('')
    setInstructions('')
    setPinnedModel('')
    setMode(1)
    setResearchAllowed(true)
    setMemoryAllowed(true)
    setFilesAllowed(true)
    setComputerAllowed(false)
    setChatAllowed(true)
    setPetSpecies('lily')
    setPetAccessory('none')
    setPetEyes('round')
    setPetBlush(true)
    setPetHue(null)
    setEditorOpen(true)
  }

  const openEdit = (ag: Agent) => {
    setIsEditingExisting(true)
    setAgentId(ag.id)
    setName(ag.name)
    setInstructions(ag.instructions || '')
    setPinnedModel(ag.model || '')
    setMode(ag.mode ?? 1)
    setResearchAllowed(ag.research_allowed ?? true)
    setMemoryAllowed(ag.memory_allowed ?? true)
    setFilesAllowed(ag.files_allowed ?? true)
    setComputerAllowed(ag.computer_allowed ?? false)
    setChatAllowed(ag.chat_allowed ?? true)
    setPetSpecies(ag.pet || 'lily')
    setPetAccessory(ag.look?.accessory || 'none')
    setPetEyes(ag.look?.eyes || 'round')
    setPetBlush(ag.look?.blush ?? true)
    setPetHue(ag.look?.hue ?? null)
    setEditorOpen(true)
  }

  const handlePreviewPrompt = async (id: string) => {
    try {
      const res = await api.get<{ prompt: string }>(`/api/agents/${id}/prompt-preview`)
      setPromptPreview(res.prompt)
    } catch (err) {
      toast(`Cannot preview prompt: ${errorText(err)}`, 'bad')
    }
  }

  const handleExportAgent = async (id: string, agentName: string) => {
    try {
      const res = await api.get<any>(`/api/agents/${id}/export`)
      const blob = new Blob([JSON.stringify(res, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${agentName.toLowerCase().replace(/\s+/g, '_')}_agent.json`
      a.click()
      URL.revokeObjectURL(url)
      toast(`Exported ${agentName} specification`, 'good')
    } catch (err) {
      toast(`Export failed: ${errorText(err)}`, 'bad')
    }
  }

  const handleValidateInstructions = async () => {
    try {
      const res = await api.post<{ ok: boolean; diagnostics?: { message: string }[] }>('/api/agents/validate-sheet', {
        sheet: instructions,
      })
      if (res.ok) {
        toast('Instructions sheet is valid!', 'good')
      } else {
        const issues = (res.diagnostics || []).map((d) => d.message).join(', ')
        toast(`Validation problems: ${issues || 'syntax problem'}`, 'warn')
      }
    } catch (err) {
      toast(`Validation error: ${errorText(err)}`, 'bad')
    }
  }

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return

    setSaving(true)
    try {
      const payload = {
        name: name.trim(),
        instructions: instructions.trim() || undefined,
        model: pinnedModel.trim() || undefined,
        mode,
        research_allowed: researchAllowed,
        memory_allowed: memoryAllowed,
        files_allowed: filesAllowed,
        computer_allowed: computerAllowed,
        chat_allowed: chatAllowed,
        pet: petSpecies,
        look: {
          hue: petHue,
          accessory: petAccessory,
          eyes: petEyes,
          blush: petBlush,
        },
      }

      if (isEditingExisting) {
        await api.patch(`/api/agents/${agentId}`, payload)
        toast('Agent updated successfully', 'good')
      } else {
        await api.post('/api/agents', { id: agentId, ...payload })
        toast('Agent created successfully', 'good')
      }

      setEditorOpen(false)
      bump()
      await reload()
    } catch (err) {
      toast(`Failed to save agent: ${errorText(err)}`, 'bad')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (id: string, agentName: string) => {
    if (!confirm(`Are you sure you want to delete agent "${agentName}"?`)) return
    try {
      await api.del(`/api/agents/${id}`)
      toast(`Agent ${agentName} deleted`, 'warn')
      bump()
      await reload()
    } catch (err) {
      toast(`Failed to delete agent: ${errorText(err)}`, 'bad')
    }
  }

  return (
    <div className="view-container">
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '24px' }}>
        <div>
          <h1 className="greeting-text">Specialist Agents</h1>
          <div className="greeting-sub">
            Curate specialized AI personas, configure standing system instructions, and assign tools.
          </div>
        </div>
        <button onClick={openCreate} className="btn btn-primary" type="button">
          <Icon name="plus" size={14} />
          <span>New Agent</span>
        </button>
      </div>

      {loading && agents.length === 0 ? (
        <div style={{ padding: '48px', textAlign: 'center', color: 'var(--text-muted)' }}>
          Loading agents...
        </div>
      ) : agents.length === 0 ? (
        <div className="card" style={{ padding: '48px', textAlign: 'center' }}>
          <h3 style={{ fontSize: '18px', fontWeight: 800 }}>No custom agents configured</h3>
          <p style={{ fontSize: '13px', color: 'var(--text-muted)', margin: '8px 0 16px 0' }}>
            Build specialized personas with dedicated instructions sheets, model bindings, and tool permissions.
          </p>
          <button onClick={openCreate} className="btn btn-primary" type="button">
            Create Your First Agent
          </button>
        </div>
      ) : (
        <div className="card-grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))' }}>
          {agents.map((ag, index) => {
            const themeClass = PASTEL_THEMES[index % PASTEL_THEMES.length]

            return (
              <div
                key={ag.id}
                className={`pastel-card ${themeClass}`}
                style={{ minHeight: '220px', cursor: 'default' }}
              >
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span className="pastel-tag-pill">
                      {ag.model ? ag.model : 'Auto-routed'}
                    </span>
                    <span className="badge badge-accent" style={{ textTransform: 'capitalize', fontSize: '10px' }}>
                      {ag.pet || 'lily'}
                    </span>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '14px', marginTop: '12px' }}>
                    <AgentPet
                      species={ag.pet || 'lily'}
                      look={ag.look}
                      size={60}
                      agentName={ag.name}
                      interactive={true}
                    />
                    <div>
                      <div className="pastel-card-title" style={{ fontSize: '18px', margin: 0 }}>
                        {ag.name}
                      </div>
                      <div style={{ fontSize: '11px', opacity: 0.75, marginTop: '2px' }}>
                        Specialist Companion
                      </div>
                    </div>
                  </div>

                  {ag.instructions && (
                    <p
                      style={{
                        fontSize: '12px',
                        opacity: 0.85,
                        marginTop: '6px',
                        display: '-webkit-box',
                        WebkitLineClamp: 3,
                        WebkitBoxOrient: 'vertical',
                        overflow: 'hidden',
                        lineHeight: 1.4,
                      }}
                    >
                      {ag.instructions}
                    </p>
                  )}
                </div>

                <div style={{ marginTop: '16px' }}>
                  {/* Capabilities chips */}
                  <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginBottom: '14px' }}>
                    {ag.computer_allowed && (
                      <span className="badge badge-primary" style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontSize: '10px' }}>
                        <Icon name="laptop" size={10} />
                        <span>Computer</span>
                      </span>
                    )}
                    {ag.files_allowed && (
                      <span className="badge badge-primary" style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontSize: '10px' }}>
                        <Icon name="file-text" size={10} />
                        <span>Files</span>
                      </span>
                    )}
                    {ag.research_allowed && (
                      <span className="badge badge-primary" style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontSize: '10px' }}>
                        <Icon name="search" size={10} />
                        <span>Search</span>
                      </span>
                    )}
                    {ag.memory_allowed && (
                      <span className="badge badge-primary" style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontSize: '10px' }}>
                        <Icon name="memory" size={10} />
                        <span>Memory</span>
                      </span>
                    )}
                  </div>

                  {/* Actions Bar */}
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      borderTop: '1px solid rgba(0,0,0,0.08)',
                      paddingTop: '10px',
                    }}
                  >
                    <div style={{ display: 'flex', gap: '6px' }}>
                      <button
                        type="button"
                        onClick={() => handlePreviewPrompt(ag.id)}
                        className="btn btn-ghost btn-sm"
                        style={{ padding: '3px 8px', fontSize: '11px', backgroundColor: 'rgba(255,255,255,0.6)' }}
                        title="View Prompt"
                      >
                        <Icon name="eye" size={12} />
                        <span>Prompt</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => handleExportAgent(ag.id, ag.name)}
                        className="btn btn-ghost btn-sm"
                        style={{ padding: '3px 8px', fontSize: '11px', backgroundColor: 'rgba(255,255,255,0.6)' }}
                        title="Export JSON"
                      >
                        <Icon name="copy" size={12} />
                        <span>Export</span>
                      </button>
                    </div>

                    <div style={{ display: 'flex', gap: '6px' }}>
                      <button
                        type="button"
                        onClick={() => openEdit(ag)}
                        className="btn btn-secondary btn-sm"
                        style={{ padding: '4px 12px', fontSize: '11px' }}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDelete(ag.id, ag.name)}
                        className="btn btn-ghost btn-sm"
                        style={{ padding: '4px 6px', color: 'var(--danger)' }}
                        title="Delete agent"
                      >
                        <Icon name="trash" size={12} />
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Prompt Preview Modal */}
      <Modal
        isOpen={Boolean(promptPreview)}
        onClose={() => setPromptPreview(null)}
        title="Compiled Agent System Prompt"
        maxWidth={640}
      >
        <div style={{ fontSize: '13px' }}>
          <p style={{ color: 'var(--text-muted)', marginBottom: '12px' }}>
            Compiled standing instructions and capabilities injected into the inference model:
          </p>
          <div
            style={{
              padding: '16px',
              backgroundColor: 'var(--bg-card-subtle)',
              borderRadius: 'var(--radius-sm)',
              maxHeight: '400px',
              overflowY: 'auto',
              border: '1px solid var(--border)',
            }}
          >
            <Markdown content={`\`\`\`markdown\n${promptPreview || ''}\n\`\`\``} />
          </div>
        </div>
      </Modal>

      {/* Create / Edit Modal */}
      <Modal
        isOpen={editorOpen}
        onClose={() => setEditorOpen(false)}
        title={isEditingExisting ? `Edit Agent: ${name || 'Agent'}` : 'Configure New Specialist Agent'}
        maxWidth={640}
        footer={
          <>
            <button type="button" onClick={() => setEditorOpen(false)} className="btn btn-secondary">
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={!name.trim() || saving}
              className="btn btn-primary"
            >
              <span>{saving ? 'Saving...' : isEditingExisting ? 'Save Changes' : 'Create Agent'}</span>
            </button>
          </>
        }
      >
        <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
            <div>
              <label style={{ display: 'block', fontSize: '12px', fontWeight: 700, marginBottom: '4px' }}>
                Agent Name *
              </label>
              <input
                className="input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Code Reviewer, System Architect"
                required
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '12px', fontWeight: 700, marginBottom: '4px' }}>
                Pinned Model Binding
              </label>
              <select
                className="select"
                value={pinnedModel}
                onChange={(e) => setPinnedModel(e.target.value)}
              >
                <option value="">Auto-Route (Best model automatically)</option>
                {availableModels.map((m) => {
                  const isUnusable = !m.enabled || (Boolean(m.key_ref) && !m.has_key && !m.local)
                  const statusLabel = !m.enabled
                    ? 'Disabled'
                    : m.key_ref && !m.has_key && !m.local
                    ? 'Missing Key'
                    : m.local
                    ? 'Local'
                    : 'Ready'
                  return (
                    <option key={m.name} value={m.name} disabled={isUnusable}>
                      {m.name} ({m.provider}) — {statusLabel}
                    </option>
                  )
                })}
              </select>
            </div>
          </div>

          {/* Pet Companion Customizer */}
          <div
            style={{
              padding: '14px',
              backgroundColor: 'var(--bg-card-subtle)',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border)',
              display: 'flex',
              flexDirection: 'column',
              gap: '12px',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <label style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-main)' }}>
                Companion Pet Character & Style
              </label>
              <span className="badge badge-primary" style={{ fontSize: '10px', textTransform: 'capitalize' }}>
                {petSpecies}
              </span>
            </div>

            <div style={{ display: 'flex', gap: '16px', alignItems: 'center' }}>
              {/* Live Preview */}
              <div
                style={{
                  width: '94px',
                  height: '94px',
                  backgroundColor: 'var(--bg-card)',
                  borderRadius: 'var(--radius-sm)',
                  border: '1px solid var(--border)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                }}
              >
                <AgentPet
                  species={petSpecies}
                  look={{
                    accessory: petAccessory,
                    eyes: petEyes,
                    blush: petBlush,
                    hue: petHue,
                  }}
                  size={76}
                  interactive={false}
                />
              </div>

              {/* Controls */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', flex: 1 }}>
                {/* Species Pills */}
                <div>
                  <div style={{ fontSize: '11px', color: 'var(--text-dim)', marginBottom: '4px' }}>Species</div>
                  <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                    {PET_SPECIES_OPTIONS.map((opt) => (
                      <button
                        key={opt.id}
                        type="button"
                        className={`filter-tab ${petSpecies === opt.id ? 'active' : ''}`}
                        style={{ fontSize: '11px', padding: '3px 8px' }}
                        onClick={() => setPetSpecies(opt.id)}
                        title={opt.hint}
                      >
                        {opt.name.split(' ')[0]}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Accessory & Eyes Selects */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '10px', color: 'var(--text-dim)', marginBottom: '2px' }}>
                      Accessory
                    </label>
                    <select
                      className="select"
                      value={petAccessory}
                      onChange={(e) => setPetAccessory(e.target.value as any)}
                      style={{ padding: '6px 24px 6px 8px', fontSize: '11px' }}
                    >
                      <option value="none">None</option>
                      <option value="glasses">Glasses</option>
                      <option value="bow">Ribbon Bow</option>
                      <option value="crown">Crown</option>
                      <option value="scarf">Scarf</option>
                      <option value="headphones">Headphones</option>
                      <option value="hat">Top Hat</option>
                    </select>
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '10px', color: 'var(--text-dim)', marginBottom: '2px' }}>
                      Eyes
                    </label>
                    <select
                      className="select"
                      value={petEyes}
                      onChange={(e) => setPetEyes(e.target.value as any)}
                      style={{ padding: '6px 24px 6px 8px', fontSize: '11px' }}
                    >
                      <option value="round">Glossy Round</option>
                      <option value="sparkle">Star Sparkle</option>
                      <option value="sleepy">Happy / Sleepy</option>
                    </select>
                  </div>
                </div>

                {/* Blush Toggle & Hue Slider */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '11px', cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={petBlush}
                      onChange={(e) => setPetBlush(e.target.checked)}
                    />
                    <span>Rosy Blush</span>
                  </label>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px' }}>
                    <span style={{ color: 'var(--text-dim)' }}>Hue:</span>
                    <input
                      type="range"
                      min={0}
                      max={359}
                      value={petHue ?? 0}
                      onChange={(e) => setPetHue(Number(e.target.value))}
                      style={{ width: '80px', cursor: 'pointer' }}
                    />
                    {petHue !== null && (
                      <button
                        type="button"
                        onClick={() => setPetHue(null)}
                        className="btn btn-ghost btn-sm"
                        style={{ padding: '1px 4px', fontSize: '9px' }}
                        title="Reset native color"
                      >
                        Reset
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
              <label style={{ fontSize: '12px', fontWeight: 700 }}>System Instructions Sheet</label>
              <button
                type="button"
                onClick={handleValidateInstructions}
                className="btn btn-ghost btn-sm"
                style={{ fontSize: '11px', padding: '2px 8px' }}
              >
                Validate Sheet
              </button>
            </div>
            <textarea
              className="textarea"
              rows={6}
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              placeholder="Standing instructions, persona constraints, behavior guidelines, tool usage rules..."
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 700, marginBottom: '6px' }}>
              Allowed Capabilities & Tool Access
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '8px' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={researchAllowed}
                  onChange={(e) => setResearchAllowed(e.target.checked)}
                />
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                  <Icon name="search" size={12} />
                  <span>Web Search</span>
                </span>
              </label>

              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={memoryAllowed}
                  onChange={(e) => setMemoryAllowed(e.target.checked)}
                />
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                  <Icon name="memory" size={12} />
                  <span>Long Memory</span>
                </span>
              </label>

              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={filesAllowed}
                  onChange={(e) => setFilesAllowed(e.target.checked)}
                />
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                  <Icon name="file-text" size={12} />
                  <span>Files Access</span>
                </span>
              </label>

              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={computerAllowed}
                  onChange={(e) => setComputerAllowed(e.target.checked)}
                />
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                  <Icon name="laptop" size={12} />
                  <span>Computer Control</span>
                </span>
              </label>

              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={chatAllowed}
                  onChange={(e) => setChatAllowed(e.target.checked)}
                />
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                  <Icon name="chat" size={12} />
                  <span>Bridges / Chat</span>
                </span>
              </label>
            </div>
          </div>
        </form>
      </Modal>
    </div>
  )
}
