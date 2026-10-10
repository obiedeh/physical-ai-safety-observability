import { useEffect, useMemo, useState } from "react";
import { Eye, EyeOff, PlugZap } from "lucide-react";
import {
  api,
  apiErrorMessage,
  RULE_IDS,
  type Camera,
  type CameraIn,
  type CameraProfile,
  type CameraTestResult,
} from "@/lib/api";
import { ruleLabel } from "@/lib/utils";
import { Button, Field, Input, Notice, Select, Toggle } from "./ui";
import { ZoneCanvas } from "./zone-canvas";
import { TestResultView } from "./test-result";

export interface CameraFormValues extends CameraIn {
  port: number | null;
}

const EMPTY: CameraFormValues = {
  name: "",
  profile: "generic_rtsp",
  host: "",
  port: null,
  username: "",
  password: "",
  stream_path: "",
  stream_quality: "main",
  channel: 1,
  rtsp_transport: "tcp",
  enabled: true,
  location: "",
  zones: [],
  rules: [],
};

function fromCamera(c: Camera): CameraFormValues {
  return {
    name: c.name,
    profile: c.profile,
    host: c.host,
    port: c.port,
    username: c.username,
    password: "",
    stream_path: c.stream_path,
    stream_quality: c.stream_quality,
    channel: c.channel,
    rtsp_transport: c.rtsp_transport,
    enabled: c.enabled,
    location: c.location ?? "",
    zones: c.zones.map((z) => ({ ...z, polygon: z.polygon.map((p) => [...p]) })),
    rules: [...c.rules],
  };
}

/** Fill the path template the way the backend does (CameraProfile.stream_path). */
export function templatePath(profile: CameraProfile, quality: "main" | "sub", channel: number): string {
  const tpl = quality === "sub" ? profile.sub_path : profile.main_path;
  return tpl
    .split("{channel2}")
    .join(String(channel).padStart(2, "0"))
    .split("{channel}")
    .join(String(channel));
}

