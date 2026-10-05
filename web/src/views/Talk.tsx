import { useEffect, useRef, useState } from 'react'
import { api, errorText } from '../api'
import { useLoad } from '../hooks'
import { useApp } from '../store'
import { LIVE_STATES, type Agent, type Message, type ModelStatus, type Skill, type Task, type Thread } from '../types'
import { Icon, Petals } from '../ui/Icon'
import { Markdown } from '../ui/Markdown'
import { Pet, type PetState } from '../ui/Pet'
import { ReplyCheck } from '../ui/ReplyCheck'
import { RunCard } from '../ui/RunCard'
import { Button, Confirm, Dialog, ErrorNote, Field, IconButton } from '../ui/kit'
import { ago } from '../ui/format'

interface ThreadView { thread: Thread; messages: Message[]; tasks: Task[] }

const IDEAS = [
  'What should I do about the heaviest apps slowing down this Mac?',
  'Summarise the latest news on a topic I care about, with sources',
  'Help me draft a polite reply to a landlord about a repair',
]

function Composer(props: { conversationId: string | null; onSent: (conversationId: string) => void; initial?: string }) {
  const [text, setText] = useState(props.initial ?? '')
  const [agentId, setAgentId] = useState('')
  const [model, setModel] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [skills, setSkills] = useState(false)
  const agents = useLoad<{ agents: Agent[] }>('/api/agents')
  const models = useLoad<{ models: ModelStatus[] }>('/api/models')
  const area = useRef<HTMLTextAreaElement>(null)

  useEffect(() => { area.current?.focus() }, [])

  const send = async (goal: string, extra: Record<string, unknown> = {}) => {
    if (!goal.trim() || busy) return
    setBusy(true)
    setError(null)
    try {
      const r = await api.post<{ task: Task }>('/api/tasks', {
        goal,
        conversation_id: props.conversationId ?? undefined,
        agent_id: agentId || undefined,
        pin_model: model || undefined,
        ...extra,
      })
      setText('')
      props.onSent(r.task.conversation_id ?? '')
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="composer">
      <ErrorNote text={error} />
      <textarea
        ref={area}
        aria-label="Message Lilly"
        placeholder="Ask Lilly to do something…"
        rows={2}
        value={text}
        maxLength={4000}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault()
            void send(text)
          }
        }}
      />
      <div className="composer-bar">
        <select aria-label="Which agent" value={agentId} onChange={(e) => setAgentId(e.target.value)}>
          <option value="">Default assistant</option>
          {agents.data?.agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
        <select aria-label="Which model" value={model} onChange={(e) => setModel(e.target.value)}>
          <option value="">Model: automatic</option>
          {models.data?.models.filter((m) => m.enabled).map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}
        </select>
        <Button small icon="spark" onClick={() => setSkills(true)}>Skills</Button>
        <span className="grow" />
        <Button kind="primary" icon="send" busy={busy} disabled={!text.trim()} onClick={() => void send(text)}>Send</Button>
      </div>
      {skills && (
        <SkillDialog
          onClose={() => setSkills(false)}
          onRun={(skill, params) => { setSkills(false); void send(`Run ${skill}`, { skill, params }) }}
        />
      )}
    </div>
  )
}

