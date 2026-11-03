# Hazard analysis: Physical AI Safety Observability rules

Written 2026-10-29 against the public edition of this repository. Every rule, threshold and number below names the file it comes from; line numbers refer to the Pro edition's source and may differ here. Results measured on 2026-10-17 and 2026-10-18 on labelled simulation scenes exist in the Pro edition and are not published; where this document says "measured privately, not yet published" that is what it means.

## 1. Scope and system boundary

**What the item is.** A monitoring layer for a manufacturing workcell: a camera feed, a vision-language model (VLM) that returns structured detections per sampled frame, a deterministic rule engine (`rules/engine.py`, `rules/policies.py`, `safety-policy-v1` at `rules/policies.py:8`) that turns detections into safety events, an evidence record on every event (`evidence/evidence_chain.py:10-30`), and an operator console (README, "Status at a Glance").

**What it is not.** It observes and alerts. It does not stop, slow or command any robot, interlock, light curtain or door. README states "Nothing here acts autonomously" and "The goal is operational review, not demo object detection" (README, opening paragraph). No output of this system is wired to an actuator; a missed or late event therefore cannot by itself cause motion, but it can remove a layer of review that an operator may have come to rely on. That reliance is the hazard this document is about.

**Operator.** A human reviewing the Events page of the console. Every event carries `human_review_required` (`events/schemas.py:66`), set true for every HIGH or CRITICAL event, for any event with confidence below 0.85, and whenever runtime status is not nominal (`rules/severity.py:4-7`). The system assumes a person is looking; nothing in the repository measures whether or how quickly they do.

**Boundary assumptions.** Zones are hand drawn on a snapshot in the UI; no camera calibration exists (README, "Not yet measured", item "Calibration error"). Footage that is not a live camera is labelled as such on every frame and event (Pro edition `edge/evidence_label.py`; the public edition records the source URI in the evidence chain). All measured real-model runs used simulation video from a file; no live-camera run is committed (README, "Not yet measured").

## 2. Vocabulary mapping

This is a monitoring layer for a manufacturing cell, not a road vehicle. ISO 26262 and ISO 21448 (SOTIF) are used here as vocabulary and method only. No conformance, no ASIL, no SOTIF acceptance is claimed.

| Standard term | Meaning here |
|---|---|
| Item (26262) | Camera, VLM adapter, rule engine, evidence chain, operator console, as one function: "tell an operator when a rule is violated" |
| Hazard (26262) | A person in the cell exposed to a robot, missing PPE, inside a restricted zone, or an emergency path blocked, with the condition not reviewed |
| Hazardous event (26262) | The hazard coinciding with an operational situation where the operator relies on this layer and it does not alert, alerts late, or alerts so often that alerts are ignored |
| Safety goal (26262) | Stated here as design intent only: every rule violation visible to the camera produces a reviewable event before the operator would otherwise have needed it. Not verified |
| ASIL | Not assigned. No hazard and risk assessment with severity, exposure and controllability classes has been done. Nothing in this document should be read as an ASIL claim |
| Functional safety concept | The existing guards: fail-closed model server guard, strict wire contracts, evidence chain, forced human review. Listed in section 3 as mitigations, not as a validated concept |
| Functional insufficiency (21448) | A limit of the VLM, prompt, parser, geometry or sampling that produces a wrong detection without any component fault |
| Triggering condition (21448) | A scene or server condition that activates an insufficiency: lighting, occlusion, PPE colour, calibration drift, a server that ignores the schema, reasoning latency |
| Known unsafe | Triggering conditions already observed in a committed run (section 4) |
| Unknown unsafe | Everything not exercised: real footage, real PPE, real lighting, real people. The repository states real-world detection quality is unmeasured (README, opening paragraph) |
| Acceptance criteria (21448) | Section 5. None has been met; most have not been defined with a number |
| Validation (21448) | Only simulation-based measurements exist, on correlated stylised scenes (README, "Labeled simulation measurement"), plus timing and guard measurements on device |

## 3. Hazard table

