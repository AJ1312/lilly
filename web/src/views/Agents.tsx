import { useState } from 'react'
import { api, errorText } from '../api'
import { useLoad } from '../hooks'
import { useApp } from '../store'
import { DEFAULT_LOOK, MAX_SKILLS, MODES, PET_ACCESSORIES, PET_EYES, type Agent, type ModelStatus, type PetLook } from '../types'
import { Pet, type PetState } from '../ui/Pet'
import { PET_IDS, PETS, speciesHue } from '../ui/petArt'
import { Button, Confirm, Dialog, Empty, ErrorNote, Field, IconButton, PageHead, Pill, Segmented, Switch } from '../ui/kit'

const BLANK: Omit<Agent, 'id'> = { name: '', instructions: '', mode: 1, research_allowed: true, memory_allowed: true, files_allowed: false, computer_allowed: false, chat_allowed: false, pet: 'lily', look: DEFAULT_LOOK, skills: '', model: '' }

const STATES: { value: PetState; label: string }[] = [
  { value: 'idle', label: 'Idle' },
  { value: 'thinking', label: 'Working' },
  { value: 'waiting', label: 'Waiting' },
  { value: 'done', label: 'Done' },
  { value: 'error', label: 'Error' },
]
const ACCESSORY_LABEL: Record<PetLook['accessory'], string> = { none: 'None', bow: 'Bow', glasses: 'Glasses', hat: 'Party hat', scarf: 'Scarf', crown: 'Crown', headphones: 'Headphones' }
const EYES_LABEL: Record<PetLook['eyes'], string> = { round: 'Round', sparkle: 'Sparkly', sleepy: 'Sleepy' }

