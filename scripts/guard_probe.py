"""Exercise the constrained-mode guard against the real vLLM containers.

Run on the device next to the API:

    python scripts/guard_probe.py [API_URL] [OTHER_APP_URL] > reports/<host>/constrained_guard_probe.json

Starts the reasoning-parser Cosmos container and checks that json_schema is
refused by the settings and caught by the live canary, then starts the
no-reasoning container and checks the canary passes. OTHER_APP_URL, when
given, is an Urban Edge API whose managed vLLM is stopped first to free the port.
"""
import json
import sys
import time
import urllib.error
import urllib.request

S = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
UE = sys.argv[2] if len(sys.argv) > 2 else None

def call(method, url, body=None, timeout=180):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")

def wait_ready(limit=240):
    t0 = time.time()
    while time.time() - t0 < limit:
        _, s = call("GET", f"{S}/models/server")
        if s.get("ready"):
            return round(time.time() - t0, 1)
        if s.get("state") == "failed":
            return None
        time.sleep(5)
    return None

out = {"started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "steps": []}
if UE:
    call("POST", f"{UE}/inference/vllm/stop")  # free the vLLM port held by the other app
    time.sleep(5)

# 1. Reasoning-parser container: settings-level refusal, then the live canary.
code, body = call("POST", f"{S}/models/server/start", {"key": "cosmos-reason2-2b-reasoning", "json_schema": True})
out["steps"].append({"step": "start reasoning entry with json_schema=true", "http": code, "detail": body.get("detail")})
code, body = call("POST", f"{S}/models/server/start", {"key": "cosmos-reason2-2b-reasoning", "json_schema": False})
ready = wait_ready()
out["steps"].append({"step": "start reasoning entry (think mode)", "http": code, "ready_after_s": ready,
                     "command": (body.get("server", {}).get("log_tail") or [""])[0]})
code, body = call("PUT", f"{S}/config/model", {"backend": "cosmos-reason2", "endpoint": "http://127.0.0.1:8000",
                  "model": "nvidia/cosmos-reason2-2b", "json_schema": True, "reasoning_parser": True})
out["steps"].append({"step": "PUT /config/model json_schema=true reasoning_parser=true", "http": code,
                     "detail": str(body.get("detail"))[:400]})
# operator claims "unknown" for the parser: the canary must still catch it
code, body = call("PUT", f"{S}/config/model", {"backend": "cosmos-reason2", "endpoint": "http://127.0.0.1:8000",
                  "model": "nvidia/cosmos-reason2-2b", "json_schema": True, "reasoning_parser": None})
code2, guard = call("POST", f"{S}/config/model/guard")
out["steps"].append({"step": "canary against reasoning-parser server (reasoning_parser unknown)", "http": code2, "guard": guard})

# 2. No-reasoning container: canary must pass.
call("POST", f"{S}/models/server/stop"); time.sleep(8)
code, body = call("POST", f"{S}/models/server/start", {"key": "cosmos-reason2-2b", "json_schema": True})
ready = wait_ready()
out["steps"].append({"step": "start no-reasoning entry with json_schema=true", "http": code, "ready_after_s": ready,
                     "command": (body.get("server", {}).get("log_tail") or [""])[0]})
code2, guard = call("POST", f"{S}/config/model/guard")
out["steps"].append({"step": "canary against no-reasoning server", "http": code2, "guard": guard})
_, cat = call("GET", f"{S}/models/catalog")
out["image"] = cat["host"]["image"]
out["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
json.dump(out, sys.stdout, indent=2)
