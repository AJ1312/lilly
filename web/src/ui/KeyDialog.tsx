import { useState } from 'react'
import { api, errorText } from '../api'
import { useApp } from '../store'
import { Button, Dialog, ErrorNote, Field } from './kit'

export function KeyDialog({ refName, present, onClose, onChanged, title }: { refName: string; present: boolean; onClose: () => void; onChanged: () => void; title?: string }) {
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)
  const toast = useApp((s) => s.toast)
  const save = async () => {
    try {
      await api.put(`/api/keys/${refName}`, { value })
      toast('Key saved')
      onChanged()
      onClose()
    } catch (e) {
      setError(errorText(e))
    }
  }
  const remove = async () => {
    try {
      await api.del(`/api/keys/${refName}`)
      toast('Key removed')
      onChanged()
      onClose()
    } catch (e) {
      setError(errorText(e))
    }
  }
  return (
    <Dialog
      title={title ?? `API key: ${refName}`}
      onClose={onClose}
      footer={<>{present && <Button kind="danger" onClick={() => void remove()}>Remove key</Button>}<Button onClick={onClose}>Cancel</Button><Button kind="primary" disabled={!value.trim()} onClick={() => void save()}>Save key</Button></>}
    >
      <p className="prose">Stored in your system keychain when there is one. It is never shown again and never written to settings or logs.</p>
      <Field label={present ? 'Replace the saved key' : 'Paste the key'}>{(id) => <input id={id} type="password" autoComplete="off" value={value} onChange={(e) => setValue(e.target.value)} />}</Field>
      <ErrorNote text={error} />
    </Dialog>
  )
}
