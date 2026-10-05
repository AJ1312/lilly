import type { ReactNode } from 'react'

// A small, safe renderer: it builds React elements (never HTML strings), and only http(s) links are live.
const INLINE = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\[[^\]\n]+\]\(https?:\/\/[^\s)]+\)|https?:\/\/[^\s<>)]+)/g

function inline(text: string, key: string): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  let n = 0
  for (const m of text.matchAll(INLINE)) {
    const at = m.index ?? 0
    if (at > last) out.push(text.slice(last, at))
    const tok = m[0]
    const k = `${key}-${n++}`
    if (tok.startsWith('`')) out.push(<code key={k}>{tok.slice(1, -1)}</code>)
    else if (tok.startsWith('**')) out.push(<strong key={k}>{tok.slice(2, -2)}</strong>)
    else if (tok.startsWith('[')) {
      const close = tok.indexOf('](')
      out.push(
        <a key={k} href={tok.slice(close + 2, -1)} target="_blank" rel="noopener noreferrer">
          {tok.slice(1, close)}
        </a>,
      )
    } else {
      out.push(
        <a key={k} href={tok} target="_blank" rel="noopener noreferrer">
          {tok}
        </a>,
      )
    }
    last = at + tok.length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

export function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r\n/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let i = 0
  let b = 0
  while (i < lines.length) {
    const line = lines[i]
    const key = `b${b++}`
    if (line.startsWith('```')) {
      const body: string[] = []
      i++
      while (i < lines.length && !lines[i].startsWith('```')) body.push(lines[i++])
      i++
      blocks.push(<pre key={key}><code>{body.join('\n')}</code></pre>)
    } else if (/^#{1,3}\s/.test(line)) {
      blocks.push(<h4 key={key}>{inline(line.replace(/^#{1,3}\s/, ''), key)}</h4>)
      i++
    } else if (/^\s*([-*]|\d+\.)\s/.test(line)) {
      const ordered = /^\s*\d+\./.test(line)
      const items: ReactNode[] = []
      while (i < lines.length && /^\s*([-*]|\d+\.)\s/.test(lines[i])) {
        items.push(<li key={`${key}-${i}`}>{inline(lines[i].replace(/^\s*([-*]|\d+\.)\s/, ''), `${key}-${i}`)}</li>)
        i++
      }
      blocks.push(ordered ? <ol key={key}>{items}</ol> : <ul key={key}>{items}</ul>)
    } else if (line.trim() === '') {
      i++
    } else {
      const para: string[] = []
      while (i < lines.length && lines[i].trim() !== '' && !lines[i].startsWith('```') && !/^#{1,3}\s/.test(lines[i]) && !/^\s*([-*]|\d+\.)\s/.test(lines[i])) para.push(lines[i++])
      blocks.push(<p key={key}>{inline(para.join('\n'), key)}</p>)
    }
  }
  return <div className="md">{blocks}</div>
}
