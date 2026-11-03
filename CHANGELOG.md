# Changelog

What changed in Physical AI Safety Observability, newest first. The public
edition is frozen behind the README's Editions section; work lands in
monthly batches. A number named here is read from a committed record under
`reports/`.

## Unreleased

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