function SkillDialog({ onClose, onRun }: { onClose: () => void; onRun: (skill: string, params: Record<string, string>) => void }) {
  const skills = useLoad<{ skills: Skill[] }>('/api/skills')
  const [picked, setPicked] = useState<Skill | null>(null)
  const [params, setParams] = useState<Record<string, string>>({})
  return (
    <Dialog
      title={picked ? picked.name : 'Skills'}
      onClose={onClose}
      footer={picked && (
        <>
          <Button onClick={() => setPicked(null)}>Back</Button>
          <Button kind="primary" disabled={picked.params.some((p) => !params[p]?.trim())} onClick={() => onRun(picked.name, params)}>Run skill</Button>
        </>
      )}
    >
      {!picked ? (
        <ul className="plain-list">
          {skills.data?.skills.map((s) => (
            <li key={s.name}>
              <button type="button" className="row-button" onClick={() => { setPicked(s); setParams({}) }}>
                <strong>{s.name}</strong>
                <span>{s.summary}</span>
                <small>{s.risk === 'R0' ? 'Reads only' : 'Changes files, asks first'}</small>
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <>
          <p className="prose">{picked.summary}</p>
          {picked.params.map((p) => (
            <Field key={p} label={p === 'topic' ? 'Topic' : p === 'path' ? 'File path' : p === 'folder' ? 'Folder path' : p}>
              {(id) => <input id={id} value={params[p] ?? ''} onChange={(e) => setParams({ ...params, [p]: e.target.value })} />}
            </Field>
          ))}
          {picked.params.length === 0 && <p className="hint">This skill needs nothing from you.</p>}
        </>
      )}
    </Dialog>
  )
}

/** A new install has no key yet: say so before the first message fails, and say where to add one. */
function NoKeyNote() {
  const models = useLoad<{ models: ModelStatus[] }>('/api/models')
  const usable = models.data?.models.some((m) => m.enabled && m.has_key)
  if (usable !== false) return null
  return (
    <p className="callout callout-warn" role="status">
      Lilly has no model to talk to yet. Add a free API key (or turn on a local model) in <a href="#/settings/models">Settings → Models &amp; keys</a>.
    </p>
  )
}

function Welcome({ onSent }: { onSent: (id: string) => void }) {
  const [seed, setSeed] = useState('')
  return (
    <div className="welcome">
      <span className="welcome-mark"><Petals size={54} /></span>
      <h1>What can I help with?</h1>
      <p className="sub">Lilly runs on this computer. It asks before it touches anything private, and shows its work.</p>
      <NoKeyNote />
      <ul className="ideas">
        {IDEAS.map((i) => <li key={i}><button type="button" onClick={() => setSeed(i)}>{i}</button></li>)}
      </ul>
      <Composer key={seed} conversationId={null} onSent={onSent} initial={seed} />
    </div>
  )
}

function Conversation({ id, onDeleted }: { id: string; onDeleted: () => void }) {
  const view = useLoad<ThreadView>(`/api/threads/${id}`, true)
  const agents = useLoad<{ agents: Agent[] }>('/api/agents')
  const bump = useApp((s) => s.bump)
  const toast = useApp((s) => s.toast)
  const [rename, setRename] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const end = useRef<HTMLDivElement>(null)
  const v = view.data

  const count = (v?.messages.length ?? 0) + (v?.tasks.length ?? 0)
  useEffect(() => { if (count > 0) end.current?.scrollIntoView({ block: 'end' }) }, [count])

  if (!v) return <div className="conversation"><ErrorNote text={view.error} /></div>
  const byTask = (taskId: string, role: string) => v.messages.find((m) => m.task_id === taskId && m.role === role)

  return (
    <div className="conversation">
      <header className="conv-head">
        <h2>{v.thread.title}</h2>
        <div className="row">
          <IconButton icon="edit" label="Rename conversation" onClick={() => setRename(true)} />
          <IconButton icon="trash" label="Delete conversation" kind="danger" onClick={() => setConfirm(true)} />
        </div>
      </header>
      <div className="messages" aria-live="polite">
        {v.tasks.map((t) => {
          const user = byTask(t.id, 'user')
          const reply = byTask(t.id, 'assistant')
          const agent = agents.data?.agents.find((a) => a.id === t.agent_id)
          const mood: PetState = t.state === 'WAITING_APPROVAL' ? 'waiting' : LIVE_STATES.includes(t.state) ? 'thinking' : t.state === 'FAILED' || t.state === 'EXPIRED' ? 'error' : 'idle'
          return (
            <article key={t.id} className="turn">
              <div className="bubble bubble-user">{user?.content ?? t.goal}</div>
              <RunCard taskId={t.id} initialState={t.state} />
              {(reply || mood !== 'idle') && (
                <div className="lilly-row">
                  <Pet id={agent?.pet ?? 'lily'} look={agent?.look} state={reply && mood === 'idle' ? 'done' : mood} size={46} />
                  {reply && (
                    <div className="bubble bubble-lilly">
                      <Markdown text={reply.content} />
                      {reply.untrusted && <p className="hint">Based partly on web content. Check important facts.</p>}
                      <ReplyCheck taskId={t.id} watch={t.id === v.tasks[v.tasks.length - 1]?.id} />
                    </div>
                  )}
                </div>
              )}
            </article>
          )
        })}
        <div ref={end} />
      </div>
      <Composer conversationId={id} onSent={() => bump()} />
      {rename && <RenameDialog thread={v.thread} onClose={() => setRename(false)} onSaved={() => { setRename(false); bump() }} />}
      {confirm && (
        <Confirm
          title="Delete this conversation?"
          danger
          confirm="Delete"
          body="The messages are removed for good. Activity records of finished tasks are kept until they age out."
          onClose={() => setConfirm(false)}
          onConfirm={() => {
            api.del(`/api/threads/${id}`).then(() => { bump(); onDeleted() }).catch((e: unknown) => toast(errorText(e), 'bad'))
          }}
        />
      )}
    </div>
  )
}

function RenameDialog({ thread, onClose, onSaved }: { thread: Thread; onClose: () => void; onSaved: () => void }) {
  const [title, setTitle] = useState(thread.title)
  const [error, setError] = useState<string | null>(null)
  const save = async () => {
    try {
      await api.patch(`/api/threads/${thread.id}`, { title })
      onSaved()
    } catch (e) {
      setError(errorText(e))
    }
  }
  return (
    <Dialog title="Rename conversation" onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button kind="primary" onClick={() => void save()}>Save</Button></>}>
      <Field label="Title">{(id) => <input id={id} value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />}</Field>
      <ErrorNote text={error} />
    </Dialog>
  )
}

export function Talk({ threadId, go }: { threadId: string | null; go: (hash: string) => void }) {
  const [query, setQuery] = useState('')
  const [archived, setArchived] = useState(false)
  const [listOpen, setListOpen] = useState(false)
  const threads = useLoad<{ threads: Thread[] }>(`/api/threads?${query ? `q=${encodeURIComponent(query)}` : archived ? 'archived=1' : ''}`, true)
  const toast = useApp((s) => s.toast)

  const toggleArchive = async (t: Thread) => {
    try {
      await api.patch(`/api/threads/${t.id}`, { archived: !t.archived })
      threads.reload()
    } catch (e) {
      toast(errorText(e), 'bad')
    }
  }

  return (
    <div className="talk">
      <aside className={`thread-list${listOpen ? ' open' : ''}`} aria-label="Conversations">
        <div className="thread-tools">
          <Button kind="primary" icon="plus" onClick={() => { go('/talk'); setListOpen(false) }}>New chat</Button>
          <input type="search" aria-label="Search conversations" placeholder="Search" value={query} onChange={(e) => setQuery(e.target.value)} />
          <label className="check"><input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> Show archived</label>
        </div>
        <ul>
          {threads.data?.threads.map((t) => (
            <li key={t.id} className={t.id === threadId ? 'current' : ''}>
              <a href={`#/talk/${t.id}`} onClick={() => setListOpen(false)}>
                <span className="thread-title">{t.title}</span>
                <span className="thread-when">{ago(t.updated_at)}</span>
              </a>
              <IconButton icon={t.archived ? 'up' : 'down'} label={t.archived ? 'Unarchive' : 'Archive'} onClick={() => void toggleArchive(t)} />
            </li>
          ))}
          {threads.data?.threads.length === 0 && <li className="thread-empty">No conversations yet.</li>}
        </ul>
      </aside>
      <section className="talk-main">
        <button type="button" className="thread-toggle" onClick={() => setListOpen(!listOpen)} aria-expanded={listOpen}>
          <Icon name="menu" size={16} /> Conversations
        </button>
        {threadId ? <Conversation key={threadId} id={threadId} onDeleted={() => go('/talk')} /> : <Welcome onSent={(id) => go(`/talk/${id}`)} />}
      </section>
    </div>
  )
}
