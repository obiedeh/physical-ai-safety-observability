// Same-origin API client. The backend (api/main.py) serves the built UI itself,
// so every call is a relative path; `pnpm dev` proxies these prefixes (see
// vite.config.ts).

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown
  ) {
    super(`API ${status}`);
  }
}

/** Best-effort human message out of a FastAPI error body. */
export function apiErrorMessage(err: unknown, fallback = "Request failed"): string {
  if (err instanceof ApiError) {
    const body = err.detail as { detail?: unknown } | undefined;
    const d = body && typeof body === "object" && "detail" in body ? body.detail : err.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      // pydantic validation error list
      return d
        .map((x) => {
          const loc = Array.isArray(x?.loc)
            ? x.loc.filter((p: unknown) => p !== "body").join(".")
            : "";
          return loc ? `${loc}: ${x?.msg ?? ""}` : String(x?.msg ?? "");
        })
        .join("; ");
    }
    if (d && typeof d === "object") {
      const m = (d as { message?: unknown }).message;
      if (typeof m === "string") return m;
      return JSON.stringify(d);
    }
    return `${fallback} (HTTP ${err.status})`;
  }
  return err instanceof Error ? err.message : fallback;
}

async function parseError(res: Response): Promise<never> {
  const detail = await res.json().catch(() => ({}));
  throw new ApiError(res.status, detail);
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) await parseError(res);
  return res.json() as Promise<T>;
}

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: {
      Accept: "application/json",
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) await parseError(res);
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const put = <T,>(path: string, body: unknown) => send<T>("PUT", path, body);
const post = <T,>(path: string, body?: unknown) => send<T>("POST", path, body);
const del = (path: string) => send<void>("DELETE", path);
const enc = encodeURIComponent;

// ── Cameras ───────────────────────────────────────────────────────────────────

export type CameraState =
  | "starting"
  | "connecting"
  | "streaming"
  | "reconnecting"
  | "error"
  | "stopped";

export interface CameraProfile {
  model_type: string;
  label: string;
  default_port: number;
  main_path: string;
  sub_path: string;
  protocol: string;
  requires_auth: boolean;
  requires_host: boolean;
  notes: string;
  example_main_path: string;
  example_sub_path: string;
}

export interface Zone {
  zone_id: string;
  type: string;
  /** normalized 0..1 vertices */
  polygon: number[][];
}

export interface WorkerStatus {
  frames_sampled: number;
  frames_skipped_same: number;
  inference_failures: number;
  consecutive_failures: number;
  last_error: string | null;
  last_result_age_s: number | null;
  events_emitted: number;
  active_zones: number;
  rules: string[] | "all";
}

export interface CameraRuntime {
  camera_id: string;
  kind: string;
  state: CameraState;
  fps: number;
  frames_decoded: number;
  frames_published: number;
  frames_dropped: number;
  decode_errors: number;
  reconnects: number;
  codec: string | null;
  source_width: number | null;
  source_height: number | null;
  source_fps: number | null;
  uptime_s: number | null;
  last_frame_age_s: number | null;
  last_error: string | null;
  frame: { width: number; height: number; seq: number } | null;
  worker: WorkerStatus | null;
}

export interface Camera {
  camera_id: string;
  name: string;
  profile: string;
  host: string;
  port: number | null;
  username: string;
  has_password: boolean;
  stream_path: string;
  effective_stream_path: string;
  stream_quality: "main" | "sub";
  channel: number;
  rtsp_transport: "tcp" | "udp";
  enabled: boolean;
  location: string | null;
  zones: Zone[];
  rules: string[];
  masked_url: string;
  created_at: string | null;
  updated_at: string | null;
  runtime: CameraRuntime | null;
}

export interface CameraIn {
  name: string;
  profile: string;
  host: string;
  port?: number | null;
  username: string;
  /** blank on update keeps the stored password */
  password: string;
  stream_path: string;
  stream_quality: "main" | "sub";
  channel: number;
  rtsp_transport: "tcp" | "udp";
  enabled: boolean;
  location?: string | null;
  zones: Zone[];
  rules: string[];
}

export type ProbeStage =
  | "reachability"
  | "auth"
  | "path"
  | "codec"
  | "timeout"
  | "decode"
  | "url"
  | "ok";

export interface CameraTestResult {
  ok: boolean;
  stage: ProbeStage;
  error: string | null;
  width?: number | null;
  height?: number | null;
  codec?: string | null;
  fps?: number | null;
  open_ms?: number | null;
  masked_url: string;
  thumbnail_data_url?: string | null;
  note?: string;
}

export const RULE_IDS = [
  "PPE_MISSING",
  "RESTRICTED_ZONE_ENTRY",
  "HUMAN_ROBOT_PROXIMITY",
  "BLOCKED_EMERGENCY_PATH",
  "UNSAFE_EVENT_SUMMARY",
] as const;

