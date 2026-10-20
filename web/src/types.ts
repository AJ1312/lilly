export type ExecutionTarget = 'host' | 'devbox'
export type TaskState = 'PENDING' | 'PLANNING' | 'RUNNING' | 'WAITING_APPROVAL' | 'VERIFYING' | 'DONE' | 'FAILED' | 'CANCELLED' | 'EXPIRED'
export type TaskOutcome = 'success' | 'partial' | 'needs_user' | 'blocked'
export type RequestIntent = 'AUTO' | 'ANSWER' | 'WEB RETRIEVE' | 'NAVIGATE' | 'ACTION'
export type ApprovalMode = 'MANUAL' | 'AUTO' | 'OFF'
export type FreedomMode = 'LOCKED' | 'ASK' | 'OPEN'
export type ThemePref = 'system' | 'light' | 'dark'

export interface DecisionLog {
  id: number
  kind: string
  choice: string
  prompt?: string
  confidence?: number
  outcome?: string
  created_at: number
}

export interface Task {
  id: string
  goal: string
  state: TaskState
  outcome?: TaskOutcome | null
  outcome_reason?: string | null
  target: ExecutionTarget
  mode: number
  label: string
  tainted: boolean
  created_at: number
  updated_at: number
  conversation_id: string | null
  agent_id: string | null
  pinned_model: string | null
  error?: string | null
  answer?: string | null
  cost_usd?: number
  tokens_used?: number
  duration_s?: number
  steps?: StepRecord[]
}

export interface StepRecord {
  id: string
  task_id: string
  tool: string
  status: 'pending' | 'running' | 'success' | 'failed' | 'cancelled'
  args: Record<string, unknown>
  result?: unknown
  error?: string | null
  started_at?: number
  completed_at?: number
  duration_s?: number
  cached?: boolean
}

export interface TaskThought {
  layer: 'plan' | 'act' | 'verify' | 'reflect'
  text: string
  step?: string | null
  ts: number
}

export interface PlanStep {
  id: string
  tool: string
  why: string
  args: Record<string, unknown>
  expect: string
  deps: string[]
  verdict?: string | null
}

export interface Approval {
  id: string
  task_id: string
  step_id: string
  tool: string
  target: ExecutionTarget
  risk: 'R0' | 'R1' | 'R2'
  why: string
  payload: Record<string, unknown>
  payload_hash: string
  created_at: number
  decline_continues?: boolean
}

export interface TaskDetail {
  task: Task
  steps: StepRecord[]
  approvals: Approval[]
  plan_steps: PlanStep[]
  reply_check?: string | null
}

export interface Thread {
  id: string
  title: string
  created_at: number
  updated_at: number
  agent_id: string | null
  task_count?: number
  last_goal?: string
}

export interface Message {
  id: string
  conversation_id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  task_id?: string | null
  created_at: number
}

export interface PetLook {
  hue: number | null
  accessory: 'none' | 'bow' | 'glasses' | 'hat' | 'scarf' | 'crown' | 'headphones'
  eyes: 'round' | 'sparkle' | 'sleepy'
  blush: boolean
}

export interface Agent {
  id: string
  name: string
  instructions: string
  mode: number
  research_allowed: boolean
  memory_allowed: boolean
  files_allowed: boolean
  computer_allowed: boolean
  chat_allowed: boolean
  pet: string
  look: PetLook
  skills: string
  model: string
  space_id?: string | null
  created_at?: number
}

export interface Memory {
  id: string
  fact?: string
  text?: string
  category?: string
  tags?: string[]
  confidence?: number
  created_at: number
  at?: number
  updated_at?: number
  source_task_id?: string | null
}

export interface Space {
  id: string
  name: string
  icon?: string
  created_at: number
  page_count?: number
}

export interface NotePage {
  id: string
  space_id: string
  title: string
  content: string
  created_at: number
  updated_at: number
  revision?: number
}

export interface SkillParam {
  name: string
  description?: string
  required?: boolean
  default?: string
}

export interface Skill {
  name: string
  summary: string
  risk: string
  params: string[]
  module?: string
}

export type Schedule =
  | { kind: 'every'; every_minutes: number }
  | { kind: 'at'; at: string; days: number[] }

export interface Routine {
  id: string
  name: string
  goal: string
  agent_id: string | null
  schedule: Schedule
  when: string
  enabled: boolean
  next_run: number | null
  last_run: number | null
  last_task_id: string | null
  last_state: string | null
  last_error: string | null
  pause_reason: string | null
  playbook_id?: string | null
  playbook_version?: number | null
  target?: ExecutionTarget | null
}