export function CameraForm({
  profiles,
  initial,
  onSaved,
  onCancel,
}: {
  profiles: CameraProfile[];
  initial: Camera | null;
  onSaved: (cam: Camera) => void;
  onCancel: () => void;
}) {
  const [values, setValues] = useState<CameraFormValues>(initial ? fromCamera(initial) : EMPTY);
  const [showPassword, setShowPassword] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [test, setTest] = useState<CameraTestResult | null>(null);

  useEffect(() => {
    setValues(initial ? fromCamera(initial) : EMPTY);
    setTest(null);
    setError(null);
  }, [initial]);

  const profile = useMemo(
    () => profiles.find((p) => p.model_type === values.profile) ?? null,
    [profiles, values.profile]
  );
  const needsHost = profile?.requires_host ?? true;
  const autoPath = profile ? templatePath(profile, values.stream_quality, values.channel) : "";
  const pathIsAuto = values.stream_path.trim() === "" || values.stream_path === autoPath;

  const set = <K extends keyof CameraFormValues>(k: K, v: CameraFormValues[K]) =>
    setValues((s) => ({ ...s, [k]: v }));

  const onProfileChange = (next: string) => {
    const p = profiles.find((x) => x.model_type === next);
    setValues((s) => {
      const prev = profiles.find((x) => x.model_type === s.profile);
      const prevAuto = prev ? templatePath(prev, s.stream_quality, s.channel) : "";
      const keepPath = s.stream_path !== "" && s.stream_path !== prevAuto;
      return {
        ...s,
        profile: next,
        port: p && p.requires_host ? p.default_port : null,
        stream_path: keepPath ? s.stream_path : p ? templatePath(p, s.stream_quality, s.channel) : "",
      };
    });
  };

  const onQualityOrChannel = (patch: Partial<Pick<CameraFormValues, "stream_quality" | "channel">>) => {
    setValues((s) => {
      const p = profiles.find((x) => x.model_type === s.profile);
      const wasAuto = !p || s.stream_path === "" || s.stream_path === templatePath(p, s.stream_quality, s.channel);
      const next = { ...s, ...patch };
      if (p && wasAuto) next.stream_path = templatePath(p, next.stream_quality, next.channel);
      return next;
    });
  };

  const payload = (): CameraIn => ({
    ...values,
    host: needsHost ? values.host.trim() : "",
    port: needsHost ? values.port : null,
    username: needsHost ? values.username : "",
    password: needsHost ? values.password : "",
    stream_path: needsHost ? values.stream_path.trim() : "",
    location: values.location?.trim() ? values.location.trim() : null,
    zones: values.zones.map((z) => ({ ...z, zone_id: z.zone_id.trim() || "zone" })),
  });

  const validate = (): string | null => {
    if (!values.name.trim()) return "Name is required.";
    if (needsHost && !values.host.trim()) return `Host is required for ${profile?.label ?? "this profile"}.`;
    const short = values.zones.filter((z) => z.polygon.length < 3);
    if (short.length) return `Zone${short.length > 1 ? "s" : ""} ${short.map((z) => z.zone_id).join(", ")} need at least 3 vertices.`;
    const ids = values.zones.map((z) => z.zone_id.trim());
    if (new Set(ids).size !== ids.length) return "Zone ids must be unique.";
    return null;
  };

  const save = async () => {
    const v = validate();
    if (v) {
      setError(v);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const body = payload();
      const saved = initial
        ? await api.cameras.update(initial.camera_id, body)
        : await api.cameras.create(body);
      onSaved(saved);
    } catch (err) {
      setError(apiErrorMessage(err, "Save failed"));
    } finally {
      setSaving(false);
    }
  };

  const runTest = async () => {
    setTesting(true);
    setTest(null);
    setError(null);
    try {
      // Unsaved form values are probed as-is. With the password left blank on an
      // existing camera the server uses the stored (encrypted) one for this
      // camera_id, so edited host/path values are still what gets probed.
      const res = await api.cameras.testUnsaved({ ...payload(), camera_id: initial?.camera_id });
      setTest(res);
    } catch (err) {
      setError(apiErrorMessage(err, "Test failed"));
    } finally {
      setTesting(false);
    }
  };

  const toggleRule = (rule: string) =>
    set("rules", values.rules.includes(rule) ? values.rules.filter((r) => r !== rule) : [...values.rules, rule]);

  return (
    <form
      className="space-y-5"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Name">
          <Input value={values.name} onChange={(e) => set("name", e.target.value)} placeholder="Line 3 east bay" required maxLength={80} />
        </Field>
        <Field label="Profile" hint={profile?.notes || undefined}>
          <Select value={values.profile} onChange={(e) => onProfileChange(e.target.value)}>
            {profiles.map((p) => (
              <option key={p.model_type} value={p.model_type}>
                {p.label}
              </option>
            ))}
          </Select>
        </Field>
      </div>

      {needsHost && (
        <div className="grid gap-4 sm:grid-cols-[1fr_8rem]">
          <Field label="Host">
            <Input value={values.host} onChange={(e) => set("host", e.target.value)} placeholder="192.0.2.20" />
          </Field>
          <Field label="Port">
            <Input
              type="number"
              min={1}
              max={65535}
              value={values.port ?? ""}
              onChange={(e) => set("port", e.target.value === "" ? null : Number(e.target.value))}
              placeholder={String(profile?.default_port ?? "")}
            />
          </Field>
        </div>
      )}

      {needsHost && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Username">
            <Input value={values.username} onChange={(e) => set("username", e.target.value)} autoComplete="off" />
          </Field>
          <Field
            label="Password"
            hint={initial?.has_password ? "A password is stored. Leave blank to keep it." : profile?.requires_auth ? "Required by this profile." : undefined}
          >
            <div className="relative">
              <Input
                type={showPassword ? "text" : "password"}
                value={values.password}
                onChange={(e) => set("password", e.target.value)}
                placeholder={initial?.has_password ? "(unchanged)" : ""}
                autoComplete="new-password"
                className="pr-9"
              />
              <button
                type="button"
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                onClick={() => setShowPassword((s) => !s)}
                aria-label={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </Field>
        </div>
      )}

      {needsHost && (
        <div className="grid gap-4 sm:grid-cols-[8rem_1fr_6rem_6rem]">
          <Field label="Quality">
            <Select value={values.stream_quality} onChange={(e) => onQualityOrChannel({ stream_quality: e.target.value as "main" | "sub" })}>
              <option value="main">main</option>
              <option value="sub">sub</option>
            </Select>
          </Field>
          <Field
            label={
              <span className="flex items-center gap-2">
                Stream path
                {!pathIsAuto && profile && (
                  <button type="button" className="text-primary normal-case tracking-normal hover:underline" onClick={() => set("stream_path", autoPath)}>
                    reset to {autoPath || "default"}
                  </button>
                )}
              </span>
            }
            hint={profile ? `Example: main ${profile.example_main_path || "—"} · sub ${profile.example_sub_path || "—"}` : undefined}
          >
            <Input value={values.stream_path} onChange={(e) => set("stream_path", e.target.value)} placeholder={autoPath} className="mono" />
          </Field>
          <Field label="Channel">
            <Input type="number" min={1} max={64} value={values.channel} onChange={(e) => onQualityOrChannel({ channel: Math.max(1, Number(e.target.value) || 1) })} />
          </Field>
          <Field label="Transport">
            <Select value={values.rtsp_transport} onChange={(e) => set("rtsp_transport", e.target.value as "tcp" | "udp")}>
              <option value="tcp">tcp</option>
              <option value="udp">udp</option>
            </Select>
          </Field>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-[1fr_auto] items-end">
        <Field label="Location" hint="Free text shown with events.">
          <Input value={values.location ?? ""} onChange={(e) => set("location", e.target.value)} placeholder="Assembly hall, bay 3" />
        </Field>
        <Toggle checked={values.enabled} onChange={(v) => set("enabled", v)} label="Enabled" />
      </div>

      <div>
        <span className="label">Rules</span>
        <p className="text-xs text-muted-foreground mb-2">None selected = all rules run.</p>
        <div className="flex flex-wrap gap-2">
          {RULE_IDS.map((r) => (
            <label key={r} className="inline-flex items-center gap-2 card px-2.5 py-1.5 cursor-pointer hover:bg-secondary/50">
              <input type="checkbox" checked={values.rules.includes(r)} onChange={() => toggleRule(r)} />
              <span className="text-sm">{ruleLabel(r)}</span>
              <span className="mono text-muted-foreground hidden md:inline">{r}</span>
            </label>
          ))}
        </div>
      </div>

      <div>
        <span className="label">Zones</span>
        <ZoneCanvas
          zones={values.zones}
          onChange={(z) => set("zones", z)}
          cameraId={initial?.camera_id ?? null}
          snapshotAvailable={!!initial?.runtime}
        />
      </div>

      {error && <Notice kind="error">{error}</Notice>}
      {test && <TestResultView result={test} />}

      <div className="flex items-center gap-2 flex-wrap pt-2 border-t border-border">
        <Button type="submit" variant="primary" busy={saving}>
          {initial ? "Save changes" : "Add camera"}
        </Button>
        <Button onClick={() => void runTest()} busy={testing} title="Probe the stream with the current form values">
          <PlugZap className="h-3.5 w-3.5" /> Test connection
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        {initial && <span className="ml-auto mono text-muted-foreground">{initial.camera_id}</span>}
      </div>
    </form>
  );
}
