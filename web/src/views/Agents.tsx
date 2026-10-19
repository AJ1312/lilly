import React, { useState } from 'react'
import { api, errorText } from '../api'
import { useLoad } from '../hooks'
import { useAppStore } from '../store'
import type { Agent, PetLook, ModelStatus } from '../types'
import { Icon } from '../ui/Icon'
import { Modal } from '../ui/Modal'
import { Markdown } from '../ui/Markdown'
import { LillyMascot, type PetSpecies } from '../ui/LillyMascot'

interface SpeciesInfo {
  id: PetSpecies
  name: string
  emoji: string
  role: string
  desc: string
}

const PET_SPECIES: SpeciesInfo[] = [
  { id: 'lily', name: 'Lily', emoji: '🐰', role: 'Clever Pioneer', desc: 'Curious rabbit with keen instincts for general reasoning.' },
  { id: 'pip', name: 'Pip', emoji: '🐧', role: 'Speedy Coder', desc: 'Fast, sharp penguin focused on code and system tools.' },
  { id: 'mochi', name: 'Mochi', emoji: '🍡', role: 'Boba Slime', desc: 'Cozy, squishy blob that excels at memory & creative notes.' },
  { id: 'bao', name: 'Bao', emoji: '🐼', role: 'Panda Defender', desc: 'Sturdy guardian with extra careful guardrails.' },
  { id: 'fern', name: 'Fern', emoji: '🦌', role: 'Forest Deer', desc: 'Gentle researcher with deep patience for long documents.' },
  { id: 'juno', name: 'Juno', emoji: '🐶', role: 'Star Hound', desc: 'Cosmic explorer that tracks remote systems and logs.' },
  { id: 'otto', name: 'Otto', emoji: '🦦', role: 'Cyber Otter', desc: 'Clever tool technician and automation engineer.' },
  { id: 'wisp', name: 'Wisp', emoji: '👻', role: 'Spirit Flame', desc: 'Ethereal shadow analyst with minimal token footprint.' },
]