Rule definitions: `rules/policies.py`. Severity per rule: PPE_MISSING HIGH (`:37`), RESTRICTED_ZONE_ENTRY CRITICAL (`:61`), HUMAN_ROBOT_PROXIMITY HIGH (`:89`), BLOCKED_EMERGENCY_PATH MEDIUM (`:108`), UNSAFE_EVENT_SUMMARY LOW (`:123`). Confidence penalties under degraded runtime: 0.08 degraded, 0.18 critical, 0.01 per dropped frame capped at 0.10 (`rules/severity.py:10-17`).

Shared mitigations referenced as M1 to M6:

- M1 Fail-closed server guard: a canary request with a one-value enum schema must come back as that value before any constrained run; a reasoning-parser server is refused (`edge/model_guard.py:23-27, 65-118`). Measured 2026-10-02, `reports/thor/constrained_guard_probe.json` (public).
- M2 Constrained decoding: the server emits only tokens that satisfy the detection schema (`edge/adapters/openai_compatible.py:255-262`); the label enum is the only vocabulary the engine understands (`:60-73`).
- M3 Strict wire contracts (Pro edition only, added 2026-10-17): a person without explicit `hard_hat` and `vest` booleans raises `PPEContractError`; a native box outside 0 to 1000, reversed or zero-area raises `CoordinateContractError`. Raw output is retained, never repaired. The public edition's adapter has no such contract: an omitted PPE field reaches the rule (TC-10).
- M4 Evidence chain: frame hash, source URI, adapter, model version, rule version, telemetry snapshot and the detections behind each event (`evidence/evidence_chain.py:10-30`); the inference frame is kept and shown (README, "Status at a Glance").
- M5 Operator review forced for HIGH and CRITICAL, low confidence or degraded runtime (`rules/severity.py:4-7`).
- M6 Zone geometry: the public edition tests box centre, corner containment and edge crossing in floating point (`spatial/zones.py`); the Pro edition replaced this on 2026-10-17 with exact rational arithmetic, closed sets, containment in both directions and segment contact, after a scripted challenge set exposed 48 misses in the float version (measured privately, not yet published).

Abbreviations in the table: MD missed detection, FA false alert, LA late alert, WG wrong geometry, NA model non-answer. "Not measured" means no committed artifact quantifies it.

