export type JsonScalar = string | number | boolean | null
export type JsonValue = JsonScalar | JsonValue[] | { [key: string]: JsonValue }
export type ObjectType = 'str' | 'int' | 'float' | 'bool' | 'none' | 'null'
export type CanonicalObjectType = Exclude<ObjectType, 'null'>

export interface Page<T> {
  items: T[]
  total: number
  offset: number
  limit: number
  next_offset: number | null
}

export interface AuthInfo {
  mode: 'manus' | 'token'
  login_available: boolean
}

export interface SessionInfo {
  authenticated: boolean
  role?: 'reader' | 'operator' | string
  csrf_token?: string
  auth_mode?: 'manus' | 'token' | string
  open_id?: string | null
  openId?: string | null
  subject?: string | null
}

export interface StatusResponse {
  core: {
    status: string
    version: string | null
    entities: number | null
    facts: number | null
    conclusions: number | null
    complete: boolean
    stale_reason: string | null
  }
  api: { status: string; version: string | null; uptime_seconds: number | null }
  rust: { status: string; available: boolean | null; operations: number | null; last_error: string | null }
  queries_executed: number | null
  events_processed: number | null
  last_query_latency_ms: number | null
  memory: MemoryStats
  cpu_percent: number | null
  activity: ActivityItem[]
  alerts: AlertItem[]
}

export interface ActivityItem { timestamp_ns: number; type?: string; operation?: string; message?: string; status?: string; [key: string]: JsonValue | undefined }
export interface AlertItem { timestamp_ns?: number; severity?: string; message: string; code?: string | null }

export interface Entity { entity_id: string; properties: Record<string, JsonValue> }
export interface Fact {
  fact_id: number
  subject: string
  predicate: string
  object: JsonScalar
  object_type: string
  properties: Record<string, JsonValue>
  confidence: number | null
  provenances: Provenance[]
  evidence_records: EvidenceRecord[]
}
export interface Provenance { source: string; evidence_type?: string | null; timestamp_ns?: number | null; detail?: string | null; [key: string]: JsonValue | undefined }
export interface EvidenceRecord { evidence_id: string; provenance: Provenance | null; confidence: number | null; context?: Record<string, string> }
export type KnowledgeStatus = 'explicit' | 'derived' | 'unknown' | 'contradicted' | 'insufficient_evidence'
export interface ConflictResolution {
  fact_ids: number[]; selected_fact_ids: number[]; reason: string; resolved_by: string
  evidence_fingerprint: string; recorded_at_ns: number; invalidated_at_ns: number | null; active: boolean
}
export interface KnowledgeAssessment {
  claim: [string, string, JsonScalar]; status: KnowledgeStatus; explicit_fact_ids: number[]; derived_proofs: ProofItem[]
  conflicting_fact_ids: number[]; evidence_sufficient: boolean; complete: boolean | null
  resolution: ConflictResolution | null; note: string
}
export interface HistoryRecord { sequence: number; timestamp_ns: number; operation: string; [key: string]: JsonValue | undefined }

export interface GraphNode { id: string; label: string; properties: Record<string, JsonValue> }
export interface GraphEdge { id: string; source: string; target: string; predicate: string; fact_id: number }
export interface GraphResponse {
  nodes: GraphNode[]
  edges: GraphEdge[]
  truncated: boolean
  total: number
  offset: number
  next_offset: number | null
}