const COLOR_PRESETS = [
  { label: 'Lavender', hue: 250 },
  { label: 'Cyber Cyan', hue: 190 },
  { label: 'Coral', hue: 350 },
  { label: 'Amber', hue: 38 },
  { label: 'Emerald', hue: 145 },
  { label: 'Bubblegum', hue: 320 },
  { label: 'Indigo', hue: 225 },
]

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
  const [pet, setPet] = useState<PetSpecies>('lily')
  const [mode, setMode] = useState<number>(1)
  const [researchAllowed, setResearchAllowed] = useState(true)
  const [memoryAllowed, setMemoryAllowed] = useState(true)
  const [filesAllowed, setFilesAllowed] = useState(true)
  const [computerAllowed, setComputerAllowed] = useState(false)
  const [chatAllowed, setChatAllowed] = useState(true)

  const [petLook, setPetLook] = useState<PetLook>({
    hue: 250,
    accessory: 'none',
    eyes: 'round',
    blush: true,
  })
  const [saving, setSaving] = useState(false)

  const openCreate = () => {
    setIsEditingExisting(false)
    setAgentId(`agent_${Date.now()}`)
    setName('')
    setInstructions('')
    setPinnedModel('')
    setPet('lily')
    setMode(1)
    setResearchAllowed(true)
    setMemoryAllowed(true)
    setFilesAllowed(true)
    setComputerAllowed(false)
    setChatAllowed(true)
    setPetLook({ hue: 250, accessory: 'none', eyes: 'round', blush: true })
    setEditorOpen(true)
  }

  const openEdit = (ag: Agent) => {
    setIsEditingExisting(true)
    setAgentId(ag.id)
    setName(ag.name)
    setInstructions(ag.instructions || '')
    setPinnedModel(ag.model || '')
    setPet((ag.pet as PetSpecies) || 'lily')
    setMode(ag.mode ?? 1)
    setResearchAllowed(ag.research_allowed ?? true)
    setMemoryAllowed(ag.memory_allowed ?? true)
    setFilesAllowed(ag.files_allowed ?? true)
    setComputerAllowed(ag.computer_allowed ?? false)
    setChatAllowed(ag.chat_allowed ?? true)
    setPetLook(ag.look || { hue: 250, accessory: 'none', eyes: 'round', blush: true })
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
        toast('Agent instructions sheet is valid!', 'good')
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
        pet,
        mode,
        research_allowed: researchAllowed,
        memory_allowed: memoryAllowed,
        files_allowed: filesAllowed,
        computer_allowed: computerAllowed,
        chat_allowed: chatAllowed,
        look: {
          hue: petLook.hue,
          accessory: petLook.accessory,
          eyes: petLook.eyes,
          blush: petLook.blush,
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
      await api.delete(`/api/agents/${id}`)
      toast(`Agent ${agentName} deleted`, 'warn')
      bump()
      await reload()
    } catch (err) {
      toast(`Failed to delete agent: ${errorText(err)}`, 'bad')
    }
  }

  return (
    <div className="view-container" style={{ padding: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <div>
          <h2 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span>Agents & Pet Crew</span>
            <span className="badge badge-primary">{agents.length} Active</span>
          </h2>
          <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
            Design specialized agents, choose 3D companion personas, tune system instructions, and assign tools.
          </p>
        </div>
        <button onClick={openCreate} className="btn btn-primary" type="button">
          <Icon name="plus" size={14} />
          <span>Create Agent</span>
        </button>
      </div>

      {loading && agents.length === 0 ? (
        <div style={{ padding: '48px', textAlign: 'center', color: 'var(--text-muted)' }}>
          Loading agents...
        </div>
      ) : agents.length === 0 ? (
        <div className="card" style={{ padding: '48px', textAlign: 'center' }}>
          <LillyMascot size={100} speech="Create your first agent companion!" />
          <h3 style={{ fontSize: '16px', fontWeight: 600, marginTop: '16px' }}>No custom agents yet</h3>
          <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginBottom: '16px' }}>
            Build specialized personas with dedicated instructions, cute 3D mascots, and custom model routing.
          </p>
          <button onClick={openCreate} className="btn btn-primary" type="button">
            Create Your First Agent
          </button>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: '16px' }}>
          {agents.map((ag) => {
            const speciesData = PET_SPECIES.find((p) => p.id === (ag.pet || 'lily')) || PET_SPECIES[0]
            return (
              <div
                key={ag.id}
                className="card card-hover"
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '12px',
                  position: 'relative',
                  overflow: 'hidden',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: '14px' }}>
                  {/* Interactive Mini Mascot Avatar */}
                  <div
                    style={{
                      flexShrink: 0,
                      backgroundColor: 'var(--bg-card-subtle)',
                      borderRadius: 'var(--radius-md)',
                      padding: '4px',
                      border: '1px solid var(--border-subtle)',
                    }}
                  >
                    <LillyMascot
                      pet={ag.pet || 'lily'}
                      look={ag.look}
                      size={54}
                      interactive={false}
                    />
                  </div>

                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                      <span style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-main)' }}>
                        {ag.name}
                      </span>
                      <span className="badge badge-accent" style={{ fontSize: '10px' }}>
                        {speciesData.emoji} {speciesData.name}
                      </span>
                    </div>

                    <div style={{ fontSize: '12px', color: 'var(--text-dim)', marginTop: '2px' }}>
                      {speciesData.role} • {ag.model ? `Pinned: ${ag.model}` : 'Auto-routed model'}
                    </div>

                    {ag.instructions && (
                      <p
                        style={{
                          fontSize: '12px',
                          color: 'var(--text-secondary)',
                          marginTop: '6px',
                          display: '-webkit-box',
                          WebkitLineClamp: 2,
                          WebkitBoxOrient: 'vertical',
                          overflow: 'hidden',
                        }}
                      >
                        {ag.instructions}
                      </p>
                    )}
                  </div>
                </div>

                {/* Capability Badges */}
                <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                  {ag.computer_allowed && (
                    <span className="badge badge-warn" style={{ fontSize: '10px' }}>💻 Computer</span>
                  )}
                  {ag.files_allowed && (
                    <span className="badge badge-secondary" style={{ fontSize: '10px' }}>📁 Files</span>
                  )}
                  {ag.research_allowed && (
                    <span className="badge badge-secondary" style={{ fontSize: '10px' }}>🔍 Web</span>
                  )}
                  {ag.memory_allowed && (
                    <span className="badge badge-secondary" style={{ fontSize: '10px' }}>🧠 Memory</span>
                  )}
                  <span className="badge badge-neutral" style={{ fontSize: '10px' }}>
                    Accessory: {ag.look?.accessory || 'none'}
                  </span>
                </div>

                {/* Actions Footer */}
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    borderTop: '1px solid var(--border-subtle)',
                    paddingTop: '10px',
                    marginTop: 'auto',
                  }}
                >
                  <div style={{ display: 'flex', gap: '6px' }}>
                    <button
                      type="button"
                      onClick={() => handlePreviewPrompt(ag.id)}
                      className="btn btn-ghost btn-sm"
                      title="Inspect System Prompt"
                      style={{ fontSize: '11px', padding: '3px 8px' }}
                    >
                      <Icon name="eye" size={11} />
                      <span>Prompt</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => handleExportAgent(ag.id, ag.name)}
                      className="btn btn-ghost btn-sm"
                      title="Export Agent Spec"
                      style={{ fontSize: '11px', padding: '3px 8px' }}
                    >
                      <Icon name="copy" size={11} />
                      <span>Export</span>
                    </button>
                  </div>

                  <div style={{ display: 'flex', gap: '6px' }}>
                    <button
                      type="button"
                      onClick={() => openEdit(ag)}
                      className="btn btn-secondary btn-sm"
                      style={{ fontSize: '11px', padding: '3px 10px' }}
                    >
                      <Icon name="sliders" size={11} />
                      <span>Edit</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDelete(ag.id, ag.name)}
                      className="btn btn-ghost btn-sm"
                      style={{ color: 'var(--danger-text)', padding: '3px 6px' }}
                      title="Delete Agent"
                    >
                      <Icon name="trash" size={11} />
                    </button>
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
            This is the exact combined system prompt and tools guidance injected into the model for this agent:
          </p>
          <div
            style={{
              padding: '12px',
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

      {/* Highly Customizable Agent & Pet Studio Modal */}
      <Modal
        isOpen={editorOpen}
        onClose={() => setEditorOpen(false)}
        title={isEditingExisting ? `Edit Agent: ${name || 'Agent'}` : 'Create New Agent & Pet Companion'}
        maxWidth={720}
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
        <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
          {/* Header Live Preview Banner */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '20px',
              padding: '16px 20px',
              backgroundColor: 'var(--bg-card-subtle)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-md)',
            }}
          >
            <LillyMascot
              pet={pet}
              look={petLook}
              size={110}
              state="happy"
              interactive
              speech={name ? `Hi! I'm ${name}!` : undefined}
            />
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: '11px', textTransform: 'uppercase', color: 'var(--text-dim)', fontWeight: 700 }}>
                Live Pet Companion Preview
              </div>
              <div style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-main)', marginTop: '2px' }}>
                {name || 'Unnamed Agent'}
              </div>
              <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>
                Click me to test bouncy animations! Your pet appearance and personality update in real-time.
              </p>
            </div>
          </div>

          {/* Basic Identity */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
            <div>
              <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
                Agent Name *
              </label>
              <input
                className="input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Code Reviewer, Lilly, Otto Tech"
                required
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
                Pinned LLM Model (Optional)
              </label>
              <select
                className="select"
                value={pinnedModel}
                onChange={(e) => setPinnedModel(e.target.value)}
              >
                <option value="">Auto-Route (Best model dynamically)</option>
                {availableModels.map((m) => (
                  <option key={m.name} value={m.name}>
                    {m.name} ({m.provider} - {m.lane === 1 ? 'Fast' : 'Heavy'})
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* 3D Pet Character Species Selector */}
          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '6px' }}>
              Pet Companion Species ({PET_SPECIES.length} options)
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px' }}>
              {PET_SPECIES.map((p) => {
                const isSelected = pet === p.id
                return (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => setPet(p.id)}
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      padding: '10px 8px',
                      borderRadius: 'var(--radius-sm)',
                      border: isSelected ? '2px solid var(--primary)' : '1px solid var(--border)',
                      backgroundColor: isSelected ? 'var(--primary-subtle)' : 'var(--bg-card)',
                      cursor: 'pointer',
                      textAlign: 'center',
                      transition: 'all 0.15s ease',
                    }}
                  >
                    <span style={{ fontSize: '24px', marginBottom: '2px' }}>{p.emoji}</span>
                    <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-main)' }}>{p.name}</span>
                    <span style={{ fontSize: '10px', color: 'var(--text-dim)', marginTop: '1px' }}>{p.role}</span>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Pet Look Visual Customizer */}
          <div
            className="card card-subtle"
            style={{
              padding: '14px',
              display: 'flex',
              flexDirection: 'column',
              gap: '12px',
              backgroundColor: 'var(--bg-card-subtle)',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: '12px', fontWeight: 600 }}>Pet Customization Studio</span>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={petLook.blush}
                  onChange={(e) => setPetLook({ ...petLook, blush: e.target.checked })}
                />
                <span>Blush Cheeks</span>
              </label>
            </div>

            {/* Hue Slider + Color Presets */}
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', marginBottom: '4px' }}>
                <span style={{ color: 'var(--text-muted)' }}>Color Spectrum Wheel ({petLook.hue ?? 250}°)</span>
                <span
                  style={{
                    display: 'inline-block',
                    width: '16px',
                    height: '16px',
                    borderRadius: '50%',
                    backgroundColor: `hsl(${petLook.hue ?? 250}, 85%, 60%)`,
                    border: '1px solid rgba(0,0,0,0.1)',
                  }}
                />
              </div>
              <input
                type="range"
                min="0"
                max="359"
                value={petLook.hue ?? 250}
                onChange={(e) => setPetLook({ ...petLook, hue: Number(e.target.value) })}
                style={{ width: '100%', cursor: 'pointer' }}
              />
              <div style={{ display: 'flex', gap: '6px', marginTop: '6px', flexWrap: 'wrap' }}>
                {COLOR_PRESETS.map((preset) => (
                  <button
                    key={preset.label}
                    type="button"
                    onClick={() => setPetLook({ ...petLook, hue: preset.hue })}
                    className="btn btn-ghost btn-sm"
                    style={{ fontSize: '10px', padding: '2px 8px', borderRadius: '12px' }}
                  >
                    <span
                      style={{
                        display: 'inline-block',
                        width: '8px',
                        height: '8px',
                        borderRadius: '50%',
                        backgroundColor: `hsl(${preset.hue}, 85%, 60%)`,
                        marginRight: '4px',
                      }}
                    />
                    {preset.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Accessories & Eyes */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <div>
                <label style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>
                  Accessory
                </label>
                <select
                  className="select"
                  value={petLook.accessory}
                  onChange={(e) => setPetLook({ ...petLook, accessory: e.target.value as any })}
                >
                  <option value="none">None (Natural)</option>
                  <option value="glasses">👓 Smart Glasses</option>
                  <option value="bow">🎀 Satin Bow</option>
                  <option value="hat">🧙 Party / Wizard Hat</option>
                  <option value="scarf">🧣 Cozy Warm Scarf</option>
                  <option value="crown">👑 Royal Gold Crown</option>
                  <option value="headphones">🎧 Cyber DJ Headphones</option>
                </select>
              </div>

              <div>
                <label style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>
                  Eyes Expression
                </label>
                <select
                  className="select"
                  value={petLook.eyes}
                  onChange={(e) => setPetLook({ ...petLook, eyes: e.target.value as any })}
                >
                  <option value="round">👀 Round Curious</option>
                  <option value="sparkle">✨ Star Sparkle</option>
                  <option value="sleepy">😴 Sleepy Relaxed</option>
                </select>
              </div>
            </div>
          </div>

          {/* Tool Capabilities Toggles */}
          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '6px' }}>
              Allowed Capabilities & Tool Access
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '8px' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={researchAllowed}
                  onChange={(e) => setResearchAllowed(e.target.checked)}
                />
                <span>🔍 Web Search</span>
              </label>

              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={memoryAllowed}
                  onChange={(e) => setMemoryAllowed(e.target.checked)}
                />
                <span>🧠 Long Memory</span>
              </label>

              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={filesAllowed}
                  onChange={(e) => setFilesAllowed(e.target.checked)}
                />
                <span>📁 Files Access</span>
              </label>

              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={computerAllowed}
                  onChange={(e) => setComputerAllowed(e.target.checked)}
                />
                <span>💻 Computer Use</span>
              </label>

              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={chatAllowed}
                  onChange={(e) => setChatAllowed(e.target.checked)}
                />
                <span>💬 Bridges / Chat</span>
              </label>
            </div>
          </div>

          {/* System Instructions Sheet */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
              <label style={{ fontSize: '12px', fontWeight: 600 }}>System Instructions Sheet</label>
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
              rows={5}
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              placeholder="Standing instructions, persona constraints, formatting rules..."
            />
          </div>
        </form>
      </Modal>
    </div>
  )
}