| ID | Rule | Direction | Hazard and hazardous event | Triggering conditions | Existing mitigation | Residual risk | Verification evidence | Status |
|---|---|---|---|---|---|---|---|---|
| H1 | PPE_MISSING | MD | Person without hard hat or vest is not flagged; operator assumes compliance | Person not detected at all (occlusion, pose, lighting, small apparent size); PPE colour or style outside what the model recognises; model answers with a person label but PPE booleans true | M2, M3 (Pro), M4, M5 | Person recall on simulation is well below 1 (measured privately, not yet published). Real PPE, colours and lighting: not measured | Private 2026-10-17 run; public code `rules/policies.py` | Open |
| H2 | PPE_MISSING | FA | Compliant person flagged; repeated false alarms train the operator to dismiss | Model omits or mis-reads a PPE boolean; rule treats any falsy value as missing (`rules/policies.py:29`), so an omitted field alerts | M3 (Pro) rejects omitted fields in constrained mode; in the public edition the rule alerts on an omitted field (fails toward an alert); M5 | Rate on real footage not measured. In the public constrained 2B run, 5 PPE_MISSING events fired on footage with no people (README, four-run table) | `reports/thor/cosmos2b_video_60_schema.json` (public) | Open |
| H3 | PPE_MISSING | LA | Violation visible but event arrives seconds later; person has moved on | Inference 2.69 s p50, 3.36 s p95 (2B constrained) to 4.35 s p50, 12.85 s p95 (2B with think block); 0.154 to 0.367 frames/s; 8B p95 up to 27.78 s | Inference worker samples the latest frame on its own cadence (README, "Live pipeline"); asynchronous poster | Frames between samples are never seen. Live-camera packet-to-event latency: not measured | `reports/thor/cosmos2b_video_60*.json`, `cosmos8b_video_60*.json` (public) | Open |
| H4 | PPE_MISSING | WG | Not applicable: rule uses no geometry | | | | | n/a |
| H5 | PPE_MISSING | NA | Model returns nothing parseable; no event, no alarm that anything is wrong | Prompt asks for an `<answer>` wrapper the grammar forbids: 60 of 60 frames empty, 7 completion tokens each (README, four-run table); JSON absent or invalid: parser returns empty detections (`openai_compatible.py:373-390, 407`) | Model outage shows "inference unavailable", no event invented (README, "Live pipeline"); M3 raises on contract breach in constrained mode | An empty but syntactically valid reply is indistinguishable from an empty scene. Not alarmed | `reports/thor/cosmos2b_video_60_schema_v1prompt.json` (public) | Open |
| H6 | RESTRICTED_ZONE_ENTRY | MD | Person inside a restricted polygon not flagged | Person not detected; box decoded in wrong units so it never overlaps the zone (see TC-5); polygon drawn on a stale snapshot after the camera moved | M6, M3 (Pro, coordinate contract), M4, M5 | Zone recall on simulation below 1 (measured privately, not yet published). Camera drift: not measured; no calibration exists | `spatial/zones.py:98-126`; README "Not yet measured" | Open |
| H7 | RESTRICTED_ZONE_ENTRY | FA | Person outside zone flagged; CRITICAL severity makes this the most disruptive false alarm | Person box too large (touching counts, `zones.py:103-105`); phantom person on empty scene | M6 has no padding or epsilon in either edition; M5 | In the public constrained 2B run 6 phantom person labels appeared on people-free footage (README, four-run table); zone false alarms on real footage: not measured | `cosmos2b_video_60_schema.json` (public) | Open |
| H8 | RESTRICTED_ZONE_ENTRY | LA | As H3; a person crossing a zone between samples is never seen | As H3 | As H3 | Not measured on live video | As H3 | Open |
| H9 | RESTRICTED_ZONE_ENTRY | WG | Polygon no longer matches the floor; events refer to the wrong place | Hand-drawn polygon in image space; no calibration; camera pan, zoom or re-mount; self-intersecting or degenerate polygon is outside the geometry contract (`zones.py:6`) | Zone model requires at least 3 points (`spatial/zones.py`); M6 | Drift error: not characterised (README, "Not yet measured"). Degenerate polygons are not rejected at drawing time: not verified | `spatial/zones.py` | Open |
| H10 | RESTRICTED_ZONE_ENTRY | NA | As H5 | As H5 | As H5 | As H5 | As H5 | Open |
| H11 | HUMAN_ROBOT_PROXIMITY | MD | Person near robot not flagged | Person or robot not detected; both centres further than 90 px apart in the image although close on the floor (perspective) | Rule fires at 90 px between box centres (`rules/policies.py:70-82`); M5 | 90 px is a fixed image distance with no calibration (README, "Not yet measured"). No positive proximity label existed in the simulation set, so recall is undefined (measured privately, not yet published) | `rules/policies.py:70` | Open |
| H12 | HUMAN_ROBOT_PROXIMITY | FA | Person far from robot flagged | Perspective: two boxes 90 px apart can be metres apart; phantom person next to a real robot | M5 | 2 false proximity events on people-free footage in the public 2B run (README, four-run table); a larger count on simulation (measured privately, not yet published) | `cosmos2b_video_60_schema.json` (public) | Open |
| H13 | HUMAN_ROBOT_PROXIMITY | LA | Approach faster than the sampling interval | As H3; the system does not estimate speed (README, "Not yet measured") | As H3 | Not measured | As H3 | Open |
| H14 | HUMAN_ROBOT_PROXIMITY | WG | Threshold meaningless after lens or mount change | Any change of resolution, zoom or distance; the 90 px default is not tied to a camera | None beyond M5 | Not measured | `rules/policies.py:70` | Open |
| H15 | HUMAN_ROBOT_PROXIMITY | NA | As H5 | As H5 | As H5 | As H5 | As H5 | Open |
| H16 | BLOCKED_EMERGENCY_PATH | MD | Blocked exit not flagged | Rule relies on the model setting `blocking_emergency_path` true on a pallet, cart or box (`rules/policies.py:101`); the model has no map of where the path is | M4, M5 | No labelled case exists; recall undefined (measured privately, not yet published). Not measured on real scenes | `rules/policies.py:97-113` | Open |
| H17 | BLOCKED_EMERGENCY_PATH | FA | Object flagged as blocking when it is not | Model guesses the flag from context | MEDIUM severity; M5 applies only when confidence is below 0.85 | Not measured | same | Open |
| H18 | BLOCKED_EMERGENCY_PATH | LA | Slow-changing hazard, latency less critical | As H3 | As H3 | Not measured | As H3 | Open |
| H19 | BLOCKED_EMERGENCY_PATH | WG | No path geometry exists; the "path" is whatever the model infers | No zone type for emergency paths in `spatial/zones.py` | None | The rule cannot be made geometric until a path zone exists | `rules/policies.py:97-113` | Open |
| H20 | BLOCKED_EMERGENCY_PATH | NA | As H5 | As H5 | As H5 | As H5 | As H5 | Open |
| H21 | UNSAFE_EVENT_SUMMARY | MD | Free-text hazard not reported | Model emits no `unsafe_event` label | LOW severity by design (`rules/policies.py:123`); M5 only on low confidence | This rule is a catch-all, not a safety function; recall undefined (measured privately, not yet published) | `rules/policies.py:116-129` | Accepted as informational |
| H22 | UNSAFE_EVENT_SUMMARY | FA | Noise in the event list | Model narrates ordinary activity | LOW severity | Not measured | same | Accepted as informational |
| H23 | UNSAFE_EVENT_SUMMARY | LA | As H3 | As H3 | As H3 | Not measured | As H3 | Accepted |
| H24 | UNSAFE_EVENT_SUMMARY | WG | Not applicable | | | | | n/a |
| H25 | UNSAFE_EVENT_SUMMARY | NA | As H5 | As H5 | As H5 | As H5 | As H5 | Open |

