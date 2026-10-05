import { useEffect, useId, useRef, useState, type CSSProperties, type PointerEvent, type ReactNode } from 'react'
import { DEFAULT_LOOK, PET_ACCESSORIES, PET_EYES, type PetLook } from '../types'
import { ACCESSORIES, INK, PETS, petColors, type PetDef } from './petArt'

/**
 * A pet: a small original character drawn as layered SVG (back, body, face, accessory) inside a CSS 3D box, so
 * it leans toward the pointer while the pointer is over it. It shows what its agent is doing: idle, thinking
 * (working), waiting (needs your approval), done, or error. Motion is CSS only and stops for reduced motion.
 */
export type PetState = 'idle' | 'thinking' | 'waiting' | 'done' | 'error'

const LINE = { stroke: 'var(--pet-line)', strokeWidth: 1.7, strokeLinejoin: 'round', strokeLinecap: 'round' } as const
const TILT_DEG = 16
const TILT_EVERY_MS = 40
const REDUCED_MOTION = window.matchMedia('(prefers-reduced-motion: reduce)')
const GAZE = 2.2        // how far (in drawing units) the pupils may move toward the pointer
const POKE_MS = 700     // how long a pet stays happy after being tapped

/** Every pet on screen, so one pointer listener can turn all their eyes toward the pointer (and none runs when no pet is shown). */
const watchers = new Set<HTMLElement>()
let frame = 0
let pointer: { x: number; y: number } | null = null
function aim() {
  frame = 0
  if (!pointer) return
  for (const el of watchers) {
    const box = el.getBoundingClientRect()
    const dx = pointer.x - (box.left + box.width / 2)
    const dy = pointer.y - (box.top + box.height / 2)
    const d = Math.hypot(dx, dy) || 1
    const pull = Math.min(1, d / 160)          // far away the eyes look fully toward it, close up they settle in the middle
    el.style.setProperty('--ex', ((dx / d) * GAZE * pull).toFixed(2))
    el.style.setProperty('--ey', ((dy / d) * GAZE * pull).toFixed(2))
  }
}
function onPointer(e: globalThis.PointerEvent) {
  if (e.pointerType === 'touch') return
  pointer = { x: e.clientX, y: e.clientY }
  if (!frame) frame = requestAnimationFrame(aim)
}
function follow(el: HTMLElement): () => void {
  if (REDUCED_MOTION.matches) return () => undefined
  if (watchers.size === 0) window.addEventListener('pointermove', onPointer, { passive: true })
  watchers.add(el)
  return () => {
    watchers.delete(el)
    if (watchers.size === 0) {
      window.removeEventListener('pointermove', onPointer)
      pointer = null
    }
  }
}

/** A look from the server or a stale cache: anything missing or unknown falls back to the default. */
function petLook(look: Partial<PetLook> | null | undefined): PetLook {
  const hue = typeof look?.hue === 'number' && Number.isFinite(look.hue) ? ((Math.round(look.hue) % 360) + 360) % 360 : null
  return {
    hue,
    accessory: PET_ACCESSORIES.find((a) => a === look?.accessory) ?? DEFAULT_LOOK.accessory,
    eyes: PET_EYES.find((e) => e === look?.eyes) ?? DEFAULT_LOOK.eyes,
    blush: typeof look?.blush === 'boolean' ? look.blush : DEFAULT_LOOK.blush,
  }
}

const star = (x: number, y: number, r: number) =>
  `M${x} ${y - r}L${x + r / 3} ${y - r / 3}L${x + r} ${y}L${x + r / 3} ${y + r / 3}L${x} ${y + r}L${x - r / 3} ${y + r / 3}L${x - r} ${y}L${x - r / 3} ${y - r / 3}z`

/** The glossy open eye: a big dark pupil with highlights. */
function Pupil({ x, y, eyes }: { x: number; y: number; eyes: PetLook['eyes'] }) {
  const shine = { fill: '#fff', stroke: 'none' } as const
  switch (eyes) {
    case 'sleepy':
      return (
        <g>
          <path d={`M${x - 4.2} ${y - 0.5}a4.2 4.2 0 008.4 0z`} fill={INK} stroke={INK} strokeWidth="1.4" />
          <circle cx={x - 1.5} cy={y + 1.7} r="1.1" {...shine} />
        </g>
      )
    case 'sparkle':
      return (
        <g>
          <circle cx={x} cy={y} r="5.4" fill={INK} stroke="none" />
          <circle cx={x - 1.8} cy={y - 2} r="2.3" {...shine} />
          <path d={star(x + 2, y + 2, 1.5)} {...shine} />
        </g>
      )
    default:
      return (
        <g>
          <circle cx={x} cy={y} r="5" fill={INK} stroke="none" />
          <circle cx={x - 1.7} cy={y - 1.9} r="2" {...shine} />
          <circle cx={x + 2} cy={y + 2} r="1" {...shine} fillOpacity=".85" />
        </g>
      )
  }
}

