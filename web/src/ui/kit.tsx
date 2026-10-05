import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { useEscape } from '../hooks'
import { useApp } from '../store'
import { STATE_LABEL } from './format'
import { Icon } from './Icon'

export function Button(props: {
  children: ReactNode
  onClick?: () => void
  kind?: 'primary' | 'quiet' | 'danger' | 'plain'
  icon?: string
  disabled?: boolean
  busy?: boolean
  type?: 'button' | 'submit'
  title?: string
  small?: boolean
}) {
  const { children, onClick, kind = 'plain', icon, disabled, busy, type = 'button', title, small } = props
  return (
    <button
      type={type}
      className={`btn btn-${kind}${small ? ' btn-small' : ''}`}
      onClick={onClick}
      disabled={disabled || busy}
      title={title}
      aria-busy={busy || undefined}
    >
      {icon && <Icon name={icon} size={small ? 15 : 17} />}
      <span>{children}</span>
    </button>
  )
}

export function IconButton(props: { icon: string; label: string; onClick?: () => void; disabled?: boolean; kind?: 'danger' }) {
  return (
    <button type="button" className={`icon-btn${props.kind ? ` icon-${props.kind}` : ''}`} onClick={props.onClick} disabled={props.disabled} aria-label={props.label} title={props.label}>
      <Icon name={props.icon} size={17} />
    </button>
  )
}

export function Switch(props: { checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string; disabled?: boolean }) {
  const id = useId()
  return (
    <div className="switch-row">
      <div className="switch-text">
        <label htmlFor={id}>{props.label}</label>
        {props.hint && <p className="hint" id={`${id}-h`}>{props.hint}</p>}
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={props.checked}
        aria-describedby={props.hint ? `${id}-h` : undefined}
        className="switch"
        disabled={props.disabled}
        onClick={() => props.onChange(!props.checked)}
      >
        <span className="switch-knob" />
      </button>
    </div>
  )
}

export function Field(props: { label: string; hint?: string; children: (id: string) => ReactNode; wide?: boolean }) {
  const id = useId()
  return (
    <div className={`field${props.wide ? ' field-wide' : ''}`}>
      <label htmlFor={id}>{props.label}</label>
      {props.children(id)}
      {props.hint && <p className="hint">{props.hint}</p>}
    </div>
  )
}

export function Segmented<T extends string | number>(props: {
  value: T
  onChange: (v: T) => void
  options: { value: T; label: string; hint?: string }[]
  label: string
}) {
  return (
    <div className="segmented" role="radiogroup" aria-label={props.label}>
      {props.options.map((o) => (
        <button
          key={String(o.value)}
          type="button"
          role="radio"
          aria-checked={props.value === o.value}
          className={props.value === o.value ? 'on' : ''}
          title={o.hint}
          onClick={() => props.onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function StatePill({ state }: { state: string }) {
  const tone = state === 'DONE' ? 'ok' : state === 'WAITING_APPROVAL' ? 'warn' : ['FAILED', 'EXPIRED'].includes(state) ? 'bad' : state === 'CANCELLED' ? 'mute' : 'live'
  return <span className={`pill pill-${tone}`}>{STATE_LABEL[state] ?? state}</span>
}

export function Pill({ children, tone = 'mute', title }: { children: ReactNode; tone?: 'ok' | 'warn' | 'bad' | 'mute' | 'live'; title?: string }) {
  return <span className={`pill pill-${tone}`} title={title}>{children}</span>
}

const FOCUSABLE = 'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'

/** A modal dialog. Focus starts on the `data-autofocus` element, else the first field, else the first button; Tab stays inside; closing returns focus. */
export function Dialog(props: { title: string; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null)
  const [opener] = useState(() => document.activeElement as HTMLElement | null)
  const titleId = useId()
  useEscape(props.onClose)
  useEffect(() => {
    const box = ref.current
    const first = box?.querySelector<HTMLElement>('[data-autofocus]') ?? box?.querySelector<HTMLElement>('.dialog-body input, .dialog-body textarea, .dialog-body select') ?? box?.querySelector<HTMLElement>('footer button')
    first?.focus()
    return () => opener?.focus()
  }, [opener])
  const trap = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'Tab') return
    const items = e.currentTarget.querySelectorAll<HTMLElement>(FOCUSABLE)
    const first = items[0]
    const last = items[items.length - 1]
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
  }
  return (
    <div className="scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) props.onClose() }}>
      <div className={`dialog${props.wide ? ' dialog-wide' : ''}`} role="dialog" aria-modal="true" aria-labelledby={titleId} ref={ref} onKeyDown={trap}>
        <header>
          <h2 id={titleId}>{props.title}</h2>
          <IconButton icon="x" label="Close" onClick={props.onClose} />
        </header>
        <div className="dialog-body">{props.children}</div>
        {props.footer && <footer>{props.footer}</footer>}
      </div>
    </div>
  )
}

export function Confirm(props: { title: string; body: ReactNode; confirm: string; danger?: boolean; onConfirm: () => void; onClose: () => void }) {
  return (
    <Dialog
      title={props.title}
      onClose={props.onClose}
      footer={
        <>
          <Button onClick={props.onClose}>Cancel</Button>
          <Button kind={props.danger ? 'danger' : 'primary'} onClick={() => { props.onConfirm(); props.onClose() }}>{props.confirm}</Button>
        </>
      }
    >
      <div className="prose">{props.body}</div>
    </Dialog>
  )
}

export function Empty(props: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{props.title}</h3>
      {props.children && <p>{props.children}</p>}
    </div>
  )
}

export function PageHead(props: { title: string; sub?: string; actions?: ReactNode }) {
  return (
    <header className="page-head">
      <div>
        <h1>{props.title}</h1>
        {props.sub && <p className="sub">{props.sub}</p>}
      </div>
      {props.actions && <div className="page-actions">{props.actions}</div>}
    </header>
  )
}

export function ErrorNote({ text }: { text: string | null }) {
  return text ? <p className="error-note" role="alert">{text}</p> : null
}

export function Toasts() {
  const toasts = useApp((s) => s.toasts)
  const dismiss = useApp((s) => s.dismiss)
  return (
    <div className="toasts" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast-${t.tone}`}>
          <span>{t.text}</span>
          <button type="button" aria-label="Dismiss" onClick={() => dismiss(t.id)}><Icon name="x" size={14} /></button>
        </div>
      ))}
    </div>
  )
}

export function Spinner() {
  return <span className="spinner" role="status" aria-label="Loading" />
}
