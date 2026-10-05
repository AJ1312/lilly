import { useState } from 'react'
import { ApiError, api, errorText } from '../api'
import { useLoad } from '../hooks'
import { useApp } from '../store'
import type { Page, Space } from '../types'
import { Button, Confirm, Dialog, Empty, ErrorNote, Field, IconButton, PageHead } from '../ui/kit'
import { ago } from '../ui/format'

function NoteForm({ page, spaceId, onSaved, onGone, onConflict }: { page: Page; spaceId: string; onSaved: () => void; onGone: () => void; onConflict: () => void }) {
  const [title, setTitle] = useState(page.title)
  const [content, setContent] = useState(page.content ?? '')
  const [revision, setRevision] = useState(page.revision)
  const [saved, setSaved] = useState({ title: page.title, content: page.content ?? '' })
  const [error, setError] = useState<string | null>(null)
  const [conflict, setConflict] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const [saving, setSaving] = useState(false)
  const toast = useApp((s) => s.toast)
  const dirty = title !== saved.title || content !== saved.content
  const canSave = dirty && title.trim() !== '' && !saving

  const save = async () => {
    if (!canSave) return
    setSaving(true)
    try {
      const r = await api.put<{ page: Page }>(`/api/spaces/${spaceId}/pages/${page.id}`, { revision, title, content })
      setRevision(r.page.revision)
      setSaved({ title, content })
      setError(null)
      onSaved()
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setConflict(true)
      setError(errorText(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="editor" onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === 's') { e.preventDefault(); void save() } }}>
      <div className="editor-bar">
        <label className="sr-only" htmlFor="note-title">Title</label>
        <input id="note-title" className="editor-title" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />
        <span className="hint">{dirty ? 'Unsaved changes' : `Saved · ${ago(page.updated_at)}`}</span>
        <Button kind="primary" disabled={!canSave} onClick={() => void save()}>Save</Button>
        <IconButton icon="trash" label="Delete note" kind="danger" onClick={() => setConfirm(true)} />
      </div>
      <label className="sr-only" htmlFor="note-body">Note</label>
      <textarea id="note-body" className="editor-body" value={content} onChange={(e) => setContent(e.target.value)} placeholder="Write here. Lilly can search your notes when you let it." />
      <ErrorNote text={error} />
      {conflict && <Button onClick={onConflict}>Load the newer version (discards your edits)</Button>}
      {confirm && (
        <Confirm
          title="Delete this note?"
          danger
          confirm="Delete"
          body="The note is deleted for good."
          onClose={() => setConfirm(false)}
          onConfirm={() => { api.del(`/api/spaces/${spaceId}/pages/${page.id}`).then(() => { onSaved(); onGone() }).catch((e: unknown) => toast(errorText(e), 'bad')) }}
        />
      )}
    </div>
  )
}

function Editor({ spaceId, pageId, onChanged, onGone }: { spaceId: string; pageId: string; onChanged: () => void; onGone: () => void }) {
  const loaded = useLoad<{ page: Page }>(`/api/spaces/${spaceId}/pages/${pageId}`)
  const page = loaded.data?.page
  if (!page) return <ErrorNote text={loaded.error} />
  // A new revision from the server remounts the form, so its fields start from what is saved.
  return <NoteForm key={`${page.id}:${page.revision}`} page={page} spaceId={spaceId} onSaved={onChanged} onGone={onGone} onConflict={loaded.reload} />
}

function SpaceDialog({ space, onClose, onSaved }: { space: Space | null; onClose: () => void; onSaved: (s: Space) => void }) {
  const [name, setName] = useState(space?.name ?? '')
  const [description, setDescription] = useState(space?.description ?? '')
  const [error, setError] = useState<string | null>(null)
  const save = async () => {
    try {
      const r = space
        ? await api.patch<{ space: Space }>(`/api/spaces/${space.id}`, { name, description })
        : await api.post<{ space: Space }>('/api/spaces', { name, description })
      onSaved(r.space)
    } catch (e) {
      setError(errorText(e))
    }
  }
  return (
    <Dialog title={space ? 'Edit space' : 'New space'} onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button kind="primary" disabled={!name.trim()} onClick={() => void save()}>Save</Button></>}>
      <Field label="Name">{(id) => <input id={id} value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />}</Field>
      <Field label="What is it for? (optional)">{(id) => <input id={id} value={description} maxLength={1000} onChange={(e) => setDescription(e.target.value)} />}</Field>
      <ErrorNote text={error} />
    </Dialog>
  )
}