// ── Model / inference ─────────────────────────────────────────────────────────

export type ModelBackend = "cosmos-reason2" | "openai-compatible" | "mock";

export interface ModelSettings {
  backend: ModelBackend;
  endpoint: string;
  model: string;
  /** write-only; "" keeps the stored key */
  api_key: string;
  has_api_key: boolean;
  think: boolean;
  json_schema: boolean;
  max_tokens: number;
  timeout_s: number;
  reasoning_parser: boolean | null;
  label: string;
}

export interface GuardResult {
  ok: boolean;
  stage: "server" | "model" | "constrained" | "ok";
  message: string;
  served_models: string[];
  constrained_enforced: boolean | null;
}

export interface GuardResponse {
  guard: GuardResult | null;
  constrained_allowed: boolean;
  json_schema?: boolean;
}

export interface InferenceSettings {
  interval_ms: number;
  width: number;
  height: number;
  jpeg_quality: number;
  display_max_width: number;
  post_batch: boolean;
  post_feedback: boolean;
}

export interface CatalogHost {
  is_jetson: boolean;
  has_docker: boolean;
  ram_total_gb: number | null;
  ram_available_gb: number | null;
  image: string;
  models_dir: string;
}

export interface CatalogModel {
  key: string;
  label: string;
  served_model_name: string;
  model_dir: string;
  params_b: number;
  gpu_memory_utilization: number;
  max_model_len: number;
  reasoning_parser: string | null;
  description: string;
  measured_note: string;
  required_memory_gb: number | null;
  weights_present: boolean;
  can_run: boolean;
  blocked_reasons: string[];
  constrained_ok: boolean;
  recommended: boolean;
}

export interface ModelServerStatus {
  state: "stopped" | "starting" | "failed";
  pid: number | null;
  uptime_s: number | null;
  exit_code: number | null;
  container_name: string;
  entry: Omit<
    CatalogModel,
    | "required_memory_gb"
    | "weights_present"
    | "can_run"
    | "blocked_reasons"
    | "constrained_ok"
    | "recommended"
  > | null;
  endpoint: string | null;
  reasoning_parser: string | null;
  log_tail: string[];
}

export interface StartServerIn {
  key: string;
  port?: number;
  model_path?: string;
  apply: boolean;
  json_schema?: boolean | null;
}

// ── Live results ──────────────────────────────────────────────────────────────

export type InferenceStatus =
  | "ok"
  | "no_frame"
  | "inference_unavailable"
  | "blocked_constrained_mode";

export interface Detection {
  label: string | null;
  confidence: number | null;
  /** normalized [x, y, w, h] 0..1, or null when the model gave no box */
  bbox: [number, number, number, number] | null;
  ppe: { hard_hat?: boolean | null; vest?: boolean | null } | null;
  blocking_emergency_path?: boolean | null;
}

export interface ResultEvent {
  event_id: string;
  rule_id: string;
  severity: Severity | string;
  confidence: number;
  summary: string;
  human_review_required: boolean;
}

export interface InferenceResult {
  camera_id: string;
  status: InferenceStatus;
  frame_id?: string;
  capture_seq?: number;
  timestamp: string;
  frame_size?: [number, number];
  inference_ms?: number;
  rule_ms?: number;
  capture_to_result_ms?: number;
  detections: Detection[];
  feedback?: string;
  events: ResultEvent[];
  model?: string;
  reasoning_text?: string | null;
  camera_state?: CameraState;
  model_error?: string | null;
  guard?: GuardResult | null;
  seq: number;
  published_at: number;
}

// ── Runtime ───────────────────────────────────────────────────────────────────

export interface LatencySummary {
  n: number;
  p50?: number;
  p95?: number;
  p99?: number;
  mean?: number;
  min?: number;
  max?: number;
  [k: string]: number | undefined;
}

export interface TransportStats {
  backend: string | null;
  queue_depth: number;
  posted: number;
  failed: number;
  dropped: number;
  last_error: string | null;
  post_latency_ms: LatencySummary;
  packet_to_event_ms: LatencySummary;
}

export interface RunStatus {
  recording: boolean;
  name?: string;
  camera_id?: string;
  elapsed_s?: number;
  frames?: number;
  events?: number;
}

export interface RuntimeCamera extends Omit<CameraRuntime, "worker"> {
  name: string;
  profile: string | null;
  worker: WorkerStatus | null;
}

export interface RuntimeModel extends Omit<ModelSettings, "api_key"> {
  adapter: string;
  guard: GuardResult | null;
  constrained_allowed: boolean;
}

export interface RuntimeStatus {
  started_at: number | null;
  backend: string | null;
  post_enabled: boolean;
  model: RuntimeModel;
  model_server: ModelServerStatus;
  inference: InferenceSettings;
  transport: TransportStats;
  run: RunStatus;
  cameras: RuntimeCamera[];
}

