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


export const OUTCOME_LABEL: Record<string, { label: string; hint: string }> = {
  success: { label: 'Completed', hint: 'The requested goal was verified as achieved.' },
  partial: { label: 'Partially completed', hint: 'Some steps completed, but the full goal was not met.' },
  needs_user: { label: 'Needs input', hint: 'Further user input, choice, or permission is needed.' },
  blocked: { label: 'Blocked', hint: 'Policy, platform, or site restrictions prevented completion.' },
  unverified: { label: 'Not verified', hint: 'Work was performed, but visible success was not verified.' },
}

export interface ToolMeta {
  title: string
  category: string
  description: string
  risk: 'R0' | 'R1' | 'R2' | 'R3'
}

export const TOOL_METADATA: Record<string, ToolMeta> = {
  // Files
  'fs.list': { title: 'List folder', category: 'Files', description: 'List files and subdirectories', risk: 'R0' },
  'fs.read': { title: 'Read file', category: 'Files', description: 'Read file content', risk: 'R0' },
  'fs.edit': { title: 'Edit file', category: 'Files', description: 'Replace exact text in file', risk: 'R1' },
  'fs.search': { title: 'Search files', category: 'Files', description: 'Search files by name or content', risk: 'R0' },
  'fs.write': { title: 'Write file', category: 'Files', description: 'Create or overwrite file', risk: 'R1' },
  'fs.apply_moves': { title: 'Move files', category: 'Files', description: 'Rename or move files', risk: 'R1' },
  'fs.trash': { title: 'Move to Trash', category: 'Files', description: 'Send files to trash', risk: 'R1' },

  // Data & Web
  'data.profile': { title: 'Profile spreadsheet', category: 'Data', description: 'Inspect structure of tabular data', risk: 'R0' },
  'web.search': { title: 'Search web', category: 'Web', description: 'Search public search engines', risk: 'R0' },
  'web.fetch': { title: 'Read web page', category: 'Web', description: 'Extract text from public URL', risk: 'R0' },

  // Memory & Notes
  'memory.search': { title: 'Search memory', category: 'Memory', description: 'Look up long-term facts', risk: 'R0' },
  'memory.write': { title: 'Save memory', category: 'Memory', description: 'Store a confirmed fact', risk: 'R1' },
  'notes.search': { title: 'Search notes', category: 'Notes', description: 'Search user notes', risk: 'R0' },
  'notes.read': { title: 'Read note', category: 'Notes', description: 'Read a saved note', risk: 'R0' },
  'notes.write': { title: 'Save note', category: 'Notes', description: 'Write or update a note', risk: 'R1' },

  // Host Desktop
  'system.stats': { title: 'System stats', category: 'System', description: 'Inspect CPU, memory and disk', risk: 'R0' },
  'computer.open_url': { title: 'Open link', category: 'Computer', description: 'Open URL in default browser', risk: 'R1' },
  'computer.open_app': { title: 'Open app', category: 'Computer', description: 'Launch a desktop application', risk: 'R1' },
  'computer.processes': { title: 'List programs', category: 'Computer', description: 'Inspect active processes', risk: 'R0' },
  'computer.stop_process': { title: 'Stop program', category: 'Computer', description: 'Terminate a process', risk: 'R2' },
  'computer.notify': { title: 'Show notification', category: 'Computer', description: 'Display desktop notification', risk: 'R1' },
  'computer.run': { title: 'Run command', category: 'Computer', description: 'Run shell command on host', risk: 'R2' },
  'computer.observe': { title: 'Capture screen', category: 'Computer', description: 'Take a screenshot of desktop', risk: 'R0' },
  'computer.click': { title: 'Click screen', category: 'Computer', description: 'Click mouse at coordinates', risk: 'R1' },
  'computer.type': { title: 'Type text', category: 'Computer', description: 'Type keystrokes on desktop', risk: 'R1' },
  'computer.press': { title: 'Press key', category: 'Computer', description: 'Press keyboard shortcut', risk: 'R1' },
  'computer.move': { title: 'Move cursor', category: 'Computer', description: 'Move mouse pointer', risk: 'R0' },
  'computer.scroll': { title: 'Scroll screen', category: 'Computer', description: 'Scroll mouse wheel', risk: 'R0' },
  'computer.drag': { title: 'Drag mouse', category: 'Computer', description: 'Click and drag mouse', risk: 'R1' },

  // Browser Control
  'browser.open': { title: 'Open browser', category: 'Browser', description: 'Navigate browser to URL', risk: 'R0' },
  'browser.read': { title: 'Read page', category: 'Browser', description: 'Inspect text and structure of current page', risk: 'R0' },
  'browser.find': { title: 'Find on page', category: 'Browser', description: 'Locate text or interactive elements', risk: 'R0' },
  'browser.click': { title: 'Click element', category: 'Browser', description: 'Click button, link or element', risk: 'R1' },
  'browser.type': { title: 'Type in page', category: 'Browser', description: 'Input text into form field', risk: 'R1' },
  'browser.press': { title: 'Press key in page', category: 'Browser', description: 'Send key event to page', risk: 'R0' },
  'browser.select': { title: 'Select option', category: 'Browser', description: 'Choose dropdown item', risk: 'R1' },
  'browser.submit': { title: 'Submit form', category: 'Browser', description: 'Submit active HTML form', risk: 'R1' },
  'browser.scroll': { title: 'Scroll page', category: 'Browser', description: 'Scroll page content', risk: 'R0' },
  'browser.back': { title: 'Back navigation', category: 'Browser', description: 'Navigate back in browser history', risk: 'R0' },
  'browser.close': { title: 'Close browser', category: 'Browser', description: 'Close current browser page/window', risk: 'R0' },

  // DevBox
  'devbox.run': { title: 'Run in DevBox', category: 'DevBox', description: 'Execute command inside isolated container', risk: 'R1' },

  // Agent & Skills
  'agent.ask': { title: 'Ask user', category: 'Agent', description: 'Ask question to the user', risk: 'R0' },
  'agent.think': { title: 'Reasoning', category: 'Agent', description: 'Record internal thought', risk: 'R0' },
  'agent.discover': { title: 'Discover tools', category: 'Agent', description: 'Find relevant available tools', risk: 'R0' },
  'skill.load': { title: 'Load skill', category: 'Skills', description: 'Load agent-sheet procedural skill', risk: 'R0' },
  'llm.work': { title: 'Write with model', category: 'Model', description: 'Generate text with model', risk: 'R0' },
  'result.read': { title: 'Read step result', category: 'System', description: 'Retrieve output of a previous step', risk: 'R0' },
}

export function toolTitle(toolName: string): string {
  if (TOOL_METADATA[toolName]) {
    return TOOL_METADATA[toolName].title
  }
  // Humanized fallback for unknown or MCP tools: e.g. "mcp.github.create_issue" -> "Create issue (mcp.github)"
  const parts = toolName.split('.')
  if (parts.length > 1) {
    const action = parts[parts.length - 1].replace(/_/g, ' ')
    const prefix = parts.slice(0, parts.length - 1).join('.')
    return `${action.charAt(0).toUpperCase() + action.slice(1)} (${prefix})`
  }
  return toolName.replace(/_/g, ' ')
}

export function toolMeta(toolName: string): ToolMeta {
  if (TOOL_METADATA[toolName]) {
    return TOOL_METADATA[toolName]
  }
  return {
    title: toolTitle(toolName),
    category: toolName.includes('.') ? toolName.split('.')[0] : 'Tool',
    description: toolName,
    risk: 'R1',
  }
}

export const TOOL_LABEL: Record<string, string> = new Proxy(
  Object.fromEntries(Object.entries(TOOL_METADATA).map(([k, v]) => [k, v.title])),
  {
    get(target, prop: string) {
      if (prop in target) return target[prop]
      return toolTitle(prop)
    },
  }
)
