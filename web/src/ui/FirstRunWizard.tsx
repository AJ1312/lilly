import { useState } from 'react'
import { api, errorText } from '../api'
import { Button, Dialog, ErrorNote } from './kit'

type Step = { title: string; body: string; checkPath?: string; checkLabel?: string }

const STEPS: Step[] = [
  { title: 'Welcome', body: 'Lilly is ready to become your private coworker.' },
  { title: 'Pet', body: 'Choose Lillys personality and visual state from Agents.' },
  { title: 'Models / Providers', body: 'Connect a provider or enable a local model in Settings -> Models & keys.', checkPath: '/api/models', checkLabel: 'model registry' },
  { title: 'Laya', body: 'Review fast routing and verification decisions in Settings -> Quick decisions.' },
  { title: 'Local Model', body: 'Enable a local model when tasks should stay on this computer.' },
  { title: 'Permissions', body: 'Share only the folders and capabilities Lilly needs.' },
  { title: 'Browser / Computer', body: 'Enable interactive control only when a task needs it.' },
  { title: 'DevBox / Security', body: 'Review the isolated execution and policy settings before running code.' },
  { title: 'Approval Mode', body: 'Choose MANUAL, AUTO, or OFF. Hard policy always remains active.' },
  { title: 'Notifications', body: 'Choose how you want to notice approvals, recovery, and completed tasks.' },
  { title: 'Health Check', body: 'Confirm the local runtime is healthy before the first task.', checkPath: '/api/system', checkLabel: 'runtime' },
  { title: 'Ready', body: 'Start in Sessions and watch Lilly work from one task workspace.' },
]

const STEP_KEY = 'lilly.firstRunStep'
const COMPLETE_KEY = 'lilly.firstRunComplete'

function savedStep(): number {
  const value = Number(localStorage.getItem(STEP_KEY))
  return Number.isInteger(value) && value >= 0 && value < STEPS.length ? value : 0
}

export function FirstRunWizard({ onDone }: { onDone: () => void }) {
  const [step, setStep] = useState(savedStep)
  const [open, setOpen] = useState(true)
  const [busy, setBusy] = useState(false)
  const [checkError, setCheckError] = useState<string | null>(null)
  const current = STEPS[step]

  const pause = () => {
    localStorage.setItem(STEP_KEY, String(step))
    setOpen(false)
    onDone()
  }

  const finish = () => {
    localStorage.setItem(COMPLETE_KEY, '2.0')
    localStorage.removeItem(STEP_KEY)
    setOpen(false)
    onDone()
  }

  const next = async () => {
    setCheckError(null)
    if (current.checkPath) {
      setBusy(true)
      try {
        await api.get<unknown>(current.checkPath)
      } catch (error) {
        setCheckError(`Could not validate the ${current.checkLabel ?? 'configuration'}: ${errorText(error)}`)
        setBusy(false)
        return
      }
      setBusy(false)
    }
    if (step === STEPS.length - 1) finish()
    else {
      const following = step + 1
      localStorage.setItem(STEP_KEY, String(following))
      setStep(following)
    }
  }

  if (!open) return null
  return (
    <Dialog title={'Getting started - ' + (step + 1) + '/' + STEPS.length} onClose={pause}
      footer={<>
        <Button onClick={pause}>Later</Button>
        {step > 0 && <Button onClick={() => { setCheckError(null); setStep(step - 1); localStorage.setItem(STEP_KEY, String(step - 1)) }}>Back</Button>}
        <Button kind="primary" icon={step === STEPS.length - 1 ? 'check' : 'arrow-right'} onClick={() => void next()} busy={busy}>
          {step === STEPS.length - 1 ? 'Finish setup' : 'Next'}
        </Button>
      </>}>
      <div className="wizard">
        <div className="wizard-progress" aria-label={'Step ' + (step + 1) + ' of ' + STEPS.length}>
          {STEPS.map((item, index) => <span key={item.title} className={index <= step ? 'on' : ''} />)}
        </div>
        <h2>{current.title}</h2>
        <p>{current.body}</p>
        {current.checkPath && <p className="hint">The Next button checks the {current.checkLabel} before continuing.</p>}
        <ErrorNote text={checkError} />
      </div>
    </Dialog>
  )
}
