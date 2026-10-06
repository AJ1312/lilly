export type TaskState =
  | 'PENDING' | 'PLANNING' | 'RUNNING' | 'WAITING_APPROVAL' | 'VERIFYING' | 'DONE' | 'FAILED' | 'CANCELLED' | 'EXPIRED'

export const LIVE_STATES: TaskState[] = ['PENDING', 'PLANNING', 'RUNNING', 'WAITING_APPROVAL', 'VERIFYING']

export interface Task {
  id: string
  conversation_id: string | null
  agent_id: string | null
  state: TaskState
  goal: string
  mode: number
  label: string
  tainted: boolean
  skill: string | null
  plan: { reasoning?: string; steps?: { id: string; tool: string; expect?: string }[] } | null
  pinned_model: string | null
  answer: string | null
  error: string | null
  created_at: number
  updated_at: number
  finished_at: number | null
  reply_check?: 'follows' | 'drifts' | null
}

export interface Step {
  id: string
  position: number
  tool: string
  status: string
  args: Record<string, unknown> | null
  output: string | null
  label: string
  untrusted: boolean
  error: string | null
  started_at: number | null
  finished_at: number | null
}

export interface Approval {
  id: string
  task_id: string
  step_id: string
  kind: 'step' | 'model' | 'question'
  summary: string
  payload: Record<string, unknown> | null
  payload_hash: string
  status: 'pending' | 'approved' | 'denied' | 'expired'
  created_at: number
  expires_at: number
  decided_at: number | null
}

export interface LilEvent {
  seq: number
  kind: string
  payload: Record<string, unknown>
  by: string
  at: number
}

export interface Thread { id: string; title: string; archived: boolean; created_at: number; updated_at: number }
export interface Message { id: number; task_id: string | null; role: 'user' | 'assistant'; content: string; label: string; untrusted: boolean; at: number }
export type Verdict = 'ALLOW' | 'NEEDS_APPROVAL' | 'DENY'
/** One step of the plan as announced before anything ran: what it needs, and what policy predicted for it. */
export interface PlanStep { id: string; tool: string; expect: string; args: Record<string, unknown>; deps: string[]; verdict: Verdict; why: string }
/** `reply_check` is Laya's advice on the finished reply: null when it was not asked, was only watching, or had no answer. */
export interface TaskDetail { task: Task; steps: Step[]; approvals: Approval[]; plan_steps: PlanStep[]; reply_check: 'follows' | 'drifts' | null }
export interface MemoryItem { id: number; text: string; label: 'PUBLIC' | 'PERSONAL' | 'SECRET'; source: string; at: number; tags: string[] }
export interface Space { id: string; name: string; description: string }
export interface Page { id: string; space_id: string; title: string; content?: string; revision: number; updated_at: number }
export const PET_ACCESSORIES = ['none', 'bow', 'glasses', 'hat', 'scarf', 'crown', 'headphones'] as const
export const PET_EYES = ['round', 'sparkle', 'sleepy'] as const
/** How a pet is dressed: `hue` (0 to 359) recolours it, null keeps the species colours. */
export interface PetLook { hue: number | null; accessory: (typeof PET_ACCESSORIES)[number]; eyes: (typeof PET_EYES)[number]; blush: boolean }
export const DEFAULT_LOOK: PetLook = { hue: null, accessory: 'none', eyes: 'round', blush: true }
export const MAX_SKILLS = 6000
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
  /** A model name, or '' for automatic. */
  model: string
}
export type Schedule = { kind: 'every'; every_minutes: number } | { kind: 'at'; at: string; days: number[] }
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
}
export interface Skill { name: string; summary: string; params: string[]; risk: string }

export interface ModelSpec {
  name: string
  provider: string
  model_id: string
  local: boolean
  enabled: boolean
  caps: string[]
  max_label: string
  rpm: number | null
  rpd: number | null
  tz: string
  key_ref: string | null
  private_access: 'ask' | 'never'
  trains: boolean
  base_url: string | null
  quick: boolean
}

export interface Settings {
  modules: string[]
  default_mode: 'LOCKED' | 'ASK' | 'OPEN'
  approval_mode: 'MANUAL' | 'AUTO' | 'OFF'
  file_roots: string[]
  retention_days: number
  network: { allowed_hosts: string[] }
  search: { engine: 'duckduckgo' | 'brave' | 'searxng'; searxng_url: string | null }
  stay_awake: boolean
  limits: Limits
  decisions: DecisionSettings
  bridges: BridgeSettings
  devbox: DevboxSettings
  browser: BrowserSettings
  capacity: CapacitySettings
  engine: EngineSettings
  grounding: GroundingSettings
  crew: CrewSettings
  models: ModelSpec[]
}

export interface CapacitySettings {
  max_wait_interactive_s: number
  max_wait_background_s: number
  inline_retry_max_s: number
  max_inflight_per_model: number
  learn_limits: boolean
  spread: string
  chars_per_token: number
}

export interface EngineSettings {
  mode: string
  observation_chars: number
  soft_context_tokens: number
  read_cache_ttl_s: number
  self_check: boolean
}

export interface GroundingSettings {
  enabled: boolean
  protected_globs: string[]
}

export interface CrewSettings {
  max_depth: number
  max_children: number
  child_budget_share: number
  min_confidence: number
}