Cross-cutting: **alert fatigue** is the hazardous event common to every FA row. The public constrained 2B run produced 7 false safety events on 60 frames of footage containing no people (README, four-run table); whatever the real rate is, it has not been measured on real footage.

## 4. SOTIF triggering-condition catalogue

Derived from committed runs. "Public" means the artifact is in the public repository; "private" means measured but not published.

| TC | Triggering condition | Insufficiency it activates | Observed in | Guard today | Scope |
|---|---|---|---|---|---|
| TC-1 | Footage with no people | 2B model under grammar labels 6 detections "person"; 5 PPE_MISSING and 2 HUMAN_ROBOT_PROXIMITY events fire. 8B under the same grammar and prompt: 0 person labels, 0 events | `reports/thor/cosmos2b_video_60_schema.json`, `cosmos8b_video_60_schema.json`; README four-run and model-size tables | None in code; 60 frames of one simulation is a signal, not a rate (README) | Public |
| TC-2 | Model server started with a reasoning parser | Server accepts `response_format` json_schema and ignores it; canary prompt "reply with the single word banana" returns `banana` instead of the only schema value `grammar_ok` | `reports/thor/constrained_guard_probe.json` (2026-10-02): refused HTTP 422 at save, canary refused, no-reasoning container passes | M1 (`edge/model_guard.py:65-118`) | Public |
| TC-3 | Unconstrained decoding | Labels outside the schema: 59 of 97 detections (2B with think block), 57 of 106 (2B no think), 20 of 81 (8B no think); 12 literal echoes of the schema string | README, real-model inference cost and model-size sections | M2 removes this entirely: 0 out-of-vocabulary labels in both constrained runs | Public |
| TC-4 | Prompt asks for a wrapper the grammar forbids | Empty detections on 60 of 60 frames, 7 completion tokens each, 2.303 frames/s "throughput" that measures generating nothing | `reports/thor/cosmos2b_video_60_schema_v1prompt.json`; README four-run table | Prompt rewritten for JSON-only output (`openai_compatible.py:194-209`); no runtime detector of "always empty" | Public |
| TC-5 | Model emits box coordinates on independent 0 to 1000 axes while the consumer assumes pixels | Boxes land outside the image; zone intersection and 90 px proximity become meaningless | Pro edition adapter declares contract `native-1000-to-pixels-v1` and scales by width/1000 and height/1000 (2026-10-17). The public edition reads the model's coordinates as pixels. Measurement that motivated the change: private, not yet published | M3 (Pro) raises on out-of-range or zero-area native boxes; no magnitude heuristic, no clipping. Public edition: none | Pro edition; numbers private |
| TC-6 | Same model, different CPU architecture | Image resize produces tensors that differ by up to one pixel-value unit between the edge device and an x86 workstation, so bitwise reproduction of a diagnostic detector's inputs fails off-device. Applies to a diagnostic detector, not the production VLM path | Private, not yet published | Saved tensor bytes and an integer reference resize used for audits | Private |
| TC-7 | Reasoning length | Latency tail: three slowest frames 977, 825 and 815 completion tokens at about 61 tokens/s; p95 12.85 s with the think block, 6.58 s without, 3.36 s with grammar | `cosmos2b_video_60.json`, `_nothink.json`, `_schema.json` | `--no-think`, `max_tokens` cap, grammar | Public |
| TC-8 | Adapter timeout | First 2B attempt failed at frame 26 on a 60 s timeout; a failed run now writes a partial artifact with the error | `reports/thor/cosmos2b_video_60_attempt1_timeout.log` | Timeout is a CLI option; run marked failed (README, "Measured runs from the UI") | Public |
| TC-9 | Lighting, occlusion, PPE colour and style, camera calibration drift, real people and robots | Unknown. Every real-model run used simulation footage; the simulation set uses one stylised worker and background with correlated variations (README, "Labeled simulation measurement") | Not measured | None | Not measured |
| TC-10 | Omitted PPE field in an unconstrained reply | `rules/policies.py:29` treats a missing boolean as missing PPE: fails toward an alert, never toward silence | Private count, not yet published | M3 (Pro) in constrained mode only; the public adapter has no contract | Pro edition |