export interface RulePattern { subject: JsonScalar; predicate: string; object: JsonScalar }
export interface Rule { rule_id: string; revision: number; enabled: boolean; antecedents: RulePattern[]; consequent: RulePattern }
export interface QueryPayload {
  subject: JsonScalar
  predicate: string
  object: JsonScalar
  object_type?: ObjectType
  strategy?: 'forward' | 'backward' | 'hybrid' | 'adaptive'
  context_filter?: Record<string, string>
  offset: number
  limit: number
}
export type ExplanationKey = [JsonScalar, string, JsonScalar]
export type ProofSupport = number | ExplanationKey
export interface ProofItem {
  proof_id?: string | number
  rule_id?: string | null
  rule_revision?: number | null
  revision?: number | null
  supports?: ProofSupport[]
  support_ids?: number[]
  dependencies?: JsonValue[]
  depth?: number
  provenance?: Provenance[]
  alternatives?: JsonValue[]
}
export interface ExplanationBranch { proof: ProofItem; supports: ExplanationNode[] }
export interface ExplanationNode {
  key: ExplanationKey
  kind?: string | null
  object_type?: ObjectType | null
  explicit_fact_id?: number | null
  provenance?: Provenance | null
  provenances?: Provenance[]
  cycle_truncated?: boolean
  proofs: ExplanationBranch[]
}
export interface QuerySolution {
  key: ExplanationKey
  object_type?: ObjectType
  bindings: Record<string, JsonValue>
  explicit: boolean
  fact_id: number | null
  proofs: ProofItem[]
  explanation: ExplanationNode[]
}
export interface QueryResult {
  solutions: QuerySolution[]
  proven: boolean
  complete: boolean
  stop_reason: string | null
  next_offset: number | null
  operations: number
  facts_examined: number | null
  conclusions_produced: number | null
  strategy: string
  decision_ns: number
  execution_ns: number
  rationale: string | null
  context_filter?: Record<string, string>
  context_fact_count?: number
}
export interface InferenceResult { complete: boolean; stop_reason: string | null; conclusions: JsonValue[]; operations: number; facts_examined?: number | null; [key: string]: unknown }
export interface ProofResponse { key: ExplanationKey; proofs: ProofItem[]; explanation: ExplanationNode[]; complete: boolean; stop_reason: string | null; context_filter?: Record<string, string>; context_fact_count?: number }

export interface MemoryStats {
  [key: string]: unknown
  resident_entries?: number | null; cold_entries?: number | null; resident_bytes?: number | null; budget_bytes?: number | null; resident_utilization?: number | null
  tiers?: Record<string, number> | null; hits?: number | null; misses?: number | null; evictions?: number | null; persist_writes?: number | null; persistence?: string | null
  query_cache?: Record<string, number> | null; patterns?: Record<string, JsonValue> | null; persistent?: boolean | null
}
export interface MemoryTier { count?: number | null; bytes?: number | null; hit_rate?: number | null; accesses?: number | null; [key: string]: unknown }

export interface EventRecord {
  sequence: number; event_id: string; event_type: string; timestamp_ns: number; source: string; payload: Record<string, JsonValue>
  provenance: Record<string, JsonValue> | null; status: string; attempts: number; created_ns: number; processed_ns: number | null; last_error: string | null
}
export interface EventsResponse { items: EventRecord[]; next_after: number | null; complete: boolean; queue: Record<string, JsonValue> }
export interface EventBatchResult { [key: string]: JsonValue | undefined; complete?: boolean; processed?: number; failed?: number; errors?: JsonValue[] }

export interface MetricSample { timestamp_ns: number; cpu_percent: number | null; rss_bytes: number | null; queries: number; events: number; last_query_latency_ms: number | null; throughput_queries_per_second: number | null; rust_operations: number | null }
export interface StrategyMetric { strategy: string; queries: number; p50_ms: number | null; p95_ms: number | null; decision_ns: number | null; maintenance_ns: number | null }
export interface MetricsResponse { samples: MetricSample[]; strategies: StrategyMetric[]; retention_limit: number }

export interface ConfigResponse {
  memory_max_bytes: number; max_depth: number; max_operations: number; max_conclusions: number; default_strategy: 'forward' | 'backward' | 'hybrid' | 'adaptive'
  join_planner: 'input' | 'selective'; persistence_enabled: boolean; rust_enabled: boolean; event_batch_size: number
}

export interface ApiErrorBody { detail: string | Record<string, JsonValue> }
