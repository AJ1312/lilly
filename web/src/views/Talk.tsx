import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { api, errorText } from '../api'
import { useLoad } from '../hooks'
import { useAppStore } from '../store'
import type { Thread, Message, Task, ExecutionTarget, Agent, Approval, Capacity, ApprovalMode, Settings } from '../types'
import { Icon } from '../ui/Icon'
import { TargetPill, StatePill } from '../ui/Pills'
import { Markdown } from '../ui/Markdown'
import { AgentPet } from '../ui/AgentPet'

interface QuickPromptCard {
  tag: string
  color: 'peach' | 'lime' | 'periwinkle' | 'mint' | 'lilac'
  title: string
  prompt: string
  target: ExecutionTarget
}

const QUICK_CARDS: QuickPromptCard[] = [
  {
    tag: 'Automate',
    color: 'peach',
    title: 'Audit all system health & background routines',
    prompt: 'Check all system health, running tasks, database size, and tell me what needs attention.',
    target: 'host',
  },
  {
    tag: 'Coding',
    color: 'lime',
    title: 'Refactor code with full test suites and lints',
    prompt: 'Review the latest codebase changes, run full tests, and check for any remaining edge cases.',
    target: 'host',
  },
  {
    tag: 'Research',
    color: 'periwinkle',
    title: 'Deep search & synthesize knowledge notes',
    prompt: 'Search the web for the latest techniques and record key facts into long-term memory.',
    target: 'host',
  },
  {
    tag: 'DevBox',
    color: 'mint',
    title: 'Prepare isolated sandbox container for execution',
    prompt: 'Prepare the DevBox Docker container and verify the sandbox runtime is ready.',
    target: 'devbox',
  },
]

