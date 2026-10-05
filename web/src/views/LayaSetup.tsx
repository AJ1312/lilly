import { useCallback, useState } from 'react'
import { api, errorText } from '../api'
import { useInterval, useLoad, type Loaded } from '../hooks'
import { useApp } from '../store'
import type { LayaCheckReply, LayaStatus, LayaTestReport } from '../types'
import { Button, Confirm, ErrorNote, Pill, Segmented, Switch } from '../ui/kit'
import type { SettingsDraft } from './settingsDraft'

type StepState = 'done' | 'now' | 'todo'
const STEP_PILL: Record<StepState, { text: string; tone: 'ok' | 'live' | 'mute' }> = {
  done: { text: 'Done', tone: 'ok' },
  now: { text: 'Next', tone: 'live' },
  todo: { text: 'Later', tone: 'mute' },
}

function Step({ n, title, state, children }: { n: number; title: string; state: StepState; children: React.ReactNode }) {
  return (
    <li className={`laya-step laya-step-${state}`}>
      <div className="row-between">
        <h4><span className="laya-step-n" aria-hidden="true">{n}</span> {title}</h4>
        <Pill tone={STEP_PILL[state].tone}>{STEP_PILL[state].text}</Pill>
      </div>
      <div className="stack laya-step-body">{children}</div>
    </li>
  )
}

function About() {
  return (
    <details className="laya-about">
      <summary>What Laya is, and what it is not</summary>
      <ul className="plain-list stack">
        <li><strong>What it is.</strong> A small classifier model. It answers a yes/no or pick-one question about a piece of text, with a confidence. Lilly uses it for three narrow questions: is a run going round in circles, does a text read like orders to the agent, which item of a short list does a wording mean.</li>
        <li><strong>What it is not.</strong> It cannot write text, run tools or approve anything. Every answer is advice that can only add caution; it can never widen what an agent may do.</li>
        <li><strong>What it costs.</strong> A download of about 850 MB (plus a few hundred MB of Python packages) kept in its own folder. It runs on your processor in its own process, needs about 2 GB of memory while loaded, loads only when a question needs it and unloads after about 90 seconds of quiet.</li>
        <li><strong>Without it.</strong> Lilly works fully. Simple rules answer the same questions, and anything they are unsure about goes to you or to the language model as before.</li>
      </ul>
    </details>
  )
}

function Checks({ check }: { check: Loaded<LayaCheckReply> }) {
  const c = check.data
  if (!c) return <ErrorNote text={check.error} />
  return (
    <>
      <ul className="plain-list stack laya-checks">
        {c.checks.map((x) => (
          <li key={x.name}>
            <Pill tone={x.ok ? 'ok' : 'bad'}>{x.ok ? 'OK' : 'Fix this'}</Pill> <strong>{x.name}.</strong> <span className={x.ok ? 'hint' : ''}>{x.detail}</span>
          </li>
        ))}
      </ul>
    </>
  )
}

function TestResults({ report }: { report: LayaTestReport }) {
  return (
    <div className="stack" role="status">
      {report.loaded && <p className="hint">Loaded in {(report.load_ms / 1000).toFixed(1)} s.</p>}
      {report.results.length > 0 && (
        <ul className="plain-list stack">
          {report.results.map((r) => (
            <li key={r.name}>
              <Pill tone={r.ok ? 'ok' : 'bad'}>{r.ok ? 'Right' : 'Wrong'}</Pill> <strong>{r.name}.</strong>{' '}
              <span className="hint">Expected “{r.expected}”, got “{r.got ?? 'no answer'}”{r.confidence !== null ? `, ${Math.round(r.confidence * 100)}% sure` : ''}, {r.ms} ms.</span>
            </li>
          ))}
        </ul>
      )}
      {report.ok ? <p><Pill tone="ok">Laya works</Pill> <span className="hint">The test did not turn it on.</span></p> : <p className="run-error" role="alert">{report.error}</p>}
    </div>
  )
}

