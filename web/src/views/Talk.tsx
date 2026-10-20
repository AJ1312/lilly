import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { api, errorText } from '../api'
import { useLoad } from '../hooks'
import { useAppStore } from '../store'
import type { Thread, Message, Task, ExecutionTarget, Agent, Approval, Capacity, ApprovalMode, Settings, Skill, ModelStatus, RequestIntent } from '../types'
import { Icon, type IconName } from '../ui/Icon'
import { TargetPill, StatePill, OutcomePill } from '../ui/Pills'

import { Markdown } from '../ui/Markdown'
import { AgentPet } from '../ui/AgentPet'

const getStepIcon = (tool: string): IconName => {
  if (tool.startsWith('computer.')) {
    if (tool.includes('run')) return 'terminal'
    if (tool.includes('observe')) return 'eye'
    return 'laptop'
  }
  if (tool.startsWith('browser.')) return 'external-link'
  if (tool.startsWith('fs.')) return 'file-text'
  if (tool.startsWith('memory.') || tool.startsWith('notes.')) return 'database'
  if (tool.startsWith('web.')) return 'search'
  return 'play'
}

const formatStepSummary = (tool: string, args: Record<string, unknown> | null | undefined): string => {
  if (!args) return ''
  if (tool === 'computer.open_app' && args.name) return `app: "${args.name}"`
  if (tool === 'computer.type' && args.text) return `type: "${String(args.text).slice(0, 30)}"`
  if (tool === 'computer.press' && args.key) return `key: "${args.key}"`
  if (tool === 'computer.click') return args.target ? `click: ${args.target}` : 'click'
  if (tool === 'computer.run' && args.command) return `cmd: "${String(args.command).slice(0, 40)}"`
  if (tool === 'browser.open' && args.url) return `url: "${String(args.url).slice(0, 40)}"`
  if (tool.startsWith('fs.') && args.path) return `path: "${args.path}"`
  if (tool.startsWith('web.') && args.query) return `query: "${args.query}"`
  const entries = Object.entries(args)
  if (entries.length === 0) return ''
  return entries.map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(' ').slice(0, 50)
}

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
  const [localApprovalMode, setLocalApprovalMode] = useState<ApprovalMode | null>(null)
  const { data: settingsData, reload: reloadSettings } = useLoad<{ settings: Settings }>('/api/settings')
  const approvalMode: ApprovalMode = localApprovalMode ?? settingsData?.settings?.approval_mode ?? 'MANUAL'

  const handleSetApprovalMode = async (newMode: ApprovalMode) => {
    setLocalApprovalMode(newMode)
    if (!settingsData?.settings) return
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
  const tick = useAppStore((s) => s.tick)

  // Composer & Task options state
  const [prompt, setPrompt] = useState('')
  const [target, setTarget] = useState<ExecutionTarget>('host')
  const [selectedAgentId, setSelectedAgentId] = useState<string>('')
  const [intent, setIntent] = useState<RequestIntent>('AUTO')
  const [pinnedModel, setPinnedModel] = useState<string>('')
  const [selectedSkill, setSelectedSkill] = useState<string>('')
  const [submitting, setSubmitting] = useState(false)
  const [showTaskOptions, setShowTaskOptions] = useState(false)

  // File attachments state & handlers
  interface AttachedFile {
    name: string
    size: number
    type: string
    content?: string
    path?: string
  }
  const [attachments, setAttachments] = useState<AttachedFile[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)

  const formatBytes = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return
    const newAttachments: AttachedFile[] = []

    for (let i = 0; i < files.length; i++) {
      const file = files[i]
      try {
        let content: string | undefined
        let encoding: 'utf-8' | 'base64' = 'utf-8'

        const isText =
          file.type.startsWith('text/') ||
          /\.(txt|md|py|js|ts|tsx|jsx|json|yaml|yml|html|css|sh|sql|csv|xml|log|toml|ini|env)$/i.test(file.name)

        if (isText) {
          content = await file.text()
        } else {
          const buffer = await file.arrayBuffer()
          const bytes = new Uint8Array(buffer)
          let binary = ''
          for (let b = 0; b < bytes.byteLength; b++) {
            binary += String.fromCharCode(bytes[b])
          }
          content = btoa(binary)
          encoding = 'base64'
        }

        let uploadedPath: string | undefined
        try {
          const res = await api.post<{ ok: boolean; path: string; name: string }>('/api/files/upload', {
            name: file.name,
            content: content || '',
            encoding,
          })
          if (res?.path) {
            uploadedPath = res.path
          }
        } catch {
          // ignore upload failure; keep client-side content
        }

        newAttachments.push({
          name: file.name,
          size: file.size,
          type: file.type,
          content: isText ? content : undefined,
          path: uploadedPath,
        })
        toast(`Attached ${file.name}`, 'good')
      } catch (err) {
        toast(`Failed to attach ${file.name}: ${errorText(err)}`, 'bad')
      }
    }

    setAttachments((prev) => [...prev, ...newAttachments])
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const removeAttachment = (index: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== index))
  }

  // Dynamic skills and models options
  const { data: skillsData } = useLoad<{ skills: Skill[] }>('/api/skills')
  const skills = skillsData?.skills || []
  const { data: modelsData } = useLoad<{ models: ModelStatus[] }>('/api/models')
  const availableModels = (modelsData?.models || []).filter((m) => m.enabled && m.has_key)

  const hasCustomOptions =
    target !== 'host' || !!selectedAgentId || intent !== 'AUTO' || !!pinnedModel || !!selectedSkill

  const activeAgent = useMemo(() => {
    if (selectedAgentId) return agents.find((a) => a.id === selectedAgentId) || null
    return agents[0] || null
  }, [agents, selectedAgentId])

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const chatScrollContainerRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const [isAtBottom, setIsAtBottom] = useState(true)

  const handleScroll = () => {
    const el = chatScrollContainerRef.current
    if (!el) return
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    setIsAtBottom(distanceFromBottom < 120)
  }

  const scrollToBottom = (behavior: ScrollBehavior = 'smooth') => {
    messagesEndRef.current?.scrollIntoView({ behavior })
    setIsAtBottom(true)
  }

  // Fetch thread conversation messages
  const reloadActiveThread = useCallback(async () => {
    if (!selectedThreadId) return
    try {
      const res = await api.get<{ thread: Thread; messages: Message[]; tasks: Task[] }>(
        `/api/threads/${selectedThreadId}`
      )
      setActiveThread(res.thread)
      setMessages(res.messages || [])
      setThreadTasks(res.tasks || [])
    } catch {
      // ignore
    }
  }, [selectedThreadId])

  useEffect(() => {
    let active = true
    if (!selectedThreadId || tick < 0) {
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
  }, [selectedThreadId, toast, tick])

  // Polling for active running tasks in current thread
  const hasActiveTask = useMemo(() => {
    return threadTasks.some((t) =>
      ['PENDING', 'PLANNING', 'RUNNING', 'WAITING_APPROVAL', 'VERIFYING'].includes(t.state)
    )
  }, [threadTasks])

  useEffect(() => {
    if (!selectedThreadId || !hasActiveTask) return
    const id = setInterval(() => {
      void reloadActiveThread()
    }, 2000)
    return () => clearInterval(id)
  }, [selectedThreadId, hasActiveTask, reloadActiveThread])

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

  // Scroll to bottom on new messages only if user was already at bottom
  useEffect(() => {
    if (isAtBottom && (messages.length >= 0 || threadTasks.length >= 0)) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages.length, threadTasks.length, isAtBottom])

  const handleStartTask = async (textToSend: string, chosenTarget: ExecutionTarget = target) => {
    const text = textToSend.trim()
    if ((!text && attachments.length === 0) || submitting) return

    setSubmitting(true)
    try {
      let finalGoal = text
      if (attachments.length > 0) {
        const fileSections: string[] = []
        for (const att of attachments) {
          if (att.path) {
            fileSections.push(`[Attached File: ${att.path}]`)
          } else {
            fileSections.push(`[Attached File: ${att.name}]`)
          }
          if (att.content && att.content.length <= 15000) {
            fileSections.push(`--- Begin ${att.name} ---\n${att.content}\n--- End ${att.name} ---`)
          }
        }
        finalGoal = fileSections.length > 0 ? (text ? `${fileSections.join('\n\n')}\n\n${text}` : fileSections.join('\n\n')) : text
      }

      const payload: Record<string, unknown> = {
        goal: finalGoal,
        target: chosenTarget,
        agent_id: selectedAgentId || undefined,
        conversation_id: selectedThreadId || undefined,
      }
      if (pinnedModel) {
        payload.pin_model = pinnedModel
      }
      if (selectedSkill) {
        payload.skill = selectedSkill
      }
      if (intent !== 'AUTO') {
        payload.intent = intent
      } else if (approvalMode === 'OFF') {
        payload.intent = 'ANSWER'
      }
      payload.approval_mode = approvalMode

      const res = await api.post<{ task: Task }>('/api/tasks', payload)
      toast('Task dispatched successfully', 'good')
      setPrompt('')
      setAttachments([])
      bump()

      // If task created a thread, select it
      if (res.task.conversation_id && res.task.conversation_id !== selectedThreadId) {
        selectThread(res.task.conversation_id)
        await reloadThreads()
      } else if (selectedThreadId) {
        // Refresh active thread immediately
        await reloadActiveThread()
      }
      scrollToBottom('smooth')
    } catch (err) {
      toast(`Failed to dispatch: ${errorText(err)}`, 'bad')
    } finally {
      setSubmitting(false)
    }
  }

  const handleApprove = async (approvalId: string, payloadHash?: string) => {
    try {
      const appr = pendingApprovals.find(a => a.id === approvalId)
      const hash = payloadHash || appr?.payload_hash
      await api.post(`/api/approvals/${approvalId}/decide`, { approve: true, payload_hash: hash })
      toast('Action approved', 'good')
      bump()
      await loadApprovals()
    } catch (err) {
      toast(`Approval failed: ${errorText(err)}`, 'bad')
    }
  }

  const handleReject = async (approvalId: string, payloadHash?: string) => {
    try {
      const appr = pendingApprovals.find(a => a.id === approvalId)
      const hash = payloadHash || appr?.payload_hash
      await api.post(`/api/approvals/${approvalId}/decide`, { approve: false, payload_hash: hash })
      toast('Action rejected', 'warn')
      bump()
      await loadApprovals()
    } catch (err) {
      toast(`Rejection failed: ${errorText(err)}`, 'bad')
    }
  }

  const renderTaskOptions = () => {
    if (!showTaskOptions) return null
    return (
      <div className="task-options-panel">
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)' }}>Target:</span>
          <select
            className="select"
            style={{ padding: '4px 8px', fontSize: '12px' }}
            value={target}
            onChange={(e) => setTarget(e.target.value as ExecutionTarget)}
            title="Execution Environment"
          >
            <option value="host">Host (Laptop)</option>
            <option value="devbox">DevBox (Sandbox)</option>
          </select>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)' }}>Specialist:</span>
          <select
            className="select"
            style={{ padding: '4px 8px', fontSize: '12px' }}
            value={selectedAgentId}
            onChange={(e) => setSelectedAgentId(e.target.value)}
            title="Assigned Specialist Agent"
          >
            <option value="">Auto Specialist</option>
            {agents.map((ag) => (
              <option key={ag.id} value={ag.id}>
                {ag.name}
              </option>
            ))}
          </select>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)' }}>Intent:</span>
          <select
            className="select"
            style={{ padding: '4px 8px', fontSize: '12px' }}
            value={intent}
            onChange={(e) => setIntent(e.target.value as RequestIntent)}
            title="Task Request Intent"
          >
            <option value="AUTO">Auto Intent</option>
            <option value="ANSWER">Chat / Answer</option>
            <option value="WEB_RETRIEVE">Web Search</option>
            <option value="NAVIGATE">Browser</option>
            <option value="ACTION">Tool Action</option>
          </select>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)' }}>Model:</span>
          <select
            className="select"
            style={{ padding: '4px 8px', fontSize: '12px' }}
            value={pinnedModel}
            onChange={(e) => setPinnedModel(e.target.value)}
            title="Pin Specific Model"
          >
            <option value="">Dynamic Model</option>
            {availableModels.map((m) => (
              <option key={m.name} value={m.name}>
                {m.name}
              </option>
            ))}
          </select>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)' }}>Skill:</span>
          <select
            className="select"
            style={{ padding: '4px 8px', fontSize: '12px' }}
            value={selectedSkill}
            onChange={(e) => setSelectedSkill(e.target.value)}
            title="Specialized Skill"
          >
            <option value="">Auto Skills</option>
            {skills.map((s) => (
              <option key={s.name} value={s.name}>
                {s.name}
              </option>
            ))}
          </select>
        </div>

        {hasCustomOptions && (
          <button
            type="button"
            onClick={() => {
              setTarget('host')
              setSelectedAgentId('')
              setIntent('AUTO')
              setPinnedModel('')
              setSelectedSkill('')
            }}
            className="btn btn-ghost btn-sm"
            style={{ fontSize: '11px', marginLeft: 'auto', padding: '2px 8px' }}
          >
            Reset
          </button>
        )}
      </div>
    )
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
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <button
                type="button"
                onClick={() => setShowTaskOptions((prev) => !prev)}
                className={`btn btn-sm ${showTaskOptions ? 'btn-secondary' : 'btn-ghost'}`}
                style={{ display: 'flex', alignItems: 'center', gap: '5px', borderRadius: '20px', padding: '6px 12px' }}
                title="Task Parameters & Environment"
              >
                <Icon name="sliders" size={13} />
                <span>Options</span>
                {hasCustomOptions && (
                  <span
                    style={{
                      width: '6px',
                      height: '6px',
                      borderRadius: '50%',
                      backgroundColor: 'var(--primary)',
                    }}
                  />
                )}
              </button>
              <div className="token-pill">
                <Icon name="sparkles" size={13} style={{ color: 'var(--pastel-lime-text)' }} />
                <span>{tokenPillText}</span>
              </div>
            </div>
          </div>

          {/* Task Parameters (Top of Landing View) */}
          {renderTaskOptions()}

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
              <button
                type="button"
                key={card.tag}
                className={`pastel-card ${card.color}`}
                onClick={() => handleStartTask(card.prompt, card.target)}
                style={{ textAlign: 'left', border: 'none', cursor: 'pointer', fontFamily: 'inherit' }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <span className="pastel-tag-pill">{card.tag}</span>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontSize: '11px', fontWeight: 700, opacity: 0.8 }}>
                    <Icon name={card.target === 'devbox' ? 'cloud' : 'laptop'} size={12} />
                    <span>{card.target === 'devbox' ? 'DevBox' : 'Host'}</span>
                  </span>
                </div>
                <div className="pastel-card-title">{card.title}</div>
              </button>
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
            {attachments.length > 0 && (
              <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', padding: '6px 12px', marginBottom: '8px' }}>
                {attachments.map((att, idx) => (
                  <span key={idx} className="attachment-chip">
                    <Icon name="paperclip" size={13} />
                    <span className="attachment-chip-name">{att.name}</span>
                    <span className="attachment-chip-size">({formatBytes(att.size)})</span>
                    <button
                      type="button"
                      onClick={() => removeAttachment(idx)}
                      className="attachment-chip-remove"
                      title="Remove attachment"
                    >
                      <Icon name="x" size={12} />
                    </button>
                  </span>
                ))}
              </div>
            )}
            <form
              onSubmit={(e) => {
                e.preventDefault()
                handleStartTask(prompt)
              }}
              className="chat-input-pill"
            >
              <select
                className="composer-pill-select"
                value={approvalMode}
                onChange={(e) => handleSetApprovalMode(e.target.value as ApprovalMode)}
                title="Autonomy mode: Auto (autonomous execution), Approve (ask permission), Off (responses only)"
              >
                <option value="AUTO">Auto</option>
                <option value="MANUAL">Approve</option>
                <option value="OFF">Off</option>
              </select>

              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="btn btn-ghost"
                style={{ padding: '6px', borderRadius: '50%' }}
                title="Attach file or context"
              >
                <Icon name="paperclip" size={16} />
              </button>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                style={{ display: 'none' }}
                onChange={handleFileSelect}
              />

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
                disabled={(!prompt.trim() && attachments.length === 0) || submitting}
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
                onClick={() => setShowTaskOptions((prev) => !prev)}
                className={`btn btn-sm ${showTaskOptions ? 'btn-secondary' : 'btn-ghost'}`}
                style={{ display: 'flex', alignItems: 'center', gap: '4px' }}
                title="Toggle Task Parameters"
              >
                <Icon name="sliders" size={12} />
                <span>Options</span>
                {hasCustomOptions && (
                  <span
                    style={{
                      width: '6px',
                      height: '6px',
                      borderRadius: '50%',
                      backgroundColor: 'var(--primary)',
                    }}
                  />
                )}
              </button>

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

          {/* Task Parameters (Top of Conversation View) */}
          {renderTaskOptions()}

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
                      onClick={() => handleApprove(appr.id, appr.payload_hash)}
                      className="btn btn-primary btn-sm"
                      style={{ padding: '4px 10px', fontSize: '11px' }}
                    >
                      Approve
                    </button>
                    <button
                      type="button"
                      onClick={() => handleReject(appr.id, appr.payload_hash)}
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
          <div className="chat-messages-scroll" ref={chatScrollContainerRef} onScroll={handleScroll}>
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
                if (msg.role === 'user') {
                  return (
                    <div key={msg.id || idx} className="chat-msg-user-row">
                      <div className="chat-bubble-user">
                        <Markdown content={msg.content} />
                      </div>
                    </div>
                  )
                }

                // If bot response has a corresponding task rendered in threadTasks, do not duplicate
                const hasTask = threadTasks.some(
                  (t) => t.id === msg.task_id || (t.answer && t.answer.trim() === msg.content.trim())
                )
                if (hasTask) return null

                // For standalone bot responses without a live task card, render only in coloured block card style
                return (
                  <div key={msg.id || idx} className="chat-msg-bot-row">
                    <div
                      className="chat-bubble-bot card-light"
                      style={{ width: '100%', maxWidth: '88%', minWidth: 0, overflowWrap: 'break-word', wordBreak: 'break-word' }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px', minWidth: 0 }}>
                        <AgentPet
                          species={activeAgent?.pet || 'lily'}
                          look={activeAgent?.look}
                          state="idle"
                          size={40}
                          interactive={false}
                          agentName={activeAgent?.name || 'Lilly'}
                        />
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontWeight: 700, fontSize: '13px' }}>{activeAgent?.name || 'Lilly'}</div>
                        </div>
                      </div>
                      <div style={{ marginTop: '6px', minWidth: 0 }}>
                        <Markdown content={msg.content} />
                      </div>
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
                  <div
                    className="chat-bubble-bot card-light"
                    style={{ width: '100%', maxWidth: '88%', minWidth: 0, overflowWrap: 'break-word', wordBreak: 'break-word' }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px', gap: '8px', flexWrap: 'wrap', minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', minWidth: 0, flex: 1 }}>
                        <AgentPet
                          species={activeAgent?.pet || 'lily'}
                          look={activeAgent?.look}
                          state={taskPetState}
                          size={46}
                          interactive={false}
                          agentName={activeAgent?.name || 'Specialist'}
                          currentThought={task.goal}
                        />
                        <div style={{ minWidth: 0, flex: 1 }}>
                          <div style={{ fontWeight: 700, fontSize: '13px', overflowWrap: 'break-word', wordBreak: 'break-word' }}>{task.goal}</div>
                          <div style={{ fontSize: '11px', color: 'var(--text-dim)', marginTop: '2px' }}>
                            {task.state} • {task.target === 'devbox' ? 'DevBox Sandbox' : 'Laptop Host'}
                          </div>
                        </div>
                      </div>
                      <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                        <TargetPill target={task.target} />
                        <StatePill state={task.state} />
                        {task.outcome && task.outcome !== 'success' && (
                          <OutcomePill outcome={task.outcome} />
                        )}
                      </div>
                    </div>

                    {task.steps && task.steps.length > 0 && (
                      <div
                        style={{
                          marginTop: '10px',
                          padding: '10px 14px',
                          borderRadius: 'var(--radius-sm)',
                          backgroundColor: 'var(--bg-card-subtle)',
                          border: '1px solid var(--border-subtle)',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: '6px',
                        }}
                      >
                        <div
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            fontSize: '11px',
                            fontWeight: 700,
                            color: 'var(--text-muted)',
                            textTransform: 'uppercase',
                            letterSpacing: '0.04em',
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <Icon name="terminal" size={12} />
                            <span>Execution Trace ({task.steps.length} {task.steps.length === 1 ? 'action' : 'actions'})</span>
                          </div>
                        </div>

                        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginTop: '4px' }}>
                          {task.steps.map((st, sidx) => {
                            const isOk = st.status === 'success'
                            const isFailed = st.status === 'failed' || st.status === 'cancelled'
                            const summary = formatStepSummary(st.tool, st.args)

                            return (
                              <div
                                key={st.id || sidx}
                                style={{
                                  display: 'flex',
                                  alignItems: 'center',
                                  justifyContent: 'space-between',
                                  padding: '5px 8px',
                                  borderRadius: '6px',
                                  backgroundColor: 'var(--bg-app)',
                                  fontSize: '12px',
                                  fontFamily: 'var(--font-mono)',
                                  gap: '8px',
                                }}
                              >
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0, flex: 1 }}>
                                  <span style={{ color: isOk ? 'var(--success)' : isFailed ? 'var(--danger)' : 'var(--pill-highlight)' }}>
                                    <Icon name={getStepIcon(st.tool)} size={12} />
                                  </span>
                                  <span style={{ fontWeight: 600, color: 'var(--text-main)' }}>{st.tool}</span>
                                  {summary && (
                                    <span style={{ color: 'var(--text-muted)', fontSize: '11px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                      {summary}
                                    </span>
                                  )}
                                </div>
                                <span
                                  style={{
                                    fontSize: '10px',
                                    fontWeight: 700,
                                    textTransform: 'uppercase',
                                    padding: '1px 6px',
                                    borderRadius: '4px',
                                    backgroundColor: isOk ? 'var(--success-subtle)' : isFailed ? 'var(--danger-subtle)' : 'var(--bg-hover)',
                                    color: isOk ? 'var(--success-text)' : isFailed ? 'var(--danger-text)' : 'var(--text-muted)',
                                  }}
                                >
                                  {st.status}
                                </span>
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    )}

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

          {/* Jump to latest button */}
          {!isAtBottom && (
            <button
              type="button"
              onClick={() => scrollToBottom('smooth')}
              className="btn btn-secondary btn-sm"
              style={{
                position: 'absolute',
                bottom: '80px',
                left: '50%',
                transform: 'translateX(-50%)',
                zIndex: 10,
                boxShadow: 'var(--shadow-md)',
                borderRadius: '20px',
                padding: '6px 14px',
                fontSize: '12px',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                backgroundColor: 'var(--bg-card)',
                border: '1px solid var(--border)',
              }}
            >
              <Icon name="chevron-down" size={13} />
              <span>Jump to latest</span>
            </button>
          )}

          {/* Input Pill Bar Dock (Reference Screen 3) */}
          <div className="chat-input-pill-wrapper">
            {attachments.length > 0 && (
              <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', padding: '6px 12px', marginBottom: '8px' }}>
                {attachments.map((att, idx) => (
                  <span key={idx} className="attachment-chip">
                    <Icon name="paperclip" size={13} />
                    <span className="attachment-chip-name">{att.name}</span>
                    <span className="attachment-chip-size">({formatBytes(att.size)})</span>
                    <button
                      type="button"
                      onClick={() => removeAttachment(idx)}
                      className="attachment-chip-remove"
                      title="Remove attachment"
                    >
                      <Icon name="x" size={12} />
                    </button>
                  </span>
                ))}
              </div>
            )}
            <form
              onSubmit={(e) => {
                e.preventDefault()
                handleStartTask(prompt)
              }}
              className="chat-input-pill"
            >
              <select
                className="composer-pill-select"
                value={approvalMode}
                onChange={(e) => handleSetApprovalMode(e.target.value as ApprovalMode)}
                title="Autonomy mode: Auto (autonomous execution), Approve (ask permission), Off (responses only)"
              >
                <option value="AUTO">Auto</option>
                <option value="MANUAL">Approve</option>
                <option value="OFF">Off</option>
              </select>

              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="btn btn-ghost"
                style={{ padding: '6px', borderRadius: '50%' }}
                title="Attach file or context"
              >
                <Icon name="paperclip" size={16} />
              </button>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                style={{ display: 'none' }}
                onChange={handleFileSelect}
              />

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
                disabled={(!prompt.trim() && attachments.length === 0) || submitting}
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
