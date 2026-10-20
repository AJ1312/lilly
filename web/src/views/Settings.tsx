import React, { useState } from 'react'
import { api, errorText } from '../api'
import { useLoad } from '../hooks'
import { useAppStore } from '../store'
import { APPROVAL_MODES, type DevboxStatus, type McpServer, type Settings, type ThemePref, type LayaCheck } from '../types'
import { Icon } from '../ui/Icon'
import { Modal } from '../ui/Modal'

export const SettingsView: React.FC = () => {
  const toast = useAppStore((s) => s.toast)
  const theme = useAppStore((s) => s.theme)
  const setTheme = useAppStore((s) => s.setTheme)
  const bump = useAppStore((s) => s.bump)

  const [activeTab, setActiveTab] = useState<
    'general' | 'engine' | 'limits' | 'grounding' | 'network' | 'laya' | 'devbox' | 'mcp' | 'data'
  >('general')

  // Settings
  const { data: settingsData, reload: reloadSettings } = useLoad<{ settings: Settings }>('/api/settings')
  const settings = settingsData?.settings

  // Presets
  const { data: presetsData } = useLoad<{ presets: { name: string; summary: string }[] }>('/api/presets')
  const presets = presetsData?.presets || []

  // DevBox
  const { data: devboxStatus, reload: reloadDevbox } = useLoad<DevboxStatus>('/api/devbox')

  // MCP Servers
  const { data: mcpData, reload: reloadMcp } = useLoad<{ servers: McpServer[] }>('/api/mcp')
  const mcpServers = mcpData?.servers || []

  // Laya Speech
  const [testingSpeech, setTestingSpeech] = useState(false)
  const [layaCheckResult, setLayaCheckResult] = useState<LayaCheck | null>(null)

  // MCP modal
  const [mcpModalOpen, setMcpModalOpen] = useState(false)
  const [mcpName, setMcpName] = useState('')
  const [mcpCommand, setMcpCommand] = useState('')
  const [mcpArgs, setMcpArgs] = useState('')
  const [savingMcp, setSavingMcp] = useState(false)

  // Protected Globs input state
  const [newGlob, setNewGlob] = useState('')

  // Allowed Hosts input state
  const [newHost, setNewHost] = useState('')

  const handleUpdate = async (updates: Partial<Settings>) => {
    if (!settings) return
    try {
      await api.put('/api/settings', { ...settings, ...updates })
      toast('Settings updated successfully', 'good')
      bump()
      await reloadSettings()
    } catch (err) {
      toast(`Update failed: ${errorText(err)}`, 'bad')
    }
  }

  const handleApplyPreset = async (presetName: string) => {
    try {
      await api.post('/api/presets', { name: presetName })
      toast(`Applied preset: ${presetName}`, 'good')
      bump()
      await reloadSettings()
    } catch (err) {
      toast(`Failed to apply preset: ${errorText(err)}`, 'bad')
    }
  }

  const handleToggleModule = async (mod: string, enabled: boolean) => {
    if (!settings) return
    const current = new Set(settings.modules || [])
    if (enabled) {
      current.add(mod)
    } else {
      current.delete(mod)
    }
    await handleUpdate({ modules: Array.from(current) as any })
  }

  const handleDevboxPrepare = async () => {
    try {
      await api.post('/api/devbox/prepare')
      toast('DevBox container prepare started', 'good')
      await reloadDevbox()
    } catch (err) {
      toast(`DevBox prepare error: ${errorText(err)}`, 'bad')
    }
  }

  const handleDevboxReset = async () => {
    if (!confirm('Are you sure you want to reset and purge the DevBox container?')) return
    try {
      await api.del('/api/devbox')
      toast('DevBox container reset', 'warn')
      await reloadDevbox()
    } catch (err) {
      toast(`DevBox reset error: ${errorText(err)}`, 'bad')
    }
  }

  const handleToggleMcp = async (name: string, enabled: boolean) => {
    try {
      await api.patch(`/api/mcp/${encodeURIComponent(name)}`, { enabled })
      toast(`MCP server ${name} ${enabled ? 'enabled' : 'disabled'}`, 'good')
      await reloadMcp()
    } catch (err) {
      toast(`Failed to update MCP: ${errorText(err)}`, 'bad')
    }
  }

  const handleDeleteMcp = async (name: string) => {
    if (!confirm(`Are you sure you want to remove MCP server "${name}"?`)) return
    try {
      await api.del(`/api/mcp/${encodeURIComponent(name)}`)
      toast(`Removed MCP server ${name}`, 'warn')
      await reloadMcp()
    } catch (err) {
      toast(`Failed to remove MCP: ${errorText(err)}`, 'bad')
    }
  }

  const handleAddMcp = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!mcpName.trim() || !mcpCommand.trim()) return

    setSavingMcp(true)
    try {
      const argsArray = mcpArgs
        .split(' ')
        .map((s) => s.trim())
        .filter(Boolean)
      await api.post('/api/mcp', {
        name: mcpName.trim(),
        command: mcpCommand.trim(),
        args: argsArray,
      })
      toast(`MCP server ${mcpName} configured`, 'good')
      setMcpModalOpen(false)
      setMcpName('')
      setMcpCommand('')
      setMcpArgs('')
      await reloadMcp()
    } catch (err) {
      toast(`Failed to add MCP: ${errorText(err)}`, 'bad')
    } finally {
      setSavingMcp(false)
    }
  }

  const handleTestLayaSpeech = async () => {
    setTestingSpeech(true)
    try {
      await api.post('/api/laya/test', { text: 'Hello! Lilly speech synthesis online.' })
      toast('Speech test succeeded!', 'good')
    } catch (err) {
      toast(`Speech test error: ${errorText(err)}`, 'bad')
    } finally {
      setTestingSpeech(false)
    }
  }

  const handleCheckLaya = async () => {
    try {
      const res = await api.get<LayaCheck>('/api/laya/check')
      setLayaCheckResult(res)
      toast(res.ok ? 'Laya speech engine ready' : 'Laya needs setup', res.ok ? 'good' : 'warn')
    } catch (err) {
      toast(`Laya check failed: ${errorText(err)}`, 'bad')
    }
  }

  const handleRevokeAllPermissions = async () => {
    if (!confirm('Are you sure you want to revoke ALL granted file and tool permissions?')) return
    try {
      await api.post('/api/permissions/revoke-all')
      toast('All tool and file permissions have been revoked', 'warn')
      bump()
    } catch (err) {
      toast(`Revocation failed: ${errorText(err)}`, 'bad')
    }
  }

  const handleBackupNow = async () => {
    try {
      await api.post('/api/data/backup')
      toast('Database snapshot backup created', 'good')
    } catch (err) {
      toast(`Backup failed: ${errorText(err)}`, 'bad')
    }
  }

  const handlePruneNow = async () => {
    try {
      const res = await api.post<{ removed: number }>('/api/data/prune')
      toast(`Pruned ${res.removed || 0} expired logs`, 'good')
    } catch (err) {
      toast(`Prune failed: ${errorText(err)}`, 'bad')
    }
  }

  const handleExportData = () => {
    window.location.href = '/api/data/export'
    toast('Data export download initiated', 'good')
  }

  const allModules = ['files', 'web', 'memory', 'notes', 'skills', 'computer', 'browser', 'devbox']

  return (
    <div className="view-container">
      <div style={{ marginBottom: '24px' }}>
        <h1 className="greeting-text">Settings & Configuration</h1>
        <div className="greeting-sub">
          Fine-tune engine execution, capacity limits, safety guardrails, MCP tools, and container sandboxes.
        </div>
      </div>

      {/* Tabs */}
      <div className="filter-bar" style={{ marginBottom: '20px', overflowX: 'auto', flexWrap: 'wrap' }}>
        {[
          { id: 'general', label: 'General & Safety' },
          { id: 'engine', label: 'Engine & Execution' },
          { id: 'limits', label: 'Limits & Capacity' },
          { id: 'grounding', label: 'Grounding & Guardrails' },
          { id: 'network', label: 'Network & Search' },
          { id: 'laya', label: 'Laya Voice' },
          { id: 'devbox', label: 'DevBox Sandbox' },
          { id: 'mcp', label: 'MCP Servers' },
          { id: 'data', label: 'Data & Maintenance' },
        ].map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`filter-tab ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.id as any)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab: General & Safety */}
      {activeTab === 'general' && settings && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', maxWidth: '780px' }}>
          {/* Appearance */}
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: 600 }}>Visual Appearance & Theme</h3>
            <div style={{ display: 'flex', gap: '8px' }}>
              {(['dark', 'light', 'system'] as ThemePref[]).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setTheme(t)}
                  className={`btn ${theme === t ? 'btn-primary' : 'btn-secondary'}`}
                  style={{ textTransform: 'capitalize' }}
                >
                  {t} Theme
                </button>
              ))}
            </div>
          </div>

          {/* Autonomy & Approval Policy */}
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: 600 }}>Approval & Autonomy Policy</h3>
            <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
              Controls whether Lilly asks for approval before executing file changes, bash commands, and computer controls.
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '10px' }}>
              {APPROVAL_MODES.map((opt) => {
                const active = settings.approval_mode === opt.value
                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => handleUpdate({ approval_mode: opt.value })}
                    style={{
                      padding: '14px',
                      borderRadius: 'var(--radius-sm)',
                      border: active ? '2px solid var(--primary)' : '1px solid var(--border)',
                      backgroundColor: active ? 'var(--primary-subtle)' : 'var(--bg-card)',
                      textAlign: 'left',
                      cursor: 'pointer',
                      transition: 'border-color 0.15s ease, background-color 0.15s ease',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <div style={{ fontWeight: 700, fontSize: '14px', color: 'var(--text-main)' }}>
                        {opt.name} Mode
                      </div>
                      <span
                        style={{
                          fontSize: '10px',
                          fontWeight: 700,
                          padding: '2px 6px',
                          borderRadius: '10px',
                          backgroundColor: active ? 'var(--primary)' : 'var(--bg-subtle)',
                          color: active ? '#fff' : 'var(--text-dim)',
                          textTransform: 'uppercase',
                        }}
                      >
                        {opt.tagline}
                      </span>
                    </div>
                    <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '6px', lineHeight: 1.4 }}>
                      {opt.blurb}
                    </div>
                  </button>
                )
              })}
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '10px' }}>
              <div>
                <div style={{ fontSize: '13px', fontWeight: 600 }}>Stay Awake While Running</div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                  Prevents macOS / host laptop sleep while background tasks are actively running.
                </div>
              </div>
              <input
                type="checkbox"
                checked={settings.stay_awake}
                onChange={(e) => handleUpdate({ stay_awake: e.target.checked })}
              />
            </div>
          </div>

          {/* Active Modules */}
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: 600 }}>Active Feature Modules</h3>
            <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
              Toggle tool systems available to agents across the entire workspace.
            </p>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '10px' }}>
              {allModules.map((mod) => {
                const isEnabled = (settings.modules || []).includes(mod)
                return (
                  <label
                    key={mod}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                      padding: '8px 10px',
                      borderRadius: 'var(--radius-xs)',
                      backgroundColor: 'var(--bg-card-subtle)',
                      border: '1px solid var(--border)',
                      fontSize: '12px',
                      fontWeight: 600,
                      cursor: 'pointer',
                      textTransform: 'capitalize',
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={isEnabled}
                      onChange={(e) => handleToggleModule(mod, e.target.checked)}
                    />
                    <span>{mod}</span>
                  </label>
                )
              })}
            </div>
          </div>
        </div>
      )}

      {/* Tab: Engine & Execution */}
      {activeTab === 'engine' && settings && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', maxWidth: '780px' }}>
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: 600 }}>Orchestrator Engine Mode</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <button
                type="button"
                onClick={() => handleUpdate({ engine: { ...settings.engine, mode: 'loop' } })}
                style={{
                  padding: '14px',
                  borderRadius: 'var(--radius-sm)',
                  border: settings.engine?.mode === 'loop' ? '2px solid var(--primary)' : '1px solid var(--border)',
                  backgroundColor: settings.engine?.mode === 'loop' ? 'var(--primary-subtle)' : 'var(--bg-card)',
                  textAlign: 'left',
                  cursor: 'pointer',
                }}
              >
                <div style={{ fontWeight: 600, fontSize: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <Icon name="refresh" size={16} />
                  <span>ReAct Tool Loop (Default)</span>
                </div>
                <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>
                  Dynamic step-by-step model execution. Best for rapid interactive coding, exploratory research, and terminal commands.
                </div>
              </button>

              <button
                type="button"
                onClick={() => handleUpdate({ engine: { ...settings.engine, mode: 'plan' } })}
                style={{
                  padding: '14px',
                  borderRadius: 'var(--radius-sm)',
                  border: settings.engine?.mode === 'plan' ? '2px solid var(--primary)' : '1px solid var(--border)',
                  backgroundColor: settings.engine?.mode === 'plan' ? 'var(--primary-subtle)' : 'var(--bg-card)',
                  textAlign: 'left',
                  cursor: 'pointer',
                }}
              >
                <div style={{ fontWeight: 600, fontSize: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <Icon name="tasks" size={16} />
                  <span>Upfront DAG Planning</span>
                </div>
                <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>
                  Generates an upfront dependency step graph before executing. High predictability for complex refactors.
                </div>
              </button>
            </div>
          </div>

          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: 600 }}>Context Window & Execution Tuning</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
                  Max Observation Characters
                </label>
                <input
                  type="number"
                  className="input"
                  value={settings.engine?.observation_chars ?? 6000}
                  onChange={(e) =>
                    handleUpdate({
                      engine: { ...settings.engine, observation_chars: Number(e.target.value) },
                    })
                  }
                />
                <div style={{ fontSize: '11px', color: 'var(--text-dim)', marginTop: '3px' }}>
                  Caps tool output characters injected into prompt context (500 - 30,000).
                </div>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
                  Soft Context Tokens Target
                </label>
                <input
                  type="number"
                  className="input"
                  value={settings.engine?.soft_context_tokens ?? 6000}
                  onChange={(e) =>
                    handleUpdate({
                      engine: { ...settings.engine, soft_context_tokens: Number(e.target.value) },
                    })
                  }
                />
                <div style={{ fontSize: '11px', color: 'var(--text-dim)', marginTop: '3px' }}>
                  Target token ceiling before history compression triggers (1,000 - 100,000).
                </div>
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontSize: '13px', fontWeight: 600 }}>Self-Check Verification Step</div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                  Asks the model to verify its final answer before concluding the task.
                </div>
              </div>
              <input
                type="checkbox"
                checked={settings.engine?.self_check ?? false}
                onChange={(e) =>
                  handleUpdate({
                    engine: { ...settings.engine, self_check: e.target.checked },
                  })
                }
              />
            </div>
          </div>
        </div>
      )}

      {/* Tab: Limits & Capacity */}
      {activeTab === 'limits' && settings && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', maxWidth: '780px' }}>
          {/* Quick Presets */}
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: 600 }}>Predefined Performance Presets</h3>
            <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
              Quickly scale concurrency and memory unloads for your machine type.
            </p>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              {presets.map((p) => (
                <button
                  key={p.name}
                  type="button"
                  onClick={() => handleApplyPreset(p.name)}
                  className="btn btn-secondary"
                  style={{ textTransform: 'capitalize', display: 'inline-flex', alignItems: 'center', gap: '6px' }}
                >
                  <Icon name="sparkles" size={12} />
                  <span>{p.name}: {p.summary}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Limits tuning */}
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: 600 }}>Task & Resource Limits</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
                  Max Concurrent Running Tasks
                </label>
                <input
                  type="number"
                  min={1}
                  max={8}
                  className="input"
                  value={settings.limits?.max_running ?? 3}
                  onChange={(e) =>
                    handleUpdate({
                      limits: { ...settings.limits, max_running: Number(e.target.value) },
                    })
                  }
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
                  Step Timeout (Seconds)
                </label>
                <input
                  type="number"
                  min={10}
                  max={900}
                  className="input"
                  value={settings.limits?.step_timeout_s ?? 180}
                  onChange={(e) =>
                    handleUpdate({
                      limits: { ...settings.limits, step_timeout_s: Number(e.target.value) },
                    })
                  }
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
                  Total Task Timeout (Minutes)
                </label>
                <input
                  type="number"
                  min={1}
                  max={240}
                  className="input"
                  value={settings.limits?.task_minutes ?? 60}
                  onChange={(e) =>
                    handleUpdate({
                      limits: { ...settings.limits, task_minutes: Number(e.target.value) },
                    })
                  }
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
                  Max Tool Turns per Task
                </label>
                <input
                  type="number"
                  min={1}
                  max={60}
                  className="input"
                  value={settings.limits?.max_agent_steps ?? 20}
                  onChange={(e) =>
                    handleUpdate({
                      limits: { ...settings.limits, max_agent_steps: Number(e.target.value) },
                    })
                  }
                />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tab: Grounding & Guardrails */}
      {activeTab === 'grounding' && settings && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', maxWidth: '780px' }}>
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <h3 style={{ fontSize: '15px', fontWeight: 600 }}>Grounding & Test Verification</h3>
                <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>
                  Validates file operations and prevents agents from tampering with test files or secret keys.
                </p>
              </div>
              <input
                type="checkbox"
                checked={settings.grounding?.enabled ?? true}
                onChange={(e) =>
                  handleUpdate({
                    grounding: { ...settings.grounding, enabled: e.target.checked },
                  })
                }
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '6px' }}>
                Protected File Patterns (Globs)
              </label>
              <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginBottom: '8px' }}>
                {(settings.grounding?.protected_globs || []).map((glob) => (
                  <span key={glob} className="badge badge-accent" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <span>{glob}</span>
                    <button
                      type="button"
                      onClick={() =>
                        handleUpdate({
                          grounding: {
                            ...settings.grounding,
                            protected_globs: settings.grounding.protected_globs.filter((g) => g !== glob),
                          },
                        })
                      }
                      style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, display: 'inline-flex', alignItems: 'center' }}
                    >
                      <Icon name="x" size={12} />
                    </button>
                  </span>
                ))}
              </div>

              <div style={{ display: 'flex', gap: '6px' }}>
                <input
                  className="input"
                  placeholder="e.g. *.pem, .env*, secrets/*"
                  value={newGlob}
                  onChange={(e) => setNewGlob(e.target.value)}
                  style={{ maxWidth: '300px' }}
                />
                <button
                  type="button"
                  onClick={() => {
                    if (!newGlob.trim()) return
                    handleUpdate({
                      grounding: {
                        ...settings.grounding,
                        protected_globs: [...(settings.grounding?.protected_globs || []), newGlob.trim()],
                      },
                    })
                    setNewGlob('')
                  }}
                  className="btn btn-secondary"
                >
                  Add Glob
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tab: Network & Search */}
      {activeTab === 'network' && settings && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', maxWidth: '780px' }}>
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: 600 }}>Web Search Engine</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
                  Search Provider
                </label>
                <select
                  className="select"
                  value={settings.search?.engine || 'duckduckgo'}
                  onChange={(e) =>
                    handleUpdate({
                      search: { ...settings.search, engine: e.target.value as any },
                    })
                  }
                >
                  <option value="duckduckgo">DuckDuckGo (Free / No Key)</option>
                  <option value="brave">Brave Search API</option>
                  <option value="searxng">SearXNG Self-Hosted</option>
                </select>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
                  SearXNG URL (If Self-Hosted)
                </label>
                <input
                  className="input"
                  placeholder="http://localhost:8080"
                  value={settings.search?.searxng_url || ''}
                  onChange={(e) =>
                    handleUpdate({
                      search: { ...settings.search, searxng_url: e.target.value || null },
                    })
                  }
                />
              </div>
            </div>
          </div>

          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: 600 }}>Network Host Access & Local Only</h3>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontSize: '13px', fontWeight: 600 }}>Strict Local-Only Mode</div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                  Refuses all external network model inference; limits execution strictly to local host models.
                </div>
              </div>
              <input
                type="checkbox"
                checked={settings.network?.local_only ?? false}
                onChange={(e) =>
                  handleUpdate({
                    network: { ...settings.network, local_only: e.target.checked },
                  })
                }
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '6px' }}>
                Allowed Hostnames (e.g. Tailscale / Remote)
              </label>
              <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginBottom: '8px' }}>
                {(settings.network?.allowed_hosts || []).map((host) => (
                  <span key={host} className="badge badge-secondary" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <span>{host}</span>
                    <button
                      type="button"
                      onClick={() =>
                        handleUpdate({
                          network: {
                            ...settings.network,
                            allowed_hosts: settings.network.allowed_hosts.filter((h) => h !== host),
                          },
                        })
                      }
                      style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, display: 'inline-flex', alignItems: 'center' }}
                    >
                      <Icon name="x" size={12} />
                    </button>
                  </span>
                ))}
              </div>

              <div style={{ display: 'flex', gap: '6px' }}>
                <input
                  className="input"
                  placeholder="e.g. my-laptop.ts.net"
                  value={newHost}
                  onChange={(e) => setNewHost(e.target.value)}
                  style={{ maxWidth: '300px' }}
                />
                <button
                  type="button"
                  onClick={() => {
                    if (!newHost.trim()) return
                    handleUpdate({
                      network: {
                        ...settings.network,
                        allowed_hosts: [...(settings.network?.allowed_hosts || []), newHost.trim()],
                      },
                    })
                    setNewHost('')
                  }}
                  className="btn btn-secondary"
                >
                  Add Host
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tab: Laya Voice */}
      {activeTab === 'laya' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', maxWidth: '780px' }}>
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <h3 style={{ fontSize: '15px', fontWeight: 600 }}>Laya On-Device Speech & Voice</h3>
                <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>
                  Local text-to-speech engine running offline on macOS via Whisper / Kokoro neural voice.
                </p>
              </div>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button type="button" onClick={handleCheckLaya} className="btn btn-secondary btn-sm">
                  Run Diagnostic Check
                </button>
                <button
                  type="button"
                  onClick={handleTestLayaSpeech}
                  disabled={testingSpeech}
                  className="btn btn-primary btn-sm"
                >
                  {testingSpeech ? 'Speaking...' : 'Test Speech Synth'}
                </button>
              </div>
            </div>

            {layaCheckResult && (
              <div
                style={{
                  padding: '12px',
                  backgroundColor: layaCheckResult.ok ? 'var(--good-subtle)' : 'var(--warn-subtle)',
                  borderRadius: 'var(--radius-sm)',
                  fontSize: '12px',
                  border: `1px solid ${layaCheckResult.ok ? 'var(--good-border)' : 'var(--warn-border)'}`,
                }}
              >
                <div style={{ fontWeight: 600 }}>{layaCheckResult.name}: {layaCheckResult.ok ? 'Diagnostic Passed' : 'Warning'}</div>
                <div style={{ color: 'var(--text-dim)', marginTop: '4px' }}>
                  {layaCheckResult.detail}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Tab: DevBox Sandbox */}
      {activeTab === 'devbox' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', maxWidth: '780px' }}>
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <h3 style={{ fontSize: '15px', fontWeight: 600 }}>DevBox Isolated Container Sandbox</h3>
                <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>
                  Secure Docker / Podman container sandbox for executing untrusted scripts and external code safely.
                </p>
              </div>

              <div style={{ display: 'flex', gap: '8px' }}>
                <button type="button" onClick={handleDevboxPrepare} className="btn btn-secondary btn-sm">
                  Prepare Container
                </button>
                <button type="button" onClick={handleDevboxReset} className="btn btn-ghost btn-sm" style={{ color: 'var(--danger-text)' }}>
                  Reset & Purge
                </button>
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <div style={{ padding: '10px', backgroundColor: 'var(--bg-card-subtle)', borderRadius: 'var(--radius-xs)', fontSize: '12px' }}>
                <div style={{ color: 'var(--text-dim)' }}>Container Status</div>
                <div style={{ fontWeight: 600, fontSize: '14px', textTransform: 'capitalize' }}>
                  {devboxStatus?.state || 'Idle / Not prepared'}
                </div>
              </div>

              <div style={{ padding: '10px', backgroundColor: 'var(--bg-card-subtle)', borderRadius: 'var(--radius-xs)', fontSize: '12px' }}>
                <div style={{ color: 'var(--text-dim)' }}>Base Image</div>
                <div style={{ fontWeight: 600, fontSize: '13px', fontFamily: 'var(--font-mono)' }}>
                  {devboxStatus?.image || 'ghcr.io/astral-sh/uv:debian-slim'}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tab: MCP Servers */}
      {activeTab === 'mcp' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', maxWidth: '780px' }}>
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <h3 style={{ fontSize: '15px', fontWeight: 600 }}>Model Context Protocol (MCP) Servers</h3>
                <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>
                  Connect external tools via stdio or SSE server bridges.
                </p>
              </div>
              <button type="button" onClick={() => setMcpModalOpen(true)} className="btn btn-primary btn-sm">
                <Icon name="plus" size={12} />
                <span>Add MCP Server</span>
              </button>
            </div>

            {mcpServers.length === 0 ? (
              <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>
                No external MCP servers installed.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {mcpServers.map((srv) => (
                  <div
                    key={srv.name}
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      padding: '10px 14px',
                      backgroundColor: 'var(--bg-card-subtle)',
                      borderRadius: 'var(--radius-xs)',
                      border: '1px solid var(--border-subtle)',
                    }}
                  >
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ fontWeight: 600, fontSize: '13px' }}>{srv.name}</span>
                        <span className={`badge ${srv.enabled ? 'badge-good' : 'badge-neutral'}`}>
                          {srv.enabled ? 'Active' : 'Disabled'}
                        </span>
                      </div>
                      <div style={{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', marginTop: '2px' }}>
                        {srv.command} {(srv.args || []).join(' ')}
                      </div>
                    </div>

                    <div style={{ display: 'flex', gap: '6px' }}>
                      <button
                        type="button"
                        onClick={() => handleToggleMcp(srv.name, !srv.enabled)}
                        className="btn btn-secondary btn-sm"
                        style={{ fontSize: '11px' }}
                      >
                        {srv.enabled ? 'Disable' : 'Enable'}
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDeleteMcp(srv.name)}
                        className="btn btn-ghost btn-sm"
                        style={{ color: 'var(--danger-text)' }}
                      >
                        <Icon name="trash" size={12} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Tab: Data & Maintenance */}
      {activeTab === 'data' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', maxWidth: '780px' }}>
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: 600 }}>Database Backups & Export</h3>
            <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
              Export complete workspace state, take live SQLite snapshot backups, or prune old audit logs.
            </p>

            <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
              <button type="button" onClick={handleBackupNow} className="btn btn-secondary">
                <Icon name="database" size={13} />
                <span>Backup Database Snapshot</span>
              </button>
              <button type="button" onClick={handlePruneNow} className="btn btn-secondary">
                <Icon name="trash" size={13} />
                <span>Prune Expired Logs</span>
              </button>
              <button type="button" onClick={handleExportData} className="btn btn-primary">
                <Icon name="copy" size={13} />
                <span>Export All Workspace JSON</span>
              </button>
            </div>
          </div>

          <div
            className="card"
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '12px',
              border: '1px solid var(--danger-border)',
              backgroundColor: 'var(--danger-subtle)',
            }}
          >
            <h3 style={{ fontSize: '15px', fontWeight: 600, color: 'var(--danger-text)' }}>
              Security Permissions Revocation
            </h3>
            <p style={{ fontSize: '12px', color: 'var(--danger-text)' }}>
              Immediately revokes all granted folder roots, shell execution approvals, and computer automation grants.
            </p>
            <div>
              <button type="button" onClick={handleRevokeAllPermissions} className="btn btn-danger">
                Revoke All Tool Permissions
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add MCP Modal */}
      <Modal
        isOpen={mcpModalOpen}
        onClose={() => setMcpModalOpen(false)}
        title="Add Stdio MCP Server"
        maxWidth={500}
        footer={
          <>
            <button type="button" onClick={() => setMcpModalOpen(false)} className="btn btn-secondary">
              Cancel
            </button>
            <button
              type="button"
              onClick={handleAddMcp}
              disabled={!mcpName.trim() || !mcpCommand.trim() || savingMcp}
              className="btn btn-primary"
            >
              <span>{savingMcp ? 'Adding...' : 'Add Server'}</span>
            </button>
          </>
        }
      >
        <form onSubmit={handleAddMcp} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
              Server Name *
            </label>
            <input
              className="input"
              value={mcpName}
              onChange={(e) => setMcpName(e.target.value)}
              placeholder="e.g. filesystem, github, fetch"
              required
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
              Command *
            </label>
            <input
              className="input"
              value={mcpCommand}
              onChange={(e) => setMcpCommand(e.target.value)}
              placeholder="e.g. npx or python"
              required
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
              Arguments (Space separated)
            </label>
            <input
              className="input"
              value={mcpArgs}
              onChange={(e) => setMcpArgs(e.target.value)}
              placeholder="-y @modelcontextprotocol/server-filesystem /path"
            />
          </div>
        </form>
      </Modal>
    </div>
  )
}