function AgentDialog({ agent, onClose, onSaved }: { agent: Agent | null; onClose: () => void; onSaved: () => void }) {
  const [draft, setDraft] = useState<Omit<Agent, 'id'>>(agent ?? BLANK)
  const [error, setError] = useState<string | null>(null)
  const [preview, setPreview] = useState<PetState>('idle')
  const models = useLoad<{ models: ModelStatus[] }>('/api/models')
  const set = <K extends keyof typeof draft>(k: K, v: (typeof draft)[K]) => setDraft({ ...draft, [k]: v })
  const dress = <K extends keyof PetLook>(k: K, v: PetLook[K]) => setDraft({ ...draft, look: { ...draft.look, [k]: v } })
  const modelNames = models.data?.models.filter((m) => m.enabled).map((m) => m.name) ?? []
  const save = async () => {
    try {
      if (agent) await api.patch(`/api/agents/${agent.id}`, draft)
      else await api.post('/api/agents', draft)
      onSaved()
    } catch (e) {
      setError(errorText(e))
    }
  }
  return (
    <Dialog
      wide
      title={agent ? 'Edit agent' : 'New agent'}
      onClose={onClose}
      footer={<><Button onClick={onClose}>Cancel</Button><Button kind="primary" disabled={!draft.name.trim()} onClick={() => void save()}>Save</Button></>}
    >
      <div className="field">
        <span className="label">Pick a pet</span>
        <div className="pet-grid" role="radiogroup" aria-label="Pet">
          {PET_IDS.map((id) => (
            <button key={id} type="button" role="radio" aria-checked={draft.pet === id} className={`pet-pick${draft.pet === id ? ' on' : ''}`} onClick={() => set('pet', id)} title={PETS[id].blurb}>
              <Pet id={id} look={draft.look} size={52} state={draft.pet === id ? 'done' : 'idle'} />
              <span>{PETS[id].name}</span>
            </button>
          ))}
        </div>
      </div>
      <div className="pet-studio">
        <div className="pet-stage">
          <Pet id={draft.pet} look={draft.look} state={preview} size={128} label={`Preview of ${draft.name.trim() || 'your agent'}, ${PETS[draft.pet].name}, ${STATES.find((x) => x.value === preview)?.label.toLowerCase()}`} />
          <Segmented label="Preview state" value={preview} onChange={setPreview} options={STATES} />
        </div>
        <div className="pet-controls">
          <Field label="Colour">
            {(id) => (
              <div className="row">
                <input id={id} className="hue" type="range" min={0} max={359} step={1} value={draft.look.hue ?? speciesHue(draft.pet)} aria-valuetext={draft.look.hue === null ? 'Species colour' : `Hue ${draft.look.hue} degrees`} onChange={(e) => dress('hue', Number(e.target.value))} />
                <Button small disabled={draft.look.hue === null} onClick={() => dress('hue', null)}>Species colour</Button>
              </div>
            )}
          </Field>
          <Field label="Accessory">
            {(id) => (
              <select id={id} value={draft.look.accessory} onChange={(e) => dress('accessory', PET_ACCESSORIES.find((a) => a === e.target.value) ?? 'none')}>
                {PET_ACCESSORIES.map((a) => <option key={a} value={a}>{ACCESSORY_LABEL[a]}</option>)}
              </select>
            )}
          </Field>
          <div className="field">
            <span className="label">Eyes</span>
            <Segmented label="Eyes" value={draft.look.eyes} onChange={(v) => dress('eyes', v)} options={PET_EYES.map((e) => ({ value: e, label: EYES_LABEL[e] }))} />
          </div>
          <Switch label="Rosy cheeks" checked={draft.look.blush} onChange={(v) => dress('blush', v)} />
        </div>
      </div>
      <Field label="Name">{(id) => <input id={id} value={draft.name} maxLength={80} onChange={(e) => set('name', e.target.value)} />}</Field>
      <Field label="Instructions" hint="How this agent should behave, in plain words.">
        {(id) => <textarea id={id} rows={4} value={draft.instructions} maxLength={8000} onChange={(e) => set('instructions', e.target.value)} />}
      </Field>
      <Field label="Model" hint="A model you choose here is always used for this agent. If it is unavailable, the task fails with a clear message instead of switching to another one.">
        {(id) => (
          <select id={id} value={draft.model} onChange={(e) => set('model', e.target.value)}>
            <option value="">Automatic</option>
            {draft.model && !modelNames.includes(draft.model) && <option value={draft.model}>{draft.model} (not available)</option>}
            {modelNames.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        )}
      </Field>
      <Field label="Skills (skills.md)" hint={`What this agent knows how to do, in plain text or Markdown. It is added to every task of this agent, so it costs tokens each time. ${draft.skills.length} / ${MAX_SKILLS}`}>
        {(id) => <textarea id={id} rows={5} value={draft.skills} maxLength={MAX_SKILLS} spellCheck={false} onChange={(e) => set('skills', e.target.value)} />}
      </Field>
      <div className="field">
        <span className="label">How much freedom?</span>
        <Segmented label="Mode" value={draft.mode} onChange={(v) => set('mode', v)} options={MODES.map((m) => ({ value: m.value, label: m.name, hint: m.blurb }))} />
        <p className="hint">{MODES[draft.mode].blurb}</p>
      </div>
      <Switch label="Search the web" checked={draft.research_allowed} onChange={(v) => set('research_allowed', v)} />
      <Switch label="Use memory and notes" checked={draft.memory_allowed} onChange={(v) => set('memory_allowed', v)} />
      <Switch label="Work with files" hint="Only inside the folders you share in Settings → Privacy." checked={draft.files_allowed} onChange={(v) => set('files_allowed', v)} />
      <Switch
        label="Control this computer"
        hint="Open links and apps, list and stop programs, show notifications, run commands in a shared folder. Every single use still asks you first, even in Open mode. Needs Computer control turned on in Settings → Privacy & access."
        checked={draft.computer_allowed}
        onChange={(v) => set('computer_allowed', v)}
      />
      <Switch
        label="Reachable from chat apps"
        hint="Lets this agent answer messages from a chat app you have paired (Settings → Chat apps). Messages from outside are treated as untrusted, and anything that needs approval is shown to you with the exact action."
        checked={draft.chat_allowed}
        onChange={(v) => set('chat_allowed', v)}
      />
      <ErrorNote text={error} />
    </Dialog>
  )
}

export function Agents() {
  const list = useLoad<{ agents: Agent[] }>('/api/agents')
  const [editing, setEditing] = useState<Agent | 'new' | null>(null)
  const [removing, setRemoving] = useState<Agent | null>(null)
  const toast = useApp((s) => s.toast)
  return (
    <div className="page">
      <PageHead
        title="Your team"
        sub="Each agent has its own pet, instructions and permissions. Pick one when you start a chat; its pet shows what it is doing."
        actions={<Button kind="primary" icon="plus" onClick={() => setEditing('new')}>New agent</Button>}
      />
      <ErrorNote text={list.error} />
      {list.data?.agents.length === 0 && <Empty title="No agents yet">Lilly uses its default settings until you make one. Try a Locked “Researcher” that can only search the web, or a “Fixer” that may control this computer.</Empty>}
      <ul className="team">
        {list.data?.agents.map((a) => (
          <li key={a.id} className="teammate">
            <div className="teammate-pet"><Pet id={a.pet} look={a.look} size={84} state="idle" label={`${a.name}, a pet`} /></div>
            <div className="teammate-body">
              <div className="row between">
                <h3>{a.name}</h3>
                <div className="row">
                  <IconButton icon="edit" label={`Edit ${a.name}`} onClick={() => setEditing(a)} />
                  <IconButton icon="trash" label={`Delete ${a.name}`} kind="danger" onClick={() => setRemoving(a)} />
                </div>
              </div>
              <p className="clamp">{a.instructions || 'No special instructions.'}</p>
              <div className="row wrap">
                <Pill tone={a.mode === 2 ? 'warn' : 'mute'}>{MODES[a.mode].name}</Pill>
                {a.research_allowed && <Pill>web</Pill>}
                {a.memory_allowed && <Pill>memory</Pill>}
                {a.files_allowed && <Pill>files</Pill>}
                {a.computer_allowed && <Pill tone="warn">computer</Pill>}
                {a.chat_allowed && <Pill>chat</Pill>}
              </div>
            </div>
          </li>
        ))}
      </ul>
      {editing && <AgentDialog agent={editing === 'new' ? null : editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); list.reload() }} />}
      {removing && (
        <Confirm
          title={`Delete ${removing.name}?`}
          danger
          confirm="Delete"
          body="Past conversations keep their messages."
          onClose={() => setRemoving(null)}
          onConfirm={() => { api.del(`/api/agents/${removing.id}`).then(() => list.reload()).catch((e: unknown) => toast(errorText(e), 'bad')) }}
        />
      )}
    </div>
  )
}
