import type { ReactNode } from 'react'
import type { PetLook } from '../types'

/**
 * The art of Lilly's pets, as data. Everything is drawn on a 64 x 64 board. Colours come from the CSS variables
 * --pf (body), --pa (accent) and --pl (a third shade), so a hue can recolour a pet without touching the drawing.
 * Accessories are placed from each species' anchors, so adding a species means adding a row here.
 */
export const INK = 'var(--pet-ink)'

/** [x, y, width] of the head's top, of its widest part at ear height, and [y, width] of the chin. */
type Anchor3 = [number, number, number]
export interface PetDef {
  name: string
  blurb: string
  palette: { fill: string; accent: string; alt?: string }
  eyes: [number, number, number, number] // left x, left y, right x, right y
  mouth: number | null // y of the mouth, or null when the pet has a beak or no mouth
  cheeks: [number, number, number] // left x, right x, y
  top: Anchor3
  side: Anchor3
  chin: [number, number]
  back?: ReactNode
  body: string
  front?: ReactNode
}

export const PETS: Record<string, PetDef> = {
  lily: {
    name: 'Lily', blurb: 'A little tiger lily', palette: { fill: '#fff1d6', accent: '#c4401a', alt: '#e0582c' },
    eyes: [23, 41, 41, 41], mouth: 48, cheeks: [17.5, 46.5, 46], top: [32, 20, 24], side: [32, 40, 44], chin: [52, 34],
    back: (
      <>
        <path d="M32 3c7 8 7 15 0 23-7-8-7-15 0-23z" fill="var(--pa)" />
        <path d="M13 11c9 1 15 8 15 15-9 0-15-6-15-15z" fill="var(--pl)" />
        <path d="M51 11c-9 1-15 8-15 15 9 0 15-6 15-15z" fill="var(--pl)" />
      </>
    ),
    body: 'M32 20c14 0 22 10 22 20 0 12-10 18-22 18S10 52 10 40c0-10 8-20 22-20z',
  },
  pip: {
    name: 'Pip', blurb: 'A round, curious chick', palette: { fill: '#ffd966', accent: '#f08a24', alt: '#ffc83d' },
    eyes: [24, 36, 40, 36], mouth: null, cheeks: [18.5, 45.5, 42], top: [32, 18, 22], side: [32, 38, 40], chin: [53, 26],
    back: <path d="M30 19c-3-7 2-9 3-4 2-6 7-3 3 4" fill="none" />,
    body: 'M32 18a20 20 0 100 40 20 20 0 000-40z',
    front: (
      <>
        <path d="M28 42h8l-4 6z" fill="var(--pa)" />
        <ellipse cx="12.5" cy="44" rx="4" ry="7" fill="var(--pl)" />
        <ellipse cx="51.5" cy="44" rx="4" ry="7" fill="var(--pl)" />
      </>
    ),
  },
  mochi: {
    name: 'Mochi', blurb: 'A soft, watchful cat', palette: { fill: '#f6cfa8', accent: '#e89aa0' },
    eyes: [23, 39, 41, 39], mouth: 48, cheeks: [17.5, 46.5, 45], top: [32, 20, 18], side: [32, 38, 38], chin: [54, 28],
    back: (
      <>
        <path d="M15 30L13 9l15 11z" fill="var(--pf)" />
        <path d="M49 30l2-21-15 11z" fill="var(--pf)" />
        <path d="M17 24l-1-9 7 5z" fill="var(--pa)" stroke="none" />
        <path d="M47 24l1-9-7 5z" fill="var(--pa)" stroke="none" />
      </>
    ),
    body: 'M13 38c0-13 8-18 19-18s19 5 19 18-8 20-19 20-19-7-19-20z',
    front: <path d="M7 41l10 1M7 47l10-3M57 41l-10 1M57 47l-10-3" fill="none" strokeWidth="1.4" />,
  },
  bao: {
    name: 'Bao', blurb: 'A calm, sturdy bear', palette: { fill: '#cfa77f', accent: '#f1dfc9' },
    eyes: [23, 33, 41, 33], mouth: 48, cheeks: [17.5, 46.5, 41], top: [32, 14, 26], side: [32, 36, 44], chin: [52, 30],
    back: (
      <>
        <circle cx="14" cy="17" r="8.5" fill="var(--pf)" />
        <circle cx="50" cy="17" r="8.5" fill="var(--pf)" />
        <circle cx="14" cy="17" r="4" fill="var(--pa)" stroke="none" />
        <circle cx="50" cy="17" r="4" fill="var(--pa)" stroke="none" />
      </>
    ),
    body: 'M32 14a22 22 0 100 44 22 22 0 000-44z',
    front: (
      <>
        <ellipse cx="32" cy="45" rx="10" ry="8" fill="var(--pa)" strokeWidth="1.4" />
        <ellipse cx="32" cy="41.5" rx="3.5" ry="2.5" fill={INK} stroke="none" />
      </>
    ),
  },
  fern: {
    name: 'Fern', blurb: 'A cheerful little frog', palette: { fill: '#a6d99f', accent: '#f4a6a6' },
    eyes: [20, 24, 44, 24], mouth: 46, cheeks: [13, 51, 46], top: [32, 21, 20], side: [32, 40, 48], chin: [53, 36],
    back: (
      <>
        <circle cx="20" cy="24" r="10" fill="var(--pf)" />
        <circle cx="44" cy="24" r="10" fill="var(--pf)" />
      </>
    ),
    body: 'M32 24c15 0 25 8 25 20 0 9-10 14-25 14S7 53 7 44c0-12 10-20 25-20z',
  },
  juno: {
    name: 'Juno', blurb: 'A quick, clever fox', palette: { fill: '#f5a050', accent: '#fff3e6' },
    eyes: [22, 35, 42, 35], mouth: null, cheeks: [16, 48, 42], top: [32, 22, 16], side: [32, 36, 48], chin: [54, 22],
    body: 'M32 58C18 58 8 47 8 37L11 11l15 11c4-1 8-1 12 0l15-11 3 26c0 10-10 21-24 21z',
    front: (
      <>
        <path d="M8 37c6 9 16 12 24 21 8-9 18-12 24-21-8 6-16 8-24 8S16 43 8 37z" fill="var(--pa)" />
        <path d="M29 47h6l-3 4z" fill={INK} />
      </>
    ),
  },
  otto: {
    name: 'Otto', blurb: 'A thoughtful octopus', palette: { fill: '#bda3f2', accent: '#8f6fe0' },
    eyes: [24, 31, 40, 31], mouth: 41, cheeks: [18, 46, 38], top: [32, 8, 28], side: [32, 30, 44], chin: [45, 40],
    body: 'M10 36C10 16 21 8 32 8s22 8 22 28v6c0 8-3 14-7 14s-5-6-6-11c-1 5-3 11-9 11s-8-6-9-11c-1 5-2 11-6 11s-7-6-7-14v-6z',
    front: (
      <g fill="var(--pa)" opacity=".45" stroke="none">
        <circle cx="19" cy="18" r="2.5" />
        <circle cx="45" cy="16" r="2" />
        <circle cx="50" cy="26" r="1.5" />
      </g>
    ),
  },
  wisp: {
    name: 'Wisp', blurb: 'A gentle little ghost', palette: { fill: '#e3edf9', accent: '#f6b6c4' },
    eyes: [24, 30, 40, 30], mouth: 39, cheeks: [17.5, 46.5, 36], top: [32, 8, 26], side: [32, 30, 38], chin: [48, 34],
    body: 'M13 57V31C13 16 21 8 32 8s19 8 19 23v26l-6-5-6 5-7-5-7 5-6-5z',
  },
}

