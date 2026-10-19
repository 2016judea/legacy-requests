#!/usr/bin/env python3
"""Deploy site/ to Vercel production over the REST API.

Not the CLI. On 2026-09-07 four consecutive `vercel deploy --prod` runs returned
BLOCKED — no error, no build log, just a BLOCKED state — while the same files
posted to /v13/deployments went READY in seconds. Ruled out along the way: the
account (brick-and-mortar deployed fine on the same token in the same minutes),
the team scope (pro, unblocked), the target (a staging CLI deploy blocked too),
and .env.local in the payload (a .vercelignore did not change it).

Needs VERCEL_TOKEN in the environment. Reads the project from .vercel/project.json.

Every file under site/ ships (dotfiles and the stopped /worth build excepted), plus
private/bundle/ (the paid open-asks set, scripts/build_asks.py) as api/_full/, which only
/api/data and /api/check read; site/vercel.json bundles it with them and redirects any
public request for it. 2026-10-15: globbed, because a hand list silently dropped new pages.
"""
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"
BUNDLE = Path(__file__).resolve().parent.parent / "private" / "bundle"
SKIP_DIRS = {"worth", "_full"}
POLL_SECONDS = 3
POLL_LIMIT = 60


def request(url, token, data=None, headers=None):
    head = {"Authorization": f"Bearer {token}"}
    head.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=head)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


# Only public/ is static (vercel.json outputDirectory). Until 2026-10-19 every file sat at the
# deployment root with outputDirectory ".", so api/_full/rows.json.gz was a static URL and the
# /api/_full/ redirect matched the raw path only: /api/%5Ffull/rows.json.gz, /api/_full%2F...,
# /api/_full/rows.json.gz/ and /%61pi/_full/... each served the paid set (curl, 1.5 MB, 200).
# Static files now upload under public/; api/ and a root copy of what the functions require()
# (asks/meta.json for checkout) stay outside it, where nothing serves them.
def upload_names(rel):
    if rel.parts[0] == "api" or str(rel) == "vercel.json":
        return [str(rel)]
    return ["public/" + str(rel), str(rel)]


def collect():
    pairs = []
    for p in sorted(SITE.rglob("*")):
        rel = p.relative_to(SITE)
        if p.is_file() and not any(x.startswith(".") for x in rel.parts) and not (set(rel.parts) & SKIP_DIRS):
            pairs += [(p, name) for name in upload_names(rel)]
    pairs += [(p, "api/_full/" + str(p.relative_to(BUNDLE))) for p in sorted(BUNDLE.rglob("*")) if p.is_file()]
    return pairs


def main():
    token = os.environ.get("VERCEL_TOKEN")
    if not token:
        sys.exit("VERCEL_TOKEN is not set.")

    link = json.loads((SITE / ".vercel" / "project.json").read_text())
    team, project = link["orgId"], link["projectName"]

    if not (BUNDLE / "rows.json.gz").exists():
        sys.exit("private/bundle/rows.json.gz missing: run scripts/build_asks.py (the paywall serves it)")
    pairs = collect()
    files = []
    for path, name in pairs:
        body = path.read_bytes()
        sha = hashlib.sha1(body).hexdigest()
        code, out = request(
            "https://api.vercel.com/v2/files", token, data=body,
            headers={"Content-Type": "application/octet-stream",
                     "x-vercel-digest": sha, "x-vercel-team-id": team},
        )
        if code >= 400:
            sys.exit(f"upload {name} failed: {code} {out}")
        print(f"  {name}: {len(body):,} bytes")
        files.append({"file": name, "sha": sha, "size": len(body)})

    payload = json.dumps({
        "name": project, "project": project, "target": "production",
        "files": files,
        "projectSettings": {"framework": None, "buildCommand": "echo build", "outputDirectory": "public", "installCommand": "echo skip"},
    }).encode()
    code, out = request(
        f"https://api.vercel.com/v13/deployments?teamId={team}&skipAutoDetectionConfirmation=1",
        token, data=payload, headers={"Content-Type": "application/json"},
    )
    if code >= 400 or out.get("error"):
        sys.exit(f"create failed: {code} {json.dumps(out.get('error'))}")

    url = out["url"]
    print(f"  deploying {url}")
    for _ in range(POLL_LIMIT):
        time.sleep(POLL_SECONDS)
        _, d = request(f"https://api.vercel.com/v13/deployments/{url}?teamId={team}", token)
        state = d.get("readyState")
        if state in ("READY", "ERROR", "BLOCKED", "CANCELED"):
            print(f"  {state} {d.get('errorMessage') or ''}")
            sys.exit(0 if state == "READY" else 1)
    sys.exit("timed out waiting for the deployment to settle")


if __name__ == "__main__":
    main()