const SUGGESTION_CHIPS = [
  'Run daily backup',
  'Check model latencies',
  'Inspect memory facts',
  'Automate git sync',
  'Audit file permissions',
  'Test speech engine',
  'Review pending approvals',
  'Explore model catalog',
]

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

  // Autonomy and Approval Mode settings (Auto / Ask / Off)
  const { data: settingsData, reload: reloadSettings } = useLoad<{ settings: Settings }>('/api/settings')
  const approvalMode: ApprovalMode = settingsData?.settings?.approval_mode || 'MANUAL'

  const handleSetApprovalMode = async (newMode: ApprovalMode) => {
    if (!settingsData?.settings || newMode === approvalMode) return
    try {
      await api.put('/api/settings', {
        ...settingsData.settings,
        approval_mode: newMode,
      })
      const modeLabel =
        newMode === 'AUTO'
          ? 'Auto Mode (Move without permission)'
          : newMode === 'MANUAL'
          ? 'Ask Mode (Ask for permission)'
          : 'Off Mode (Responses only)'
      toast(`Switched to ${modeLabel}`, 'good')
      await reloadSettings()
      bump()
    } catch (err) {
      toast(`Failed to update mode: ${errorText(err)}`, 'bad')
    }
  }

  // Load live capacity & token limits
  const { data: capacityData } = useLoad<Capacity>('/api/capacity', 5000)

  // Compute live token counter and quota
  const totalTpdUsed = capacityData?.models?.reduce((acc, m) => acc + (m.tpd_used || 0), 0) ?? 0
  const totalTpdQuota = capacityData?.models?.reduce((acc, m) => acc + (m.tpd || 0), 0) ?? 0
  const estTasksLeft = capacityData?.estimated_tasks_left_today

  const tokenPillText = useMemo(() => {
    if (totalTpdQuota > 0) {
      const left = Math.max(0, totalTpdQuota - totalTpdUsed)
      if (left >= 1_000_000) return `${(left / 1_000_000).toFixed(1)}M tokens left`
      if (left >= 1_000) return `${(left / 1_000).toFixed(0)}k tokens left`
      return `${left} tokens left`
    }
    if (estTasksLeft !== null && estTasksLeft !== undefined) {
      return `~${estTasksLeft} tasks left today`
    }
    if (totalTpdUsed > 0) {
      if (totalTpdUsed >= 1_000_000) return `${(totalTpdUsed / 1_000_000).toFixed(1)}M spent`
      if (totalTpdUsed >= 1_000) return `${(totalTpdUsed / 1_000).toFixed(0)}k spent`
      return `${totalTpdUsed} spent`
    }
    return 'Capacity online'
  }, [totalTpdQuota, totalTpdUsed, estTasksLeft])

  const composerTokenCount = useMemo(() => {
    if (totalTpdQuota > 0) {
      const left = Math.max(0, totalTpdQuota - totalTpdUsed)
      if (left >= 1_000_000) return `${(left / 1_000_000).toFixed(1)}M`
      if (left >= 1_000) return `${(left / 1_000).toFixed(0)}k`
      return `${left}`
    }
    if (estTasksLeft !== null && estTasksLeft !== undefined) {
      return `${estTasksLeft}`
    }
    if (totalTpdUsed > 0) {
      if (totalTpdUsed >= 1_000) return `${(totalTpdUsed / 1_000).toFixed(0)}k`
      return `${totalTpdUsed}`
    }
    return 'Quota'
  }, [totalTpdQuota, totalTpdUsed, estTasksLeft])

  // Active thread details
  const [activeThread, setActiveThread] = useState<Thread | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [threadTasks, setThreadTasks] = useState<Task[]>([])
  const [pendingApprovals, setPendingApprovals] = useState<Approval[]>([])
  const [loadingMessages, setLoadingMessages] = useState(false)

  // Composer state
  const [prompt, setPrompt] = useState('')
  const [target, setTarget] = useState<ExecutionTarget>('host')
  const [selectedAgentId, setSelectedAgentId] = useState<string>('')
  const [submitting, setSubmitting] = useState(false)

  const activeAgent = useMemo(() => {
    if (selectedAgentId) return agents.find((a) => a.id === selectedAgentId) || null
    return agents[0] || null
  }, [agents, selectedAgentId])

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Fetch thread conversation messages
  useEffect(() => {
    let active = true
    if (!selectedThreadId) {
      setActiveThread(null)
      setMessages([])
      setThreadTasks([])
      return
    }

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

  // Poll for approvals
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
    const id = setInterval(loadApprovals, 3500)
    return () => clearInterval(id)
  }, [loadApprovals])

  // Scroll to bottom on new messages
  useEffect(() => {
    if (messages.length > 0 || threadTasks.length > 0) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages.length, threadTasks.length])

  const handleStartTask = async (textToSend: string, chosenTarget: ExecutionTarget = target) => {
    const text = textToSend.trim()
    if (!text || submitting) return

    setSubmitting(true)
    try {
      const payload: Record<string, unknown> = {
        goal: text,
        target: chosenTarget,
        agent_id: selectedAgentId || undefined,
      }
      if (selectedThreadId) {
        payload.thread_id = selectedThreadId
      }
      if (approvalMode === 'OFF') {
        payload.intent = 'ANSWER'
      }

      const res = await api.post<{ task: Task }>('/api/tasks', payload)
      toast('Task dispatched successfully', 'good')
      setPrompt('')
      bump()

      // If task created a thread, select it
      if (res.task.conversation_id && res.task.conversation_id !== selectedThreadId) {
        selectThread(res.task.conversation_id)
        await reloadThreads()
      } else if (selectedThreadId) {
        // Refresh active thread
        const updated = await api.get<{ thread: Thread; messages: Message[]; tasks: Task[] }>(
          `/api/threads/${selectedThreadId}`
        )
        setMessages(updated.messages || [])
        setThreadTasks(updated.tasks || [])
      }
    } catch (err) {
      toast(`Failed to dispatch: ${errorText(err)}`, 'bad')
    } finally {
      setSubmitting(false)
    }
  }

  const handleApprove = async (approvalId: string) => {
    try {
      await api.post(`/api/approvals/${approvalId}/decide`, { approve: true })
      toast('Action approved', 'good')
      bump()
      await loadApprovals()
    } catch (err) {
      toast(`Approval failed: ${errorText(err)}`, 'bad')
    }
  }

  const handleReject = async (approvalId: string) => {
    try {
      await api.post(`/api/approvals/${approvalId}/decide`, { approve: false })
      toast('Action rejected', 'warn')
      bump()
      await loadApprovals()
    } catch (err) {
      toast(`Rejection failed: ${errorText(err)}`, 'bad')
    }
  }

  return (
    <div className="view-container">
      {/* If No Thread is Selected: Full Editorial Home View (Reference Phone Screen 1 & 2) */}
      {!selectedThreadId ? (
        <div style={{ maxWidth: '880px', margin: '0 auto', paddingTop: '10px' }}>
          {/* Top Greeting & Token Left Pill */}
          <div className="hero-greeting" style={{ alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
              <AgentPet
                species={activeAgent?.pet || 'lily'}
                look={activeAgent?.look}
                size={54}
                agentName={activeAgent?.name || 'Lilly'}
                interactive={true}
              />
              <div>
                <h1 className="greeting-text">Hey, Operator</h1>
                <div className="greeting-sub">What is the plan for today?</div>
              </div>
            </div>
            <div className="token-pill">
              <Icon name="sparkles" size={13} style={{ color: 'var(--pastel-lime-text)' }} />
              <span>{tokenPillText}</span>
            </div>
          </div>

          {/* Large Editorial Headline Card (Reference Screen 2) */}
          <div className="hero-editorial-card periwinkle">
            <h2 className="editorial-headline">
              Offload the <span className="highlight-pill">daily clutter.</span> Let AI handle the details.
              <button
                type="button"
                className="hero-arrow-btn"
                onClick={() => inputRef.current?.focus()}
                title="Start prompt"
              >
                <Icon name="chevron-right" size={18} />
              </button>
            </h2>

            <div style={{ marginTop: '24px', display: 'flex', gap: '12px', alignItems: 'center' }}>
              <button
                type="button"
                onClick={() => handleStartTask('Review workspace tasks, system health, and tell me what needs attention.', 'host')}
                className="btn btn-primary"
              >
                Get Started
              </button>
              {threads.length > 0 && (
                <button
                  type="button"
                  onClick={() => selectThread(threads[0].id)}
                  className="btn btn-secondary"
                >
                  Resume Last Thread ({threads[0].title || 'Active'})
                </button>
              )}
            </div>
          </div>

          {/* Quick Prompt Category Cards (Reference Screen 1) */}
          <div style={{ marginBottom: '14px' }}>
            <h3 style={{ fontSize: '18px', fontWeight: 800, color: 'var(--text-main)', letterSpacing: '-0.02em' }}>
              How can I help you today?
            </h3>
          </div>

          <div className="card-grid">
            {QUICK_CARDS.map((card) => (
              <div
                key={card.tag}
                className={`pastel-card ${card.color}`}
                onClick={() => handleStartTask(card.prompt, card.target)}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <span className="pastel-tag-pill">{card.tag}</span>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontSize: '11px', fontWeight: 700, opacity: 0.8 }}>
                    <Icon name={card.target === 'devbox' ? 'cloud' : 'laptop'} size={12} />
                    <span>{card.target === 'devbox' ? 'DevBox' : 'Host'}</span>
                  </span>
                </div>
                <div className="pastel-card-title">{card.title}</div>
              </div>
            ))}
          </div>

          {/* Suggestion Chips Row */}
          <div style={{ marginBottom: '8px' }}>
            <div style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '8px' }}>
              Quick Suggestions
            </div>
            <div className="chips-scroll-row">
              {SUGGESTION_CHIPS.map((chip) => (
                <button
                  key={chip}
                  type="button"
                  className="prompt-chip"
                  onClick={() => handleStartTask(chip, 'host')}
                >
                  {chip}
                </button>
              ))}
            </div>
          </div>

          {/* Persistent Pill Composer Dock at Bottom */}
          <div className="chat-input-pill-wrapper" style={{ marginTop: '20px' }}>
            <form
              onSubmit={(e) => {
                e.preventDefault()
                handleStartTask(prompt)
              }}
              className="chat-input-pill"
            >
              <div style={{ display: 'flex', gap: '6px' }}>
                <select
                  className="composer-pill-select"
                  value={approvalMode}
                  onChange={(e) => handleSetApprovalMode(e.target.value as ApprovalMode)}
                  title="Autonomy: Auto (move without permission), Ask (ask permission), Off (responses only)"
                >
                  <option value="AUTO">Auto (Move without permission)</option>
                  <option value="MANUAL">Ask (Ask for permission)</option>
                  <option value="OFF">Off (Responses only)</option>
                </select>
                <select
                  className="composer-pill-select"
                  value={target}
                  onChange={(e) => setTarget(e.target.value as ExecutionTarget)}
                >
                  <option value="host">Host (Laptop)</option>
                  <option value="devbox">DevBox (Sandbox)</option>
                </select>
                <select
                  className="composer-pill-select"
                  value={selectedAgentId}
                  onChange={(e) => setSelectedAgentId(e.target.value)}
                >
                  <option value="">Auto Specialist</option>
                  {agents.map((ag) => (
                    <option key={ag.id} value={ag.id}>
                      {ag.name}
                    </option>
                  ))}
                </select>
              </div>

              <input
                ref={inputRef}
                className="chat-input-field"
                placeholder="Ask Lilly anything or describe an automation task..."
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                disabled={submitting}
              />

              <div className="token-pill" style={{ display: 'flex', alignItems: 'center', gap: '4px', padding: '4px 10px', fontSize: '11px' }}>
                <Icon name="sparkles" size={11} />
                <span>{composerTokenCount}</span>
              </div>

              <button
                type="submit"
                disabled={!prompt.trim() || submitting}
                className="chat-send-btn"
                title="Send message"
              >
                <Icon name="play" size={14} />
              </button>
            </form>
          </div>
        </div>
      ) : (
        /* Active Conversation Thread View (Reference Phone Screen 3) */
        <div className="chat-thread-container">
          {/* Header */}
          <div className="chat-header">
            <div className="chat-title-group">
              <button
                type="button"
                onClick={() => selectThread(null)}
                className="btn btn-ghost btn-sm"
                style={{ padding: '6px 10px' }}
                title="Return to Home"
              >
                <Icon name="chevron-left" size={16} />
              </button>
              <div>
                <h2 className="chat-thread-title">
                  {activeThread?.title || 'Active Conversation'}
                </h2>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span>{messages.length} messages</span>
                  <span>•</span>
                  <span>Target: {target}</span>
                  <span>•</span>
                  <span
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '4px',
                      padding: '2px 8px',
                      borderRadius: '12px',
                      fontSize: '11px',
                      fontWeight: 600,
                      backgroundColor:
                        approvalMode === 'AUTO'
                          ? 'var(--primary-subtle)'
                          : approvalMode === 'MANUAL'
                          ? 'var(--warning-subtle)'
                          : 'var(--bg-subtle)',
                      color:
                        approvalMode === 'AUTO'
                          ? 'var(--primary)'
                          : approvalMode === 'MANUAL'
                          ? 'var(--warning-text)'
                          : 'var(--text-muted)',
                      border: '1px solid var(--border)',
                    }}
                  >
                    <Icon
                      name={approvalMode === 'AUTO' ? 'play' : approvalMode === 'MANUAL' ? 'shield' : 'chat'}
                      size={11}
                    />
                    <span>{approvalMode === 'AUTO' ? 'Auto Mode' : approvalMode === 'MANUAL' ? 'Ask Mode' : 'Off Mode (Chat)'}</span>
                  </span>
                </div>
              </div>
            </div>

            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                type="button"
                onClick={() => selectThread(null)}
                className="btn btn-secondary btn-sm"
              >
                <Icon name="plus" size={12} />
                <span>New Topic</span>
              </button>
            </div>
          </div>

          {/* Pending Approvals Banner */}
          {pendingApprovals.length > 0 && (
            <div
              style={{
                marginBottom: '16px',
                padding: '14px 18px',
                borderRadius: 'var(--radius-md)',
                backgroundColor: 'var(--warning-subtle)',
                border: '1px solid var(--warning-border)',
                display: 'flex',
                flexDirection: 'column',
                gap: '8px',
              }}
            >
              <div style={{ fontWeight: 700, fontSize: '13px', color: 'var(--warning-text)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Icon name="alert-triangle" size={14} />
                <span>Action Approval Required ({pendingApprovals.length})</span>
              </div>
              {pendingApprovals.map((appr) => (
                <div key={appr.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '12px' }}>
                  <div>
                    <code style={{ fontFamily: 'var(--font-mono)' }}>{appr.tool}</code>: {appr.why || 'Tool call approval requested'}
                  </div>
                  <div style={{ display: 'flex', gap: '6px' }}>
                    <button
                      type="button"
                      onClick={() => handleApprove(appr.id)}
                      className="btn btn-primary btn-sm"
                      style={{ padding: '4px 10px', fontSize: '11px' }}
                    >
                      Approve
                    </button>
                    <button
                      type="button"
                      onClick={() => handleReject(appr.id)}
                      className="btn btn-ghost btn-sm"
                      style={{ padding: '4px 8px', fontSize: '11px', color: 'var(--danger)' }}
                    >
                      Reject
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Messages Flow */}
          <div className="chat-messages-scroll">
            {loadingMessages && messages.length === 0 ? (
              <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)' }}>
                Loading conversation history...
              </div>
            ) : messages.length === 0 && threadTasks.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '48px 0', color: 'var(--text-muted)' }}>
                No messages yet. Send a prompt below to begin!
              </div>
            ) : (
              messages.map((msg, idx) => {
                const isUser = msg.role === 'user'
                return (
                  <div key={msg.id || idx} className={isUser ? 'chat-msg-user-row' : 'chat-msg-bot-row'}>
                    <div className={isUser ? 'chat-bubble-user' : 'chat-bubble-bot'}>
                      <Markdown content={msg.content} />
                    </div>
                  </div>
                )
              })
            )}

            {/* Live Task Execution Stream */}
            {threadTasks.map((task) => {
              const taskPetState =
                task.state === 'WAITING_APPROVAL'
                  ? 'approval'
                  : task.state === 'PLANNING'
                  ? 'thinking'
                  : task.state === 'RUNNING' || task.state === 'VERIFYING'
                  ? 'working'
                  : task.state === 'DONE'
                  ? 'success'
                  : 'idle'

              return (
                <div key={task.id} className="chat-msg-bot-row">
                  <div className="chat-bubble-bot card-light" style={{ width: '100%', maxWidth: '88%' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                        <AgentPet
                          species={activeAgent?.pet || 'lily'}
                          look={activeAgent?.look}
                          state={taskPetState}
                          size={46}
                          interactive={true}
                          agentName={activeAgent?.name || 'Specialist'}
                          currentThought={task.goal}
                        />
                        <div>
                          <div style={{ fontWeight: 700, fontSize: '13px' }}>{task.goal}</div>
                          <div style={{ fontSize: '11px', color: 'var(--text-dim)', marginTop: '2px' }}>
                            {task.state} • {task.target === 'devbox' ? 'DevBox Sandbox' : 'Laptop Host'}
                          </div>
                        </div>
                      </div>
                      <div style={{ display: 'flex', gap: '6px' }}>
                        <TargetPill target={task.target} />
                        <StatePill state={task.state} />
                      </div>
                    </div>

                  {task.answer && (
                    <div style={{ marginTop: '10px', paddingTop: '10px', borderTop: '1px solid var(--border-subtle)' }}>
                      <Markdown content={task.answer} />
                    </div>
                  )}

                  {task.error && (
                    <div
                      style={{
                        marginTop: '10px',
                        padding: '10px',
                        backgroundColor: 'var(--danger-subtle)',
                        borderRadius: 'var(--radius-sm)',
                        color: 'var(--danger-text)',
                        fontSize: '12px',
                      }}
                    >
                      {task.error}
                    </div>
                  )}
                </div>
              </div>
            )
          })}
            <div ref={messagesEndRef} />
          </div>

          {/* Input Pill Bar Dock (Reference Screen 3) */}
          <div className="chat-input-pill-wrapper">
            <form
              onSubmit={(e) => {
                e.preventDefault()
                handleStartTask(prompt)
              }}
              className="chat-input-pill"
            >
              <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                <select
                  className="composer-pill-select"
                  value={approvalMode}
                  onChange={(e) => handleSetApprovalMode(e.target.value as ApprovalMode)}
                  title="Autonomy: Auto (move without permission), Ask (ask permission), Off (responses only)"
                >
                  <option value="AUTO">Auto</option>
                  <option value="MANUAL">Ask</option>
                  <option value="OFF">Off</option>
                </select>
                <select
                  className="composer-pill-select"
                  value={target}
                  onChange={(e) => setTarget(e.target.value as ExecutionTarget)}
                  title="Execution environment"
                >
                  <option value="host">Host</option>
                  <option value="devbox">DevBox</option>
                </select>
              </div>

              <button
                type="button"
                className="btn btn-ghost"
                style={{ padding: '4px', borderRadius: '50%' }}
                title="Attach file or context"
              >
                <Icon name="paperclip" size={16} />
              </button>

              <input
                className="chat-input-field"
                placeholder="Message Lilly..."
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                disabled={submitting}
              />

              <div className="token-pill" style={{ display: 'flex', alignItems: 'center', gap: '4px', padding: '4px 10px', fontSize: '11px' }}>
                <Icon name="sparkles" size={11} />
                <span>{composerTokenCount}</span>
              </div>

              <button
                type="submit"
                disabled={!prompt.trim() || submitting}
                className="chat-send-btn"
                title="Send message"
              >
                <Icon name="play" size={14} />
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
