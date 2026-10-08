import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { api, evidenceFrameUrl, type Incident, type SafetyEvent } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { cn, fmtPct, fmtTime, ruleLabel, shortId } from "@/lib/utils";
import { Button, Card, Chip, Empty, Notice, Select } from "@/components/ui";
import { SeverityChip } from "@/components/status-chip";
import { SourceKindBadge, evidenceNote } from "@/components/source-kind-badge";

type Tab = "events" | "incidents";

export function EventsPage() {
  const [tab, setTab] = useState<Tab>("events");
  const events = usePoll(() => api.events.list(), 3000);
  const incidents = usePoll(() => api.events.incidents(), 5000, [tab]);
  const cameras = usePoll(() => api.cameras.list(), 10000);

  const cameraName = useMemo(() => {
    const m = new Map<string, string>();
    (cameras.data ?? []).forEach((c) => m.set(c.camera_id, c.name));
    return (id: string) => m.get(id) ?? id;
  }, [cameras.data]);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-1 border-b border-border">
        {(["events", "incidents"] as Tab[]).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={cn(
              "px-3 py-2 text-sm border-b-2 -mb-px capitalize",
              tab === t ? "border-primary text-primary font-medium" : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {t}
            <span className="ml-1.5 text-xs text-muted-foreground">
              {t === "events" ? events.data?.length ?? "" : incidents.data?.length ?? ""}
            </span>
          </button>
        ))}
      </div>
      {tab === "events" ? (
        <EventsTab events={events.data ?? []} error={events.error} loading={events.loading} cameraName={cameraName} />
      ) : (
        <IncidentsTab incidents={incidents.data ?? []} error={incidents.error} loading={incidents.loading} cameraName={cameraName} />
      )}
    </div>
  );
}

