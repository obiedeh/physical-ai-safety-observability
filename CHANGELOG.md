# Changelog

What changed in Physical AI Safety Observability, newest first. The public
edition is frozen behind the README's Editions section; work lands in
monthly batches. A number named here is read from a committed record under
`reports/`.

## Unreleased

- 2026-11-15: Showcase brought up to the README: a section on the labeled simulation results and the Cosmos 3 runs (false gear alarms 11 to 0 with required fields; people found 29 to 44 of 45 and false proximity alarms 16 to 0 with Cosmos 3 Edge, which read gear worse; gate scenes redrawn darker with Cosmos Transfer), Cosmos 3 Edge in the models line, the status ledger moved to November, and two ledger lines that said no rule had been rated corrected. The hero's artifact count, now stale, is reworded without a number.
- 2026-11-15: The README reports the other Cosmos 3 work in the full build: Cosmos3-Nano-Sim-Transfer on `jetson-agx-thor` redrew the access gate's five test clips as daylight, dusk and night (148 to 156 s and 3.5 to 3.8 Wh a clip); with Cosmos Reason 2 the gate's decision held at 15 of 15 in every version while the safety-glasses read fell from 45 to 27 of 45 by night; Cosmos 3 Edge behind the same gate denied every compliant worker. Summary and generation records and one still under `reports/thor/gate_lighting_transfer_2026-11-15_*`.
- 2026-11-15: Results on 60 labeled simulation pictures, measured with the full build's scorer on `jetson-agx-thor`, are reported in the README with their summary reports. Baseline, Cosmos Reason 2 (2B): required `hard_hat` and `vest` fields took false protective-gear alarms from 11 to 0 with all 15 real ones kept, the person found in 29 of 45, 16 false proximity alarms (2026-10-17, `reports/thor/model_accuracy_*_2026-10-17.json`). Cosmos 3 Edge (4B) on the same request: the person found in 44 of 45, 14 of 15 zone entries, no false proximity alarms, and 3 false gear alarms with 13 of 15 real ones kept, with the launch flag it needed (2026-11-14, `reports/thor/reasoner_comparison_2026-11-14*`). The README's statements that nothing measures detection quality are updated to match. A machine name in the two copied 2026-10-17 reports was replaced with a board label; hashes in `reports/thor/SCRUB_2026-11-15.json`.
- 2026-11-03: The report header band reads "EmbodiedEdge Evidence"; the retired Labs label is removed.
- 2026-11-03: Evidence pages and their theme name the lab EmbodiedEdge; the retired EmbodiedEdge Labs name is removed.
- 2026-11-03: Machine names and a home path in 12 committed records replaced with board labels and <home>, with the as-measured hashes kept in reports/thor/SCRUB_2026-11-03.json; a committed handoff note removed (handoff notes live outside repositories).
- `docs/safety/hazard_analysis.md`: the observability rules read in SOTIF and
  ISO 26262 vocabulary (item, hazard table, triggering conditions, acceptance
  criteria, open items). Method and vocabulary only; no ASIL, no conformance
  claim.
- This changelog.

## 2026-10-10: the public edition is frozen behind an Editions section

- Reverts of the October work that continues privately in Physical AI
  Safety Pro, and the README's Editions section pointing at it.

## 2026-09-09 and before

- Measured on the Jetson AGX Thor: runtime overhead with the mock adapter,
  Cosmos-Reason2 2B and 8B inference cost via vLLM, constrained decoding,
  the evidence page. Event model, policy engine, operator console, evidence
  chain.
