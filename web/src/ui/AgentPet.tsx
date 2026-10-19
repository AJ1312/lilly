import React, { useState } from 'react'
import type { PetLook } from '../types'
import { Icon } from './Icon'

export type PetSpecies = 'lily' | 'pip' | 'mochi' | 'bao' | 'fern' | 'juno' | 'otto' | 'wisp'
export type PetState = 'idle' | 'thinking' | 'working' | 'approval' | 'success' | 'sleeping'

interface AgentPetProps {
  species?: string
  look?: Partial<PetLook>
  state?: PetState
  size?: number
  agentName?: string
  currentThought?: string
  interactive?: boolean
  onClick?: () => void
  onAction?: (action: 'talk' | 'praise' | 'details') => void
  className?: string
}

export const AgentPet: React.FC<AgentPetProps> = ({
  species = 'lily',
  look = {},
  state = 'idle',
  size = 80,
  agentName,
  currentThought,
  interactive = true,
  onClick,
  onAction,
  className = '',
}) => {
  const [popoverOpen, setPopoverOpen] = useState(false)
  const [bouncing, setBouncing] = useState(false)
  const [morale, setMorale] = useState(100)
  const [hearts, setHearts] = useState<{ id: number; x: number; y: number }[]>([])

  const sp = (species || 'lily').toLowerCase() as PetSpecies
  const validSpecies: PetSpecies[] = ['lily', 'pip', 'mochi', 'bao', 'fern', 'juno', 'otto', 'wisp']
  const cleanSpecies: PetSpecies = validSpecies.includes(sp) ? sp : 'lily'

  const accessory = look.accessory || 'none'
  const eyeStyle = look.eyes || (state === 'sleeping' ? 'sleepy' : state === 'success' ? 'sparkle' : 'round')
  const blush = look.blush ?? true
  const hue = look.hue ?? null

  const handlePetClick = (e: React.MouseEvent) => {
    e.stopPropagation()
    setBouncing(true)
    setTimeout(() => setBouncing(false), 500)

    // Spawn tiny heart effect on interaction
    const rect = e.currentTarget.getBoundingClientRect()
    const newHeart = { id: Date.now(), x: e.clientX - rect.left, y: e.clientY - rect.top }
    setHearts((prev) => [...prev.slice(-3), newHeart])
    setTimeout(() => {
      setHearts((prev) => prev.filter((h) => h.id !== newHeart.id))
    }, 1200)

    if (onClick) {
      onClick()
    } else if (interactive) {
      setPopoverOpen((v) => !v)
    }
  }

  // Base species color presets
  const speciesColors: Record<PetSpecies, { body: string; belly: string; accent: string; ears: string }> = {
    lily: { body: '#eef3ff', belly: '#ffffff', accent: '#a5b4fc', ears: '#c7d2fe' },
    pip: { body: '#fef3c7', belly: '#fffbeb', accent: '#f59e0b', ears: '#fbbf24' },
    mochi: { body: '#fce7f3', belly: '#fff1f2', accent: '#ec4899', ears: '#f472b6' },
    bao: { body: '#f3f4f6', belly: '#ffffff', accent: '#1f2937', ears: '#374151' },
    fern: { body: '#dcfce7', belly: '#f0fdf4', accent: '#16a34a', ears: '#4ade80' },
    juno: { body: '#ffedd5', belly: '#fff7ed', accent: '#ea580c', ears: '#fb923c' },
    otto: { body: '#e0f2fe', belly: '#f0f9ff', accent: '#0284c7', ears: '#38bdf8' },
    wisp: { body: '#f5f3ff', belly: '#faf5ff', accent: '#8b5cf6', ears: '#a78bfa' },
  }

  const cols = speciesColors[cleanSpecies]

  // Dynamic thoughts based on live execution state
  const defaultThought = () => {
    switch (state) {
      case 'thinking':
        return currentThought || 'Formulating optimal plan & tool strategy...'
      case 'working':
        return currentThought || 'Executing step on host runtime...'
      case 'approval':
        return currentThought || 'Awaiting your review to proceed safely!'
      case 'success':
        return currentThought || 'Task completed with verified outcome!'
      case 'sleeping':
        return currentThought || 'Resting. Standing by for your instructions.'
      case 'idle':
      default:
        return currentThought || `Ready to assist you today, Operator.`
    }
  }

  const filterStyle = hue !== null ? { filter: `hue-rotate(${hue}deg)` } : {}

  return (
    <div
      className={`agent-pet-root ${state} ${bouncing ? 'bouncing' : ''} ${className}`}
      style={{
        position: 'relative',
        display: 'inline-flex',
        flexDirection: 'column',
        alignItems: 'center',
        cursor: interactive ? 'pointer' : 'default',
        userSelect: 'none',
        ...filterStyle,
      }}
      onClick={handlePetClick}
      title={agentName ? `${agentName} (${cleanSpecies}) - Click to interact` : undefined}
    >
      {/* Floating State Indicators (Thinking / Approval / Success Bubble) */}
      {state === 'thinking' && (
        <div className="pet-state-badge thinking" style={{ position: 'absolute', top: -14, zIndex: 10 }}>
          <div className="dot-pulse" />
          <div className="dot-pulse delay-1" />
          <div className="dot-pulse delay-2" />
        </div>
      )}

      {state === 'approval' && (
        <div className="pet-state-badge approval" style={{ position: 'absolute', top: -16, zIndex: 10 }}>
          <Icon name="shield" size={12} />
          <span>Needs approval</span>
        </div>
      )}

      {state === 'working' && (
        <div className="pet-state-badge working" style={{ position: 'absolute', top: -14, zIndex: 10 }}>
          <Icon name="sparkles" size={11} />
        </div>
      )}

      {state === 'success' && (
        <div className="pet-state-badge success" style={{ position: 'absolute', top: -14, zIndex: 10 }}>
          <Icon name="check" size={12} />
        </div>
      )}

      {/* Floating Hearts Particle FX on Click */}
      {hearts.map((h) => (
        <div
          key={h.id}
          style={{
            position: 'absolute',
            left: `${h.x}px`,
            top: `${h.y}px`,
            pointerEvents: 'none',
            color: '#ec4899',
            animation: 'floatUpAndFade 1.1s cubic-bezier(0.16, 1, 0.3, 1) forwards',
            zIndex: 30,
            fontSize: '14px',
          }}
        >
          <Icon name="sparkles" size={14} />
        </div>
      ))}

      {/* Full Body Pet Vector SVG */}
      <svg
        width={size}
        height={size}
        viewBox="0 0 100 100"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        style={{
          transition: 'transform var(--transition-bounce)',
          transform: bouncing ? 'scale(1.15, 0.85)' : 'scale(1)',
          overflow: 'visible',
        }}
      >
        <defs>
          <filter id={`pet-shadow-${cleanSpecies}`} x="-10%" y="-10%" width="120%" height="130%">
            <feDropShadow dx="0" dy="4" stdDeviation="3" floodOpacity="0.12" />
          </filter>
        </defs>

        {/* Ground Ambient Shadow */}
        <ellipse cx="50" cy="94" rx="28" ry="5" fill="rgba(30,24,18,0.12)" />

        {/* Species Tail / Wings / Botanical Calyx */}
        {cleanSpecies === 'juno' && (
          /* Bushy Fox Tail */
          <path
            d="M68 68C84 64 96 46 88 34C82 26 72 38 64 56"
            fill={cols.accent}
            stroke="#1c1c1e"
            strokeWidth="2.5"
            strokeLinecap="round"
          />
        )}

        {cleanSpecies === 'mochi' && (
          /* Curled Cat Tail */
          <path
            d="M68 76C82 78 88 64 82 52C78 44 72 48 74 56"
            fill="none"
            stroke={cols.accent}
            strokeWidth="5"
            strokeLinecap="round"
          />
        )}

        {cleanSpecies === 'pip' && (
          /* Tiny Cute Bird Wings */
          <>
            <path
              d="M20 54C14 50 12 60 18 64C22 66 26 62 26 56Z"
              fill={cols.ears}
              stroke="#1c1c1e"
              strokeWidth="2"
            />
            <path
              d="M80 54C86 50 88 60 82 64C78 66 74 62 74 56Z"
              fill={cols.ears}
              stroke="#1c1c1e"
              strokeWidth="2"
            />
          </>
        )}

        {cleanSpecies === 'wisp' && (
          /* Floating Spirit Tail */
          <path
            d="M50 86C44 94 36 96 38 100C44 98 56 98 62 100C64 96 56 94 50 86Z"
            fill={cols.accent}
            opacity={0.6}
          />
        )}

        {/* Full Torso Body */}
        <ellipse
          cx="50"
          cy="66"
          rx="25"
          ry="24"
          fill={cols.body}
          stroke="#1c1c1e"
          strokeWidth="2.5"
          filter={`url(#pet-shadow-${cleanSpecies})`}
        />

        {/* Soft Tummy / Belly Patch */}
        <ellipse cx="50" cy="70" rx="16" ry="15" fill={cols.belly} />

        {/* Cute Feet / Paws */}
        <ellipse cx="36" cy="88" rx="8" ry="5" fill={cols.ears} stroke="#1c1c1e" strokeWidth="2" />
        <ellipse cx="64" cy="88" rx="8" ry="5" fill={cols.ears} stroke="#1c1c1e" strokeWidth="2" />

        {/* Ears / Antennae / Horns */}
        {cleanSpecies === 'juno' && (
          <>
            {/* Pointy Fox Ears */}
            <polygon points="26,38 34,14 44,32" fill={cols.accent} stroke="#1c1c1e" strokeWidth="2.5" />
            <polygon points="74,38 66,14 56,32" fill={cols.accent} stroke="#1c1c1e" strokeWidth="2.5" />
            <polygon points="29,35 34,19 41,31" fill="#fff" />
            <polygon points="71,35 66,19 59,31" fill="#fff" />
          </>
        )}

        {cleanSpecies === 'mochi' && (
          <>
            {/* Cute Cat Ears */}
            <polygon points="28,34 35,18 45,30" fill={cols.accent} stroke="#1c1c1e" strokeWidth="2.5" />
            <polygon points="72,34 65,18 55,30" fill={cols.accent} stroke="#1c1c1e" strokeWidth="2.5" />
            <polygon points="31,32 35,22 42,29" fill="#fbcfe8" />
            <polygon points="69,32 65,22 58,29" fill="#fbcfe8" />
          </>
        )}

        {cleanSpecies === 'bao' && (
          <>
            {/* Round Panda Ears */}
            <circle cx="30" cy="24" r="10" fill={cols.accent} stroke="#1c1c1e" strokeWidth="2.5" />
            <circle cx="70" cy="24" r="10" fill={cols.accent} stroke="#1c1c1e" strokeWidth="2.5" />
          </>
        )}

        {cleanSpecies === 'fern' && (
          <>
            {/* Sprout Leaf Antenna */}
            <path
              d="M50 24C46 14 36 12 36 18C36 24 46 22 50 24Z"
              fill={cols.accent}
              stroke="#1c1c1e"
              strokeWidth="2"
            />
            <path
              d="M50 24C54 14 64 12 64 18C64 24 54 22 50 24Z"
              fill={cols.accent}
              stroke="#1c1c1e"
              strokeWidth="2"
            />
          </>
        )}

        {cleanSpecies === 'lily' && (
          <>
            {/* Water-Lily Fairy Petals */}
            <path
              d="M26 30C20 18 34 16 38 28Z"
              fill={cols.accent}
              stroke="#1c1c1e"
              strokeWidth="2"
            />
            <path
              d="M74 30C80 18 66 16 62 28Z"
              fill={cols.accent}
              stroke="#1c1c1e"
              strokeWidth="2"
            />
          </>
        )}

        {/* Main Head Sphere */}
        <circle
          cx="50"
          cy="42"
          r="26"
          fill={cols.body}
          stroke="#1c1c1e"
          strokeWidth="2.5"
        />

        {/* Panda Eye Patches */}
        {cleanSpecies === 'bao' && (
          <>
            <ellipse cx="38" cy="40" rx="8" ry="7" transform="rotate(-15 38 40)" fill={cols.accent} />
            <ellipse cx="62" cy="40" rx="8" ry="7" transform="rotate(15 62 40)" fill={cols.accent} />
          </>
        )}

        {/* Expressive Eyes */}
        {eyeStyle === 'sleepy' ? (
          <>
            {/* Curved Happy/Sleepy Eyes */}
            <path d="M34 42Q40 47 44 42" stroke="#1c1c1e" strokeWidth="3" strokeLinecap="round" fill="none" />
            <path d="M56 42Q60 47 66 42" stroke="#1c1c1e" strokeWidth="3" strokeLinecap="round" fill="none" />
          </>
        ) : eyeStyle === 'sparkle' ? (
          <>
            {/* Star Sparkle Eyes */}
            <g transform="translate(35, 36) scale(0.7)">
              <polygon points="6,0 8,4 12,6 8,8 6,12 4,8 0,6 4,4" fill="#1c1c1e" />
              <circle cx="9" cy="3" r="1.5" fill="#ffffff" />
            </g>
            <g transform="translate(57, 36) scale(0.7)">
              <polygon points="6,0 8,4 12,6 8,8 6,12 4,8 0,6 4,4" fill="#1c1c1e" />
              <circle cx="9" cy="3" r="1.5" fill="#ffffff" />
            </g>
          </>
        ) : (
          <>
            {/* Glossy Anime Boba Eyes */}
            <circle cx="39" cy="40" r="5" fill="#1c1c1e" />
            <circle cx="37.5" cy="38.5" r="2" fill="#ffffff" />
            <circle cx="40.5" cy="41.5" r="0.9" fill="#ffffff" />

            <circle cx="61" cy="40" r="5" fill="#1c1c1e" />
            <circle cx="59.5" cy="38.5" r="2" fill="#ffffff" />
            <circle cx="62.5" cy="41.5" r="0.9" fill="#ffffff" />
          </>
        )}

        {/* Tiny Sweet Snout / Nose */}
        <ellipse cx="50" cy="46" rx="2" ry="1.5" fill="#1c1c1e" />
        <path d="M47 48Q50 51 53 48" stroke="#1c1c1e" strokeWidth="1.8" strokeLinecap="round" fill="none" />

        {/* Cheeks Blush */}
        {blush && (
          <>
            <circle cx="31" cy="46" r="4" fill="#fb7185" opacity={0.45} />
            <circle cx="69" cy="46" r="4" fill="#fb7185" opacity={0.45} />
          </>
        )}

        {/* Front Resting Paws */}
        <ellipse cx="42" cy="68" rx="5" ry="4" fill={cols.belly} stroke="#1c1c1e" strokeWidth="2" />
        <ellipse cx="58" cy="68" rx="5" ry="4" fill={cols.belly} stroke="#1c1c1e" strokeWidth="2" />

        {/* Accessories Layer */}
        {accessory === 'glasses' && (
          <g stroke="#1c1c1e" strokeWidth="2.5" fill="none">
            <circle cx="38" cy="40" r="9" />
            <circle cx="62" cy="40" r="9" />
            <line x1="47" y1="40" x2="53" y2="40" />
          </g>
        )}

        {accessory === 'bow' && (
          <g transform="translate(62, 16) scale(0.9)">
            <polygon points="0,6 -8,0 -8,12" fill="#f43f5e" stroke="#1c1c1e" strokeWidth="1.5" />
            <polygon points="0,6 8,0 8,12" fill="#f43f5e" stroke="#1c1c1e" strokeWidth="1.5" />
            <circle cx="0" cy="6" r="3" fill="#fda4af" stroke="#1c1c1e" strokeWidth="1.5" />
          </g>
        )}

        {accessory === 'crown' && (
          <g transform="translate(40, 10)">
            <polygon
              points="0,10 4,2 10,7 16,2 20,10"
              fill="#fbbf24"
              stroke="#1c1c1e"
              strokeWidth="2"
            />
            <circle cx="4" cy="2" r="1.5" fill="#f43f5e" />
            <circle cx="10" cy="7" r="1.5" fill="#3b82f6" />
            <circle cx="16" cy="2" r="1.5" fill="#10b981" />
          </g>
        )}

        {accessory === 'scarf' && (
          <g>
            <path
              d="M34 58Q50 64 66 58Q50 68 34 58Z"
              fill="#ef4444"
              stroke="#1c1c1e"
              strokeWidth="2"
            />
            <path
              d="M54 62L52 76L60 76L58 62Z"
              fill="#dc2626"
              stroke="#1c1c1e"
              strokeWidth="1.8"
            />
          </g>
        )}

        {accessory === 'headphones' && (
          <g stroke="#1c1c1e" strokeWidth="2.5" fill="none">
            <path d="M24 38C24 16 76 16 76 38" />
            <rect x="18" y="34" width="8" height="14" rx="4" fill="#3b82f6" />
            <rect x="74" y="34" width="8" height="14" rx="4" fill="#3b82f6" />
          </g>
        )}

        {accessory === 'hat' && (
          <g transform="translate(38, 6)">
            <ellipse cx="12" cy="14" rx="16" ry="3" fill="#1c1c1e" />
            <rect x="4" y="2" width="16" height="12" rx="2" fill="#1c1c1e" />
            <rect x="4" y="10" width="16" height="3" fill="#f43f5e" />
          </g>
        )}
      </svg>

      {/* Interactive Popover Dialog on Click */}
      {popoverOpen && (
        <div
          className="pet-interactive-popover"
          onClick={(e) => e.stopPropagation()}
          style={{
            position: 'absolute',
            bottom: '105%',
            left: '50%',
            transform: 'translateX(-50%)',
            width: '260px',
            backgroundColor: 'var(--bg-card)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-md)',
            boxShadow: 'var(--shadow-overlay)',
            padding: '14px',
            zIndex: 100,
            animation: 'fadeInScale 180ms cubic-bezier(0.16, 1, 0.3, 1)',
          }}
        >
          {/* Header */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ fontWeight: 800, fontSize: '13px', color: 'var(--text-main)' }}>
                {agentName || cleanSpecies.toUpperCase()}
              </span>
              <span className="badge badge-accent" style={{ fontSize: '9px', textTransform: 'capitalize' }}>
                {cleanSpecies}
              </span>
            </div>
            <button
              type="button"
              onClick={() => setPopoverOpen(false)}
              className="btn btn-ghost"
              style={{ padding: '2px', height: 'auto', minWidth: 'auto' }}
            >
              <Icon name="x" size={12} />
            </button>
          </div>

          {/* Current Thought Bubble */}
          <div
            style={{
              padding: '10px',
              backgroundColor: 'var(--bg-card-subtle)',
              borderRadius: 'var(--radius-sm)',
              fontSize: '12px',
              lineHeight: 1.4,
              color: 'var(--text-secondary)',
              marginBottom: '10px',
              border: '1px solid var(--border-subtle)',
            }}
          >
            <div style={{ fontSize: '10px', fontWeight: 700, color: 'var(--text-dim)', textTransform: 'uppercase', marginBottom: '4px' }}>
              Active Thought
            </div>
            <div>{defaultThought()}</div>
          </div>

          {/* Morale & Stats Bar */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '11px', color: 'var(--text-muted)', marginBottom: '12px' }}>
            <span>Affection & Morale</span>
            <span style={{ fontWeight: 700, color: 'var(--good-text)' }}>{morale}%</span>
          </div>

          {/* Quick Action Buttons */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              style={{ fontSize: '11px', padding: '6px 8px' }}
              onClick={() => {
                setMorale((m) => Math.min(150, m + 5))
                setBouncing(true)
                setTimeout(() => setBouncing(false), 400)
                onAction?.('praise')
              }}
            >
              <Icon name="sparkles" size={12} />
              <span>Pet (+Affection)</span>
            </button>

            <button
              type="button"
              className="btn btn-primary btn-sm"
              style={{ fontSize: '11px', padding: '6px 8px' }}
              onClick={() => {
                setPopoverOpen(false)
                onAction?.('talk')
              }}
            >
              <Icon name="chat" size={12} />
              <span>Command</span>
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