export const PET_IDS = Object.keys(PETS)

type Accessory = Exclude<PetLook['accessory'], 'none'>
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

/** Each accessory is drawn from the pet's anchors, so it sits right on every species. */
export const ACCESSORIES: Record<Accessory, (pet: PetDef) => ReactNode> = {
  hat: ({ top: [x, y, w] }) => (
    <g transform={`translate(${x} ${y + 1.5}) rotate(-9) scale(${clamp(w / 24, 0.75, 1.2)})`}>
      <path d="M-10 1L0-19l10 20q-10 3.5-20 0z" fill="#6f7bff" />
      <path d="M-5.5-8h11l2 4h-15z" fill="#fff" fillOpacity=".85" stroke="none" />
      <circle cy="-19" r="3" fill="#ffd34d" />
    </g>
  ),
  crown: ({ top: [x, y, w] }) => (
    <g transform={`translate(${x} ${y + 2}) scale(${clamp(w / 24, 0.75, 1.2)})`}>
      <path d="M-9 0l-1-11 5.5 5L0-13l4.5 7 5.5-5-1 11z" fill="#ffcf3f" />
      <circle cy="-3.2" r="1.5" fill="#ff5c7a" stroke="none" />
      <circle cx="-5" cy="-2.6" r="1" fill="#5cc8ff" stroke="none" />
      <circle cx="5" cy="-2.6" r="1" fill="#5cc8ff" stroke="none" />
    </g>
  ),
  bow: ({ top: [x, y, w] }) => (
    <g transform={`translate(${x + w * 0.28} ${y + 3}) rotate(14) scale(${clamp(w / 24, 0.8, 1.1)})`}>
      <path d="M0 0C-4-6.5-11-5.5-11 0s7 6.5 11 0z" fill="#ff6f91" />
      <path d="M0 0C4-6.5 11-5.5 11 0S4 6.5 0 0z" fill="#ff6f91" />
      <circle r="2.4" fill="#ff4f7b" />
    </g>
  ),
  glasses: ({ eyes: [lx, ly, rx, ry] }) => (
    <g fill="#fff" fillOpacity=".2" strokeWidth="1.5">
      <circle cx={lx} cy={ly} r="6.4" />
      <circle cx={rx} cy={ry} r="6.4" />
      <path d={`M${lx + 6.4} ${ly}Q${(lx + rx) / 2} ${ly - 2.4} ${rx - 6.4} ${ry}M${lx - 6.4} ${ly}l-3-1M${rx + 6.4} ${ry}l3-1`} fill="none" />
      <path d={`M${lx - 3.8} ${ly - 3.2}a4.8 4.8 0 013.2-1.800M${rx - 3.8} ${ry - 3.2}a4.8 4.8 0 013.2-1.8`} fill="none" stroke="#fff" strokeWidth="1.2" />
    </g>
  ),
  scarf: ({ chin: [y, w], top: [x] }) => {
    const band = `M${x - w / 2} ${y - 1}Q${x} ${y + 6} ${x + w / 2} ${y - 1}`
    return (
      <g fill="none">
        <path d={`M${x + w / 2 - 8} ${y + 2}l2.5 10 5.5-1-1.5-10z`} fill="#e5484d" strokeWidth="1.4" />
        <path d={band} stroke={INK} strokeWidth="7" />
        <path d={band} stroke="#e5484d" strokeWidth="4.6" />
        <path d={band} stroke="#fff" strokeOpacity=".4" strokeWidth="4.6" strokeDasharray="2 5" strokeLinecap="butt" />
      </g>
    )
  },
  headphones: ({ side: [x, y, w], top: [, topY] }) => (
    <g>
      <path d={`M${x - w / 2} ${y}Q${x} ${2 * (topY - 2.5) - y} ${x + w / 2} ${y}`} fill="none" stroke="#59627a" strokeWidth="3" />
      <ellipse cx={x - w / 2} cy={y + 1} rx="3.3" ry="5.2" fill="#ff6f91" />
      <ellipse cx={x + w / 2} cy={y + 1} rx="3.3" ry="5.2" fill="#ff6f91" />
    </g>
  ),
}

