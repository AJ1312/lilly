import React, { useState, useEffect, useRef } from 'react'
import type { PetLook } from '../types'

export type PetSpecies = 'lily' | 'pip' | 'mochi' | 'bao' | 'fern' | 'juno' | 'otto' | 'wisp'

export interface LillyMascotProps {
  look?: Omit<Partial<PetLook>, 'eyes'> & { eyes?: 'round' | 'sparkle' | 'sleepy' | 'happy' | 'wink' }
  pet?: string
  size?: number
  state?: 'idle' | 'thinking' | 'happy' | 'sleeping' | 'celebrate'
  interactive?: boolean
  speech?: string | null
  className?: string
  onClick?: () => void
}

export const LillyMascot: React.FC<LillyMascotProps> = ({
  look,
  pet = 'lily',
  size = 120,
  state = 'idle',
  interactive = true,
  speech = null,
  className = '',
  onClick,
}) => {
  const species = (pet || 'lily').toLowerCase() as PetSpecies
  const hue = look?.hue ?? 250
  const accessory = look?.accessory ?? 'none'
  const eyeStyle = look?.eyes ?? 'round'
  const blush = look?.blush ?? true

  const [mousePos, setMousePos] = useState({ x: 0, y: 0 })
  const [blinking, setBlinking] = useState(false)
  const [bouncing, setBouncing] = useState(false)
  const [currentSpeech, setCurrentSpeech] = useState<string | null>(speech)
  const svgRef = useRef<SVGSVGElement>(null)

  // Species-specific playful quips
  const speciesQuips: Record<PetSpecies, string[]> = {
    lily: ['Hop to it!', 'Automation ready!', 'Host laptop secured! ✨', 'Let’s build something magical!'],
    pip: ['Chirp! Speed run mode!', 'Running full throttle!', 'Zero latency ahead!', 'Pip is on the case! 🐧'],
    mochi: ['Squish squish!', 'Cozy vibes only~', 'Mochi memory cached!', 'Everything is sweet & clean! 🍡'],
    bao: ['Defending the perimeter!', 'Sturdy like a bao!', 'All guardrails active!', 'Steamed and ready! 🐼'],
    fern: ['Grounded & growing! 🌿', 'Deep research underway!', 'Natural flow achieved!', 'Branching thoughts...'],
    juno: ['Barking at the cosmos! 🚀', 'To infinity and laptops!', 'Star radar locked on!', 'Good boy on duty! 🐶'],
    otto: ['Tightening the bolts! 🔧', 'Automating all workflows!', 'Cyber otter online!', 'DevBox patched! 🦦'],
    wisp: ['Floating through data...', 'Mystical logic aligned ✨', 'Whispering clean tokens...', 'Spirit mode active! 👻'],
  }

  // Track cursor for cute 3D eye parallax follow
  useEffect(() => {
    if (!interactive) return
    const handleMove = (e: MouseEvent) => {
      if (!svgRef.current) return
      const rect = svgRef.current.getBoundingClientRect()
      const centerX = rect.left + rect.width / 2
      const centerY = rect.top + rect.height / 2
      const dx = (e.clientX - centerX) / window.innerWidth
      const dy = (e.clientY - centerY) / window.innerHeight
      setMousePos({
        x: Math.max(-5, Math.min(5, dx * 16)),
        y: Math.max(-4, Math.min(4, dy * 12)),
      })
    }

    window.addEventListener('mousemove', handleMove)
    return () => window.removeEventListener('mousemove', handleMove)
  }, [interactive])

  // Random cute blink
  useEffect(() => {
    if (state === 'sleeping') return
    const blinkInterval = setInterval(() => {
      setBlinking(true)
      setTimeout(() => setBlinking(false), 160)
    }, 3800 + Math.random() * 2500)

    return () => clearInterval(blinkInterval)
  }, [state])

  const handleClick = () => {
    setBouncing(true)
    setTimeout(() => setBouncing(false), 600)
    if (!speech) {
      const pool = speciesQuips[species] || speciesQuips.lily
      const randomQuip = pool[Math.floor(Math.random() * pool.length)]
      setCurrentSpeech(randomQuip)
      setTimeout(() => setCurrentSpeech(null), 3200)
    }
    if (onClick) onClick()
  }

  // Base colors derived from hue
  const primaryColor = `hsl(${hue}, 86%, 62%)`
  const secondaryColor = `hsl(${hue + 25}, 90%, 52%)`
  const bellyColor = `hsl(${hue}, 85%, 93%)`
  const blushColor = `hsl(350, 92%, 75%)`

  return (
    <div
      className={`lilly-mascot-wrapper ${className}`}
      style={{
        position: 'relative',
        display: 'inline-flex',
        flexDirection: 'column',
        alignItems: 'center',
        userSelect: 'none',
      }}
    >
      {/* Playful Speech Bubble */}
      {(currentSpeech || speech) && (
        <div
          className="mascot-speech-bubble"
          style={{
            position: 'absolute',
            bottom: '105%',
            marginBottom: '8px',
            backgroundColor: 'var(--bg-card)',
            color: 'var(--text-main)',
            border: '2px solid var(--border)',
            borderRadius: 'var(--radius-md)',
            padding: '6px 12px',
            fontSize: '12px',
            fontWeight: 600,
            whiteSpace: 'nowrap',
            boxShadow: 'var(--shadow-md)',
            zIndex: 10,
            animation: 'bubblePop 0.25s cubic-bezier(0.175, 0.885, 0.32, 1.275)',
          }}
        >
          {currentSpeech || speech}
          <div
            style={{
              position: 'absolute',
              top: '100%',
              left: '50%',
              transform: 'translateX(-50%)',
              width: 0,
              height: 0,
              borderLeft: '6px solid transparent',
              borderRight: '6px solid transparent',
              borderTop: '6px solid var(--border)',
            }}
          />
        </div>
      )}

      {/* Interactive Mascot SVG with 3D Gradients & Lively Species Details */}
      <svg
        ref={svgRef}
        width={size}
        height={size}
        viewBox="0 0 120 120"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        onClick={handleClick}
        style={{
          cursor: interactive ? 'pointer' : 'default',
          transition: 'transform 0.15s cubic-bezier(0.175, 0.885, 0.32, 1.275)',
          transform: bouncing
            ? 'scale(1.18) translateY(-8px)'
            : state === 'celebrate'
            ? 'translateY(-4px)'
            : 'scale(1)',
          filter: 'drop-shadow(0 8px 16px rgba(0, 0, 0, 0.12))',
        }}
      >
        <defs>
          <linearGradient id={`grad-${hue}-${species}`} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={primaryColor} />
            <stop offset="100%" stopColor={secondaryColor} />
          </linearGradient>
          <radialGradient id={`glow-${hue}`} cx="45%" cy="35%" r="55%">
            <stop offset="0%" stopColor="white" stopOpacity="0.45" />
            <stop offset="100%" stopColor="white" stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* Species Feature: Behind-Body Elements (Ears, Horns, Wings) */}
        {species === 'lily' && (
          /* Bunny Ears */
          <g className="mascot-ears">
            <path d="M28 42 C16 16, 34 4, 44 26 Z" fill={`url(#grad-${hue}-${species})`} stroke="rgba(0,0,0,0.15)" strokeWidth="2" />
            <path d="M30 38 C22 22, 34 12, 40 28 Z" fill={blushColor} opacity="0.65" />
            <path d="M92 42 C104 16, 86 4, 76 26 Z" fill={`url(#grad-${hue}-${species})`} stroke="rgba(0,0,0,0.15)" strokeWidth="2" />
            <path d="M90 38 C98 22, 86 12, 80 28 Z" fill={blushColor} opacity="0.65" />
          </g>
        )}

        {species === 'pip' && (
          /* Penguin/Bird Flippers & Feather Crest */
          <g>
            <path d="M18 64 C8 68, 10 82, 22 76 Z" fill={`url(#grad-${hue}-${species})`} stroke="rgba(0,0,0,0.15)" strokeWidth="1.5" />
            <path d="M102 64 C112 68, 110 82, 98 76 Z" fill={`url(#grad-${hue}-${species})`} stroke="rgba(0,0,0,0.15)" strokeWidth="1.5" />
            {/* Crest on top */}
            <path d="M54 26 Q60 16 66 26 Z" fill={primaryColor} />
          </g>
        )}

        {species === 'bao' && (
          /* Panda Bear Round Ears */
          <g>
            <circle cx="28" cy="36" r="14" fill="#1e1b4b" stroke="rgba(0,0,0,0.15)" strokeWidth="1.5" />
            <circle cx="28" cy="36" r="8" fill={blushColor} opacity="0.4" />
            <circle cx="92" cy="36" r="14" fill="#1e1b4b" stroke="rgba(0,0,0,0.15)" strokeWidth="1.5" />
            <circle cx="92" cy="36" r="8" fill={blushColor} opacity="0.4" />
          </g>
        )}

        {species === 'fern' && (
          /* Forest Deer Antlers & Leaf Sprout */
          <g stroke="#78350f" strokeWidth="2.5" strokeLinecap="round">
            <path d="M36 34 Q30 18 24 16 M30 24 Q36 20 38 18" fill="none" />
            <path d="M84 34 Q90 18 96 16 M90 24 Q84 20 82 18" fill="none" />
            {/* Little green sprout */}
            <path d="M60 26 Q64 16 70 20 Q66 28 60 26 Z" fill="#22c55e" stroke="#15803d" strokeWidth="1" />
          </g>
        )}

        {species === 'juno' && (
          /* Star Dog Floppy Ears */
          <g>
            <path d="M24 44 C12 50, 16 76, 28 66 Z" fill={`url(#grad-${hue}-${species})`} stroke="rgba(0,0,0,0.15)" strokeWidth="2" />
            <path d="M96 44 C108 50, 104 76, 92 66 Z" fill={`url(#grad-${hue}-${species})`} stroke="rgba(0,0,0,0.15)" strokeWidth="2" />
          </g>
        )}

        {species === 'otto' && (
          /* Tech Otter Tiny Ears & Antenna */
          <g>
            <circle cx="26" cy="42" r="9" fill={`url(#grad-${hue}-${species})`} stroke="rgba(0,0,0,0.15)" strokeWidth="1.5" />
            <circle cx="94" cy="42" r="9" fill={`url(#grad-${hue}-${species})`} stroke="rgba(0,0,0,0.15)" strokeWidth="1.5" />
            <line x1="60" y1="28" x2="60" y2="14" stroke="#0284c7" strokeWidth="2" strokeLinecap="round" />
            <circle cx="60" cy="12" r="3.5" fill="#38bdf8" />
          </g>
        )}

        {species === 'wisp' && (
          /* Spirit Flame Flickers */
          <g opacity="0.6">
            <path d="M46 22 Q60 6 74 22 Q68 12 60 16 Z" fill={`url(#grad-${hue}-${species})`} />
          </g>
        )}

        {/* Main Character Body (3D Ellipse / Droplet) */}
        {species === 'mochi' || species === 'wisp' ? (
          /* Squishy Teardrop Blob Silhouette */
          <path
            d="M60 26 C86 26, 106 50, 106 72 C106 94, 86 104, 60 104 C34 104, 14 94, 14 72 C14 50, 34 26, 60 26 Z"
            fill={`url(#grad-${hue}-${species})`}
            stroke="rgba(0,0,0,0.12)"
            strokeWidth="2"
          />
        ) : (
          /* Classic 3D Chubby Body */
          <ellipse
            cx="60"
            cy="66"
            rx="44"
            ry="38"
            fill={`url(#grad-${hue}-${species})`}
            stroke="rgba(0,0,0,0.12)"
            strokeWidth="2"
          />
        )}

        {/* 3D Radial Highlight for Premium Glass/Clay Feel */}
        <ellipse cx="58" cy="52" rx="34" ry="22" fill={`url(#glow-${hue})`} />

        {/* Soft Tummy / Belly (different per species) */}
        {species !== 'wisp' && (
          <ellipse cx="60" cy="74" rx="26" ry="18" fill={bellyColor} opacity="0.85" />
        )}

        {/* Panda Eye Patches */}
        {species === 'bao' && (
          <g fill="#1e1b4b" opacity="0.88">
            <ellipse cx="44" cy="58" rx="10" ry="8" transform="rotate(-15 44 58)" />
            <ellipse cx="76" cy="58" rx="10" ry="8" transform="rotate(15 76 58)" />
          </g>
        )}

        {/* Blush Cheeks */}
        {blush && (
          <g opacity="0.75">
            <ellipse cx="32" cy="70" rx="7" ry="4" fill={blushColor} />
            <ellipse cx="88" cy="70" rx="7" ry="4" fill={blushColor} />
          </g>
        )}

        {/* Otter Whiskers */}
        {species === 'otto' && (
          <g stroke="rgba(0,0,0,0.25)" strokeWidth="1.5" strokeLinecap="round">
            <line x1="28" y1="65" x2="16" y2="63" />
            <line x1="28" y1="69" x2="16" y2="71" />
            <line x1="92" y1="65" x2="104" y2="63" />
            <line x1="92" y1="69" x2="104" y2="71" />
          </g>
        )}

        {/* Eyes Group with Mouse Parallax Follow */}
        <g transform={`translate(${mousePos.x}, ${mousePos.y})`}>
          {blinking || state === 'sleeping' ? (
            /* Sleeping / Blinking closed eyes */
            <g stroke="#1e1b4b" strokeWidth="3" strokeLinecap="round">
              <path d="M40 60 Q46 65 52 60" />
              <path d="M68 60 Q74 65 80 60" />
            </g>
          ) : eyeStyle === 'happy' ? (
            /* Joyful arch eyes */
            <g stroke="#1e1b4b" strokeWidth="3.5" strokeLinecap="round">
              <path d="M38 62 Q45 54 52 62" />
              <path d="M68 62 Q75 54 82 62" />
            </g>
          ) : eyeStyle === 'sparkle' ? (
            /* Star Sparkle eyes */
            <g fill="#1e1b4b">
              <polygon points="45,50 47,56 53,58 47,60 45,66 43,60 37,58 43,56" />
              <circle cx="48" cy="54" r="1.5" fill="white" />
              <polygon points="75,50 77,56 83,58 77,60 75,66 73,60 67,58 73,56" />
              <circle cx="78" cy="54" r="1.5" fill="white" />
            </g>
          ) : eyeStyle === 'sleepy' ? (
            /* Relaxed half-lidded eyes */
            <g>
              <ellipse cx="45" cy="60" rx="6.5" ry="5" fill="#0f172a" />
              <rect x="38" y="55" width="14" height="4" fill={primaryColor} />
              <ellipse cx="75" cy="60" rx="6.5" ry="5" fill="#0f172a" />
              <rect x="68" y="55" width="14" height="4" fill={primaryColor} />
            </g>
          ) : eyeStyle === 'wink' ? (
            /* Playful wink */
            <g>
              <ellipse cx="45" cy="58" rx="6" ry="7" fill="#0f172a" />
              <circle cx="43" cy="55" r="2.5" fill="white" />
              <path d="M68 60 Q75 66 82 60" stroke="#0f172a" strokeWidth="3.5" strokeLinecap="round" />
            </g>
          ) : (
            /* Classic Curious 3D Anime Eyes */
            <g>
              <ellipse cx="45" cy="58" rx="6.5" ry="7.5" fill="#0f172a" />
              <circle cx="43" cy="55" r="2.8" fill="white" />
              <circle cx="47" cy="61" r="1.2" fill="white" />

              <ellipse cx="75" cy="58" rx="6.5" ry="7.5" fill="#0f172a" />
              <circle cx="73" cy="55" r="2.8" fill="white" />
              <circle cx="77" cy="61" r="1.2" fill="white" />
            </g>
          )}

          {/* Cute Nose / Snout */}
          {species === 'pip' ? (
            /* Little Bird Beak */
            <polygon points="60,61 56,66 64,66" fill="#f59e0b" stroke="#b45309" strokeWidth="1" />
          ) : (
            <ellipse cx="60" cy="64" rx="3" ry="2.2" fill="#312e81" />
          )}

          {/* Smiling Mouth */}
          <path
            d="M56 68 Q60 72 64 68"
            stroke="#1e1b4b"
            strokeWidth="2.5"
            strokeLinecap="round"
            fill="none"
          />
        </g>

        {/* Paws / Feet */}
        {species !== 'wisp' && (
          <g fill={`url(#grad-${hue}-${species})`} stroke="rgba(0,0,0,0.12)" strokeWidth="1.5">
            <ellipse cx="38" cy="94" rx="8" ry="6" />
            <ellipse cx="82" cy="94" rx="8" ry="6" />
          </g>
        )}

        {/* Dynamic Customizable Accessories */}
        {accessory === 'glasses' && (
          <g stroke="#0f172a" strokeWidth="2.5" fill="rgba(6, 182, 212, 0.2)">
            <rect x="34" y="50" width="22" height="17" rx="5" />
            <rect x="64" y="50" width="22" height="17" rx="5" />
            <line x1="56" y1="58" x2="64" y2="58" />
            <line x1="34" y1="56" x2="26" y2="52" />
            <line x1="86" y1="56" x2="94" y2="52" />
          </g>
        )}

        {accessory === 'bow' && (
          <g transform="translate(48, 16)">
            <polygon points="0,6 10,0 10,12" fill="#ec4899" stroke="#9d174d" strokeWidth="1.5" />
            <polygon points="24,6 14,0 14,12" fill="#ec4899" stroke="#9d174d" strokeWidth="1.5" />
            <circle cx="12" cy="6" r="4" fill="#fb7185" stroke="#9d174d" strokeWidth="1.5" />
          </g>
        )}

        {accessory === 'hat' && (
          <g transform="translate(42, 4)">
            <polygon points="18,0 0,30 36,30" fill="#f59e0b" stroke="#b45309" strokeWidth="2" />
            <circle cx="18" cy="0" r="3" fill="#fde68a" />
            <rect x="-2" y="28" width="40" height="6" rx="3" fill="#fbbf24" stroke="#b45309" strokeWidth="1.5" />
          </g>
        )}

        {accessory === 'scarf' && (
          <g transform="translate(36, 78)">
            <path
              d="M0 0 Q24 10 48 0 Q52 10 44 14 Q24 20 4 14 Z"
              fill="#ef4444"
              stroke="#991b1b"
              strokeWidth="2"
            />
            <rect x="36" y="8" width="10" height="20" rx="3" fill="#ef4444" stroke="#991b1b" strokeWidth="1.5" />
          </g>
        )}

        {accessory === 'crown' && (
          <g transform="translate(45, 10)">
            <polygon points="0,16 6,4 15,12 24,4 30,16" fill="#fbbf24" stroke="#b45309" strokeWidth="2" />
            <circle cx="6" cy="4" r="2" fill="#ef4444" />
            <circle cx="15" cy="12" r="2" fill="#3b82f6" />
            <circle cx="24" cy="4" r="2" fill="#ef4444" />
            <rect x="0" y="15" width="30" height="4" rx="2" fill="#f59e0b" stroke="#b45309" strokeWidth="1" />
          </g>
        )}

        {accessory === 'headphones' && (
          <g stroke="#0284c7" strokeWidth="3" fill="none">
            <path d="M26 60 C26 26, 94 26, 94 60" />
            {/* Ear pads */}
            <rect x="20" y="52" width="8" height="18" rx="4" fill="#38bdf8" stroke="#0284c7" strokeWidth="1.5" />
            <rect x="92" y="52" width="8" height="18" rx="4" fill="#38bdf8" stroke="#0284c7" strokeWidth="1.5" />
          </g>
        )}

        {/* State Indicators (Thinking sparkles / Sleeping zZ / Celebrate stars) */}
        {state === 'thinking' && (
          <g className="mascot-think-spin" transform="translate(86, 20)">
            <path d="M0 0 L3 6 L9 9 L3 12 L0 18 L-3 12 L-9 9 L-3 6 Z" fill="#fbbf24" stroke="#d97706" strokeWidth="1" />
          </g>
        )}

        {state === 'sleeping' && (
          <g fill="var(--text-muted)" fontSize="12" fontWeight="bold" fontFamily="monospace">
            <text x="82" y="32">z</text>
            <text x="90" y="24">Z</text>
          </g>
        )}

        {state === 'celebrate' && (
          <g fill="#f59e0b">
            <circle cx="20" cy="24" r="3" />
            <circle cx="100" cy="20" r="3" />
            <polygon points="26,12 28,16 32,18 28,20 26,24 24,20 20,18 24,16" />
          </g>
        )}
      </svg>
    </div>
  )
}
