import { useState } from 'react'
import { api, errorText } from '../api'
import { useLoad } from '../hooks'
import { useApp } from '../store'
import type { KindSettings, Settings } from '../types'

type Reply = { settings: Settings; problems: string[] }

/** The decisions Laya's endpoints change on the server: only these are taken into a draft with unsaved edits. */
const LAYA_KINDS = ['loop', 'instructions', 'pick'] as const
/** Laya assist is switched through its own endpoint too, and its watch-only choice is part of the change. */
const ASSIST_KINDS = ['plan', 'reply', 'route'] as const

/** The settings being edited. Nothing is applied until the user saves. */
/** The chain of `fresh`, with the numbers that belong to it: a decider that left the chain must not keep a threshold, the server refuses those. Unsaved edits to the others stay. */
function withChain(draft: KindSettings, fresh: KindSettings): KindSettings {
  const only = (mine: Record<string, number>, theirs: Record<string, number>) =>
    Object.fromEntries(fresh.chain.flatMap((n) => { const v = mine[n] ?? theirs[n]; return v === undefined ? [] : [[n, v]] }))
  return { ...draft, chain: fresh.chain, min_confidence: only(draft.min_confidence, fresh.min_confidence), timeout_s: only(draft.timeout_s, fresh.timeout_s) }
}

export function useSettingsDraft() {
  const loaded = useLoad<Reply>('/api/settings')
  const [draft, setDraft] = useState<Settings | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saves, setSaves] = useState(0)
  const toast = useApp((s) => s.toast)
  const bump = useApp((s) => s.bump)
  const saved = loaded.data?.settings ?? null
  const current = draft ?? saved
  const dirty = draft !== null && JSON.stringify(draft) !== JSON.stringify(saved)

  const edit = (change: (s: Settings) => Settings) => {
    if (current) setDraft(change(current))
  }

  const save = async () => {
    if (!current) return
    setSaving(true)
    try {
      loaded.replace(await api.put<Reply>('/api/settings', current))
      setDraft(null)
      setError(null)
      setSaves((n) => n + 1)
      bump()
      toast('Settings saved')
    } catch (e) {
      setError(errorText(e))
    } finally {
      setSaving(false)
    }
  }

  /** Laya is switched on or off on the server directly. Take its chains into the draft, or saving would undo it, and keep every other unsaved edit. */
  const syncDecisions = async () => {
    try {
      const reply = await api.get<Reply>('/api/settings')
      const fresh = reply.settings
      loaded.replace(reply)
      setDraft((prev) => {
        if (!prev) return prev
        const decisions = { ...prev.decisions }
        for (const k of LAYA_KINDS) decisions[k] = withChain(decisions[k], fresh.decisions[k])
        for (const k of ASSIST_KINDS) decisions[k] = { ...withChain(decisions[k], fresh.decisions[k]), shadow: fresh.decisions[k].shadow }
        return { ...prev, decisions }
      })
    } catch {
      loaded.reload() // the server changed but we could not read it: start again from what it holds
      setDraft(null)
    }
  }

  const revert = () => {
    setDraft(null)
    setError(null)
  }

  return { current, edit, dirty, save, saves, revert, syncDecisions, saving, error, problems: loaded.data?.problems ?? [], loadError: loaded.error }
}

export type SettingsDraft = ReturnType<typeof useSettingsDraft>