function Eyes({ pet, state, eyes }: { pet: PetDef; state: PetState; eyes: PetLook['eyes'] }) {
  const [lx, ly, rx, ry] = pet.eyes
  const at = (x: number, y: number) => {
    switch (state) {
      case 'done':
        return <path key={x} d={`M${x - 3.8} ${y + 1.6}Q${x} ${y - 4.2} ${x + 3.8} ${y + 1.6}`} fill="none" stroke={INK} strokeWidth="2.4" />
      case 'error':
        return <path key={x} d={`M${x - 3} ${y - 3}l6 6M${x + 3} ${y - 3}l-6 6`} stroke={INK} strokeWidth="2.4" />
      case 'waiting':
        return (
          <g key={x}>
            <circle cx={x} cy={y} r="5.2" fill="#fff" strokeWidth="1.4" />
            <circle cx={x} cy={y} r="2.8" fill={INK} stroke="none" />
            <circle cx={x - 0.9} cy={y - 1} r="0.9" fill="#fff" stroke="none" />
          </g>
        )
      case 'thinking':
        return <g key={x}><Pupil x={x + 1.5} y={y - 1.5} eyes={eyes} /></g>
      default:
        return <g key={x} className="pet-eye"><g className="pet-look"><Pupil x={x} y={y} eyes={eyes} /></g></g>
    }
  }
  return <g>{at(lx, ly)}{at(rx, ry)}</g>
}

function Mouth({ pet, state }: { pet: PetDef; state: PetState }) {
  const y = pet.mouth
  if (y === null) return null
  const common = { fill: 'none', stroke: INK, strokeWidth: 1.8 } as const
  switch (state) {
    case 'done':
      return <path d={`M26 ${y - 1}Q32 ${y + 7} 38 ${y - 1}Z`} {...common} fill="#fff" />
    case 'error':
      return <path d={`M27 ${y + 3}Q32 ${y - 2} 37 ${y + 3}`} {...common} />
    case 'waiting':
      return <ellipse cx="32" cy={y + 1} rx="2.5" ry="3" fill={INK} stroke="none" />
    case 'thinking':
      return <path d={`M28 ${y + 1}h8`} {...common} />
    default:
      return <path d={`M27.5 ${y}Q29.75 ${y + 4} 32 ${y}Q34.25 ${y + 4} 36.5 ${y}`} {...common} />
  }
}

const heart = (x: number, y: number, s: number) =>
  `M${x} ${y + 4 * s}C${x - 7 * s} ${y - s} ${x - 3 * s} ${y - 6 * s} ${x} ${y - 2.5 * s}C${x + 3 * s} ${y - 6 * s} ${x + 7 * s} ${y - s} ${x} ${y + 4 * s}z`

function Overlay({ state, poked }: { state: PetState; poked: boolean }) {
  if (poked) {
    return (
      <g fill="#ff5c85" stroke="none">
        <path className="pet-heart pet-heart-1" d={heart(46, 14, 1.3)} />
        <path className="pet-heart pet-heart-2" d={heart(18, 12, 0.9)} />
      </g>
    )
  }
  switch (state) {
    case 'thinking':
      return (
        <g fill="var(--ink-2)" stroke="none">
          <circle className="pet-dot pet-dot-1" cx="47" cy="7" r="2.2" />
          <circle className="pet-dot pet-dot-2" cx="53" cy="7" r="2.2" />
          <circle className="pet-dot pet-dot-3" cx="59" cy="7" r="2.2" />
        </g>
      )
    case 'waiting':
      return (
        <g className="pet-bang">
          <circle cx="54" cy="10" r="8" fill="#f08a24" stroke={INK} strokeWidth="1.6" />
          <path d="M54 5.5v6" stroke="#fff" strokeWidth="2.6" />
          <circle cx="54" cy="14.8" r="1.5" fill="#fff" stroke="none" />
        </g>
      )
    case 'done':
      return <path className="pet-spark" d="M54 2l2 6 6 2-6 2-2 6-2-6-6-2 6-2z" fill="#ffd34d" stroke={INK} strokeWidth="1.3" />
    case 'error':
      return <path className="pet-sweat" d="M52 14c3 4 4 6 4 8a4 4 0 01-8 0c0-2 1-4 4-8z" fill="#8ec9f2" stroke={INK} strokeWidth="1.5" />
    default:
      return null
  }
}

