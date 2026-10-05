export function ago(epoch: number | null, now = Date.now() / 1000): string {
  if (epoch === null) return 'never'
  const s = Math.max(0, now - epoch)
  if (s < 45) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400) return `${Math.round(s / 3600)} h ago`
  if (s < 86400 * 14) return `${Math.round(s / 86400)} d ago`
  return new Date(epoch * 1000).toLocaleDateString()
}

/** A future moment in friendly words: "today 08:30", "tomorrow 08:30", "Mon 08:30", or a date. */
export function when(epoch: number, now = new Date()): string {
  const d = new Date(epoch * 1000)
  const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  const days = Math.round((new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() - new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()) / 86_400_000)
  if (days === 0) return `today ${time}`
  if (days === 1) return `tomorrow ${time}`
  if (days > 1 && days < 7) return `${d.toLocaleDateString([], { weekday: 'short' })} ${time}`
  return `${d.toLocaleDateString([], { day: 'numeric', month: 'short' })} ${time}`
}

export function clock(epoch: number): string {
  return new Date(epoch * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function bytes(n: number): string {
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = n
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`
}

export function duration(seconds: number): string {
  if (seconds < 90) return `${Math.round(seconds)} s`
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`
  if (seconds < 172800) return `${(seconds / 3600).toFixed(1)} h`
  return `${Math.round(seconds / 86400)} days`
}

export const STATE_LABEL: Record<string, string> = {
  PENDING: 'Queued',
  PLANNING: 'Thinking',
  RUNNING: 'Working',
  WAITING_APPROVAL: 'Needs you',
  VERIFYING: 'Checking',
  DONE: 'Done',
  FAILED: 'Failed',
  CANCELLED: 'Stopped',
  EXPIRED: 'Timed out',
}

export const TOOL_LABEL: Record<string, string> = {
  'fs.list': 'List a folder',
  'fs.read': 'Read a file',
  'fs.search': 'Search files',
  'fs.write': 'Write a file',
  'fs.apply_moves': 'Move files',
  'fs.trash': 'Move to Trash',
  'data.profile': 'Profile a spreadsheet',
  'web.search': 'Search the web',
  'web.fetch': 'Read web pages',
  'memory.search': 'Look in memory',
  'memory.write': 'Remember something',
  'notes.search': 'Search notes',
  'notes.read': 'Read a note',
  'notes.write': 'Save a note',
  'system.stats': 'Check this computer',
  'computer.open_url': 'Open a link in your browser',
  'computer.open_app': 'Open an app',
  'computer.processes': 'List running programs',
  'computer.stop_process': 'Stop a program',
  'computer.notify': 'Show a notification',
  'computer.run': 'Run a command',
  'llm.work': 'Write with a model',
}