export function Notes() {
  const spaces = useLoad<{ spaces: Space[] }>('/api/spaces')
  const [pickedSpace, setSpaceId] = useState<string | null>(null)
  const [pageId, setPageId] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [dialog, setDialog] = useState<'new' | 'edit' | null>(null)
  const [confirmSpace, setConfirmSpace] = useState(false)
  const toast = useApp((s) => s.toast)
  const spaceId = pickedSpace ?? spaces.data?.spaces[0]?.id ?? null
  const current = spaces.data?.spaces.find((s) => s.id === spaceId) ?? null

  const pages = useLoad<{ pages: Page[] }>(query ? `/api/pages?q=${encodeURIComponent(query)}` : spaceId ? `/api/spaces/${spaceId}/pages` : null)

  const newNote = async () => {
    if (!spaceId) return
    try {
      const r = await api.post<{ page: Page }>(`/api/spaces/${spaceId}/pages`, { title: 'Untitled note', content: '' })
      pages.reload()
      setPageId(r.page.id)
    } catch (e) {
      toast(errorText(e), 'bad')
    }
  }

  const openPage = (p: Page) => { setSpaceId(p.space_id); setPageId(p.id) }

  return (
    <div className="page page-wide">
      <PageHead title="Notes" sub="Your own writing. Lilly can search it only when an agent is allowed to." actions={<Button icon="plus" onClick={() => setDialog('new')}>New space</Button>} />
      <ErrorNote text={spaces.error} />
      {spaces.data?.spaces.length === 0 && <Empty title="No notes yet">Create a space to start. Think of it as a folder for one topic.</Empty>}
      {spaces.data && spaces.data.spaces.length > 0 && (
        <div className="notes">
          <aside className="notes-side">
            <div className="chips" role="tablist" aria-label="Spaces">
              {spaces.data.spaces.map((s) => (
                <button key={s.id} type="button" role="tab" aria-selected={s.id === spaceId} className={s.id === spaceId ? 'chip on' : 'chip'} onClick={() => { setSpaceId(s.id); setPageId(null); setQuery('') }}>{s.name}</button>
              ))}
            </div>
            {current && (
              <div className="row">
                <Button small onClick={() => setDialog('edit')}>Rename space</Button>
                <Button small kind="danger" onClick={() => setConfirmSpace(true)}>Delete space</Button>
              </div>
            )}
            <input type="search" aria-label="Search all notes" placeholder="Search all notes" value={query} onChange={(e) => setQuery(e.target.value)} />
            <Button icon="plus" onClick={() => void newNote()} disabled={!spaceId}>New note</Button>
            <ul className="page-list">
              {pages.data?.pages.map((p) => (
                <li key={p.id} className={p.id === pageId ? 'current' : ''}>
                  <button type="button" onClick={() => openPage(p)}><strong>{p.title}</strong><span className="hint">{ago(p.updated_at)}</span></button>
                </li>
              ))}
              {pages.data?.pages.length === 0 && <li className="thread-empty">{query ? 'No notes match.' : 'No notes in this space yet.'}</li>}
            </ul>
          </aside>
          <section className="notes-main">
            {spaceId && pageId ? <Editor key={pageId} spaceId={spaceId} pageId={pageId} onChanged={pages.reload} onGone={() => setPageId(null)} /> : <Empty title="Pick or create a note" />}
          </section>
        </div>
      )}
      {dialog && <SpaceDialog space={dialog === 'edit' ? current : null} onClose={() => setDialog(null)} onSaved={(s) => { setDialog(null); setSpaceId(s.id); spaces.reload() }} />}
      {confirmSpace && current && (
        <Confirm
          title={`Delete “${current.name}”?`}
          danger
          confirm="Delete space and notes"
          body="Every note in this space is deleted for good."
          onClose={() => setConfirmSpace(false)}
          onConfirm={() => { api.del(`/api/spaces/${current.id}`).then(() => { setSpaceId(null); setPageId(null); spaces.reload() }).catch((e: unknown) => toast(errorText(e), 'bad')) }}
        />
      )}
    </div>
  )
}