export interface Playbook {
  id: string
  name: string
  description?: string
  task_signature: string
  version: number
  target: ExecutionTarget
  steps_json?: string
  parameters_json?: string
  preconditions_json?: string
  provenance_task_id?: string | null
  success_count: number
  status?: string
  created_at: number
}

export interface ModelSpec {
  name: string
  provider: string
  model_id: string
  local: boolean
  enabled: boolean
  caps?: string[]
  max_label?: string
  rpm?: number | null
  rpd?: number | null
  tpm?: number | null
  tpd?: number | null
  tz?: string
  key_ref?: string
  private_access?: string
  trains?: boolean
  base_url?: string | null
  quick?: boolean
  lane?: number
  tags?: string[]
  tools?: string
  max_context_tokens?: number | null
}

export interface ModelStatus extends ModelSpec {
  breaker: string
  minute_used: number | null
  day_used: number | null
  resets_in_s: number | null
  last_error: string | null
  calls: number
  tokens_in: number
  tokens_out: number
  has_key: boolean
}

export interface KeyInfo {
  ref: string
  present: boolean
}

export interface LearningSettings {
  mode: 'off' | 'suggest' | 'auto'
  auto_playbooks: boolean
}

export interface Limits {
  max_running: number
  lanes: number
  step_timeout_s: number
  task_minutes: number
  local_unload_s: number
  max_agent_steps: number
  max_model_calls: number
  max_task_tokens: number
}

export interface BrowserSettings {
  mode: 'ask_every' | 'ask_risky' | 'allowlist'
  allow_hosts: string[]
  max_actions: number
  idle_quit_s: number
  headless: boolean
  chrome_path: string
}

export interface DevboxSettings {
  runtime: 'auto' | 'docker' | 'podman'
  image: string
  shared_folder: string
  cpus: number
  memory_mb: number
  pids: number
  idle_stop_s: number
  destroy_after_s: number
  command_timeout_s: number
}

export interface DevboxStatus {
  engine: string | null
  image: string
  image_ready: boolean
  state: 'unavailable' | 'missing' | 'stopped' | 'running'
  folder_ok: boolean
  folder_problem: string | null
  preparing: boolean
  prepare_error: string | null
}

export interface KindSettings {
  chain: string[]
  enabled: boolean
  min_confidence: Record<string, number>
  min_precision: Record<string, number>
  min_samples: Record<string, number>
  shadow: boolean
  timeout_s: Record<string, number>
}

export interface DecisionSettings {
  enabled: boolean
  instructions: KindSettings
  loop: KindSettings
  max_model_tokens_per_task: number
  max_per_task: number
  min_free_mb: number
  pick: KindSettings
  plan: KindSettings
  reply: KindSettings
  route: KindSettings
  tools: KindSettings
}

export interface BridgeSettings {
  enabled: boolean
  agent_id: string | null
  private_replies: boolean
  per_minute: number
  max_chars: number
}

export interface BridgeIdentity {
  user_id: number
  label: string
  paired_at: number
}

export interface BridgeStatus {
  platform: string
  enabled: boolean
  running: boolean
  token_set: boolean
  bot: string | null
  error: string | null
  pairing_until: number | null
  identities: BridgeIdentity[]
}

export interface Settings {
  modules: string[]
  default_mode: FreedomMode
  approval_mode: ApprovalMode
  file_roots: string[]
  retention_days: number
  network: { allowed_hosts: string[]; local_only?: boolean }
  search: { engine: 'duckduckgo' | 'brave' | 'searxng'; searxng_url: string | null }
  stay_awake: boolean
  limits: Limits
  decisions: DecisionSettings
  bridges: BridgeSettings
  devbox: DevboxSettings
  browser: BrowserSettings
  capacity: {
    max_wait_interactive_s: number
    max_wait_background_s: number
    inline_retry_max_s: number
    max_inflight_per_model: number
    learn_limits: boolean
    spread: string
    chars_per_token: number
  }
  engine: {
    mode: string
    observation_chars: number
    soft_context_tokens: number
    read_cache_ttl_s: number
    self_check: boolean
  }
  grounding: {
    enabled: boolean
    protected_globs: string[]
  }
  crew: {
    max_depth: number
    max_children: number
    child_budget_share: number
    min_confidence: number
  }
  learning: LearningSettings
  models: ModelSpec[]
}

