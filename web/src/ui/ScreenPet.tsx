import React, { useState, useEffect } from 'react'
import { useAppStore } from '../store'
import { LillyMascot } from './LillyMascot'
import { Icon } from './Icon'
import type { PetSpecies } from './LillyMascot'

export const ScreenPet: React.FC = () => {
  const pendingApprovals = useAppStore((s) => s.pendingApprovalsCount)
  const [minimized, setMinimized] = useState(false)
  const [visible, setVisible] = useState(true)
  const [pet, setPet] = useState<PetSpecies>('lily')
  const [accessory, setAccessory] = useState<'none' | 'glasses' | 'bow' | 'hat' | 'scarf' | 'crown' | 'headphones'>('glasses')
  const [hue, setHue] = useState(250)
  const [expression, setExpression] = useState<'round' | 'happy' | 'sparkle' | 'sleepy' | 'wink'>('sparkle')
  const [speech, setSpeech] = useState<string | null>('Hi friend! I’m your screen companion! ✨')
  const [showConfig, setShowConfig] = useState(false)
  const [hearts, setHearts] = useState<{ id: number; x: number; y: number }[]>([])

  useEffect(() => {
    const timer = setTimeout(() => {
      setSpeech(null)
    }, 4500)
    return () => clearTimeout(timer)
  }, [])

  // React to pending approvals
  useEffect(() => {
    if (pendingApprovals > 0) {
      setSpeech(`Attention! ${pendingApprovals} action${pendingApprovals > 1 ? 's need' : ' needs'} approval!`)
      setExpression('round')
    }
  }, [pendingApprovals])

  const handlePat = () => {
    const id = Date.now()
    setHearts((prev) => [...prev, { id, x: 20 + Math.random() * 40, y: 10 + Math.random() * 20 }])
    setTimeout(() => {
      setHearts((prev) => prev.filter((h) => h.id !== id))
    }, 1200)

    const compliments = [
      'Purr~ Keep up the great work!',
      'You are doing amazing!',
      'All tests passing! ✨',
      'Host system safe and sound!',
      'Pip & Lilly approve this workflow! ❤️',
    ]
    setSpeech(compliments[Math.floor(Math.random() * compliments.length)])
    setExpression('happy')
    setTimeout(() => setSpeech(null), 3000)
  }

  if (!visible) {
    return (
      <button
        type="button"
        onClick={() => setVisible(true)}
        style={{
          position: 'fixed',
          bottom: '20px',
          right: '20px',
          backgroundColor: 'var(--primary)',
          color: 'white',
          border: 'none',
          borderRadius: 'var(--radius-full)',
          padding: '8px 14px',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          boxShadow: 'var(--shadow-lg)',
          cursor: 'pointer',
          zIndex: 90,
          fontSize: '12px',
          fontWeight: 600,
        }}
        title="Summon Screen Pet Companion"
      >
        <span>🐾 Summon Pet</span>
      </button>
    )
  }

  return (
    <aside
      aria-label="Screen Pet Companion"
      style={{
        position: 'fixed',
        bottom: '20px',
        right: '24px',
        zIndex: 90,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-end',
        pointerEvents: 'none',
      }}
    >
      {/* Floating Hearts Animation */}
      {hearts.map((h) => (
        <span
          key={h.id}
          style={{
            position: 'absolute',
            bottom: '100px',
            right: `${h.x}px`,
            fontSize: '18px',
            animation: 'bubblePop 1.2s ease-out forwards',
            pointerEvents: 'none',
            zIndex: 100,
          }}
        >
          💖
        </span>
      ))}

      {/* Mini Companion Settings Popover */}
      {showConfig && !minimized && (
        <div
          className="card"
          style={{
            pointerEvents: 'auto',
            marginBottom: '12px',
            width: '260px',
            padding: '14px',
            boxShadow: 'var(--shadow-lg)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-md)',
            backgroundColor: 'var(--bg-card)',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
            <span style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-main)' }}>Companion Customizer</span>
            <button
              type="button"
              onClick={() => setShowConfig(false)}
              className="btn btn-ghost btn-sm"
              style={{ padding: '2px 6px' }}
            >
              ✕
            </button>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '11px' }}>
            <div>
              <label style={{ display: 'block', color: 'var(--text-muted)', marginBottom: '3px' }}>Species</label>
              <select
                className="select"
                value={pet}
                onChange={(e) => setPet(e.target.value as PetSpecies)}
                style={{ fontSize: '11px', padding: '4px 8px' }}
              >
                <option value="lily">🐰 Lily (Bunny)</option>
                <option value="pip">🐧 Pip (Penguin / Bird)</option>
                <option value="mochi">🍡 Mochi (Boba Slime)</option>
                <option value="bao">🐼 Bao (Panda)</option>
                <option value="fern">🦌 Fern (Forest Deer)</option>
                <option value="juno">🐶 Juno (Star Dog)</option>
                <option value="otto">🦦 Otto (Cyber Otter)</option>
                <option value="wisp">👻 Wisp (Spirit Flame)</option>
              </select>
            </div>

            <div>
              <label style={{ display: 'block', color: 'var(--text-muted)', marginBottom: '3px' }}>Accessory</label>
              <select
                className="select"
                value={accessory}
                onChange={(e) => setAccessory(e.target.value as any)}
                style={{ fontSize: '11px', padding: '4px 8px' }}
              >
                <option value="none">None</option>
                <option value="glasses">Smart Glasses</option>
                <option value="bow">Pink Bow</option>
                <option value="hat">Wizard Hat</option>
                <option value="scarf">Warm Scarf</option>
                <option value="crown">Royal Crown</option>
                <option value="headphones">DJ Headphones</option>
              </select>
            </div>

            <div>
              <label style={{ display: 'block', color: 'var(--text-muted)', marginBottom: '3px' }}>
                Hue Color ({hue}°)
              </label>
              <input
                type="range"
                min="0"
                max="359"
                value={hue}
                onChange={(e) => setHue(Number(e.target.value))}
                style={{ width: '100%', cursor: 'pointer' }}
              />
            </div>

            <div>
              <label style={{ display: 'block', color: 'var(--text-muted)', marginBottom: '3px' }}>Expression</label>
              <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                {(['round', 'happy', 'sparkle', 'sleepy', 'wink'] as const).map((exp) => (
                  <button
                    key={exp}
                    type="button"
                    onClick={() => setExpression(exp)}
                    className={`btn btn-sm ${expression === exp ? 'btn-primary' : 'btn-secondary'}`}
                    style={{ fontSize: '10px', padding: '2px 6px', textTransform: 'capitalize' }}
                  >
                    {exp}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Screen Pet Body & Actions Dock */}
      <div
        style={{
          pointerEvents: 'auto',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          position: 'relative',
        }}
      >
        {!minimized && (
          <div
            style={{
              position: 'relative',
              cursor: 'pointer',
              marginBottom: '-6px',
            }}
            onClick={handlePat}
            title="Click to pet and cheer on!"
          >
            <LillyMascot
              pet={pet}
              look={{ hue, accessory, eyes: expression, blush: true }}
              size={96}
              speech={speech}
              state={pendingApprovals > 0 ? 'thinking' : expression === 'happy' ? 'happy' : 'idle'}
              interactive
            />
          </div>
        )}

        {/* Companion Control Dock */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            padding: '4px 8px',
            backgroundColor: 'var(--bg-card)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-full)',
            boxShadow: 'var(--shadow-md)',
          }}
        >
          <button
            type="button"
            onClick={handlePat}
            className="btn btn-ghost btn-sm"
            style={{ padding: '2px 6px', fontSize: '12px' }}
            title="Pet companion"
          >
            💖 Pat
          </button>

          <button
            type="button"
            onClick={() => setShowConfig(!showConfig)}
            className="btn btn-ghost btn-sm"
            style={{ padding: '2px 6px' }}
            title="Customize companion"
          >
            <Icon name="sliders" size={12} />
          </button>

          <button
            type="button"
            onClick={() => setMinimized(!minimized)}
            className="btn btn-ghost btn-sm"
            style={{ padding: '2px 6px' }}
            title={minimized ? 'Expand pet' : 'Minimize pet'}
          >
            <Icon name={minimized ? 'chevron-down' : 'chevron-right'} size={12} />
          </button>

          <button
            type="button"
            onClick={() => setVisible(false)}
            className="btn btn-ghost btn-sm"
            style={{ padding: '2px 6px', color: 'var(--text-dim)' }}
            title="Dismiss pet"
          >
            ✕
          </button>
        </div>
      </div>
    </aside>
  )
}