export interface RunSummary {
  path: string;
  name: string;
  host: string;
  status: string | null;
  started_at: string | null;
  frames: number | null;
  /** processed (inferred) frames per second, not camera fps */
  fps: number | null;
  model: string | null;
  events: number | null;
  inference_p50_ms: number | null;
}

// ── Events ────────────────────────────────────────────────────────────────────

export type Severity = "low" | "medium" | "high" | "critical";

export interface Evidence {
  frame_hash: string;
  source_uri: string;
  adapter_name: string;
  model_version: string;
  rule_version: string;
  captured_at: string;
  telemetry_snapshot: Record<string, unknown>;
  detections: Record<string, unknown>[];
}

export interface SafetyEvent {
  event_id: string;
  camera_id: string;
  timestamp: string;
  rule_id: string;
  severity: Severity;
  confidence: number;
  human_review_required: boolean;
  runtime_context: Record<string, unknown>;
  evidence: Evidence;
  summary: string;
  incident_id: string | null;
}

export interface Incident {
  incident_id: string;
  camera_id: string;
  rule_id: string | null;
  grouping_severity: Severity | null;
  opened_at: string;
  updated_at: string;
  highest_severity: Severity;
  status: string;
  event_ids: string[];
  timeline: SafetyEvent[];
}

// ── API surface ───────────────────────────────────────────────────────────────

export const evidenceFrameUrl = (frameHash: string) =>
  `/evidence/frames/${encodeURIComponent(frameHash)}.jpg`;

export const api = {
  cameras: {
    profiles: () => get<CameraProfile[]>("/config/profiles"),
    list: () => get<Camera[]>("/config/cameras"),
    get: (id: string) => get<Camera>(`/config/cameras/${enc(id)}`),
    create: (body: CameraIn) => post<Camera>("/config/cameras", body),
    update: (id: string, body: CameraIn) => put<Camera>(`/config/cameras/${enc(id)}`, body),
    remove: (id: string) => del(`/config/cameras/${enc(id)}`),
    setEnabled: (id: string, enabled: boolean) =>
      post<Camera>(`/config/cameras/${enc(id)}/enabled`, { enabled }),
    testUnsaved: (body: CameraIn & { camera_id?: string }) =>
      post<CameraTestResult>("/config/cameras/test", body),
    testSaved: (id: string) => post<CameraTestResult>(`/config/cameras/${enc(id)}/test`),
  },

  model: {
    get: () => get<ModelSettings>("/config/model"),
    put: (body: ModelSettings) => put<ModelSettings>("/config/model", body),
    guard: () => get<GuardResponse>("/config/model/guard"),
    rerunGuard: () => post<GuardResponse>("/config/model/guard"),
    inference: () => get<InferenceSettings>("/config/inference"),
    putInference: (body: InferenceSettings) => put<InferenceSettings>("/config/inference", body),
  },

  models: {
    catalog: () => get<{ host: CatalogHost; models: CatalogModel[] }>("/models/catalog"),
    server: () => get<ModelServerStatus>("/models/server"),
    start: (body: StartServerIn) =>
      post<{ server: ModelServerStatus; applied: ModelSettings | null }>(
        "/models/server/start",
        body
      ),
    stop: () => post<ModelServerStatus>("/models/server/stop"),
  },

  stream: {
    mjpegUrl: (cameraId: string, maxFps?: number) =>
      `/stream/${enc(cameraId)}/live.mjpeg${maxFps ? `?max_fps=${maxFps}` : ""}`,
    snapshotUrl: (cameraId: string) => `/stream/${enc(cameraId)}/snapshot.jpg?t=${Date.now()}`,
    status: (cameraId: string) => get<CameraRuntime>(`/stream/${enc(cameraId)}/status`),
    pushUrl: (cameraId: string) => `/stream/${enc(cameraId)}/push`,
  },

  live: {
    resultsUrl: (cameraId?: string) =>
      `/live/results${cameraId ? `?camera_id=${enc(cameraId)}` : ""}`,
    latest: () => get<Record<string, InferenceResult>>("/live/latest"),
  },

  runtime: {
    status: () => get<RuntimeStatus>("/runtime/status"),
  },

  runs: {
    list: () => get<RunSummary[]>("/runs"),
    status: () => get<RunStatus>("/runs/status"),
    start: (body: { camera_id: string; name: string; notes?: string }) =>
      post<RunStatus>("/runs/start", body),
    stop: () => post<{ recording: false; written: string; frames: number }>("/runs/stop"),
  },

  events: {
    list: () => get<SafetyEvent[]>("/events"),
    incidents: () => get<Incident[]>("/incidents"),
    incident: (id: string) => get<Incident>(`/incidents/${enc(id)}`),
  },
};