function EventsTab({
  events,
  error,
  loading,
  cameraName,
}: {
  events: SafetyEvent[];
  error: string | null;
  loading: boolean;
  cameraName: (id: string) => string;
}) {
  const [camera, setCamera] = useState("");
  const [rule, setRule] = useState("");
  const [severity, setSeverity] = useState("");
  const [reviewOnly, setReviewOnly] = useState(false);
  const [open, setOpen] = useState<Set<string>>(new Set());

  const cameraIds = useMemo(() => [...new Set(events.map((e) => e.camera_id))].sort(), [events]);
  const ruleIds = useMemo(() => [...new Set(events.map((e) => e.rule_id))].sort(), [events]);

  const filtered = useMemo(
    () =>
      [...events]
        .reverse()
        .filter((e) => !camera || e.camera_id === camera)
        .filter((e) => !rule || e.rule_id === rule)
        .filter((e) => !severity || e.severity === severity)
        .filter((e) => !reviewOnly || e.human_review_required),
    [events, camera, rule, severity, reviewOnly]
  );

  const toggle = (id: string) =>
    setOpen((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  return (
    <Card
      title="Safety events"
      actions={
        <div className="flex items-center gap-2 flex-wrap">
          <Select value={camera} onChange={(e) => setCamera(e.target.value)} className="w-auto">
            <option value="">all cameras</option>
            {cameraIds.map((id) => (
              <option key={id} value={id}>
                {cameraName(id)}
              </option>
            ))}
          </Select>
          <Select value={rule} onChange={(e) => setRule(e.target.value)} className="w-auto">
            <option value="">all rules</option>
            {ruleIds.map((r) => (
              <option key={r} value={r}>
                {ruleLabel(r)}
              </option>
            ))}
          </Select>
          <Select value={severity} onChange={(e) => setSeverity(e.target.value)} className="w-auto">
            <option value="">all severities</option>
            {["critical", "high", "medium", "low"].map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </Select>
          <label className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            <input type="checkbox" checked={reviewOnly} onChange={(e) => setReviewOnly(e.target.checked)} /> review required
          </label>
        </div>
      }
      bodyClassName="p-0"
    >
      {error && <Notice kind="error" className="m-3">{error}</Notice>}
      {!loading && filtered.length === 0 ? (
        <div className="p-4">
          <Empty>No events{events.length ? " match these filters" : " yet"}.</Empty>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs uppercase tracking-wide text-muted-foreground border-b border-border">
              <tr>
                <th className="w-6" />
                <th className="text-left px-3 py-2">Time</th>
                <th className="text-left px-3 py-2">Severity</th>
                <th className="text-left px-3 py-2">Rule</th>
                <th className="text-left px-3 py-2">Camera</th>
                <th className="text-right px-3 py-2">Conf</th>
                <th className="text-left px-3 py-2">Review</th>
                <th className="text-left px-3 py-2 w-full">Summary</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {filtered.map((e) => {
                const isOpen = open.has(e.event_id);
                return (
                  <EventRows key={e.event_id} e={e} isOpen={isOpen} onToggle={() => toggle(e.event_id)} cameraName={cameraName} />
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function EventRows({
  e,
  isOpen,
  onToggle,
  cameraName,
}: {
  e: SafetyEvent;
  isOpen: boolean;
  onToggle: () => void;
  cameraName: (id: string) => string;
}) {
  return (
    <>
      <tr className="hover:bg-secondary/30 cursor-pointer" onClick={onToggle}>
        <td className="pl-2 text-muted-foreground">{isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}</td>
        <td className="px-3 py-2 whitespace-nowrap text-muted-foreground tabular-nums">{fmtTime(e.timestamp)}</td>
        <td className="px-3 py-2"><SeverityChip severity={e.severity} /></td>
        <td className="px-3 py-2 whitespace-nowrap font-medium">{ruleLabel(e.rule_id)}</td>
        <td className="px-3 py-2 whitespace-nowrap"><span className="flex items-center gap-2">{cameraName(e.camera_id)}<SourceKindBadge kind={e.source_kind} /></span></td>
        <td className="px-3 py-2 text-right tabular-nums">{fmtPct(e.confidence)}</td>
        <td className="px-3 py-2">{e.human_review_required ? <Chip tone="warn">required</Chip> : <span className="text-muted-foreground text-xs">—</span>}</td>
        <td className="px-3 py-2 text-muted-foreground">{e.summary}</td>
      </tr>
      {isOpen && (
        <tr className="bg-background/40">
          <td />
          <td colSpan={7} className="px-3 py-3">
            <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                <dt className="text-muted-foreground">event</dt>
                <dd className="mono break-all">{e.event_id}</dd>
                <dt className="text-muted-foreground">incident</dt>
                <dd className="mono break-all">{e.incident_id ?? "—"}</dd>
                <dt className="text-muted-foreground">camera id</dt>
                <dd className="mono break-all">{e.camera_id}</dd>
                <dt className="text-muted-foreground">captured</dt>
                <dd>{fmtTime(e.evidence.captured_at)}</dd>
                <dt className="text-muted-foreground">adapter</dt>
                <dd className="mono">{e.evidence.adapter_name}</dd>
                <dt className="text-muted-foreground">model</dt>
                <dd className="mono break-all">{e.evidence.model_version}</dd>
                <dt className="text-muted-foreground">rule version</dt>
                <dd className="mono">{e.evidence.rule_version}</dd>
                <dt className="text-muted-foreground">source</dt>
                <dd className="mono break-all">{e.evidence.source_uri}</dd>
                <dt className="text-muted-foreground">source kind</dt>
                <dd className="flex items-center gap-2"><SourceKindBadge kind={e.source_kind} />{!e.source_kind && <span className="text-muted-foreground">not recorded (older event)</span>}</dd>
                <dt className="text-muted-foreground">frame hash</dt>
                <dd className="mono break-all">{e.evidence.frame_hash}</dd>
                <dt className="text-muted-foreground">frame</dt>
                <dd className="space-y-1">
                  {(e.evidence.evidence_note || evidenceNote(e.source_kind)) && (
                    <div className="rounded border border-warn/40 bg-warn/10 px-2 py-1 text-xs text-warn">{e.evidence.evidence_note ?? evidenceNote(e.source_kind)}</div>
                  )}
                  {/* Stored at event time by the worker; events from before that have no frame (404 → hidden). */}
                  <a href={evidenceFrameUrl(e.evidence.frame_hash)} target="_blank" rel="noreferrer">
                    <img
                      src={evidenceFrameUrl(e.evidence.frame_hash)}
                      alt="evidence frame"
                      className="max-h-40 rounded border border-border bg-black"
                      onError={(ev) => { (ev.currentTarget.parentElement as HTMLElement).replaceChildren(document.createTextNode("no frame stored")); }}
                    />
                  </a>
                </dd>
              </dl>
              <div className="min-w-0 space-y-2">
                <div className="label">evidence detections</div>
                <pre className="mono bg-background border border-border rounded-md p-3 max-h-72 overflow-auto whitespace-pre-wrap">
                  {JSON.stringify(e.evidence.detections, null, 2)}
                </pre>
                <details className="text-xs text-muted-foreground">
                  <summary className="cursor-pointer">runtime context</summary>
                  <pre className="mono mt-1 bg-background border border-border rounded-md p-3 max-h-48 overflow-auto whitespace-pre-wrap">
                    {JSON.stringify(e.runtime_context, null, 2)}
                  </pre>
                </details>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function IncidentsTab({
  incidents,
  error,
  loading,
  cameraName,
}: {
  incidents: Incident[];
  error: string | null;
  loading: boolean;
  cameraName: (id: string) => string;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  const sorted = useMemo(() => [...incidents].sort((a, b) => b.updated_at.localeCompare(a.updated_at)), [incidents]);
  return (
    <Card title="Incidents" bodyClassName="p-0">
      {error && <Notice kind="error" className="m-3">{error}</Notice>}
      {!loading && sorted.length === 0 ? (
        <div className="p-4">
          <Empty>No incidents yet. Events of the same rule and camera are grouped into incidents.</Empty>
        </div>
      ) : (
        <ul className="divide-y divide-border">
          {sorted.map((inc) => {
            const isOpen = openId === inc.incident_id;
            return (
              <li key={inc.incident_id} className="px-3 py-2">
                <div className="flex items-center gap-2 flex-wrap">
                  <Button size="sm" variant="ghost" onClick={() => setOpenId(isOpen ? null : inc.incident_id)} aria-expanded={isOpen}>
                    {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                  </Button>
                  <SeverityChip severity={inc.highest_severity} />
                  <Chip tone={inc.status === "open" ? "warn" : "neutral"}>{inc.status}</Chip>
                  <span className="font-medium">{inc.rule_id ? ruleLabel(inc.rule_id) : "mixed rules"}</span>
                  <span className="text-muted-foreground">{cameraName(inc.camera_id)}</span>
                  <span className="text-xs text-muted-foreground">{inc.event_ids.length} events</span>
                  <span className="ml-auto text-xs text-muted-foreground tabular-nums">
                    {fmtTime(inc.opened_at)} → {fmtTime(inc.updated_at)}
                  </span>
                  <span className="mono text-muted-foreground" title={inc.incident_id}>{shortId(inc.incident_id, 12)}</span>
                </div>
                {isOpen && (
                  <div className="mt-2 ml-8 space-y-1">
                    {inc.timeline.length === 0 ? (
                      <p className="text-xs text-muted-foreground">
                        Timeline not included; event ids: <span className="mono">{inc.event_ids.join(", ")}</span>
                      </p>
                    ) : (
                      <ul className="space-y-1">
                        {[...inc.timeline].reverse().map((e) => (
                          <li key={e.event_id} className="flex items-center gap-2 text-sm">
                            <span className="text-xs text-muted-foreground tabular-nums w-40 shrink-0">{fmtTime(e.timestamp)}</span>
                            <SeverityChip severity={e.severity} />
                            <span className="truncate text-muted-foreground">{e.summary}</span>
                            <span className="ml-auto text-xs tabular-nums">{fmtPct(e.confidence)}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
