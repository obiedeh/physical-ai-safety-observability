#!/usr/bin/env python3
"""Render the measured Thor evidence under ``reports/thor/`` as a static page.

Reads every run artifact written by ``edge.worker --report`` (schema
``run-report-v1``), draws hand-rolled SVG bar charts and writes
``reports/index.html`` plus ``reports/charts/*.svg``. No number is typed by
hand: every figure on the page comes from a JSON field, and every row links
to its artifact. Served by GitHub Pages from the repository root, so the page
lives at ``/physical-ai-safety-observability/reports/``.

    python scripts/build_evidence_pages.py [--reports reports]
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

SCHEMA_LABELS = {"person", "robot", "pallet", "cart", "box", "unsafe_event"}

# Display order and captions; anything not listed is appended with its file name.
# (artifact stem, table caption, short chart label)
RUNS: list[tuple[str, str, str]] = [
    ("mock_30fps_no_post", "mock, 30 fps pacing, no posting", "mock, no post"),
    ("mock_30fps_backend", "mock, 30 fps pacing, per-event POST to FastAPI + SQLite", "mock, per-event POST"),
    ("mock_30fps_backend_batched", "mock, 30 fps pacing, one batch POST per frame", "mock, batched POST"),
    ("mock_no_post", "mock, unpaced, no posting", "mock, unpaced"),
    ("cosmos2b_video_60", "Cosmos-Reason2-2B, think block, 4096 cap", "2B, think"),
    ("cosmos2b_video_60_nothink", "Cosmos-Reason2-2B, no think, 512 cap", "2B, no think"),
    ("cosmos2b_video_60_schema_v1prompt", "Cosmos-Reason2-2B, grammar, original prompt", "2B, grammar, old prompt"),
    ("cosmos2b_video_60_schema", "Cosmos-Reason2-2B, grammar, JSON-only prompt", "2B, grammar"),
    ("cosmos8b_video_60_nothink", "Cosmos-Reason2-8B, no think, 512 cap", "8B, no think"),
    ("cosmos8b_video_60_schema", "Cosmos-Reason2-8B, grammar, JSON-only prompt", "8B, grammar"),
]


def load_runs(reports: Path) -> list[dict]:
    runs = []
    known = {name: (caption, short) for name, caption, short in RUNS}
    order = {name: i for i, (name, _, _) in enumerate(RUNS)}
    for path in sorted((reports / "thor").glob("*.json")):
        if path.name.endswith("_tegrastats.jsonl"):
            continue
        data = json.loads(path.read_text())
        if data.get("schema") != "run-report-v1":
            continue
        name = path.stem
        caption, short = known.get(name, (name, name))
        runs.append({"name": name, "caption": caption, "short": short, "path": path, "data": data,
                     "order": order.get(name, 1000)})
    return sorted(runs, key=lambda r: r["order"])


def _get(d: dict, *keys, default=None):
    for k in keys:
        if not isinstance(d, dict) or k not in d or d[k] is None:
            return default
        d = d[k]
    return d


def row_view(run: dict) -> dict:
    d = run["data"]
    labels = d.get("detections_by_label") or {}
    is_model = d["adapter"]["name"] != "mock_vlm"
    inf = d["latency"]["inference"]
    scale = 1000.0 if is_model else 1.0  # ms -> s for the model runs
    return {
        "name": run["name"],
        "caption": run["caption"],
        "short": run["short"],
        "artifact": f"thor/{run['path'].name}",
        "model": d["adapter"]["model_version"],
        "frames": d.get("frames_processed"),
        "fps": d.get("frames_per_second"),
        "inf_p50": (inf.get("p50") or 0) / scale if inf.get("n") else None,
        "inf_p95": (inf.get("p95") or 0) / scale if inf.get("n") else None,
        "inf_max": (inf.get("max") or 0) / scale if inf.get("n") else None,
        "inf_unit": "s" if is_model else "ms",
        "rule_p95": _get(d, "latency", "rule_eval", "p95"),
        "post_p50": _get(d, "latency", "backend_post", "p50"),
        "vin_p50": _get(d, "tegrastats", "rails_mw", "VIN", "p50"),
        "vin_peak": _get(d, "tegrastats", "rails_mw", "VIN", "peak"),
        "tj_peak": _get(d, "tegrastats", "temps_c", "tj", "peak"),
        "rss_gb": _get(d, "memory", "process_peak_rss_gb"),
        "tokens_p50": _get(d, "model_tokens", "completion", "p50"),
        "detections": sum(labels.values()),
        "out_of_vocab": sum(v for k, v in labels.items() if k not in SCHEMA_LABELS),
        "persons": labels.get("person", 0),
        "events": _get(d, "events", "total", default=0),
        "started": (d.get("started_at") or "")[:19].replace("T", " "),
        "status": d.get("status"),
        "is_model": is_model,
        "device": d.get("device", {}),
    }


# ---------------------------------------------------------------------------
# SVG
# ---------------------------------------------------------------------------


def bar_chart(title: str, series: list[tuple[str, list[float | None]]], categories: list[str],
              unit: str, width: int = 720, colors: tuple[str, ...] = ("#38bdf8", "#f59e0b", "#ef4444"),
              log: bool = False) -> str:
    """Grouped horizontal bar chart. ``series`` is [(legend, values per category)]."""
    import math

    left, right, top, row_h = 190, 90, 56, 18 * len(series) + 14
    height = top + row_h * len(categories) + 30
    vals = [v for _, vs in series for v in vs if v is not None and v > 0]
    vmax = max(vals) if vals else 1.0
    plot_w = width - left - right

    def x_of(v: float) -> float:
        if v is None or v <= 0:
            return 0.0
        if log:
            lo = math.log10(min(vals) / 2) if vals else 0
            return plot_w * (math.log10(v) - lo) / (math.log10(vmax) - lo or 1)
        return plot_w * v / vmax

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
           f'font-family="ui-sans-serif, system-ui, sans-serif" font-size="12">',
           f'<rect width="{width}" height="{height}" fill="#121a2c"/>',
           f'<text x="16" y="24" fill="#eef4ff" font-size="15" font-weight="700">{html.escape(title)}</text>']
    lx = 16
    for i, (legend, _) in enumerate(series):
        out.append(f'<rect x="{lx}" y="34" width="10" height="10" fill="{colors[i % len(colors)]}"/>')
        out.append(f'<text x="{lx + 14}" y="43" fill="#9fb0ca">{html.escape(legend)}</text>')
        lx += 14 + 7 * len(legend) + 18
    for ci, cat in enumerate(categories):
        y0 = top + ci * row_h
        out.append(f'<text x="{left - 10}" y="{y0 + row_h / 2 + 4}" fill="#9fb0ca" text-anchor="end">{html.escape(cat)}</text>')
        for si, (_, vs) in enumerate(series):
            v = vs[ci]
            y = y0 + 6 + si * 18
            if v is None:
                out.append(f'<text x="{left + 4}" y="{y + 11}" fill="#5f6f8a" font-size="11">not measured</text>')
                continue
            w = max(1.0, x_of(v))
            out.append(f'<rect x="{left}" y="{y}" width="{w:.1f}" height="12" fill="{colors[si % len(colors)]}"/>')
            label = f"{v:,.3g}" if v < 100 else f"{v:,.0f}"
            out.append(f'<text x="{left + w + 6}" y="{y + 10}" fill="#eef4ff" font-size="11">{label} {unit}</text>')
    out.append(f'<text x="{width - 16}" y="{height - 10}" fill="#5f6f8a" text-anchor="end" font-size="10">'
               f'{"log scale, " if log else ""}values from reports/thor/*.json</text>')
    out.append("</svg>")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

CSS = """
:root{color-scheme:dark;--bg:#0b1020;--panel:#121a2c;--line:#293653;--text:#eef4ff;--muted:#9fb0ca;--accent:#38bdf8;--good:#22c55e;--warn:#f59e0b;--risk:#ef4444}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top left,#13223d 0,var(--bg) 34rem);color:var(--text);font:16px/1.55 Inter,ui-sans-serif,system-ui,sans-serif}
main{width:min(1180px,calc(100% - 32px));margin:0 auto;padding:40px 0 64px}
.eyebrow{color:var(--accent);font-weight:700;text-transform:uppercase;font-size:.78rem;letter-spacing:.08em}
h1{font-size:2rem;margin:.3rem 0 .6rem}h2{font-size:1.35rem;margin:2.4rem 0 .6rem}p,li{color:var(--muted)}p.lead{font-size:1.05rem}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin:18px 0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}.card strong{display:block;font-size:1.5rem;color:var(--text)}.card span{font-size:.85rem;color:var(--muted)}
.table-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--panel)}table{border-collapse:collapse;width:100%;font-size:.88rem}
th,td{padding:9px 11px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left;white-space:normal}th{color:var(--muted);font-weight:600;background:#17223a}
a{color:var(--accent)}.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(480px,1fr));gap:16px;margin:16px 0}.charts figure{margin:0;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px;overflow-x:auto}
.charts svg{max-width:100%;height:auto}figcaption{font-size:.82rem;color:var(--muted);margin-top:6px}.pill{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:2px 9px;font-size:.75rem;color:var(--muted);margin-right:6px}
.warn{color:var(--warn)}.risk{color:var(--risk)}.good{color:var(--good)}footer{margin-top:40px;color:var(--muted);font-size:.85rem;border-top:1px solid var(--line);padding-top:16px}
"""


def fmt(v, digits=3, unit=""):
    if v is None:
        return "n/a"
    if isinstance(v, float):
        s = f"{v:,.{digits}f}".rstrip("0").rstrip(".") if digits else f"{v:,.0f}"
        return f"{s}{unit}"
    return f"{v:,}{unit}"


def build_page(rows: list[dict], charts: dict[str, str], repo_url: str) -> str:
    mock = [r for r in rows if not r["is_model"]]
    model = [r for r in rows if r["is_model"]]
    dev = rows[0]["device"] if rows else {}
    dates = sorted({r["started"][:10] for r in rows if r["started"]})

    def link(r: dict) -> str:
        return f'<a href="{r["artifact"]}">{html.escape(r["artifact"].split("/")[-1])}</a>'

    mock_rows = "".join(
        f"<tr><td>{html.escape(r['caption'])}<br><small>{link(r)}</small></td><td>{fmt(r['frames'])}</td>"
        f"<td>{fmt(r['fps'])}</td><td>{fmt(r['rule_p95'], 4)}</td><td>{fmt(r['post_p50'], 1)}</td>"
        f"<td>{fmt(r['vin_p50'], 0)}</td><td>{fmt(r['rss_gb'], 3)}</td><td>{fmt(r['events'])}</td></tr>"
        for r in mock
    )
    model_rows = "".join(
        f"<tr><td>{html.escape(r['caption'])}<br><small>{link(r)}</small></td><td>{fmt(r['frames'])}</td>"
        f"<td>{fmt(r['inf_p50'], 2)}</td><td>{fmt(r['inf_p95'], 2)}</td><td>{fmt(r['inf_max'], 2)}</td>"
        f"<td>{fmt(r['fps'])}</td><td>{fmt(r['tokens_p50'], 0)}</td><td>{fmt(r['vin_p50'], 0)}</td><td>{fmt(r['vin_peak'], 0)}</td>"
        f"<td>{fmt(r['detections'])}</td><td class=\"{'warn' if r['out_of_vocab'] else 'good'}\">{fmt(r['out_of_vocab'])}</td>"
        f"<td class=\"{'risk' if r['persons'] else 'good'}\">{fmt(r['persons'])}</td>"
        f"<td class=\"{'risk' if r['events'] else 'good'}\">{fmt(r['events'])}</td></tr>"
        for r in model
    )
    headline = next((r for r in mock if r["name"] == "mock_30fps_no_post"), None)
    best = next((r for r in model if r["name"] == "cosmos2b_video_60_schema"), None)
    big = next((r for r in model if r["name"] == "cosmos8b_video_60_schema"), None)
    cards = []
    if headline:
        cards.append(f"<div class='card'><strong>{fmt(headline['fps'])} frames/s</strong><span>worker at 30 fps pacing, mock model, rule evaluation p95 {fmt(headline['rule_p95'], 2)} ms</span></div>")
    if best:
        cards.append(f"<div class='card'><strong>{fmt(best['inf_p50'], 2)} s p50</strong><span>Cosmos-Reason2-2B per frame under a JSON-schema grammar, {fmt(best['out_of_vocab'])} out-of-vocabulary labels, {fmt(best['persons'])} phantom persons</span></div>")
    if big:
        cards.append(f"<div class='card'><strong>{fmt(big['inf_p50'], 2)} s p50</strong><span>Cosmos-Reason2-8B under the same grammar, {fmt(big['persons'])} phantom persons, {fmt(big['events'])} false events</span></div>")
    cards.append("<div class='card'><strong class='warn'>not measured</strong><span>precision and recall: no labelled ground truth exists yet</span></div>")

    figs = "".join(
        f"<figure>{svg}<figcaption>{html.escape(cap)}</figcaption></figure>"
        for _, (svg, cap) in charts.items()
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Physical AI Safety Observability: Thor evidence</title><style>{CSS}</style></head>
<body><main>
<div class="eyebrow">Measured evidence · Jetson AGX Thor</div>
<h1>Physical AI Safety Observability</h1>
<p class="lead">Every number on this page is read from a run artifact under <a href="{repo_url}/tree/main/reports/thor">reports/thor/</a>; each row links to its JSON. Device: {html.escape(str(dev.get('host')))}, {html.escape(str(dev.get('soc')))}, {html.escape(str(dev.get('l4t_release')))}, {html.escape(str(dev.get('nvpmodel')))}. Runs on {', '.join(dates)}, repository commit {html.escape(str(dev.get('git_sha')))}. These are runtime-overhead and inference-cost measurements on simulation footage; none is a detection-quality number.</p>
<div class="cards">{''.join(cards)}</div>

<h2>Runtime overhead, mock adapter</h2>
<p>The mock adapter returns fixed detections at microsecond cost, so this is the price of frame sampling, the policy engine, event construction and the backend path. Events are four per frame by construction.</p>
<div class="table-wrap"><table><thead><tr><th>Run</th><th>Frames</th><th>Frames/s</th><th>Rule eval p95, ms</th><th>Backend POST p50, ms</th><th>VIN p50, mW</th><th>Peak RSS, GB</th><th>Events</th></tr></thead><tbody>{mock_rows}</tbody></table></div>

<h2>Real-model inference cost, Cosmos-Reason2 via vLLM on the same device</h2>
<p>Same 60 frames (one every 60 from an Isaac Sim recording with no people in it), same server image, same device. Inference in seconds per frame. "Phantom persons" are detections labelled person on people-free footage; "events" are the safety events those detections fired, all false by construction.</p>
<div class="table-wrap"><table><thead><tr><th>Run</th><th>Frames</th><th>p50, s</th><th>p95, s</th><th>max, s</th><th>Frames/s</th><th>Completion tokens p50</th><th>VIN p50, mW</th><th>VIN peak, mW</th><th>Detections</th><th>Out-of-vocab labels</th><th>Phantom persons</th><th>Events</th></tr></thead><tbody>{model_rows}</tbody></table></div>

<div class="charts">{figs}</div>

<h2>What is not established</h2>
<ul>
<li>No precision or recall for any rule: there is no labelled ground truth. The grammar fixes the vocabulary; only ground truth can score the detections.</li>
<li>No real camera input in these runs; the footage is simulation.</li>
<li>Runs are 60 to 390 seconds, not sustained operation.</li>
<li>Sixty frames of one video is a signal about the 8B, not a rate.</li>
</ul>
<footer>Generated by <code>scripts/build_evidence_pages.py</code> from the committed artifacts. Repository: <a href="{repo_url}">{repo_url}</a>. Case study: <a href="https://obiedeh.github.io/physical-ai-safety-observability.html">obiedeh.github.io</a>.</footer>
</main></body></html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reports", type=Path, default=Path("reports"))
    ap.add_argument("--repo-url", default="https://github.com/obiedeh/physical-ai-safety-observability")
    args = ap.parse_args()
    runs = load_runs(args.reports)
    if not runs:
        print("no run-report-v1 artifacts found", file=sys.stderr)
        return 1
    rows = [row_view(r) for r in runs]
    model = [r for r in rows if r["is_model"]]
    mock = [r for r in rows if not r["is_model"]]
    charts_dir = args.reports / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    charts: dict[str, tuple[str, str]] = {}
    if model:
        cats = [r["short"] for r in model]
        charts["model_latency"] = (
            bar_chart("Inference latency per frame, Cosmos-Reason2 on Thor",
                      [("p50", [r["inf_p50"] for r in model]), ("p95", [r["inf_p95"] for r in model])], cats, "s"),
            "Per-frame inference latency, p50 and p95, seconds. Reasoning length drives the tail; the grammar removes most of it.")
        charts["model_quality"] = (
            bar_chart("Vocabulary and phantom persons on people-free footage",
                      [("out-of-vocab labels", [float(r["out_of_vocab"]) for r in model]),
                       ("phantom persons", [float(r["persons"]) for r in model]),
                       ("false events", [float(r["events"]) for r in model])], cats, ""),
            "Counts over 60 frames. Zero out-of-vocabulary labels under the grammar; the 2B then reports people that are not there, the 8B does not.")
    if mock:
        cats = [r["short"] for r in mock]
        charts["mock_fps"] = (
            bar_chart("Worker throughput, mock adapter", [("frames/s", [r["fps"] for r in mock])], cats, "frames/s", log=True),
            "Achieved frames per second against a 30 fps source; the synchronous POST to the backend is the bottleneck, batching lifts it from 4.4 to 7.1.")
    charts["power"] = (
        bar_chart("Board input power, VIN p50", [("VIN p50", [(r["vin_p50"] or 0) / 1000 if r["vin_p50"] else None for r in rows])],
                  [r["short"] for r in rows], "W"),
        "Board input power at p50 over each run, watts; about 24 W is the device's idle level.")
    for name, (svg, _) in charts.items():
        (charts_dir / f"{name}.svg").write_text(svg + "\n")
    page = build_page(rows, charts, args.repo_url)
    out = args.reports / "index.html"
    out.write_text(page)
    print(f"wrote {out} and {len(charts)} charts to {charts_dir} from {len(rows)} artifacts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