function Layer({ name, children }: { name: string; children: ReactNode }) {
  return (
    <svg className={`pet-layer pet-${name}`} viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <g {...LINE}>{children}</g>
    </svg>
  )
}

export function Pet({ id, state = 'idle', size = 56, label, look }: { id: string; state?: PetState; size?: number; label?: string; look?: Partial<PetLook> | null }) {
  const pet = PETS[id] ?? PETS.lily
  const { hue, accessory, eyes, blush } = petLook(look)
  const uid = useId()
  const tilt = useRef<HTMLSpanElement>(null)
  const root = useRef<HTMLSpanElement>(null)
  const [poked, setPoked] = useState(false)
  useEffect(() => (root.current ? follow(root.current) : undefined), [])
  useEffect(() => {
    if (!poked) return
    const timer = setTimeout(() => setPoked(false), POKE_MS)
    return () => clearTimeout(timer)
  }, [poked])
  const last = useRef(0)

  const lean = (e: PointerEvent<HTMLSpanElement>) => {
    if (REDUCED_MOTION.matches || e.pointerType === 'touch' || e.timeStamp - last.current < TILT_EVERY_MS) return
    last.current = e.timeStamp
    const box = e.currentTarget.getBoundingClientRect()
    const nx = Math.min(1, Math.max(-1, ((e.clientX - box.left) / box.width) * 2 - 1))
    const ny = Math.min(1, Math.max(-1, ((e.clientY - box.top) / box.height) * 2 - 1))
    tilt.current?.style.setProperty('--ry', `${nx * TILT_DEG}deg`)
    tilt.current?.style.setProperty('--rx', `${-ny * TILT_DEG}deg`)
  }
  const rest = () => {
    tilt.current?.style.removeProperty('--rx')
    tilt.current?.style.removeProperty('--ry')
  }

  const style = { '--s': `${size}px`, ...petColors(pet, hue) } as CSSProperties
  const [cl, cr, cy] = pet.cheeks
  const Dress = accessory === 'none' ? null : ACCESSORIES[accessory]
  const clip = `${uid}-clip`
  return (
    <span
      ref={root}
      className="pet"
      data-state={state}
      data-poked={poked || undefined}
      onPointerDown={() => { if (!REDUCED_MOTION.matches) setPoked(true) }}
      style={style}
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      onPointerMove={lean}
      onPointerLeave={rest}
    >
      <span className="pet-shadow" />
      <span className="pet-tilt" ref={tilt}>
        <span className="pet-bob">
          {pet.back && <Layer name="back">{pet.back}</Layer>}
          <Layer name="body">
            <defs>
              <radialGradient id={`${uid}-shade`} cx=".36" cy=".3" r=".85">
                <stop offset="0" stopColor="#fff" stopOpacity=".5" />
                <stop offset=".4" stopColor="#fff" stopOpacity="0" />
                <stop offset=".55" stopColor="#1d2b24" stopOpacity="0" />
                <stop offset="1" stopColor="#1d2b24" stopOpacity=".24" />
              </radialGradient>
              <linearGradient id={`${uid}-rim`} x1="0" y1="0" x2="1" y2="1">
                <stop offset=".5" stopColor="#fff" stopOpacity="0" />
                <stop offset="1" stopColor="#fff" stopOpacity=".8" />
              </linearGradient>
              <clipPath id={clip}><path d={pet.body} /></clipPath>
            </defs>
            <path d={pet.body} fill="var(--pf)" />
            <path d={pet.body} fill={`url(#${uid}-shade)`} stroke="none" />
            <path d={pet.body} fill="none" stroke={`url(#${uid}-rim)`} strokeWidth="4" clipPath={`url(#${clip})`} />
          </Layer>
          <Layer name="face">
            {pet.front}
            {blush && (
              <g fill="#ff6f8f" fillOpacity=".38" stroke="none">
                <ellipse cx={cl} cy={cy} rx="3.6" ry="2.2" />
                <ellipse cx={cr} cy={cy} rx="3.6" ry="2.2" />
              </g>
            )}
            <Eyes pet={pet} state={state} eyes={eyes} />
            <Mouth pet={pet} state={state} />
          </Layer>
          <Layer name="top">
            {Dress?.(pet)}
            <Overlay state={state} poked={poked} />
          </Layer>
        </span>
      </span>
    </span>
  )
}
