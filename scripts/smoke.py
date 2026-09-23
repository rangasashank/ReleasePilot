"""Local full-stack smoke: real HTTP, worker, database, and private MCP transport."""
import http.cookiejar
import json
import os
import time
import urllib.request
import uuid
from pathlib import Path

root = Path(__file__).resolve().parents[1]
env = {}
if (root / ".env").exists():
    env = dict(line.split("=", 1) for line in (root / ".env").read_text().splitlines()
               if "=" in line and not line.startswith("#"))
origin = os.getenv("SMOKE_ORIGIN", "http://localhost:3000")
client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
headers = {"Origin": origin, "Content-Type": "application/json"}


def call(path, data=None):
    request = urllib.request.Request(origin + "/api/v1" + path,
        data=json.dumps(data).encode() if data is not None else None, headers=headers)
    with client.open(request, timeout=30) as response:
        body = response.read()
        return json.loads(body) if body else None


call("/auth/demo/login", {"email": env.get("DEMO_EMAIL", "demo@releasepilot.local"),
                         "password": env.get("DEMO_PASSWORD", "local-demo-change-me")})
headers["X-CSRF-Token"] = call("/me")["csrf_token"]
services = call("/services?limit=100")
service = next((s for s in services if s["name"] == "Workflow verification"), None)
if not service:
    service = call("/services", {"name": "Workflow verification", "description": "Local full-stack smoke test"})
results = []
for scenario, expected in [("safe", "GO"), ("failed_ci", "NO_GO"), ("missing_evidence", "CAUTION")]:
    headers["Idempotency-Key"] = str(uuid.uuid4())
    started = time.monotonic()
    created = call("/analyses", {"service_id": service["id"], "mode": "demo", "scenario": scenario})
    replay = call("/analyses", {"service_id": service["id"], "mode": "demo", "scenario": scenario})
    assert replay["id"] == created["id"]
    deadline = started + 90
    while time.monotonic() < deadline:
        status = call(f"/analyses/{created['id']}/status")
        if status["state"] in ("COMPLETED", "PARTIAL", "FAILED"):
            break
        time.sleep(1)
    assert status["state"] == "COMPLETED", status
    assert len(status["agents"]) == 3, status
    assert all(a["state"] == "COMPLETED" for a in status["agents"]), status
    assert len(status["tools"]) >= 3, status
    assert all(t["status"] == "COMPLETED" for t in status["tools"]), status
    report = call(f"/analyses/{created['id']}")
    assert report["decision"]["recommendation"] == expected, report["decision"]
    ids = {e["id"] for e in report["evidence"]}
    assert all(set(f["evidence_ids"]) <= ids for f in report["decision"]["findings"])
    results.append({"scenario": scenario, "recommendation": expected, "analysis_id": created["id"],
                    "duration_seconds": round(time.monotonic()-started, 2),
                    "agents": len(status["agents"]), "mcp_calls": len(status["tools"])})
    print(json.dumps(results[-1]), flush=True)
(root / "artifacts").mkdir(exist_ok=True)
(root / "artifacts/smoke.json").write_text(json.dumps(results, indent=2) + "\n")
boundary = "rp" + uuid.uuid4().hex
body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"service_id\"\r\n\r\n{service['id']}\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"deployment.md\"\r\n"
        "Content-Type: text/markdown\r\n\r\n# Rollback\nRestore the previous checkout image after verifying database compatibility.\r\n"
        f"--{boundary}--\r\n").encode()
request = urllib.request.Request(origin + "/api/v1/documents", data=body,
    headers={**headers, "Content-Type": f"multipart/form-data; boundary={boundary}"})
with client.open(request, timeout=30) as response:
    document = json.load(response)
for _ in range(60):
    docs = call(f"/documents?service_id={service['id']}")
    current = next(d for d in docs if d['id'] == document['id'])
    if current['status'] in ('READY', 'FAILED'):
        break
    time.sleep(1)
assert current['status'] == 'READY', current
passages = call(f"/documents/search?service_id={service['id']}&query=rollback")
assert any(c['document_id'] == document['id'] for c in passages)
print("Document upload, background indexing, and passage retrieval passed.")
print("Full-stack smoke passed. Fixture agents were deterministic; document embedding mode: " + current["embedding_model"])
