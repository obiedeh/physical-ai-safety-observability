# Safety Policy Model

Implemented rules:

- `PPE_MISSING`
- `RESTRICTED_ZONE_ENTRY`
- `HUMAN_ROBOT_PROXIMITY`
- `BLOCKED_EMERGENCY_PATH`
- `UNSAFE_EVENT_SUMMARY`

Rules are deterministic and versioned with `safety-policy-v1`. Runtime degradation lowers event
confidence and can force human review even when model confidence is high.

