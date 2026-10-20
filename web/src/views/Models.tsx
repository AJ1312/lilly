import React, { useState } from 'react'
import { api, errorText } from '../api'
import { useLoad } from '../hooks'
import { useAppStore } from '../store'
import type { ModelStatus, KeyInfo, Settings, ModelSpec } from '../types'
import { Icon } from '../ui/Icon'
import { Modal } from '../ui/Modal'

export interface CatalogEntry {
  id: string
  name: string
  provider: string
  model_id: string
  base_url: string
  openai_compatible: boolean
  starter: boolean
  enabled: boolean
  local: boolean
  lane: number
  tags: string[]
  caps: string[]
  key_ref: string | null
  free_tier: {
    rpm: number | null
    rpd: number | null
    tpm: number | null
    tpd: number | null
    notes: string
  }
  tools: string
  max_context_tokens: number | null
  source_url: string
  verified_on: string | null
  confidence: string
}

export const ModelsView: React.FC = () => {
  const toast = useAppStore((s) => s.toast)
  const bump = useAppStore((s) => s.bump)

  // 1. Configured models in Lilly runtime
  const { data: modelsData, loading: loadingModels, reload: reloadModels } =
    useLoad<{ models: ModelStatus[]; default?: string }>('/api/models')
  const models = modelsData?.models || []

  // 2. Pre-existing starter catalog from /api/providers/catalog
  const { data: catalogData, loading: loadingCatalog } =
    useLoad<CatalogEntry[]>('/api/providers/catalog')
  const catalog = catalogData || []

  // 3. API Keys from vault
  const { data: keysData, reload: reloadKeys } =
    useLoad<{ keys: KeyInfo[] }>('/api/keys')
  const keys = keysData?.keys || []

  // 4. Current settings for adding/updating models
  const { reload: reloadSettings } =
    useLoad<{ settings: Settings }>('/api/settings')

  // Testing model state
  const [testingModelName, setTestingModelName] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<{
    model: string
    ok: boolean
    latency_ms?: number
    text?: string
  } | null>(null)

  // Ollama local discovery modal
  const [ollamaResult, setOllamaResult] = useState<{
    model: string
    reachable: boolean
    version?: string
    models?: string[]
    message?: string
  } | null>(null)

  // API Key modal
  const [keyModalOpen, setKeyModalOpen] = useState(false)
  const [keyRef, setKeyRef] = useState('')
  const [keyValue, setKeyValue] = useState('')
  const [savingKey, setSavingKey] = useState(false)

  // Custom Model Modal
  const [customModelOpen, setCustomModelOpen] = useState(false)
  const [customName, setCustomName] = useState('')
  const [customProvider, setCustomProvider] = useState('openai')
  const [customModelId, setCustomModelId] = useState('')
  const [customBaseUrl, setCustomBaseUrl] = useState('')
  const [customKeyRef, setCustomKeyRef] = useState('')
  const [customLane, setCustomLane] = useState(1)
  const [addingModel, setAddingModel] = useState(false)

  // Check if a model is already configured
  const configuredNames = new Set(models.map((m) => m.name.toLowerCase()))

  const handleTestModel = async (modelName: string) => {
    setTestingModelName(modelName)
    try {
      const res = await api.post<{ ok: boolean; latency_ms?: number; reply?: string; error?: string }>(
        `/api/models/${encodeURIComponent(modelName)}/test`
      )
      setTestResult({
        model: modelName,
        ok: res.ok,
        latency_ms: res.latency_ms,
        text: res.ok ? (res.reply || 'Model responded successfully') : (res.error || res.reply || 'Model test failed'),
      })
      toast(`Tested ${modelName}: ${res.ok ? 'Online' : (res.error || 'Failed')}`, res.ok ? 'good' : 'bad')
      await reloadModels()
    } catch (err) {
      toast(`Test error: ${errorText(err)}`, 'bad')
      setTestResult({
        model: modelName,
        ok: false,
        text: errorText(err),
      })
    } finally {
      setTestingModelName(null)
    }
  }

  const handleDiscoverOllama = async (modelName: string) => {
    try {
      const res = await api.get<{
        reachable: boolean
        version?: string
        models?: string[]
        message?: string
      }>(`/api/models/${encodeURIComponent(modelName)}/ollama`)
      setOllamaResult({
        model: modelName,
        reachable: res.reachable,
        version: res.version,
        models: res.models || [],
        message: res.message,
      })
    } catch (err) {
      toast(`Ollama discovery failed: ${errorText(err)}`, 'bad')
    }
  }

  const handleAddCatalogModel = async (entry: CatalogEntry) => {
    setAddingModel(true)
    try {
      // Fetch latest settings
      const currentRes = await api.get<{ settings: Settings }>('/api/settings')
      const currentSettings = currentRes.settings
      const existing = (currentSettings.models || []).filter((m) => m.name !== entry.name)

      const newSpec: ModelSpec = {
        name: entry.name,
        provider: entry.provider,
        model_id: entry.model_id,
        local: entry.local,
        enabled: true,
        caps: entry.caps || [],
        max_label: entry.local ? 'PERSONAL' : 'PUBLIC',
        rpm: entry.free_tier?.rpm ?? undefined,
        rpd: entry.free_tier?.rpd ?? undefined,
        tpm: entry.free_tier?.tpm ?? undefined,
        tpd: entry.free_tier?.tpd ?? undefined,
        key_ref: entry.key_ref || undefined,
        trains: !entry.local,
        base_url: entry.base_url || undefined,
        quick: entry.tags.includes('quick'),
        lane: entry.lane,
        tags: entry.tags,
        tools: entry.tools as any,
        max_context_tokens: entry.max_context_tokens ?? undefined,
      }

      await api.put('/api/settings', {
        ...currentSettings,
        models: [...existing, newSpec],
      })

      toast(`Added model "${entry.name}" to Lilly!`, 'good')
      bump()
      await reloadModels()
      await reloadSettings()

      // If requires key and missing in keys vault, prompt directly!
      if (entry.key_ref) {
        const keyObj = keys.find((k) => k.ref === entry.key_ref)
        if (!keyObj || !keyObj.present) {
          openSetKey(entry.key_ref)
        }
      }
    } catch (err) {
      toast(`Failed to add model: ${errorText(err)}`, 'bad')
    } finally {
      setAddingModel(false)
    }
  }

  const handleCreateCustomModel = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!customName.trim() || !customModelId.trim()) return

    setAddingModel(true)
    try {
      const currentRes = await api.get<{ settings: Settings }>('/api/settings')
      const currentSettings = currentRes.settings
      const existing = (currentSettings.models || []).filter((m) => m.name !== customName.trim())

      const isLocal = customProvider === 'ollama'
      const newSpec: ModelSpec = {
        name: customName.trim(),
        provider: customProvider,
        model_id: customModelId.trim(),
        local: isLocal,
        enabled: true,
        caps: [],
        max_label: isLocal ? 'PERSONAL' : 'PUBLIC',
        key_ref: customKeyRef.trim() || undefined,
        base_url: customBaseUrl.trim() || undefined,
        lane: customLane,
        quick: false,
        tags: [customProvider],
      }

      await api.put('/api/settings', {
        ...currentSettings,
        models: [...existing, newSpec],
      })

      toast(`Custom model "${customName}" added!`, 'good')
      setCustomModelOpen(false)
      setCustomName('')
      setCustomModelId('')
      setCustomBaseUrl('')
      setCustomKeyRef('')
      bump()
      await reloadModels()
      await reloadSettings()
    } catch (err) {
      toast(`Failed to add custom model: ${errorText(err)}`, 'bad')
    } finally {
      setAddingModel(false)
    }
  }

  const openSetKey = (ref: string) => {
    setKeyRef(ref)
    setKeyValue('')
    setKeyModalOpen(true)
  }

  const handleSaveKey = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!keyValue.trim()) return

    setSavingKey(true)
    try {
      await api.put(`/api/keys/${encodeURIComponent(keyRef)}`, { value: keyValue.trim() })
      toast(`API key stored for ${keyRef}`, 'good')
      setKeyModalOpen(false)
      bump()
      await reloadKeys()
      await reloadModels()
    } catch (err) {
      toast(`Failed to store key: ${errorText(err)}`, 'bad')
    } finally {
      setSavingKey(false)
    }
  }

  const handleDeleteKey = async (ref: string) => {
    if (!confirm(`Are you sure you want to remove the API key for ${ref}?`)) return
    try {
      await api.del(`/api/keys/${encodeURIComponent(ref)}`)
      toast(`API key cleared for ${ref}`, 'warn')
      bump()
      await reloadKeys()
      await reloadModels()
    } catch (err) {
      toast(`Failed to clear key: ${errorText(err)}`, 'bad')
    }
  }

  return (
    <div className="view-container">
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '24px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <h1 className="greeting-text">Models & Catalog</h1>
            <span className="badge badge-primary">{models.length} Active</span>
          </div>
          <div className="greeting-sub">
            Pre-existing models catalog, live ping latency diagnostics, and encrypted credential vault.
          </div>
        </div>

        <div style={{ display: 'flex', gap: '8px' }}>
          <button onClick={() => reloadModels()} className="btn btn-ghost" type="button">
            <Icon name="refresh" size={14} />
            <span>Refresh</span>
          </button>
          <button onClick={() => setCustomModelOpen(true)} className="btn btn-primary" type="button">
            <Icon name="plus" size={14} />
            <span>Add Custom Model</span>
          </button>
        </div>
      </div>

      {/* Main Grid: Configured Models & API Key Vault */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(440px, 1fr))', gap: '24px', marginBottom: '32px' }}>
        {/* Active Models in Lilly */}
        <div>
          <h3 style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-main)', marginBottom: '12px' }}>
            Configured Active Models ({models.length})
          </h3>

          {loadingModels && models.length === 0 ? (
            <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)' }}>
              Loading models...
            </div>
          ) : models.length === 0 ? (
            <div className="card" style={{ padding: '32px', textAlign: 'center' }}>
              <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '10px', color: 'var(--text-muted)' }}>
                <Icon name="cpu" size={32} />
              </div>
              <div style={{ fontWeight: 600, fontSize: '14px' }}>No models configured yet</div>
              <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>
                Add models from the pre-existing catalog below to enable inference!
              </p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {models.map((m) => (
                <div key={m.name} className="card card-hover" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-main)' }}>
                          {m.name}
                        </span>
                        {(() => {
                          if (!m.enabled) {
                            return <span className="badge badge-neutral">Disabled</span>
                          }
                          if (m.key_ref && !m.has_key && !m.local) {
                            return <span className="badge badge-warn">Missing Key</span>
                          }
                          if (m.breaker === 'open' || m.last_error) {
                            return (
                              <span className="badge badge-warn" title={m.last_error || 'Circuit breaker open'}>
                                Degraded
                              </span>
                            )
                          }
                          if (m.calls > 0) {
                            return <span className="badge badge-good">Healthy</span>
                          }
                          return <span className="badge badge-good">Configured / Ready</span>
                        })()}
                        {m.local && <span className="badge badge-accent">Host Local</span>}
                      </div>
                      <div style={{ fontSize: '12px', color: 'var(--text-dim)', marginTop: '2px' }}>
                        {m.provider} • Lane {m.lane} • Max: {m.max_label}
                      </div>
                    </div>

                    <div style={{ display: 'flex', gap: '6px' }}>
                      {m.provider === 'ollama' && (
                        <button
                          type="button"
                          onClick={() => handleDiscoverOllama(m.name)}
                          className="btn btn-ghost btn-sm"
                          style={{ fontSize: '11px', padding: '3px 8px' }}
                          title="Discover local Ollama models"
                        >
                          <Icon name="search" size={11} />
                          <span>Ollama</span>
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => handleTestModel(m.name)}
                        disabled={testingModelName === m.name}
                        className="btn btn-secondary btn-sm"
                        style={{ fontSize: '11px', padding: '3px 8px' }}
                        title="Runs a 100-token test completion using model credits"
                      >
                        {testingModelName === m.name ? (
                          <span>Testing...</span>
                        ) : (
                          <>
                            <Icon name="activity" size={11} />
                            <span>Run test completion</span>
                          </>
                        )}
                      </button>
                    </div>
                  </div>

                  {/* Latency & Status Info */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '11px', color: 'var(--text-muted)' }}>
                    <span>RPM: {m.rpm ?? 'Unlimited'} • Minute: {m.minute_used ?? 0}</span>
                    <span>Total Calls: {m.calls ?? 0}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* API Keys Vault */}
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <h3 style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-main)' }}>
              Provider Credentials Vault ({keys.length})
            </h3>
            <button onClick={() => reloadKeys()} className="btn btn-ghost btn-sm" type="button">
              <Icon name="refresh" size={12} />
              <span>Refresh Vault</span>
            </button>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {keys.map((k) => (
              <div
                key={k.ref}
                className="card"
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '10px 14px',
                }}
              >
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-main)', textTransform: 'capitalize' }}>
                      {k.ref}
                    </span>
                    <span className={`badge ${k.present ? 'badge-good' : 'badge-neutral'}`}>
                      {k.present ? 'Configured' : 'Missing'}
                    </span>
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--text-dim)', marginTop: '2px' }}>
                    Key ref: <code style={{ fontFamily: 'var(--font-mono)' }}>{k.ref}</code>
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '6px' }}>
                  <button
                    type="button"
                    onClick={() => openSetKey(k.ref)}
                    className="btn btn-secondary btn-sm"
                    style={{ fontSize: '11px', padding: '3px 8px' }}
                  >
                    <span>{k.present ? 'Rotate Key' : 'Set Key'}</span>
                  </button>
                  {k.present && (
                    <button
                      type="button"
                      onClick={() => handleDeleteKey(k.ref)}
                      className="btn btn-ghost btn-sm"
                      style={{ color: 'var(--danger-text)', padding: '3px 6px' }}
                      title="Clear key"
                    >
                      <Icon name="trash" size={11} />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Pre-Existing Starter Model Catalog */}
      <div style={{ marginTop: '36px' }}>
        <div style={{ marginBottom: '16px' }}>
          <h3 style={{ fontSize: '18px', fontWeight: 600, color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
              <Icon name="sparkles" size={16} />
              <span>Pre-Existing Starter Models Catalog</span>
            </span>
            <span className="badge badge-accent">{catalog.length} Available</span>
          </h3>
          <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
            One-click add verified starter models with documented free tiers, token limits, and zero setup friction.
          </p>
        </div>

        {loadingCatalog && catalog.length === 0 ? (
          <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)' }}>
            Loading catalog models...
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: '16px' }}>
            {catalog.map((entry) => {
              const isConfigured = configuredNames.has(entry.name.toLowerCase())
              return (
                <div
                  key={entry.id}
                  className="card card-hover"
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '12px',
                    position: 'relative',
                    border: isConfigured ? '1px solid var(--good-border)' : '1px solid var(--border)',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                        <span style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-main)' }}>
                          {entry.name}
                        </span>
                        {entry.starter && (
                          <span className="badge badge-primary" style={{ fontSize: '10px' }}>Starter</span>
                        )}
                        {entry.local && (
                          <span className="badge badge-accent" style={{ fontSize: '10px' }}>Host Local</span>
                        )}
                      </div>
                      <div style={{ fontSize: '12px', color: 'var(--text-dim)', marginTop: '2px' }}>
                        Provider: <strong>{entry.provider}</strong> • Model: {entry.model_id}
                      </div>
                    </div>

                    {isConfigured ? (
                      <span className="badge badge-good" style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontSize: '11px' }}>
                        <Icon name="check" size={11} />
                        <span>Installed</span>
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => handleAddCatalogModel(entry)}
                        disabled={addingModel}
                        className="btn btn-primary btn-sm"
                        style={{ fontSize: '11px', padding: '4px 10px' }}
                      >
                        <Icon name="plus" size={11} />
                        <span>Add Model</span>
                      </button>
                    )}
                  </div>

                  {/* Free Tier & Limits Description */}
                  {entry.free_tier?.notes && (
                    <div
                      style={{
                        padding: '8px 10px',
                        backgroundColor: 'var(--bg-card-subtle)',
                        borderRadius: 'var(--radius-xs)',
                        fontSize: '11px',
                        color: 'var(--text-secondary)',
                        lineHeight: 1.4,
                        display: 'flex',
                        alignItems: 'flex-start',
                        gap: '6px',
                      }}
                    >
                      <Icon name="eye" size={13} style={{ marginTop: '2px', flexShrink: 0 }} />
                      <span>{entry.free_tier.notes}</span>
                    </div>
                  )}

                  {/* Badges / Capabilities */}
                  <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginTop: 'auto' }}>
                    {entry.free_tier?.rpd && (
                      <span className="badge badge-secondary" style={{ fontSize: '10px' }}>
                        {entry.free_tier.rpd} req/day free
                      </span>
                    )}
                    {entry.free_tier?.rpm && (
                      <span className="badge badge-secondary" style={{ fontSize: '10px' }}>
                        {entry.free_tier.rpm} RPM
                      </span>
                    )}
                    {entry.tools === 'native' && (
                      <span className="badge badge-neutral" style={{ fontSize: '10px' }}>
                        Native Tools
                      </span>
                    )}
                    {entry.key_ref && (
                      <span className="badge badge-neutral" style={{ fontSize: '10px' }}>
                        Key: {entry.key_ref}
                      </span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Latency Test Result Modal */}
      <Modal
        isOpen={Boolean(testResult)}
        onClose={() => setTestResult(null)}
        title={`Ping Test Result: ${testResult?.model}`}
        maxWidth={500}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div
            style={{
              padding: '12px',
              backgroundColor: testResult?.ok ? 'var(--good-subtle)' : 'var(--danger-subtle)',
              border: `1px solid ${testResult?.ok ? 'var(--good-border)' : 'var(--danger-border)'}`,
              borderRadius: 'var(--radius-sm)',
              color: testResult?.ok ? 'var(--good-text)' : 'var(--danger-text)',
            }}
          >
            <div style={{ fontWeight: 600, fontSize: '14px', marginBottom: '4px', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Icon name={testResult?.ok ? 'check' : 'x'} size={15} />
              <span>{testResult?.ok ? 'Provider Responded Successfully' : 'Provider Test Failed'}</span>
            </div>
            {testResult?.latency_ms !== undefined && (
              <div style={{ fontSize: '12px' }}>Response Latency: {testResult.latency_ms}ms</div>
            )}
            <div style={{ fontSize: '12px', marginTop: '6px' }}>{testResult?.text}</div>
          </div>
        </div>
      </Modal>

      {/* Ollama Discovery Modal */}
      <Modal
        isOpen={Boolean(ollamaResult)}
        onClose={() => setOllamaResult(null)}
        title={`Ollama Local Models: ${ollamaResult?.model}`}
        maxWidth={500}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div style={{ fontSize: '13px' }}>
            {ollamaResult?.reachable ? (
              <div>
                <p style={{ color: 'var(--good-text)', fontWeight: 600, marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Icon name="check" size={14} />
                  <span>Ollama daemon is reachable (v{ollamaResult.version})</span>
                </p>
                <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '6px' }}>
                  Installed models on your computer:
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  {(ollamaResult.models || []).map((m) => (
                    <div
                      key={m}
                      style={{
                        padding: '6px 10px',
                        backgroundColor: 'var(--bg-card-subtle)',
                        borderRadius: 'var(--radius-xs)',
                        fontFamily: 'var(--font-mono)',
                        fontSize: '12px',
                      }}
                    >
                      {m}
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div style={{ color: 'var(--danger-text)' }}>
                {ollamaResult?.message || 'Could not connect to Ollama at http://127.0.0.1:11434'}
              </div>
            )}
          </div>
        </div>
      </Modal>

      {/* API Key Modal */}
      <Modal
        isOpen={keyModalOpen}
        onClose={() => setKeyModalOpen(false)}
        title={`Configure API Key: ${keyRef}`}
        maxWidth={480}
        footer={
          <>
            <button type="button" onClick={() => setKeyModalOpen(false)} className="btn btn-secondary">
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSaveKey}
              disabled={!keyValue.trim() || savingKey}
              className="btn btn-primary"
            >
              <span>{savingKey ? 'Storing...' : 'Save API Key'}</span>
            </button>
          </>
        }
      >
        <form onSubmit={handleSaveKey} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
            Paste the API key for <strong>{keyRef}</strong>. Keys are stored encrypted in the OS keychain or local secure vault and never logged.
          </p>
          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
              Secret Key
            </label>
            <input
              type="password"
              className="input"
              value={keyValue}
              onChange={(e) => setKeyValue(e.target.value)}
              placeholder="sk-..."
              autoFocus
              required
            />
          </div>
        </form>
      </Modal>

      {/* Add Custom Model Modal */}
      <Modal
        isOpen={customModelOpen}
        onClose={() => setCustomModelOpen(false)}
        title="Add Custom Model Connection"
        maxWidth={540}
        footer={
          <>
            <button type="button" onClick={() => setCustomModelOpen(false)} className="btn btn-secondary">
              Cancel
            </button>
            <button
              type="button"
              onClick={handleCreateCustomModel}
              disabled={!customName.trim() || !customModelId.trim() || addingModel}
              className="btn btn-primary"
            >
              <span>{addingModel ? 'Saving...' : 'Add Model'}</span>
            </button>
          </>
        }
      >
        <form onSubmit={handleCreateCustomModel} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
              Model Label *
            </label>
            <input
              className="input"
              value={customName}
              onChange={(e) => setCustomName(e.target.value)}
              placeholder="e.g. claude-3-5, deepseek-coder"
              required
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
            <div>
              <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
                Provider
              </label>
              <select
                className="select"
                value={customProvider}
                onChange={(e) => setCustomProvider(e.target.value)}
              >
                <option value="openai">OpenAI Compatible</option>
                <option value="mistral">Mistral AI</option>
                <option value="gemini">Google Gemini</option>
                <option value="openrouter">OpenRouter</option>
                <option value="ollama">Ollama Local</option>
                <option value="omniroute">OmniRoute Gateway</option>
              </select>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
                Model ID *
              </label>
              <input
                className="input"
                value={customModelId}
                onChange={(e) => setCustomModelId(e.target.value)}
                placeholder="e.g. gpt-4o, claude-3-5-sonnet"
                required
              />
            </div>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
              Base URL (Optional)
            </label>
            <input
              className="input"
              value={customBaseUrl}
              onChange={(e) => setCustomBaseUrl(e.target.value)}
              placeholder="e.g. https://api.openai.com/v1 or http://127.0.0.1:11434"
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
            <div>
              <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
                Key Ref in Vault (Optional)
              </label>
              <input
                className="input"
                value={customKeyRef}
                onChange={(e) => setCustomKeyRef(e.target.value)}
                placeholder="e.g. openai, mistral"
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
                Execution Lane
              </label>
              <select
                className="select"
                value={customLane}
                onChange={(e) => setCustomLane(Number(e.target.value))}
              >
                <option value={1}>Lane 1 (Priority / Interactive)</option>
                <option value={2}>Lane 2 (Standard / Workload)</option>
                <option value={3}>Lane 3 (Background / Batch)</option>
                <option value={4}>Lane 4 (Specialized / Heavy)</option>
                <option value={5}>Lane 5 (Custom High-Capacity)</option>
              </select>
            </div>
          </div>

          <div style={{ fontSize: '12px', padding: '10px 12px', background: 'var(--bg-card-subtle)', borderRadius: '6px', border: '1px solid var(--border-subtle)', marginTop: '4px' }}>
            {customProvider === 'ollama' ? (
              <span style={{ color: 'var(--success)' }}>
                ✓ Local engine: Ollama runs directly on this Mac; zero data leaves your machine (PERSONAL data permitted).
              </span>
            ) : (
              <span style={{ color: 'var(--text-muted)' }}>
                ℹ Cloud/Gateway provider: requests are sent over HTTPS under PUBLIC data policy. To use an entirely local offline LLM, select Ollama Local.
              </span>
            )}
          </div>
        </form>
      </Modal>
    </div>
  )
}
