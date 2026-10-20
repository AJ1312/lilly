import React, { useState } from 'react'
import { Icon } from './Icon'

interface MarkdownProps {
  content: string
  className?: string
}

export const Markdown: React.FC<MarkdownProps> = ({ content, className = '' }) => {
  if (!content) return null

  // Split by code blocks
  const parts = content.split(/(```[\s\S]*?```)/g)

  return (
    <div className={`markdown-rendered ${className}`} style={{ lineHeight: 1.6, wordBreak: 'break-word' }}>
      {parts.map((part, index) => {
        if (part.startsWith('```') && part.endsWith('```')) {
          const firstLineEnd = part.indexOf('\n')
          const lang =
            firstLineEnd > 3 ? part.slice(3, firstLineEnd).trim() : 'text'
          const code =
            firstLineEnd > 3
              ? part.slice(firstLineEnd + 1, -3)
              : part.slice(3, -3)
          return <CodeBlock key={index} code={code} lang={lang} />
        }

        return <MarkdownText key={index} text={part} />
      })}
    </div>
  )
}

const CodeBlock: React.FC<{ code: string; lang: string }> = ({ code, lang }) => {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // fallback
    }
  }

  return (
    <div
      style={{
        margin: '12px 0',
        borderRadius: 'var(--radius-sm)',
        border: '1px solid var(--border)',
        overflow: 'hidden',
        backgroundColor: 'var(--bg-input)',
        maxWidth: '100%',
        minWidth: 0,
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '6px 12px',
          backgroundColor: 'var(--bg-card-subtle)',
          borderBottom: '1px solid var(--border-subtle)',
          fontSize: '11px',
          color: 'var(--text-muted)',
          fontFamily: 'var(--font-mono)',
        }}
      >
        <span>{lang || 'code'}</span>
        <button
          onClick={handleCopy}
          className="btn btn-ghost btn-sm"
          style={{ padding: '2px 6px', fontSize: '11px' }}
          type="button"
          title="Copy to clipboard"
        >
          <Icon name={copied ? 'check' : 'copy'} size={12} />
          <span>{copied ? 'Copied' : 'Copy'}</span>
        </button>
      </div>
      <pre
        style={{
          padding: '12px',
          overflowX: 'auto',
          maxWidth: '100%',
          minWidth: 0,
          boxSizing: 'border-box',
          fontSize: '12px',
          lineHeight: 1.45,
          margin: 0,
          fontFamily: 'var(--font-mono)',
          color: 'var(--text-main)',
        }}
      >
        <code>{code}</code>
      </pre>
    </div>
  )
}

const MarkdownText: React.FC<{ text: string }> = ({ text }) => {
  // Parse paragraphs and linebreaks
  const paragraphs = text.split(/\n\n+/)

  return (
    <>
      {paragraphs.map((p, pIdx) => {
        const trimmed = p.trim()
        if (!trimmed) return null

        // Header detection
        if (trimmed.startsWith('### ')) {
          return (
            <h4
              key={pIdx}
              style={{
                fontSize: '15px',
                fontWeight: 600,
                margin: '12px 0 6px 0',
                color: 'var(--text-main)',
              }}
            >
              <InlineText text={trimmed.slice(4)} />
            </h4>
          )
        }
        if (trimmed.startsWith('## ')) {
          return (
            <h3
              key={pIdx}
              style={{
                fontSize: '17px',
                fontWeight: 600,
                margin: '14px 0 6px 0',
                color: 'var(--text-main)',
              }}
            >
              <InlineText text={trimmed.slice(3)} />
            </h3>
          )
        }
        if (trimmed.startsWith('# ')) {
          return (
            <h2
              key={pIdx}
              style={{
                fontSize: '19px',
                fontWeight: 700,
                margin: '16px 0 8px 0',
                color: 'var(--text-main)',
              }}
            >
              <InlineText text={trimmed.slice(2)} />
            </h2>
          )
        }

        // List detection
        const lines = trimmed.split('\n')
        const isList = lines.every((l) => /^\s*[-*]\s+/.test(l) || /^\s*\d+\.\s+/.test(l))
        if (isList) {
          return (
            <ul
              key={pIdx}
              style={{
                paddingLeft: '20px',
                margin: '8px 0',
                display: 'flex',
                flexDirection: 'column',
                gap: '4px',
              }}
            >
              {lines.map((li, liIdx) => (
                <li key={liIdx}>
                  <InlineText text={li.replace(/^\s*[-*]\s+/, '').replace(/^\s*\d+\.\s+/, '')} />
                </li>
              ))}
            </ul>
          )
        }

        return (
          <p key={pIdx} style={{ margin: '8px 0' }}>
            {lines.map((l, lIdx) => (
              <React.Fragment key={lIdx}>
                {lIdx > 0 && <br />}
                <InlineText text={l} />
              </React.Fragment>
            ))}
          </p>
        )
      })}
    </>
  )
}

const InlineText: React.FC<{ text: string }> = ({ text }) => {
  // Simple regex parser for inline code, bold, links
  const tokens = text.split(/(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g)

  return (
    <>
      {tokens.map((tok, idx) => {
        if (tok.startsWith('`') && tok.endsWith('`')) {
          return (
            <code
              key={idx}
              style={{
                backgroundColor: 'var(--bg-input)',
                border: '1px solid var(--border-subtle)',
                padding: '1px 5px',
                borderRadius: 'var(--radius-xs)',
                fontSize: '12px',
                color: 'var(--primary)',
                wordBreak: 'break-all',
                overflowWrap: 'anywhere',
                maxWidth: '100%',
              }}
            >
              {tok.slice(1, -1)}
            </code>
          )
        }
        if (tok.startsWith('**') && tok.endsWith('**')) {
          return <strong key={idx}>{tok.slice(2, -2)}</strong>
        }
        const linkMatch = tok.match(/^\[([^\]]+)\]\(([^)]+)\)$/)
        if (linkMatch) {
          return (
            <a
              key={idx}
              href={linkMatch[2]}
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: 'var(--primary)', textDecoration: 'underline' }}
            >
              {linkMatch[1]}
            </a>
          )
        }
        return <span key={idx}>{tok}</span>
      })}
    </>
  )
}