## 5. Acceptance criteria needed before any safety-related use, and what is not established

None of the following has been met. Where a threshold is not in the repository, no number is given; choosing it is a decision for the operator of the cell, not for this document.

| Criterion | Current state | Source |
|---|---|---|
| Per-rule precision and recall on real footage of the actual cell, with independent labels, including negatives | Not measured. Only simulation results exist, and they are private | README, opening paragraph and "Not yet measured" |
| Person detection recall on real footage at the working distance, lighting and PPE of the cell | Not measured | same |
| False-alert rate per hour of real operation, below a budget the operator sets | Not measured; public evidence shows 7 false events per 60 simulation frames for the 2B model | README, four-run table |
| End-to-end latency from frame capture to event on the console with a live camera, with a bound chosen for the cell | Not measured; file-source inference latency only (0.154 to 0.367 frames/s for 2B) | `reports/thor/cosmos2b_video_60*.json` |
| Zone polygons and the proximity threshold derived from camera calibration, with a stated image-to-floor error | No calibration; 90 px fixed | `rules/policies.py:70`; README "Not yet measured" |
| Sustained operation over hours or days (reconnects, memory, store growth) | Committed runs last 60 to 390 s | README, "Not yet measured" |
| Operator response: evidence that `human_review_required` events are reviewed within a stated time | No mechanism measures this | `events/schemas.py:66` |
| A documented decision that this layer is supplementary to, and never a replacement for, the cell's certified safeguards | Stated in README ("Nothing here acts autonomously") but not recorded as a signed operating assumption | README |

**Not established:** any ASIL; any SOTIF validation; real-world detection quality; a safe-state behaviour beyond "no event is invented"; the behaviour of the 8B model when a person is present (README: "it does not say what the 8B does when a person is present"); calibration error; the effect of the asynchronous poster on throughput.

## 6. Open items

1. Run the labelled simulation protocol on real footage of a cell with independent labels; publish per-rule TP/FP/FN. Until then the public claim stays "real-world detection quality remains unmeasured".
2. Add a runtime detector for TC-4 and H5: a constrained run that returns empty detections on every frame for N consecutive samples should raise a runtime status, not stay silent.
3. Replace the 90 px proximity constant and hand-drawn zones with calibrated geometry, or document the pixel-to-floor error for each camera (H11, H12, H14, H9).
4. Reject degenerate or self-intersecting polygons at drawing time, since they are outside the geometry contract (`spatial/zones.py:6`).
5. Decide and record the alert budget and the operator response-time expectation (section 5).
6. Measure a live-camera run on the device: capture rate, dropped frames, packet-to-event latency (README, "Planned upgrades").
7. Publish the 2026-10-17 simulation results or keep them private; this document's public body must not cite their numbers until that decision is taken.
8. Decide whether BLOCKED_EMERGENCY_PATH should exist without path geometry (H19) or be re-labelled informational like UNSAFE_EVENT_SUMMARY.
