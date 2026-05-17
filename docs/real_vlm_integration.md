# Real VLM Integration

The runtime defaults to the mock adapter for deterministic local tests. Real models are
selected through config or CLI flags and must return detections that can be normalized into
the event contract.

Cosmos-Reason2:

```bash
export COSMOS_API_KEY=...
python -m edge.worker \
  --config configs/cosmos_reasoning.json \
  --source examples/sample_source.json
```

OpenAI-compatible local service:

```bash
python -m edge.worker \
  --config configs/jetson.json \
  --source examples/sample_source.json \
  --adapter openai-compatible \
  --adapter-endpoint http://127.0.0.1:8000/v1 \
  --model local-vlm
```

Accepted adapter outputs:

- top-level `{"detections": [...]}`
- OpenAI chat-completion message content containing JSON
- fenced JSON blocks
- Cosmos `<answer>{...}</answer>` blocks

