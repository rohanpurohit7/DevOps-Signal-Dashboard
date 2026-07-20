#!/usr/bin/env python3
"""Generate a red/yellow/green DevOps signal dashboard for public GitHub repos."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OWNER = os.getenv("DEVOPS_SIGNAL_OWNER", "rohanpurohit7")
ROOT = Path(__file__).resolve().parents[1]
STATUS_JSON = ROOT / "status.json"
STATUS_MD = ROOT / "STATUS.md"
TOKEN = os.getenv("DEVOPS_SIGNAL_TOKEN", "").strip()
USER_AGENT = "devops-signal-dashboard/1.0"
GREEN, YELLOW, RED = "GREEN", "YELLOW", "RED"
ICONS = {GREEN: "🟢", YELLOW: "🟡", RED: "🔴"}
FAILURE_CONCLUSIONS = {"failure", "cancelled", "timed_out", "action_required", "startup_failure", "stale"}


def api_get(url: str, authenticated: bool = True) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if authenticated and TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if authenticated and TOKEN and exc.code in {403, 404}:
            return api_get(url, authenticated=False)
        raise


def public_repositories() -> list[dict[str, Any]]:
    url = f"https://api.github.com/users/{urllib.parse.quote(OWNER)}/repos?per_page=100&sort=updated"
    repos = api_get(url, authenticated=False)
    return [
        repo for repo in repos
        if not repo.get("fork") and not repo.get("archived") and repo.get("visibility", "public") == "public"
    ]


def latest_run(repo_name: str) -> dict[str, Any] | None:
    url = f"https://api.github.com/repos/{OWNER}/{urllib.parse.quote(repo_name)}/actions/runs?per_page=1"
    payload = api_get(url)
    runs = payload.get("workflow_runs", [])
    return runs[0] if runs else None


def failed_steps(repo_name: str, run_id: int) -> list[dict[str, str]]:
    url = f"https://api.github.com/repos/{OWNER}/{urllib.parse.quote(repo_name)}/actions/runs/{run_id}/jobs?per_page=100"
    try:
        payload = api_get(url)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return []
    failures: list[dict[str, str]] = []
    for job in payload.get("jobs", []):
        job_conclusion = job.get("conclusion") or "unknown"
        failed = [s for s in job.get("steps", []) if (s.get("conclusion") or "") in FAILURE_CONCLUSIONS]
        if job_conclusion in FAILURE_CONCLUSIONS or failed:
            if failed:
                for step in failed:
                    failures.append({
                        "job": job.get("name", "unknown job"),
                        "step": step.get("name", "unknown step"),
                        "conclusion": step.get("conclusion", job_conclusion),
                    })
            else:
                failures.append({
                    "job": job.get("name", "unknown job"),
                    "step": "Job failed; no failed step detail returned",
                    "conclusion": job_conclusion,
                })
    return failures


def classify(run: dict[str, Any] | None) -> tuple[str, str]:
    if run is None:
        return YELLOW, "No GitHub Actions runs"
    status = run.get("status") or "unknown"
    conclusion = run.get("conclusion")
    if status != "completed":
        return YELLOW, status
    if conclusion == "success":
        return GREEN, "success"
    if conclusion in FAILURE_CONCLUSIONS:
        return RED, conclusion or "failure"
    return YELLOW, conclusion or status


def build() -> dict[str, Any]:
    repositories: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    summary = {"green": 0, "yellow": 0, "red": 0}
    for repo in public_repositories():
        name = repo["name"]
        try:
            run = latest_run(name)
            signal, detail = classify(run)
            record: dict[str, Any] = {
                "repository": name,
                "url": repo.get("html_url"),
                "signal": signal,
                "detail": detail,
                "workflow": run.get("name") if run else None,
                "run_number": run.get("run_number") if run else None,
                "run_url": run.get("html_url") if run else None,
                "branch": run.get("head_branch") if run else None,
                "updated_at": run.get("updated_at") if run else repo.get("updated_at"),
            }
            if signal == RED and run:
                step_errors = failed_steps(name, int(run["id"]))
                record["failed_steps"] = step_errors
                errors.append({
                    "repository": name,
                    "workflow": run.get("name"),
                    "run_number": run.get("run_number"),
                    "run_url": run.get("html_url"),
                    "conclusion": run.get("conclusion"),
                    "updated_at": run.get("updated_at"),
                    "failed_steps": step_errors,
                })
            repositories.append(record)
            summary[signal.lower()] += 1
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            repositories.append({
                "repository": name,
                "url": repo.get("html_url"),
                "signal": YELLOW,
                "detail": f"Status check error: {type(exc).__name__}",
                "workflow": None,
                "run_number": None,
                "run_url": None,
                "branch": None,
                "updated_at": repo.get("updated_at"),
            })
            summary["yellow"] += 1
        time.sleep(0.05)
    order = {RED: 0, YELLOW: 1, GREEN: 2}
    repositories.sort(key=lambda item: (order[item["signal"]], item["repository"].lower()))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "owner": OWNER,
        "summary": summary,
        "repositories": repositories,
        "errors": errors,
    }


def write_markdown(data: dict[str, Any]) -> None:
    s = data["summary"]
    lines = [
        "# DevOps Signal Dashboard", "", f"Last refreshed: `{data['generated_at']}`", "",
        f"## 🟢 {s['green']} Green &nbsp;&nbsp; 🟡 {s['yellow']} Yellow &nbsp;&nbsp; 🔴 {s['red']} Red", "",
        "| Signal | Repository | Latest workflow | Result | Branch | Updated |",
        "|---|---|---|---|---|---|",
    ]
    for repo in data["repositories"]:
        repo_link = f"[{repo['repository']}]({repo['url']})"
        workflow = f"[{repo.get('workflow') or 'workflow'}]({repo['run_url']})" if repo.get("run_url") else (repo.get("workflow") or "—")
        lines.append(
            "| {icon} **{signal}** | {repo} | {workflow} | {detail} | {branch} | {updated} |".format(
                icon=ICONS[repo["signal"]], signal=repo["signal"], repo=repo_link, workflow=workflow,
                detail=repo.get("detail") or "—", branch=repo.get("branch") or "—", updated=repo.get("updated_at") or "—",
            )
        )
    lines += ["", "## Error Log", ""]
    if not data["errors"]:
        lines.append("No red workflow signals were detected at the last refresh.")
    else:
        for error in data["errors"]:
            lines += [
                f"### 🔴 {error['repository']} — {error.get('workflow') or 'workflow'} #{error.get('run_number') or '—'}", "",
                f"- Conclusion: `{error.get('conclusion') or 'unknown'}`",
                f"- Updated: `{error.get('updated_at') or 'unknown'}`",
                f"- Run: {error.get('run_url') or 'unavailable'}",
            ]
            steps = error.get("failed_steps") or []
            if steps:
                lines += ["", "| Failed job | Failed step | Conclusion |", "|---|---|---|"]
                for step in steps:
                    lines.append(f"| {step['job']} | {step['step']} | `{step['conclusion']}` |")
            else:
                lines.append("- Failed job/step details were not exposed by the API for this run.")
            lines.append("")
    STATUS_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    try:
        data = build()
    except Exception as exc:
        print(f"DevOps signal generation failed: {exc}", file=sys.stderr)
        return 1
    STATUS_JSON.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    write_markdown(data)
    print(f"DevOps signal updated: green={data['summary']['green']} yellow={data['summary']['yellow']} red={data['summary']['red']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
