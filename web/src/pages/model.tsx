import { useEffect, useState } from "react";
import { Eye, EyeOff, Play, RefreshCw, ShieldAlert, ShieldCheck, Square } from "lucide-react";
import {
  api,
  apiErrorMessage,
  type CatalogHost,
  type CatalogModel,
  type GuardResponse,
  type InferenceSettings,
  type ModelServerStatus,
  type ModelSettings,
} from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { cn, fmtDuration, fmtNum } from "@/lib/utils";
import { Button, Card, Chip, Field, Input, KV, Notice, Select, Toggle } from "@/components/ui";
import { ServerStateChip } from "@/components/status-chip";

export function ModelPage() {
  const catalog = usePoll(() => api.models.catalog(), 15000);
  const server = usePoll(() => api.models.server(), 3000);
  const guard = usePoll(() => api.model.guard(), 10000);
  const settings = usePoll(() => api.model.get(), 0);
  const inference = usePoll(() => api.model.inference(), 0);

  const refreshAll = () => {
    void server.refresh();
    void guard.refresh();
    void settings.refresh();
    void catalog.refresh();
  };

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-[20rem_minmax(0,1fr)]">
        <HostCard host={catalog.data?.host ?? null} error={catalog.error} />
        <ServerPanel server={server.data} error={server.error} onChanged={refreshAll} />
      </div>

      <Card title="Catalog" actions={<span className="text-xs text-muted-foreground">app-managed vLLM containers</span>}>
        {catalog.error && <Notice kind="error">{catalog.error}</Notice>}
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {(catalog.data?.models ?? []).map((m) => (
            <CatalogCard key={m.key} model={m} host={catalog.data?.host ?? null} currentKey={server.data?.entry?.key ?? null} onStarted={refreshAll} />
          ))}
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-4">
          {settings.data ? (
            <ModelSettingsForm initial={settings.data} onSaved={refreshAll} />
          ) : (
            <Card title="Model settings">
              <p className="text-sm text-muted-foreground">{settings.error ?? "Loading…"}</p>
            </Card>
          )}
          <GuardPanel guard={guard.data} error={guard.error} onRerun={async () => guard.refresh()} />
        </div>
        {inference.data ? (
          <InferenceForm initial={inference.data} />
        ) : (
          <Card title="Inference settings">
            <p className="text-sm text-muted-foreground">{inference.error ?? "Loading…"}</p>
          </Card>
        )}
      </div>
    </div>
  );
}

function HostCard({ host, error }: { host: CatalogHost | null; error: string | null }) {
  return (
    <Card title="Host">
      {error && <Notice kind="error">{error}</Notice>}
      {host && (
        <div>
          <KV k="platform" v={host.is_jetson ? <Chip tone="ok">Jetson</Chip> : <Chip tone="neutral">not Jetson</Chip>} />
          <KV k="docker" v={host.has_docker ? <Chip tone="ok">available</Chip> : <Chip tone="danger">missing</Chip>} />
          <KV k="RAM" v={`${fmtNum(host.ram_available_gb)} / ${fmtNum(host.ram_total_gb)} GB free`} />
          <KV k="models dir" v={host.models_dir} mono />
          <KV k="image" v={host.image} mono />
        </div>
      )}
    </Card>
  );
}