export type BrowserMode = 'ask_every' | 'ask_risky' | 'allowlist'
export interface BrowserSettings { mode: BrowserMode; allow_hosts: string[]; max_actions: number; idle_quit_s: number; headless: boolean; chrome_path: string }

export interface Limits { max_running: number; lanes: number; step_timeout_s: number; task_minutes: number; local_unload_s: number; max_agent_steps: number; max_model_calls: number; max_task_tokens: number }

export interface ModelStatus {
  name: string
  enabled: boolean
  breaker: string
  minute_used: number | null
  rpm: number | null
  day_used: number | null
  rpd: number | null
  resets_in_s: number | null
  last_error: string | null
  calls: number
  tokens_in: number
  tokens_out: number
  suggested_rpm: number | null
  suggested_rpd: number | null
  provider: string
  model_id: string
  local: boolean
  has_key: boolean
  max_label: string
  private_access: string
  trains: boolean
}

export interface KeyInfo { ref: string; present: boolean }
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
  maintenance: { last_backup: number | null; last_backup_file: string | null; integrity_ok: boolean | null }
  stats: {
    cpu_percent: number
    memory: { total: number; available: number; percent: number }
    disk: { total: number; free: number; percent: number }
  }
}

export const MODES = [
  { value: 0, key: 'LOCKED', name: 'Locked', blurb: 'Never reads your private files or memory.' },
  { value: 1, key: 'ASK', name: 'Ask', blurb: 'Asks you before touching anything private or changing anything.' },
  { value: 2, key: 'OPEN', name: 'Open', blurb: 'Works without asking inside your shared folders. Hard limits still apply.' },
] as const

export const APPROVAL_MODES = [
  { value: 'MANUAL', name: 'Manual', blurb: 'Ask before approval-required actions.' },
  { value: 'AUTO', name: 'Auto', blurb: 'Run safe changes directly; hard policy and risky actions still stop.' },
  { value: 'OFF', name: 'Off', blurb: 'Never prompt; approval-required actions are denied.' },
] as const

export interface Resources {
  machine: {
    cpu_percent: number
    memory: { total: number; available: number; percent: number }
    disk: { total: number; free: number; percent: number }
    top_processes: { pid: number; name: string; memory_percent: number }[]
  }
  lilly: { pid: number; cpu_percent: number; memory_bytes: number; threads: number; database_bytes: number; backups_bytes: number; logs_bytes: number }
  tasks: { running: number; queued: number; waiting_approval: number; live: { id: string; goal: string; state: TaskState; created_at: number }[] }
  limits: Limits
  models: ModelStatus[]
  stay_awake_active: boolean
}

export type McpRisk = 'R0' | 'R1' | 'R2'
export interface McpServer {
  name: string
  command: string
  args: string[]
  env: Record<string, string>
  secret_vars: { var: string; ref: string; present: boolean }[]
  enabled: boolean
  data_label: 'PUBLIC' | 'PERSONAL'
  idle_stop_s: number
  approved: boolean
  approved_tools: { name: string; description: string; risk: McpRisk }[]
  state: 'stopped' | 'starting' | 'running' | 'failed' | 'changed'
  error: string
  last_used: number | null
}
export interface McpReview {
  fingerprint: string
  tools: { name: string; description: string }[]
}
export interface OllamaCheck {
  reachable: boolean
  version: string | null
  models: string[]
  model_ready: boolean | null
  message: string
}

export type DecisionKind = 'tools' | 'loop' | 'instructions' | 'pick' | 'plan' | 'reply' | 'route'
export interface KindSettings { enabled: boolean; shadow: boolean; chain: string[]; min_confidence: Record<string, number>; timeout_s: Record<string, number>; min_samples: number; min_precision: number }
export interface DecisionSettings {
  enabled: boolean
  max_per_task: number
  max_model_tokens_per_task: number
  min_free_mb: number
  tools: KindSettings
  loop: KindSettings
  instructions: KindSettings
  pick: KindSettings
  plan: KindSettings
  reply: KindSettings
  route: KindSettings
}
export interface DeciderSummary { kind: string; decider: string | null; decisions: number; answered: number; shadow: number; accepted: number; corrected: number }
export interface DecisionRow { id: number; ts: number; task_id: string | null; kind: string; decider: string | null; choice: string | null; confidence: number | null; shadow: boolean; options: number; summary: string; reason: string; outcome: 'accepted' | 'corrected' | 'unknown' }
export interface LayaStatus {
  installed: boolean
  installing: boolean
  progress: string[]
  error: string | null
  download_mb: number
  worker: 'off' | 'loading' | 'ready'
  note: string | null
  enabled_for: DecisionKind[]
}

/** One finding of the pre-check, in plain words. */
export interface LayaCheck { name: string; ok: boolean; detail: string }
export interface LayaCheckReply { checks: LayaCheck[]; ok: boolean }
export interface LayaTestCase { name: string; expected: string; got: string | null; confidence: number | null; ms: number; ok: boolean }
/** The self-test: `error` says what went wrong and what to do; null when everything passed. */
export interface LayaTestReport { ok: boolean; loaded: boolean; load_ms: number; results: LayaTestCase[]; error: string | null }

export interface BridgeSettings { enabled: boolean; agent_id: string | null; private_replies: boolean; per_minute: number; max_chars: number }
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
export interface BridgeIdentity { user_id: number; label: string; paired_at: number }
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

export interface Preset {
  name: string
  summary: string
}
