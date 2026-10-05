import { useId, useState, type KeyboardEvent } from 'react'
import { useLoad } from '../hooks'
import { NAV } from '../nav'
import type { Thread } from '../types'
import { Icon } from './Icon'
import { Dialog } from './kit'

export interface PaletteAction { id: string; label: string; icon: string; run: () => void }
interface Item { id: string; label: string; detail: string; icon: string; run: () => void }

const MAX_SHOWN = 9
const MAX_THREADS = 30

/** Jump to a view, a recent conversation or an action from the keyboard. Loads the conversation list only while open. */
export function Palette({ actions, go, onClose }: { actions: PaletteAction[]; go: (hash: string) => void; onClose: () => void }) {
  const threads = useLoad<{ threads: Thread[] }>('/api/threads?')
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const listId = useId()

  const items: Item[] = [
    ...actions.map((a) => ({ id: `a-${a.id}`, label: a.label, detail: 'Action', icon: a.icon, run: a.run })),
    ...NAV.map((n) => ({ id: `v-${n.path}`, label: n.label, detail: 'Go to', icon: n.icon, run: () => go(`/${n.path}`) })),
    ...(threads.data?.threads ?? []).slice(0, MAX_THREADS).map((t) => ({ id: `t-${t.id}`, label: t.title, detail: 'Conversation', icon: 'talk', run: () => go(`/talk/${t.id}`) })),
  ]
  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  const shown = items.filter((i) => words.every((w) => `${i.label} ${i.detail}`.toLowerCase().includes(w))).slice(0, MAX_SHOWN)
  const at = Math.min(active, Math.max(0, shown.length - 1))

  const choose = (item: Item | undefined) => { if (item) { onClose(); item.run() } }
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((at + 1) % Math.max(1, shown.length)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((at + shown.length - 1) % Math.max(1, shown.length)) }
    else if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); choose(shown[at]) }
  }

  return (
    <Dialog title="Jump to" onClose={onClose}>
      <input
        data-autofocus
        role="combobox"
        aria-expanded="true"
        aria-controls={listId}
        aria-activedescendant={shown[at] ? `${listId}-${shown[at].id}` : undefined}
        aria-label="Search views, conversations and actions"
        placeholder="Type to search…"
        value={query}
        onChange={(e) => { setQuery(e.target.value); setActive(0) }}
        onKeyDown={onKey}
      />
      <ul className="palette" id={listId} role="listbox" aria-label="Results">
        {shown.map((i, n) => (
          <li key={i.id} id={`${listId}-${i.id}`} role="option" aria-selected={n === at} className={n === at ? 'on' : ''} onMouseMove={() => setActive(n)} onClick={() => choose(i)}>
            <Icon name={i.icon} size={16} />
            <span className="clamp1">{i.label}</span>
            <small>{i.detail}</small>
          </li>
        ))}
      </ul>
      {shown.length === 0 && <p className="hint">Nothing matches “{query}”.</p>}
    </Dialog>
  )
}