function ServerPanel({ server, error, onChanged }: { server: ModelServerStatus | null; error: string | null; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [armed, setArmed] = useState(false);
  const stop = async () => {
    // Two-step: the container may be serving another app on this device.
    if (!armed) {
      setArmed(true);
      return;
    }
    setArmed(false);
    setBusy(true);
    setErr(null);
    try {
      await api.models.stop();
      onChanged();
    } catch (e) {
      setErr(apiErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          Model server {server && <ServerStateChip state={server.state} />}
        </span>
      }
      actions={
        <span className="flex items-center gap-2">
          {armed && <span className="text-xs text-destructive">Stops the shared model server for every app. Click again to confirm.</span>}
          <Button size="sm" variant="danger" busy={busy} disabled={!server || server.state === "stopped"} onClick={() => void stop()}>
            <Square className="h-3.5 w-3.5" /> {armed ? "Confirm stop" : "Stop"}
          </Button>
        </span>
      }
      bodyClassName="p-0"
    >
      {error && <Notice kind="error" className="m-3">{error}</Notice>}
      {err && <Notice kind="error" className="m-3">{err}</Notice>}
      {server && (
        <div className="grid gap-x-6 gap-y-1 px-4 py-3 sm:grid-cols-2 text-sm">
          <KV k="entry" v={server.entry?.label ?? "—"} />
          <KV k="container" v={server.container_name} mono />
          <KV k="pid" v={server.pid ?? "—"} mono />
          <KV k="uptime" v={fmtDuration(server.uptime_s)} />
          <KV k="endpoint" v={server.endpoint ?? "—"} mono />
          <KV
            k="reasoning parser"
            v={server.reasoning_parser ? <Chip tone="warn">{server.reasoning_parser} — no constrained mode</Chip> : server.entry ? <Chip tone="ok">none — json_schema OK</Chip> : "—"}
          />
          {server.exit_code !== null && <KV k="exit code" v={server.exit_code} mono />}
        </div>
      )}
      {server && server.state === "starting" && (
        <p className="px-4 pb-2 text-xs text-muted-foreground">
          "starting" means the container process is alive; readiness is confirmed by the Guard panel below (re-check until it reports ok).
        </p>
      )}
      <pre className="mono bg-background border-t border-border px-4 py-3 max-h-56 overflow-auto whitespace-pre-wrap text-muted-foreground">
        {server?.log_tail?.length ? server.log_tail.join("\n") : "no log output"}
      </pre>
    </Card>
  );
}

function CatalogCard({ model, host, currentKey, onStarted }: { model: CatalogModel; host: CatalogHost | null; currentKey: string | null; onStarted: () => void }) {
  const [jsonSchema, setJsonSchema] = useState(model.constrained_ok);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const blocked = !model.can_run;
  const avail = host?.ram_available_gb ?? null;
  const memTone = model.required_memory_gb != null && avail != null && model.required_memory_gb > avail ? "text-destructive" : "text-foreground";

  const start = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api.models.start({ key: model.key, apply: true, json_schema: jsonSchema });
      onStarted();
    } catch (e) {
      setErr(apiErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={cn("card p-3 space-y-2 flex flex-col", blocked && "opacity-70")}>
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="font-medium leading-tight">{model.label}</div>
          <div className="mono text-muted-foreground">{model.served_model_name}</div>
        </div>
        <div className="flex flex-col items-end gap-1">
          {model.recommended && <Chip tone="info">recommended</Chip>}
          {currentKey === model.key && <Chip tone="ok">running</Chip>}
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5">
        <Chip tone="neutral">{model.params_b}B</Chip>
        {model.constrained_ok ? (
          <Chip tone="ok" title="json_schema (constrained decoding) is enforced on this server">json_schema OK</Chip>
        ) : (
          <Chip tone="warn" title="vLLM 0.14 ignores response_format json_schema with --reasoning-parser">
            reasoning parser — no constrained mode
          </Chip>
        )}
        <Chip tone={model.weights_present ? "ok" : "neutral"}>{model.weights_present ? "weights present" : "weights missing"}</Chip>
      </div>
      <div className="text-xs text-muted-foreground space-y-0.5">
        <div>
          memory: <span className={memTone}>~{fmtNum(model.required_memory_gb, 0)} GB</span>
          {avail != null && <> of {fmtNum(avail, 0)} GB available</>} · ctx {model.max_model_len}
        </div>
        {model.description && <div>{model.description}</div>}
        {model.measured_note && <div className="italic">{model.measured_note}</div>}
      </div>
      {blocked && (
        <ul className="text-xs text-muted-foreground list-disc pl-4">
          {model.blocked_reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
      {err && <Notice kind="error" className="text-xs">{err}</Notice>}
      <div className="mt-auto flex items-center gap-2 pt-1">
        <Toggle
          checked={jsonSchema}
          disabled={!model.constrained_ok}
          onChange={setJsonSchema}
          label={<span className="text-xs">json_schema</span>}
          title={model.constrained_ok ? "Apply constrained decoding to the model settings" : "Not available with a reasoning parser"}
        />
        <Button size="sm" variant="primary" className="ml-auto" busy={busy} disabled={blocked} onClick={() => void start()}>
          <Play className="h-3.5 w-3.5" /> Start & use
        </Button>
      </div>
    </div>
  );
}

function ModelSettingsForm({ initial, onSaved }: { initial: ModelSettings; onSaved: () => void }) {
  const [v, setV] = useState<ModelSettings>({ ...initial, api_key: "" });
  const [showKey, setShowKey] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  useEffect(() => setV({ ...initial, api_key: "" }), [initial]);
  const set = <K extends keyof ModelSettings>(k: K, val: ModelSettings[K]) => setV((s) => ({ ...s, [k]: val }));

  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const saved = await api.model.put(v);
      setV({ ...saved, api_key: "" });
      setMsg({ kind: "ok", text: "Model settings saved. The guard re-runs on the next inference." });
      onSaved();
    } catch (e) {
      setMsg({ kind: "error", text: apiErrorMessage(e) });
    } finally {
      setBusy(false);
    }
  };

  const conflict = v.json_schema && v.reasoning_parser === true;

  return (
    <Card title="Model settings">
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Backend">
            <Select value={v.backend} onChange={(e) => set("backend", e.target.value as ModelSettings["backend"])}>
              <option value="mock">mock (synthetic detections)</option>
              <option value="cosmos-reason2">cosmos-reason2 (vLLM)</option>
              <option value="openai-compatible">openai-compatible</option>
            </Select>
          </Field>
          <Field label="Label">
            <Input value={v.label} onChange={(e) => set("label", e.target.value)} placeholder="shown in status" />
          </Field>
        </div>
        <Field label="Endpoint" hint="/v1 is appended if missing">
          <Input value={v.endpoint} onChange={(e) => set("endpoint", e.target.value)} className="mono" disabled={v.backend === "mock"} />
        </Field>
        <Field label="Model">
          <Input value={v.model} onChange={(e) => set("model", e.target.value)} className="mono" disabled={v.backend === "mock"} />
        </Field>
        <Field label="API key" hint={initial.has_api_key ? "A key is stored. Leave blank to keep it." : "Optional."}>
          <div className="relative">
            <Input type={showKey ? "text" : "password"} value={v.api_key} onChange={(e) => set("api_key", e.target.value)} placeholder={initial.has_api_key ? "(unchanged)" : ""} autoComplete="off" className="pr-9" />
            <button type="button" className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground" onClick={() => setShowKey((s) => !s)} aria-label="toggle key visibility">
              {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        </Field>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Max tokens">
            <Input type="number" min={32} max={8192} value={v.max_tokens} onChange={(e) => set("max_tokens", Number(e.target.value))} />
          </Field>
          <Field label="Timeout (s)">
            <Input type="number" min={5} max={900} step={1} value={v.timeout_s} onChange={(e) => set("timeout_s", Number(e.target.value))} />
          </Field>
          <Field label="Reasoning parser" hint="How the server was started.">
            <Select
              value={v.reasoning_parser === null ? "unknown" : v.reasoning_parser ? "yes" : "no"}
              onChange={(e) => set("reasoning_parser", e.target.value === "unknown" ? null : e.target.value === "yes")}
            >
              <option value="unknown">unknown (probe)</option>
              <option value="no">no — constrained OK</option>
              <option value="yes">yes (--reasoning-parser)</option>
            </Select>
          </Field>
        </div>
        <div className="flex flex-wrap gap-6">
          <Toggle checked={v.think} onChange={(b) => set("think", b)} label="think (reasoning mode)" />
          <Toggle checked={v.json_schema} onChange={(b) => set("json_schema", b)} label="json_schema (constrained decoding)" />
        </div>
        {conflict && (
          <Notice kind="warn">
            json_schema cannot be enabled against a server started with --reasoning-parser: vLLM 0.14 silently ignores the schema. The server will refuse this save.
          </Notice>
        )}
        {msg && <Notice kind={msg.kind}>{msg.text}</Notice>}
        <div className="flex gap-2">
          <Button type="submit" variant="primary" busy={busy}>
            Save
          </Button>
          <Button variant="ghost" onClick={() => setV({ ...initial, api_key: "" })}>
            Reset
          </Button>
        </div>
      </form>
    </Card>
  );
}

function GuardPanel({ guard, error, onRerun }: { guard: GuardResponse | null; error: string | null; onRerun: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<GuardResponse | null>(null);
  const g = result?.guard ?? guard?.guard ?? null;
  const constrainedAllowed = result?.constrained_allowed ?? guard?.constrained_allowed ?? null;
  const jsonSchema = guard?.json_schema ?? null;

  const rerun = async () => {
    setBusy(true);
    setErr(null);
    try {
      setResult(await api.model.rerunGuard());
      await onRerun();
    } catch (e) {
      setErr(apiErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const blockedConstrained = jsonSchema === true && constrainedAllowed === false;

  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          {g?.ok ? <ShieldCheck className="h-4 w-4 text-ok" /> : <ShieldAlert className="h-4 w-4 text-warn" />}
          Guard
        </span>
      }
      actions={
        <Button size="sm" busy={busy} onClick={() => void rerun()} title="Probe the server and constrained-mode enforcement (can take a few seconds)">
          <RefreshCw className="h-3.5 w-3.5" /> Re-check
        </Button>
      }
    >
      {error && <Notice kind="error">{error}</Notice>}
      {err && <Notice kind="error">{err}</Notice>}
      {!g ? (
        <p className="text-sm text-muted-foreground">Guard has not run yet. It runs before the first inference, or on Re-check.</p>
      ) : (
        <div className="space-y-2 text-sm">
          <div className="flex items-center gap-2 flex-wrap">
            <Chip tone={g.ok ? "ok" : "danger"}>{g.ok ? "ok" : `failed at ${g.stage}`}</Chip>
            <span className="break-words">{g.message}</span>
          </div>
          {g.served_models.length > 0 && <div className="text-xs text-muted-foreground">served: <span className="mono">{g.served_models.join(", ")}</span></div>}
          <div className="flex items-center gap-2 flex-wrap text-xs">
            <span className="text-muted-foreground">constrained mode:</span>
            {g.constrained_enforced === true && <Chip tone="ok">enforced</Chip>}
            {g.constrained_enforced === false && <Chip tone="danger">not enforced</Chip>}
            {g.constrained_enforced === null && <Chip tone="neutral">not probed</Chip>}
            {constrainedAllowed !== null && <span className="text-muted-foreground">· {constrainedAllowed ? "allowed" : "blocked"} by settings</span>}
          </div>
        </div>
      )}
      {blockedConstrained && (
        <Notice kind="warn" className="mt-3">
          json_schema is enabled but constrained mode is blocked: the server runs with a reasoning parser (or the probe found the schema ignored), so vLLM would return free text while claiming JSON. Inference reports <span className="mono">blocked_constrained_mode</span> until you either disable json_schema or start the no-reasoning catalog entry.
        </Notice>
      )}
    </Card>
  );
}

function InferenceForm({ initial }: { initial: InferenceSettings }) {
  const [v, setV] = useState<InferenceSettings>(initial);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  useEffect(() => setV(initial), [initial]);
  const num = <K extends keyof InferenceSettings>(k: K) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setV((s) => ({ ...s, [k]: Number(e.target.value) }));

  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      setV(await api.model.putInference(v));
      setMsg({ kind: "ok", text: "Inference settings applied to running cameras." });
    } catch (e) {
      setMsg({ kind: "error", text: apiErrorMessage(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Inference settings">
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Interval (ms)" hint="100–60000; how often a frame is sent to the model">
            <Input type="number" min={100} max={60000} value={v.interval_ms} onChange={num("interval_ms")} />
          </Field>
          <Field label="JPEG quality" hint="40–95">
            <Input type="number" min={40} max={95} value={v.jpeg_quality} onChange={num("jpeg_quality")} />
          </Field>
          <Field label="Inference width" hint="160–1920">
            <Input type="number" min={160} max={1920} value={v.width} onChange={num("width")} />
          </Field>
          <Field label="Inference height" hint="120–1080">
            <Input type="number" min={120} max={1080} value={v.height} onChange={num("height")} />
          </Field>
          <Field label="Display max width" hint="320–3840; MJPEG/snapshot size">
            <Input type="number" min={320} max={3840} value={v.display_max_width} onChange={num("display_max_width")} />
          </Field>
        </div>
        <div className="flex flex-wrap gap-6">
          <Toggle checked={v.post_batch} onChange={(b) => setV((s) => ({ ...s, post_batch: b }))} label="post events as one batch per frame" />
          <Toggle checked={v.post_feedback} onChange={(b) => setV((s) => ({ ...s, post_feedback: b }))} label="post PPE feedback" />
        </div>
        {msg && <Notice kind={msg.kind}>{msg.text}</Notice>}
        <div className="flex gap-2">
          <Button type="submit" variant="primary" busy={busy}>
            Save
          </Button>
          <Button variant="ghost" onClick={() => setV(initial)}>
            Reset
          </Button>
        </div>
      </form>
    </Card>
  );
}
