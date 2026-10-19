import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { api, errorText } from '../api'
import { useLoad } from '../hooks'
import { useAppStore } from '../store'
import type { Thread, Message, Task, ExecutionTarget, RequestIntent, Agent, Approval } from '../types'
import { Icon } from '../ui/Icon'
import { TargetPill, StatePill, RiskPill } from '../ui/Pills'
import { Markdown } from '../ui/Markdown'

export const TalkView: React.FC = () => {
  const selectedThreadId = useAppStore((s) => s.selectedThreadId)
  const selectThread = useAppStore((s) => s.selectThread)
  const toast = useAppStore((s) => s.toast)
  const bump = useAppStore((s) => s.bump)

  // Load threads
  const { data: threadsData, reload: reloadThreads } = useLoad<{ threads: Thread[] }>('/api/threads', 4000)
  const threads = useMemo(() => threadsData?.threads || [], [threadsData])

  // Load available agents
  const { data: agentsData } = useLoad<{ agents: Agent[] }>('/api/agents')
  const agents = useMemo(() => agentsData?.agents || [], [agentsData])

  // Active thread details (messages, tasks)
  const [activeThread, setActiveThread] = useState<Thread | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [threadTasks, setThreadTasks] = useState<Task[]>([])
  const [pendingApprovals, setPendingApprovals] = useState<Approval[]>([])
  const [loadingMessages, setLoadingMessages] = useState(false)

  // Composer state
  const [prompt, setPrompt] = useState('')
  const [target, setTarget] = useState<ExecutionTarget>('host')
  const [intent, setIntent] = useState<RequestIntent>('AUTO')
  const [selectedAgentId, setSelectedAgentId] = useState<string>('')
  const [submitting, setSubmitting] = useState(false)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Sync selected thread
  const firstThreadId = threads[0]?.id
  useEffect(() => {
    if (!selectedThreadId && firstThreadId) {
      selectThread(firstThreadId)
    }
  }, [firstThreadId, selectedThreadId, selectThread])

  // Fetch thread conversation messages
  useEffect(() => {
    let active = true
    if (!selectedThreadId) return

    setLoadingMessages(true)
    api
      .get<{ thread: Thread; messages: Message[]; tasks: Task[] }>(`/api/threads/${selectedThreadId}`)
      .then((res) => {
        if (!active) return
        setActiveThread(res.thread)
        setMessages(res.messages || [])
        setThreadTasks(res.tasks || [])
      })
      .catch((err) => {
        if (!active) return
        toast(`Error loading thread: ${errorText(err)}`, 'bad')
      })
      .finally(() => {
        if (active) setLoadingMessages(false)
      })

    return () => {
      active = false
    }
  }, [selectedThreadId, toast])

  // Also check for pending approvals
  const loadApprovals = useCallback(async () => {
    try {
      const res = await api.get<{ approvals: Approval[] }>('/api/approvals?status=pending')
      setPendingApprovals(res.approvals || [])
    } catch {
      // ignore
    }
  }, [])

  useEffect(() => {
    void loadApprovals()
    const id = setInterval(loadApprovals, 3000)
    return () => clearInterval(id)
  }, [loadApprovals])

  // Auto-scroll on new message
  useEffect(() => {
    if (messages.length > 0 || threadTasks.length > 0) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages.length, threadTasks.length])

  const handleNewThread = () => {
    selectThread(null)
    setActiveThread(null)
    setMessages([])
    setThreadTasks([])
    textareaRef.current?.focus()
  }

  const handleDeleteThread = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm('Are you sure you want to delete this conversation?')) return
    try {
      await api.delete(`/api/threads/${id}`)
      toast('Conversation deleted', 'good')
      await reloadThreads()
      if (selectedThreadId === id) {
        selectThread(null)
      }
    } catch (err) {
      toast(`Cannot delete thread: ${errorText(err)}`, 'bad')
    }
  }

  const handleSubmit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    const goal = prompt.trim()
    if (!goal || submitting) return

    setSubmitting(true)
    try {
      const payload = {
        goal,
        conversation_id: selectedThreadId || undefined,
        target,
        intent,
        agent_id: selectedAgentId || undefined,
      }
      const res = await api.post<{ task: Task }>('/api/tasks', payload)
      setPrompt('')
      bump()

      // Optimistically append user message and refresh thread
      if (selectedThreadId) {
        const reloadRes = await api.get<{ thread: Thread; messages: Message[]; tasks: Task[] }>(
          `/api/threads/${selectedThreadId}`
        )
        setMessages(reloadRes.messages || [])
        setThreadTasks(reloadRes.tasks || [])
      } else if (res.task.conversation_id) {
        selectThread(res.task.conversation_id)
        await reloadThreads()
      }
    } catch (err) {
      toast(`Failed to submit: ${errorText(err)}`, 'bad')
    } finally {
      setSubmitting(false)
    }
  }

  const handleApprove = async (approval: Approval, approve: boolean) => {
    try {
      await api.post(`/api/approvals/${approval.id}/decide`, {
        approve,
        payload_hash: approval.payload_hash,
        decline_reason: approve ? undefined : 'Declined in talk view',
      })
      toast(approve ? 'Action approved' : 'Action declined', approve ? 'good' : 'warn')
      bump()
      await loadApprovals()
    } catch (err) {
      toast(`Decision failed: ${errorText(err)}`, 'bad')
    }
  }

  return (
    <div className="talk-layout">
      {/* Threads Sidebar */}
      <div className="talk-threads-pane">
        <div className="threads-header">
          <span style={{ fontWeight: 600, fontSize: '13px', color: 'var(--text-main)' }}>
            Conversations
          </span>
          <button
            onClick={handleNewThread}
            className="btn btn-secondary btn-sm"
            type="button"
            title="Start new thread"
          >
            <Icon name="plus" size={14} />
            <span>New</span>
          </button>
        </div>

        <div className="threads-list">
          {threads.length === 0 ? (
            <div style={{ padding: '20px 12px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '12px' }}>
              No conversations yet. Start one!
            </div>
          ) : (
            threads.map((th) => {
              const active = th.id === selectedThreadId
              return (
                <div
                  key={th.id}
                  onClick={() => selectThread(th.id)}
                  className={`thread-item ${active ? 'active' : ''}`}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflow: 'hidden' }}>
                    <Icon name="chat" size={14} style={{ color: active ? 'var(--primary)' : 'var(--text-muted)', flexShrink: 0 }} />
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {th.title || 'Untitled conversation'}
                    </span>
                  </div>
                  <button
                    onClick={(e) => handleDeleteThread(th.id, e)}
                    className="btn btn-ghost btn-sm btn-icon"
                    style={{ padding: '2px', opacity: active ? 1 : 0.4 }}
                    title="Delete thread"
                    type="button"
                  >
                    <Icon name="trash" size={12} />
                  </button>
                </div>
              )
            })
          )}
        </div>
      </div>

      {/* Main Conversation Pane */}
      <div className="talk-conversation-pane">
        {/* Top Control Bar */}
        <div className="app-topbar" style={{ backgroundColor: 'var(--bg-card)' }}>
          <div className="topbar-left">
            <h2 className="page-title">{activeThread?.title || 'Talk with Lilly'}</h2>
            <TargetPill target={target} size="sm" />
          </div>

          <div className="topbar-right">
            {/* Agent picker */}
            {agents.length > 0 && (
              <select
                className="select"
                style={{ width: 'auto', padding: '4px 8px', fontSize: '12px' }}
                value={selectedAgentId}
                onChange={(e) => setSelectedAgentId(e.target.value)}
                title="Select agent persona"
              >
                <option value="">Lilly (Default)</option>
                {agents.map((ag) => (
                  <option key={ag.id} value={ag.id}>
                    {ag.name}
                  </option>
                ))}
              </select>
            )}

            {/* Target Selector Button */}
            <div
              className="filter-tabs"
              style={{ padding: '2px' }}
              title="Switch execution target (Host laptop vs DevBox sandbox)"
            >
              <button
                type="button"
                className={`filter-tab ${target === 'host' ? 'active' : ''}`}
                onClick={() => setTarget('host')}
              >
                Host
              </button>
              <button
                type="button"
                className={`filter-tab ${target === 'devbox' ? 'active' : ''}`}
                onClick={() => setTarget('devbox')}
              >
                DevBox
              </button>
            </div>
          </div>
        </div>

        {/* Messages & Execution Flow */}
        <div className="chat-messages-container">
          {loadingMessages ? (
            <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
              Loading conversation...
            </div>
          ) : messages.length === 0 && threadTasks.length === 0 ? (
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                margin: 'auto',
                maxWidth: '540px',
                textAlign: 'center',
                gap: '16px',
                padding: '40px 20px',
              }}
            >
              <div
                style={{
                  width: '56px',
                  height: '56px',
                  borderRadius: 'var(--radius-lg)',
                  background: 'linear-gradient(135deg, #4f46e5 0%, #06b6d4 100%)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: '#fff',
                  boxShadow: 'var(--shadow-md)',
                }}
              >
                <Icon name="sparkles" size={28} />
              </div>
              <h3 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--text-main)' }}>
                How can Lilly help you today?
              </h3>
              <p style={{ fontSize: '13px', color: 'var(--text-muted)', lineHeight: 1.5 }}>
                Directly interact with your laptop runtime, automate workflows, execute in isolated
                DevBox containers, manage scheduled routines, or ask anything.
              </p>

              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                  gap: '8px',
                  width: '100%',
                  marginTop: '12px',
                }}
              >
                {[
                  'Inspect workspace and summarize status',
                  'Run test suite in DevBox sandbox',
                  'Schedule routine to clean temporary logs',
                  'Show active CPU & memory telemetry',
                ].map((promptText, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => {
                      setPrompt(promptText)
                      textareaRef.current?.focus()
                    }}
                    className="card card-subtle"
                    style={{
                      cursor: 'pointer',
                      textAlign: 'left',
                      fontSize: '12px',
                      color: 'var(--text-main)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                    }}
                  >
                    <span>{promptText}</span>
                    <Icon name="chevron-right" size={12} style={{ color: 'var(--text-muted)' }} />
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              {/* Render thread messages */}
              {messages.map((m) => {
                const isUser = m.role === 'user'
                return (
                  <div key={m.id} className={`chat-bubble-wrapper ${isUser ? 'user' : 'assistant'}`}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px', fontSize: '11px', color: 'var(--text-dim)' }}>
                      <Icon name={isUser ? 'user' : 'bot'} size={12} />
                      <span>{isUser ? 'You' : 'Lilly'}</span>
                    </div>
                    <div className={`chat-bubble ${isUser ? 'user' : 'assistant'}`}>
                      <Markdown content={m.content} />
                    </div>
                  </div>
                )
              })}

              {/* Render thread tasks */}
              {threadTasks.map((t) => {
                const taskPendingApproval = pendingApprovals.filter((a) => a.task_id === t.id)
                return (
                  <div key={t.id} className="chat-bubble-wrapper assistant">
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px', fontSize: '11px', color: 'var(--text-dim)' }}>
                      <StatePill state={t.state} />
                      <TargetPill target={t.target} size="sm" />
                      <span>Task {t.id.slice(0, 8)}</span>
                    </div>

                    <div className="card" style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                      <div style={{ fontWeight: 600, fontSize: '14px', color: 'var(--text-main)' }}>
                        {t.goal}
                      </div>

                      {t.answer && (
                        <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: '10px' }}>
                          <Markdown content={t.answer} />
                        </div>
                      )}

                      {t.error && (
                        <div
                          style={{
                            padding: '8px 12px',
                            backgroundColor: 'var(--danger-subtle)',
                            border: '1px solid var(--danger-border)',
                            borderRadius: 'var(--radius-sm)',
                            color: 'var(--danger-text)',
                            fontSize: '12px',
                          }}
                        >
                          {t.error}
                        </div>
                      )}

                      {/* Inline Approvals required for this task */}
                      {taskPendingApproval.length > 0 && (
                        <div
                          style={{
                            marginTop: '8px',
                            padding: '12px',
                            backgroundColor: 'var(--warning-subtle)',
                            border: '1px solid var(--warning-border)',
                            borderRadius: 'var(--radius-sm)',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '8px',
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                              <Icon name="alert-triangle" size={16} style={{ color: 'var(--warning-text)' }} />
                              <span style={{ fontWeight: 600, fontSize: '12px', color: 'var(--warning-text)' }}>
                                Security Approval Required
                              </span>
                            </div>
                            <RiskPill risk={taskPendingApproval[0].risk} />
                          </div>

                          <div style={{ fontSize: '12px', color: 'var(--warning-text)' }}>
                            Tool: <strong>{taskPendingApproval[0].tool}</strong> — {taskPendingApproval[0].why}
                          </div>

                          <div style={{ display: 'flex', gap: '8px', marginTop: '4px' }}>
                            <button
                              type="button"
                              onClick={() => handleApprove(taskPendingApproval[0], true)}
                              className="btn btn-primary btn-sm"
                            >
                              <Icon name="check" size={12} />
                              <span>Approve Execution</span>
                            </button>
                            <button
                              type="button"
                              onClick={() => handleApprove(taskPendingApproval[0], false)}
                              className="btn btn-secondary btn-sm"
                            >
                              <Icon name="x" size={12} />
                              <span>Decline</span>
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Bottom Composer */}
        <div className="chat-composer-box">
          <div className="composer-toolbar">
            <div className="composer-controls">
              {/* Intent Selector */}
              <select
                className="select"
                style={{ width: 'auto', padding: '3px 8px', fontSize: '11px' }}
                value={intent}
                onChange={(e) => setIntent(e.target.value as RequestIntent)}
                title="Execution intent"
              >
                <option value="AUTO">Intent: Auto</option>
                <option value="ANSWER">Intent: Answer Only</option>
                <option value="WEB RETRIEVE">Intent: Web Retrieve</option>
                <option value="NAVIGATE">Intent: Navigate</option>
                <option value="ACTION">Intent: Action</option>
              </select>

              <button
                type="button"
                onClick={() => setTarget(target === 'host' ? 'devbox' : 'host')}
                className="btn btn-ghost btn-sm"
                title="Click to toggle execution target"
              >
                <TargetPill target={target} size="sm" />
              </button>
            </div>

            <span style={{ fontSize: '11px', color: 'var(--text-dim)' }}>
              Press <strong>Return</strong> to send, <strong>Shift+Return</strong> for new line
            </span>
          </div>

          <div className="composer-input-row">
            <textarea
              ref={textareaRef}
              className="composer-textarea"
              placeholder="Ask Lilly anything or describe a task..."
              rows={1}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  void handleSubmit()
                }
              }}
            />

            <button
              type="button"
              onClick={() => void handleSubmit()}
              disabled={!prompt.trim() || submitting}
              className="btn btn-primary btn-sm btn-icon"
              style={{ width: '32px', height: '32px', borderRadius: 'var(--radius-sm)' }}
              title="Submit task"
            >
              <Icon name={submitting ? 'refresh' : 'play'} size={14} />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
