import { useState } from 'react'
import { api, errorText } from '../api'
import { useLoad } from '../hooks'
import { useApp } from '../store'
import type { MemoryItem } from '../types'
import { Button, Confirm, Empty, ErrorNote, IconButton, PageHead, Pill } from '../ui/kit'
import { ago } from '../ui/format'

function Row({ item, onChanged }: { item: MemoryItem; onChanged: () => void }) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(item.text)
  const [tags, setTags] = useState(item.tags.join(', '))
  const toast = useApp((s) => s.toast)
  const run = async (fn: () => Promise<unknown>) => {
    try {
      await fn()
      onChanged()
    } catch (e) {
      toast(errorText(e), 'bad')
    }
  }
  return (
    <li className="memory-row">
      {editing ? (
        <div className="memory-edit">
          <textarea aria-label="Edit memory" value={text} rows={2} onChange={(e) => setText(e.target.value)} />
          <input aria-label="Memory tags" value={tags} placeholder="Tags, separated by commas" onChange={(e) => setTags(e.target.value)} />
          <div className="row">
            <Button small kind="primary" onClick={() => void run(async () => { await api.patch(`/api/memory/${item.id}`, { text, tags: tags.split(',').map((tag) => tag.trim()).filter(Boolean) }); setEditing(false) })}>Save</Button>
            <Button small onClick={() => { setText(item.text); setTags(item.tags.join(', ')); setEditing(false) }}>Cancel</Button>
          </div>
        </div>
      ) : (
        <>
          <p>{item.text}</p>
          <div className="row">
            {item.tags.map((tag) => <Pill key={tag}>{tag}</Pill>)}
            <Pill tone={item.label === 'PERSONAL' ? 'warn' : 'mute'}>{item.label === 'PERSONAL' ? 'private' : 'shareable'}</Pill>
            <span className="hint">{item.source === 'agent' ? 'Lilly noted this' : 'You added this'} · {ago(item.at)}</span>
            <span className="grow" />
            <Button small onClick={() => void run(() => api.patch(`/api/memory/${item.id}`, { label: item.label === 'PERSONAL' ? 'PUBLIC' : 'PERSONAL' }))}>
              {item.label === 'PERSONAL' ? 'Make shareable' : 'Make private'}
            </Button>
            <IconButton icon="edit" label="Edit" onClick={() => setEditing(true)} />
            <IconButton icon="trash" label="Forget this" kind="danger" onClick={() => void run(() => api.del(`/api/memory/${item.id}`))} />
          </div>
        </>
      )}
    </li>
  )
}

export function Memory() {
  const [query, setQuery] = useState('')
  const [text, setText] = useState('')
  const [tags, setTags] = useState('')
  const [wipe, setWipe] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const list = useLoad<{ memory: MemoryItem[] }>(`/api/memory${query ? `?q=${encodeURIComponent(query)}` : ''}`, true)
  const toast = useApp((s) => s.toast)

  const add = async () => {
    try {
      await api.post('/api/memory', { text, tags: tags.split(',').map((tag) => tag.trim()).filter(Boolean) })
      setText('')
      setTags('')
      setError(null)
      list.reload()
    } catch (e) {
      setError(errorText(e))
    }
  }

  return (
    <div className="page">
      <PageHead
        title="Memory"
        sub="Short facts Lilly keeps about you. Private ones are only shown to models you allow."
        actions={<Button kind="danger" icon="trash" onClick={() => setWipe(true)}>Forget everything</Button>}
      />
      <form className="inline-form" onSubmit={(e) => { e.preventDefault(); void add() }}>
        <label className="sr-only" htmlFor="new-memory">Add a memory</label>
        <input id="new-memory" placeholder="For example: I prefer metric units" value={text} maxLength={8000} onChange={(e) => setText(e.target.value)} />
        <input aria-label="Memory tags" placeholder="Tags, separated by commas" value={tags} onChange={(e) => setTags(e.target.value)} />
        <Button type="submit" kind="primary" icon="plus" disabled={!text.trim()}>Remember</Button>
      </form>
      <ErrorNote text={error ?? list.error} />
      <input type="search" aria-label="Search memory" placeholder="Search memory" value={query} onChange={(e) => setQuery(e.target.value)} />
      {list.data?.memory.length === 0 && <Empty title="Nothing remembered yet">Add a fact above, or ask Lilly to remember something.</Empty>}
      <ul className="memory-list">{list.data?.memory.map((m) => <Row key={m.id} item={m} onChanged={list.reload} />)}</ul>
      {wipe && (
        <Confirm
          title="Forget everything?"
          danger
          confirm="Forget everything"
          body="This permanently deletes every memory. It cannot be undone."
          onClose={() => setWipe(false)}
          onConfirm={() => {
            api.post('/api/memory/clear', { confirm: 'forget everything' }).then(() => { list.reload(); toast('Memory cleared') }).catch((e: unknown) => toast(errorText(e), 'bad'))
          }}
        />
      )}
    </div>
  )
}