export interface SystemInfo {
  version: string
  python: string
  platform: string
  home: string
  uptime_s: number
  running_tasks: number
  pending_approvals: number
  stay_awake_active: boolean
  settings_problems: string[]
  key_store: { kind: string; secure: boolean }
  stats: {
    cpu_percent: number
    memory: { total: number; available: number; percent: number }
    disk: { total: number; free: number; percent: number }
  }
}

export interface Resources {
  machine: {
    cpu_percent: number
    memory: { total: number; available: number; percent: number }
    disk: { total: number; free: number; percent: number }
    top_processes: Array<{ pid: number; name: string; memory_percent: number }>
  }
  lilly: {
    pid: number
    cpu_percent: number
    memory_bytes: number
    threads: number
    database_bytes: number
    backups_bytes: number
    logs_bytes: number
  }
  tasks: {
    running: number
    queued: number
    waiting_approval: number
    live: Array<{ id: string; goal: string; state: TaskState; created_at: number; target: ExecutionTarget }>
  }
  limits: Limits
  models: ModelStatus[]
  stay_awake_active: boolean
}

export interface McpServer {
  name: string
  command: string
  args: string[]
  env: Record<string, string>
  secret_vars: Array<{ var: string; ref: string; present: boolean }>
  enabled: boolean
  data_label: 'PUBLIC' | 'PERSONAL'
  tools?: Array<{ name: string; description: string; risk: string }>
}

export interface LayaStatus {
  installed: boolean
  installing: boolean
  progress: string[]
  error: string | null
  download_mb: number
  worker: 'off' | 'loading' | 'ready'
  note: string | null
  enabled_for: string[]
}

export interface LayaCheck {
  name: string
  ok: boolean
  detail: string
}

export interface LayaTestCase {
  name: string
  expected: string
  got: string
  confidence: number
  ms: number
  ok: boolean
}

export interface LayaTestReport {
  ok: boolean
  loaded: boolean
  load_ms: number
  results: LayaTestCase[]
  error?: string | null
}

export const EXECUTION_TARGETS: Array<{ value: ExecutionTarget; label: string; hint: string }> = [
  { value: 'host', label: 'This laptop', hint: 'Direct host execution with granted file and desktop permissions.' },
  { value: 'devbox', label: 'Isolated DevBox', hint: 'Runs in a secured container; strictly separated from host files and desktop.' },
]

export const REQUEST_INTENTS: Array<{ value: RequestIntent; label: string; hint: string }> = [
  { value: 'AUTO', label: 'Automatic', hint: 'Classify intent automatically from wording.' },
  { value: 'ANSWER', label: 'Answer', hint: 'Direct answer without starting browser or tools.' },
  { value: 'WEB RETRIEVE', label: 'Web search', hint: 'Fetch research and public listings.' },
  { value: 'NAVIGATE', label: 'Navigate', hint: 'Open a URL or destination application.' },
  { value: 'ACTION', label: 'Act', hint: 'Execute steps until outcome is independently verified.' },
]

export const APPROVAL_MODES: Array<{ value: ApprovalMode; name: string; blurb: string; tagline: string }> = [
  {
    value: 'AUTO',
    name: 'Auto',
    tagline: 'Move without permission',
    blurb: 'Move without my permission; executes tasks and actions autonomously within safety guardrails.',
  },
  {
    value: 'MANUAL',
    name: 'Ask',
    tagline: 'Ask for my permission',
    blurb: 'Ask mode; pauses and requests your permission before taking any actions.',
  },
  {
    value: 'OFF',
    name: 'Off',
    tagline: 'Responses only',
    blurb: 'Off mode; stops all agentic tasks and tool execution, giving direct conversational responses only.',
  },
]

export const FREEDOM_MODES: Array<{ value: FreedomMode; name: string; blurb: string }> = [
  { value: 'LOCKED', name: 'Locked', blurb: 'Never reads private files or stored memories.' },
  { value: 'ASK', name: 'Ask', blurb: 'Prompts before reading private folders or altering data.' },
  { value: 'OPEN', name: 'Open', blurb: 'Operates freely inside shared folders.' },
]

export interface CapacityModel {
  name: string
  lane: number
  breaker: string
  rpm: number | null
  rpm_used: number | null
  rpd: number | null
  rpd_used: number | null
  tpm: number | null
  tpm_used: number | null
  tpd: number | null
  tpd_used: number | null
  ready_in_s: number | null
  resets_in_s: number | null
}

export interface Capacity {
  models: CapacityModel[]
  queue_length: number
  estimated_tasks_left_today: number | null
}

