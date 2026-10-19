import React, { useState } from 'react'
import { api, errorText } from '../api'
import { useLoad } from '../hooks'
import { useAppStore } from '../store'
import type { Skill, ExecutionTarget, Task } from '../types'
import { Icon } from '../ui/Icon'
import { RiskPill } from '../ui/Pills'
import { Modal } from '../ui/Modal'

export const SkillsView: React.FC = () => {
  const toast = useAppStore((s) => s.toast)
  const setSection = useAppStore((s) => s.setSection)
  const selectTask = useAppStore((s) => s.selectTask)
  const bump = useAppStore((s) => s.bump)

  const { data, loading } = useLoad<{ skills: Skill[] }>('/api/skills')
  const skills = data?.skills || []

  const [selectedSkill, setSelectedSkill] = useState<Skill | null>(null)
  const [params, setParams] = useState<Record<string, string>>({})
  const [target, setTarget] = useState<ExecutionTarget>('host')
  const [running, setRunning] = useState(false)

  const handleOpenRunner = (skill: Skill) => {
    setSelectedSkill(skill)
    const initialParams: Record<string, string> = {}
    skill.params.forEach((p) => {
      initialParams[p] = ''
    })
    setParams(initialParams)
  }

  const handleExecuteSkill = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedSkill) return

    setRunning(true)
    try {
      const res = await api.post<{ task: Task }>('/api/tasks', {
        skill: selectedSkill.name,
        params,
        target,
        goal: `Execute skill ${selectedSkill.name}`,
      })
      toast(`Skill ${selectedSkill.name} dispatched`, 'good')
      setSelectedSkill(null)
      bump()
      selectTask(res.task.id)
      setSection('workspace')
    } catch (err) {
      toast(`Failed to run skill: ${errorText(err)}`, 'bad')
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="view-container" style={{ padding: '24px' }}>
      <div style={{ marginBottom: '24px' }}>
        <h2 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--text-main)' }}>Skills Catalog</h2>
        <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
          High-level capability primitives for terminal execution, file inspection, web retrieval, and desktop actions.
        </p>
      </div>

      {loading && skills.length === 0 ? (
        <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
          Loading skills...
        </div>
      ) : skills.length === 0 ? (
        <div className="card" style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
          No skills registered in the engine.
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '16px' }}>
          {skills.map((skill) => (
            <div key={skill.name} className="card" style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <h3 style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-main)', fontFamily: 'var(--font-mono)' }}>
                    {skill.name}
                  </h3>
                </div>
                <RiskPill risk={skill.risk} />
              </div>

              <div style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.5, flex: 1 }}>
                {skill.summary}
              </div>

              {skill.params && skill.params.length > 0 && (
                <div>
                  <div style={{ fontSize: '11px', color: 'var(--text-dim)', textTransform: 'uppercase', marginBottom: '4px', fontWeight: 600 }}>
                    Parameters
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                    {skill.params.map((p) => (
                      <span
                        key={p}
                        style={{
                          fontSize: '11px',
                          fontFamily: 'var(--font-mono)',
                          padding: '2px 6px',
                          borderRadius: 'var(--radius-xs)',
                          backgroundColor: 'var(--bg-card-subtle)',
                          color: 'var(--text-muted)',
                        }}
                      >
                        {p}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <div style={{ paddingTop: '8px', borderTop: '1px solid var(--border-subtle)', marginTop: 'auto' }}>
                <button
                  type="button"
                  onClick={() => handleOpenRunner(skill)}
                  className="btn btn-secondary btn-sm"
                  style={{ width: '100%' }}
                >
                  <Icon name="play" size={12} />
                  <span>Run Skill</span>
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Dynamic Skill Runner Modal */}
      <Modal
        isOpen={Boolean(selectedSkill)}
        onClose={() => setSelectedSkill(null)}
        title={`Execute Skill: ${selectedSkill?.name}`}
        maxWidth={520}
        footer={
          <>
            <button type="button" onClick={() => setSelectedSkill(null)} className="btn btn-secondary">
              Cancel
            </button>
            <button
              type="button"
              onClick={handleExecuteSkill}
              disabled={running}
              className="btn btn-primary"
            >
              <span>{running ? 'Launching...' : 'Run Skill'}</span>
            </button>
          </>
        }
      >
        {selectedSkill && (
          <form onSubmit={handleExecuteSkill} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
              {selectedSkill.summary}
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, marginBottom: '6px' }}>
                Execution Target
              </label>
              <div style={{ display: 'flex', gap: '12px' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', cursor: 'pointer' }}>
                  <input
                    type="radio"
                    name="skillTarget"
                    checked={target === 'host'}
                    onChange={() => setTarget('host')}
                  />
                  <span>Host (This Laptop)</span>
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', cursor: 'pointer' }}>
                  <input
                    type="radio"
                    name="skillTarget"
                    checked={target === 'devbox'}
                    onChange={() => setTarget('devbox')}
                  />
                  <span>DevBox (Container)</span>
                </label>
              </div>
            </div>

            {selectedSkill.params.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <div style={{ fontSize: '12px', fontWeight: 600 }}>Parameters</div>
                {selectedSkill.params.map((paramName) => (
                  <div key={paramName}>
                    <label style={{ display: 'block', fontSize: '11px', fontFamily: 'var(--font-mono)', marginBottom: '4px', color: 'var(--text-muted)' }}>
                      {paramName}
                    </label>
                    <input
                      className="input"
                      value={params[paramName] || ''}
                      onChange={(e) => setParams({ ...params, [paramName]: e.target.value })}
                      placeholder={`Enter ${paramName}...`}
                      required
                    />
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ fontSize: '12px', color: 'var(--text-dim)' }}>
                This skill requires no additional parameters.
              </div>
            )}
          </form>
        )}
      </Modal>
    </div>
  )
}
