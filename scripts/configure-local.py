"""Create local-only secrets once, preserving existing configuration."""
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / ".env"
existing = path.read_text() if path.exists() else (root / ".env.example").read_text()
for key in ("INTERNAL_SECRET", "GITHUB_WEBHOOK_SECRET"):
    lines = existing.splitlines()
    if not any(line.startswith(key + "=") and len(line.split("=", 1)[1]) >= 32 for line in lines):
        lines = [line for line in lines if not line.startswith(key + "=")]
        lines.append(f"{key}={secrets.token_urlsafe(48)}")
        existing = "\n".join(lines) + "\n"
path.write_text(existing)
path.chmod(0o600)
print("Local configuration ready. Secret values were not printed.")
