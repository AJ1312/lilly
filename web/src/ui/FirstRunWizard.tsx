import { useState } from 'react'
import { Button, Dialog } from './kit'

const STEPS = [
  ['Welcome', 'Lilly is ready to become your private coworker.'],
  ['Pet', 'Choose Lillys personality and visual state from Agents.'],
  ['Models', 'Connect a model or enable a local one in Settings -> Models & keys.'],
  ['Laya', 'Review fast routing and verification decisions in Settings -> Quick decisions.'],
  ['Permissions', 'Share only the folders and capabilities Lilly needs.'],
  ['Browser / Computer', 'Enable interactive control only when a task needs it.'],
  ['DevBox', 'Prepare the isolated execution environment for code tasks.'],
  ['Approval mode', 'Choose Manual, Auto, or Off. Hard policy always remains active.'],
  ['Health check', 'Open Settings -> About to confirm the local runtime is healthy.'],
  ['Ready', 'Start in Sessions and watch Lilly work from one task workspace.'],
] as const

export function FirstRunWizard({ onDone }: { onDone: () => void }) {
  const [step, setStep] = useState(0)
  const [open, setOpen] = useState(true)
  const finish = () => {
    localStorage.setItem('lilly.firstRunComplete', '2.0')
    setOpen(false)
    onDone()
  }
  if (!open) return null
  const [title, body] = STEPS[step]
  return (
    <Dialog title={'Getting started - ' + (step + 1) + '/' + STEPS.length} onClose={finish}
      footer={<>
        <Button onClick={finish}>Skip</Button>
        {step > 0 && <Button onClick={() => setStep(step - 1)}>Back</Button>}
        <Button kind="primary" icon={step === STEPS.length - 1 ? 'check' : 'arrow-right'} onClick={() => step === STEPS.length - 1 ? finish() : setStep(step + 1)}>
          {step === STEPS.length - 1 ? 'Ready' : 'Next'}
        </Button>
      </>}>
      <div className="wizard">
        <div className="wizard-progress" aria-label={'Step ' + (step + 1) + ' of ' + STEPS.length}>
          {STEPS.map((s, i) => <span key={s[0]} className={i <= step ? 'on' : ''} />)}
        </div>
        <h2>{title}</h2>
        <p>{body}</p>
      </div>
    </Dialog>
  )
}