/** Laya, step by step: check this computer, install, prove it works, turn it on. Each step follows what the server says is true now. */
function LayaGuide({ d, laya }: { d: SettingsDraft; laya: Loaded<LayaStatus> }) {
  const check = useLoad<LayaCheckReply>('/api/laya/check')
  const toast = useApp((s) => s.toast)
  const [busy, setBusy] = useState(false)
  const [testing, setTesting] = useState(false)
  const [report, setReport] = useState<LayaTestReport | null>(null)
  const [confirm, setConfirm] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const s = laya.data
  const reload = laya.reload
  useInterval(useCallback(() => { if (s?.installing) reload() }, [s?.installing, reload]), 1500)

  const act = async (run: () => Promise<unknown>, done?: string) => {
    setBusy(true)
    try {
      await run()
      setError(null)
      reload()
      await d.syncDecisions()
      if (done) toast(done)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  const runTest = async () => {
    setTesting(true)
    setReport(null)
    try {
      setReport(await api.post<LayaTestReport>('/api/laya/test'))
      setError(null)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setTesting(false)
    }
  }

  if (!s) return <ErrorNote text={laya.error} />
  const on = s.enabled_for.length > 0
  const fits = check.data?.ok ?? true
  const tested = report?.ok === true
  const stateOf = (done: boolean, ready: boolean): StepState => (done ? 'done' : ready ? 'now' : 'todo')
  const installState = s.installed ? 'done' : fits ? 'now' : 'todo'

  return (
    <section className="card stack" aria-labelledby="laya-h">
      <h3 id="laya-h">Laya</h3>
      <p className="hint">A small model that runs only on this computer and helps with a few quick yes/no and pick-one questions. Lilly works fully without it; these steps check this computer, install it and prove it works before anything relies on it.</p>
      <About />
      {s.note && <p className="hint">{s.note}</p>}
      <ErrorNote text={s.error ?? error} />
      <ol className="laya-steps">
        <Step n={1} title="Check this computer" state={stateOf(s.installed || check.data?.ok === true, true)}>
          <Checks check={check} />
          <div className="row"><Button small onClick={check.reload}>Check again</Button></div>
        </Step>
        <Step n={2} title="Download and install" state={installState}>
          <p className="hint">About {s.download_mb} MB for the model plus a few hundred MB of Python packages, kept in their own folder. Roughly 5 to 15 minutes on a typical connection; it carries on in the background if you leave this page.</p>
          {s.installing && <p><Pill tone="live">Installing…</Pill></p>}
          {s.installed && <p><Pill tone="ok">Installed</Pill> <span className="hint">Downloaded and ready on this computer.</span></p>}
          {s.progress.length > 0 && (s.installing || s.error) && <pre className="laya-log">{s.progress.join('\n')}</pre>}
          {!fits && !s.installed && <p className="hint" role="status">Fix the checks in step 1 first.</p>}
          <div className="row">
            {!s.installed && <Button kind="primary" busy={busy || s.installing} disabled={s.installing || !fits} onClick={() => void act(() => api.post('/api/laya/install'))}>{s.error ? 'Try again' : 'Download and install'}</Button>}
            {s.installed && <Button kind="danger" disabled={busy || testing} onClick={() => setConfirm(true)}>Remove</Button>}
          </div>
        </Step>
        <Step n={3} title="Test it" state={stateOf(tested, s.installed)}>
          <p className="hint">Loads Laya and asks it three questions whose answers are known: an order aimed at an agent, ordinary prose and a repeating list of steps. The first load can take a minute. It does not turn Laya on.</p>
          <div className="row"><Button busy={testing} disabled={!s.installed || testing} onClick={() => void runTest()}>{testing ? 'Testing…' : 'Run the test'}</Button></div>
          {report && <TestResults report={report} />}
        </Step>
        <Step n={4} title="Turn it on" state={stateOf(on, s.installed)}>
          <p className="hint">Once on, Laya is asked after the simple rules about loops, orders hidden in data and pick-one lists. It only adds caution: it can make Lilly more careful, never less. {s.installed && !tested && !on ? 'Testing first is recommended.' : ''}</p>
          <div className="row"><Button kind={on ? undefined : 'primary'} busy={busy} disabled={!s.installed} onClick={() => void act(() => api.put('/api/laya/enabled', { enabled: !on }), on ? 'Laya is off' : 'Laya is on')}>{on ? 'Turn off' : 'Turn on'}</Button></div>
          {on && <p className="hint">Model: {s.worker === 'ready' ? 'loaded' : s.worker === 'loading' ? 'loading' : 'asleep until needed'}</p>}
        </Step>
        <Step n={5} title="Optional: Laya assist" state={stateOf(false, on)}>
          <p className="hint">Laya can also judge a step before it runs and a reply afterwards. Both start as watch only. See the next card.</p>
        </Step>
      </ol>
      {confirm && (
        <Confirm title="Remove Laya?" danger confirm="Remove" body="Its files are deleted from this computer and it is turned off. Lilly works the same without it."
          onClose={() => setConfirm(false)} onConfirm={() => { setReport(null); void act(() => api.del('/api/laya'), 'Laya removed') }} />
      )}
    </section>
  )
}

type AssistKind = 'plan' | 'reply' | 'route'
const ASSIST: { id: AssistKind; label: string; hint: string; act: string }[] = [
  {
    id: 'plan',
    label: 'Check steps before they run',
    hint: 'Before a step that changes something runs on its own, Laya compares it with what you asked and with the agent’s instructions. Reading steps are never checked.',
    act: 'Ask me when Laya doubts',
  },
  {
    id: 'reply',
    label: 'Check replies afterwards',
    hint: 'Once a reply is shown, Laya checks it against your request and the agent’s instructions: topic, language, format and length. It never changes or holds back a reply.',
    act: 'Warn me when Laya doubts',
  },
  {
    id: 'route',
    label: 'Answer simple questions without tools',
    hint: 'When Laya judges a request needs nothing looked up or changed, a quick model answers it without being sent the tool list, which saves tokens. If that model asks for tools, the normal planner runs.',
    act: 'Use Laya to skip the tool list',
  },
]

/** Optional Laya questions. The first two judge what the language model did; the third saves tokens. Switching one on starts it as watch only. */
function AssistCard({ d, laya }: { d: SettingsDraft; laya: Loaded<LayaStatus> }) {
  const toast = useApp((s) => s.toast)
  const [busy, setBusy] = useState(false)
  const s = laya.data
  const cfg = d.current?.decisions
  if (!s || !cfg) return null
  const blocked = !s.installed ? 'Laya is not installed. Install it above to use these checks.' : s.enabled_for.length === 0 ? 'Laya is off. Turn it on above to use these checks.' : null

  const set = async (kind: AssistKind, enabled: boolean, act: boolean) => {
    setBusy(true)
    try {
      await api.put('/api/laya/assist', { kind, enabled, act })
      await d.syncDecisions()
    } catch (e) {
      toast(errorText(e), 'bad')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card stack" aria-labelledby="assist-h">
      <h3 id="assist-h">Laya assist (optional)</h3>
      <p className="hint">Have Laya judge what the language model does against what you asked. Laya can make a step ask you first, flag a reply, or skip the tool list for a simple question; it can never approve anything, change a reply or widen what an agent may do. It starts as watch only: its answers are recorded, not acted on, until you have seen how often it is right (<code>lilly decisions report</code>).</p>
      {blocked && <p className="hint" role="status">{blocked}</p>}
      {!blocked && !cfg.enabled && <p className="hint" role="status">Quick deciders are switched off above, so these checks do not run.</p>}
      {ASSIST.map((a) => {
        const on = cfg[a.id].chain.includes('laya')
        const acting = !cfg[a.id].shadow
        return (
          <div key={a.id} className="stack">
            <Switch label={a.label} hint={a.hint} checked={on} disabled={busy || blocked !== null} onChange={(v) => void set(a.id, v, false)} />
            {on && blocked === null && (
              <Segmented
                label={`${a.label}: what Laya may do`}
                value={acting ? 'act' : 'watch'}
                onChange={(v) => { if (!busy) void set(a.id, true, v === 'act') }}
                options={[
                  { value: 'watch', label: 'Watch only', hint: 'Record what Laya would have said and change nothing.' },
                  { value: 'act', label: a.act, hint: 'Use Laya’s answer. It can never allow more.' },
                ]}
              />
            )}
          </div>
        )
      })}
    </section>
  )
}

export function LayaSetup({ d }: { d: SettingsDraft }) {
  const laya = useLoad<LayaStatus>('/api/laya')
  return (
    <>
      <LayaGuide d={d} laya={laya} />
      <AssistCard d={d} laya={laya} />
    </>
  )
}