type Hsl = [number, number, number]
function toHsl(hex: string): Hsl {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
  const max = Math.max(r, g, b)
  const min = Math.min(r, g, b)
  const l = (max + min) / 2
  const d = max - min
  if (d === 0) return [0, 0, l * 100]
  const s = d / (1 - Math.abs(2 * l - 1))
  const h = max === r ? ((g - b) / d + 6) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4
  return [h * 60, s * 100, l * 100]
}

/** The hue (degrees) of a species' own body colour: where a hue slider starts. */
export const speciesHue = (id: string): number => Math.round(toHsl((PETS[id] ?? PETS.lily).palette.fill)[0])

/** The three colour variables of a pet. A hue moves all of its colours together, keeping their differences. */
export function petColors(pet: PetDef, hue: number | null): Record<'--pf' | '--pa' | '--pl', string> {
  const { fill, accent, alt = fill } = pet.palette
  if (hue === null) return { '--pf': fill, '--pa': accent, '--pl': alt }
  const turn = hue - toHsl(fill)[0]
  const shift = (hex: string) => {
    const [h, s, l] = toHsl(hex)
    return `hsl(${Math.round((h + turn + 360) % 360)} ${s.toFixed(1)}% ${l.toFixed(1)}%)`
  }
  return { '--pf': shift(fill), '--pa': shift(accent), '--pl': shift(alt) }
}
