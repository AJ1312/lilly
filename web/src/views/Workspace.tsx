import React, { useState, useEffect, useMemo } from 'react'
import { api, errorText } from '../api'
import { useLoad, useDebounce } from '../hooks'
import { useAppStore } from '../store'
import type { Task, TaskDetail, ExecutionTarget } from '../types'
import { Icon } from '../ui/Icon'
import { TargetPill, StatePill, OutcomePill } from '../ui/Pills'
import { Markdown } from '../ui/Markdown'
import { ReceiptViewer } from '../ui/ReceiptViewer'
import { Modal } from '../ui/Modal'

export const WorkspaceView: React.FC = () => {
  const selectedTaskId = useAppStore((s) => s.selectedTaskId)
  const selectTask = useAppStore((s) => s.selectTask)
  const toast = useAppStore((s) => s.toast)
  const bump = useAppStore((s) => s.bump)

  // Filters
  const [search, setSearch] = useState('')
  const debouncedSearch = useDebounce(search, 300)
  const [filterTab, setFilterTab] = useState<'all' | 'active' | 'approval' | 'done' | 'failed'>('all')
  const [targetFilter, setTargetFilter] = useState<'all' | 'host' | 'devbox'>('all')

  // Modals
  const [receiptTaskId, setReceiptTaskId] = useState<string | null>(null)
  const [newTaskOpen, setNewTaskOpen] = useState(false)
  const [newTaskGoal, setNewTaskGoal] = useState('')
  const [newTaskTarget, setNewTaskTarget] = useState<ExecutionTarget>('host')
  const [submittingNewTask, setSubmittingNewTask] = useState(false)

  // Construct query url
  let url = '/api/tasks?limit=50'
  if (debouncedSearch) url += `&q=${encodeURIComponent(debouncedSearch)}`
  if (filterTab === 'active') url += '&state=RUNNING,PLANNING,VERIFYING'
  else if (filterTab === 'approval') url += '&state=WAITING_APPROVAL'
  else if (filterTab === 'done') url += '&state=DONE'
  else if (filterTab === 'failed') url += '&state=FAILED,CANCELLED,EXPIRED'
  if (targetFilter !== 'all') url += `&target=${targetFilter}`

  const { data: tasksData, loading, reload } = useLoad<{ tasks: Task[]; total?: number }>(url, 4000)
  const tasks = useMemo(() => tasksData?.tasks || [], [tasksData])

  // Active Task Detail
  const [taskDetail, setTaskDetail] = useState<TaskDetail | null>(null)
  const [taskEvents, setTaskEvents] = useState<any[]>([])
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailTab, setDetailTab] = useState<'overview' | 'steps' | 'events'>('overview')

  // Auto-select first task if none selected
  const firstTaskId = tasks[0]?.id
  useEffect(() => {
    if (!selectedTaskId && firstTaskId) {
      selectTask(firstTaskId)
    }
  }, [firstTaskId, selectedTaskId, selectTask])

  // Load task details
  useEffect(() => {
    let active = true
    if (!selectedTaskId) return

    setDetailLoading(true)
    Promise.all([
      api.get<{ task: Task; steps: any[]; plan_steps: any[]; approvals?: any[]; reply_check?: any }>(
        `/api/tasks/${selectedTaskId}`
      ),
      api.get<{ events: any[] }>(`/api/tasks/${selectedTaskId}/events`).catch(() => ({ events: [] })),
    ])
      .then(([res, evRes]) => {
        if (!active) return
        setTaskDetail({
          task: res.task,
          steps: res.steps || [],
          approvals: res.approvals || [],
          plan_steps: (res.plan_steps || []).map((s: any, idx: number) => ({
            id: s.id || `plan_${idx}`,
            tool: s.tool || 'step',
            why: s.why || '',
            args: s.args || {},
            expect: s.expect || '',
            deps: s.deps || [],
            verdict: s.verdict,
          })),
          reply_check: res.reply_check,
        })
        setTaskEvents(evRes.events || [])
      })
      .catch((err) => {
        if (!active) return
        toast(`Error loading task: ${errorText(err)}`, 'bad')
      })
      .finally(() => {
        if (active) setDetailLoading(false)
      })

    return () => {
      active = false
    }
  }, [selectedTaskId, toast])

  const handleCancelTask = async (id: string) => {
    try {
      await api.post(`/api/tasks/${id}/cancel`)
      toast('Task cancellation sent', 'warn')
      bump()
      await reload()
    } catch (err) {
      toast(`Cancel failed: ${errorText(err)}`, 'bad')
    }
  }

  const handleResumeTask = async (id: string) => {
    try {
      await api.post(`/api/tasks/${id}/resume`, { confirm_ambiguous: true })
      toast('Task resumed/redriven', 'good')
      bump()
      await reload()
    } catch (err) {
      toast(`Resume failed: ${errorText(err)}`, 'bad')
    }
  }

  const handleCreateNewTask = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newTaskGoal.trim()) return

    setSubmittingNewTask(true)
    try {
      const res = await api.post<{ task: Task }>('/api/tasks', {
        goal: newTaskGoal.trim(),
        target: newTaskTarget,
      })
      toast('Task created successfully', 'good')
      setNewTaskOpen(false)
      setNewTaskGoal('')
      selectTask(res.task.id)
      bump()
      await reload()
    } catch (err) {
      toast(`Failed to create task: ${errorText(err)}`, 'bad')
    } finally {
      setSubmittingNewTask(false)
    }
  }

  const activeTask = taskDetail?.task

  return (
    <div className="workspace-layout">
      {/* Task List Pane */}
      <div className="tasks-pane">
        <div className="tasks-toolbar">
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1, maxWidth: '420px' }}>
            <div style={{ position: 'relative', width: '100%' }}>
              <Icon
                name="search"
                size={14}
                style={{ position: 'absolute', left: '10px', top: '10px', color: 'var(--text-muted)' }}
              />
              <input
                className="input"
                style={{ paddingLeft: '30px', fontSize: '12px' }}
                placeholder="Search tasks by goal or ID..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>

            <div className="filter-tabs">
              <button
                type="button"
                className={`filter-tab ${filterTab === 'all' ? 'active' : ''}`}
                onClick={() => setFilterTab('all')}
              >
                All
              </button>
              <button
                type="button"
                className={`filter-tab ${filterTab === 'active' ? 'active' : ''}`}
                onClick={() => setFilterTab('active')}
              >
                Active
              </button>
              <button
                type="button"
                className={`filter-tab ${filterTab === 'approval' ? 'active' : ''}`}
                onClick={() => setFilterTab('approval')}
              >
                Approvals
              </button>
              <button
                type="button"
                className={`filter-tab ${filterTab === 'done' ? 'active' : ''}`}
                onClick={() => setFilterTab('done')}
              >
                Done
              </button>
              <button
                type="button"
                className={`filter-tab ${filterTab === 'failed' ? 'active' : ''}`}
                onClick={() => setFilterTab('failed')}
              >
                Failed
              </button>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <div className="filter-tabs">
              <button
                type="button"
                className={`filter-tab ${targetFilter === 'all' ? 'active' : ''}`}
                onClick={() => setTargetFilter('all')}
              >
                All
              </button>
              <button
                type="button"
                className={`filter-tab ${targetFilter === 'host' ? 'active' : ''}`}
                onClick={() => setTargetFilter('host')}
              >
                Host
              </button>
              <button
                type="button"
                className={`filter-tab ${targetFilter === 'devbox' ? 'active' : ''}`}
                onClick={() => setTargetFilter('devbox')}
              >
                DevBox
              </button>
            </div>

            <button
              onClick={() => setNewTaskOpen(true)}
              className="btn btn-primary btn-sm"
              type="button"
            >
              <Icon name="plus" size={14} />
              <span>New Task</span>
            </button>
          </div>
        </div>

        {/* Task Table */}
        <div className="tasks-table-container">
          {loading && tasks.length === 0 ? (
            <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
              Loading workspace tasks...
            </div>
          ) : tasks.length === 0 ? (
            <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
              No tasks found matching filter.
            </div>
          ) : (
            <div>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: '36px 1fr 100px 90px 100px 100px',
                  padding: '8px 16px',
                  borderBottom: '1px solid var(--border)',
                  fontSize: '11px',
                  fontWeight: 600,
                  color: 'var(--text-dim)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.04em',
                  backgroundColor: 'var(--bg-card-subtle)',
                }}
              >
                <span>#</span>
                <span>Goal</span>
                <span>Target</span>
                <span>State</span>
                <span>Outcome</span>
                <span>Duration</span>
              </div>

              {tasks.map((t, idx) => {
                const isSelected = t.id === selectedTaskId
                return (
                  <div
                    key={t.id}
                    className={`task-row ${isSelected ? 'selected' : ''}`}
                    onClick={() => selectTask(t.id)}
                  >
                    <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                      {idx + 1}
                    </span>
                    <span
                      style={{
                        fontWeight: 500,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                        paddingRight: '12px',
                        color: 'var(--text-main)',
                      }}
                    >
                      {t.goal}
                    </span>
                    <div>
                      <TargetPill target={t.target} size="sm" />
                    </div>
                    <div>
                      <StatePill state={t.state} />
                    </div>
                    <div>
                      <OutcomePill outcome={t.outcome} />
                    </div>
                    <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                      {t.duration_s !== undefined ? `${t.duration_s.toFixed(1)}s` : '—'}
                    </span>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* Task Detail Inspector Pane */}
      {selectedTaskId && (
        <div className="task-detail-pane">
          {detailLoading && !taskDetail ? (
            <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
              Loading task details...
            </div>
          ) : activeTask ? (
            <>
              <div className="task-detail-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <StatePill state={activeTask.state} />
                  <TargetPill target={activeTask.target} size="sm" />
                  <OutcomePill outcome={activeTask.outcome} />
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  {(activeTask.state === 'RUNNING' ||
                    activeTask.state === 'PLANNING' ||
                    activeTask.state === 'VERIFYING') && (
                    <button
                      type="button"
                      onClick={() => handleCancelTask(activeTask.id)}
                      className="btn btn-danger btn-sm"
                      title="Cancel active execution"
                    >
                      <Icon name="x" size={12} />
                      <span>Cancel</span>
                    </button>
                  )}

                  {(activeTask.state === 'FAILED' || activeTask.state === 'CANCELLED') && (
                    <button
                      type="button"
                      onClick={() => handleResumeTask(activeTask.id)}
                      className="btn btn-secondary btn-sm"
                      title="Resume/redrive task"
                    >
                      <Icon name="refresh" size={12} />
                      <span>Resume</span>
                    </button>
                  )}

                  <button
                    type="button"
                    onClick={() => setReceiptTaskId(activeTask.id)}
                    className="btn btn-ghost btn-sm"
                    title="View cryptographic verification receipt"
                  >
                    <Icon name="shield" size={14} />
                    <span>Receipt</span>
                  </button>
                </div>
              </div>

              <div style={{ padding: '0 20px', borderBottom: '1px solid var(--border)' }}>
                <div className="filter-tabs" style={{ background: 'transparent', padding: '6px 0' }}>
                  <button
                    type="button"
                    className={`filter-tab ${detailTab === 'overview' ? 'active' : ''}`}
                    onClick={() => setDetailTab('overview')}
                  >
                    Overview
                  </button>
                  <button
                    type="button"
                    className={`filter-tab ${detailTab === 'steps' ? 'active' : ''}`}
                    onClick={() => setDetailTab('steps')}
                  >
                    Steps ({taskDetail?.steps?.length || 0})
                  </button>
                  <button
                    type="button"
                    className={`filter-tab ${detailTab === 'events' ? 'active' : ''}`}
                    onClick={() => setDetailTab('events')}
                  >
                    Events ({taskEvents.length})
                  </button>
                </div>
              </div>

              <div className="task-detail-body">
                {detailTab === 'overview' && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                    <div>
                      <div style={{ fontSize: '11px', color: 'var(--text-dim)', textTransform: 'uppercase', fontWeight: 600, marginBottom: '6px' }}>
                        Goal
                      </div>
                      <div style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-main)', lineHeight: 1.4 }}>
                        {activeTask.goal}
                      </div>
                    </div>

                    {activeTask.answer && (
                      <div className="card">
                        <div style={{ fontSize: '11px', color: 'var(--text-dim)', textTransform: 'uppercase', fontWeight: 600, marginBottom: '8px' }}>
                          Answer / Output
                        </div>
                        <Markdown content={activeTask.answer} />
                      </div>
                    )}

                    {activeTask.error && (
                      <div
                        style={{
                          padding: '12px',
                          backgroundColor: 'var(--danger-subtle)',
                          border: '1px solid var(--danger-border)',
                          borderRadius: 'var(--radius-sm)',
                          color: 'var(--danger-text)',
                          fontSize: '12px',
                        }}
                      >
                        <div style={{ fontWeight: 600, marginBottom: '4px' }}>Execution Error</div>
                        <div>{activeTask.error}</div>
                      </div>
                    )}

                    <div className="card card-subtle" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                      <div>
                        <div style={{ fontSize: '11px', color: 'var(--text-dim)' }}>Task ID</div>
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', marginTop: '2px' }}>
                          {activeTask.id}
                        </div>
                      </div>
                      <div>
                        <div style={{ fontSize: '11px', color: 'var(--text-dim)' }}>Execution Target</div>
                        <div style={{ marginTop: '2px' }}>
                          <TargetPill target={activeTask.target} size="sm" />
                        </div>
                      </div>
                      <div>
                        <div style={{ fontSize: '11px', color: 'var(--text-dim)' }}>Duration</div>
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', marginTop: '2px' }}>
                          {activeTask.duration_s !== undefined ? `${activeTask.duration_s.toFixed(2)}s` : '—'}
                        </div>
                      </div>
                      <div>
                        <div style={{ fontSize: '11px', color: 'var(--text-dim)' }}>Tokens Used</div>
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', marginTop: '2px' }}>
                          {activeTask.tokens_used ?? '—'}
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {detailTab === 'steps' && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {taskDetail?.steps?.length === 0 ? (
                      <div style={{ color: 'var(--text-muted)', fontSize: '13px', textAlign: 'center', padding: '24px' }}>
                        No execution steps recorded yet.
                      </div>
                    ) : (
                      taskDetail?.steps?.map((st) => (
                        <div key={st.id} className="card card-subtle" style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontFamily: 'var(--font-mono)', fontSize: '13px', fontWeight: 600 }}>
                              <Icon name="terminal" size={14} style={{ color: 'var(--primary)' }} />
                              <span>{st.tool}</span>
                            </div>
                            <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                              {st.duration_s ? `${st.duration_s.toFixed(2)}s` : st.status}
                            </span>
                          </div>

                          {st.args && Object.keys(st.args).length > 0 && (
                            <div
                              style={{
                                backgroundColor: 'var(--bg-input)',
                                padding: '6px 8px',
                                borderRadius: 'var(--radius-xs)',
                                fontSize: '11px',
                                fontFamily: 'var(--font-mono)',
                                overflowX: 'auto',
                                maxWidth: '100%',
                                minWidth: 0,
                              }}
                            >
                              <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                                {JSON.stringify(st.args, null, 2)}
                              </pre>
                            </div>
                          )}

                          {(() => {
                            const outputVal = (st as any).output !== undefined ? (st as any).output : st.result
                            if (outputVal === undefined) return null
                            return (
                              <div
                                style={{
                                  backgroundColor: 'var(--bg-card)',
                                  padding: '6px 8px',
                                  borderRadius: 'var(--radius-xs)',
                                  fontSize: '11px',
                                  fontFamily: 'var(--font-mono)',
                                  overflowX: 'auto',
                                  maxHeight: '140px',
                                  border: '1px solid var(--border-subtle)',
                                  maxWidth: '100%',
                                  minWidth: 0,
                                }}
                              >
                                <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                                  {typeof outputVal === 'string' ? outputVal : JSON.stringify(outputVal, null, 2)}
                                </pre>
                              </div>
                            )
                          })()}
                        </div>
                      ))
                    )}
                  </div>
                )}

                {detailTab === 'events' && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {taskEvents.length === 0 ? (
                      <div style={{ color: 'var(--text-muted)', fontSize: '13px', textAlign: 'center', padding: '24px' }}>
                        No audit events recorded for this task.
                      </div>
                    ) : (
                      taskEvents.map((ev, idx) => (
                        <div key={idx} style={{ padding: '8px 12px', borderLeft: '2px solid var(--primary)', backgroundColor: 'var(--bg-card-subtle)', borderRadius: 'var(--radius-xs)', fontSize: '12px' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-dim)', fontSize: '10px', marginBottom: '2px' }}>
                            <span>{ev.actor}</span>
                            <span>{new Date(ev.ts * 1000).toLocaleTimeString()}</span>
                          </div>
                          <div style={{ fontWeight: 600, color: 'var(--text-main)' }}>{ev.type}</div>
                          {ev.payload && (
                            <pre style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)', margin: '4px 0 0 0', overflowX: 'auto' }}>
                              {JSON.stringify(ev.payload, null, 2)}
                            </pre>
                          )}
                        </div>
                      ))
                    )}
                  </div>
                )}
              </div>
            </>
          ) : null}
        </div>
      )}

      {/* Verification Receipt Modal */}
      <ReceiptViewer taskId={receiptTaskId} onClose={() => setReceiptTaskId(null)} />

      {/* New Task Dialog */}
      <Modal
        isOpen={newTaskOpen}
        onClose={() => setNewTaskOpen(false)}
        title="Create New Task"
        footer={
          <>
            <button
              type="button"
              onClick={() => setNewTaskOpen(false)}
              className="btn btn-secondary"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleCreateNewTask}
              disabled={!newTaskGoal.trim() || submittingNewTask}
              className="btn btn-primary"
            >
              <span>{submittingNewTask ? 'Creating...' : 'Create & Run'}</span>
            </button>
          </>
        }
      >
        <form onSubmit={handleCreateNewTask} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '6px' }}>
              Goal / Instruction
            </label>
            <textarea
              className="textarea"
              placeholder="e.g. Inspect tests and fix any resource leaks..."
              rows={4}
              value={newTaskGoal}
              onChange={(e) => setNewTaskGoal(e.target.value)}
              required
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '6px' }}>
              Execution Target
            </label>
            <div style={{ display: 'flex', gap: '10px' }}>
              <label
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  cursor: 'pointer',
                  fontSize: '13px',
                }}
              >
                <input
                  type="radio"
                  name="newTaskTarget"
                  checked={newTaskTarget === 'host'}
                  onChange={() => setNewTaskTarget('host')}
                />
                <span>Host (This Laptop)</span>
              </label>

              <label
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  cursor: 'pointer',
                  fontSize: '13px',
                }}
              >
                <input
                  type="radio"
                  name="newTaskTarget"
                  checked={newTaskTarget === 'devbox'}
                  onChange={() => setNewTaskTarget('devbox')}
                />
                <span>DevBox (Isolated Sandbox)</span>
              </label>
            </div>
          </div>
        </form>
      </Modal>
    </div>
  )
}
