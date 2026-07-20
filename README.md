# DevOps Signal Dashboard

This repository contains a self-updating portfolio-wide CI/CD health dashboard for the public repositories owned by `rohanpurohit7`.

## Signal meanings

- 🟢 **GREEN** — latest GitHub Actions run completed successfully.
- 🟡 **YELLOW** — workflow is queued/in progress, no workflow run exists, or the repository could not be checked.
- 🔴 **RED** — latest run failed, was cancelled, timed out, or requires action.

## Dashboard

Open [`STATUS.md`](STATUS.md) for the GitHub-rendered dashboard and rolling error log.

A browser-friendly traffic-light view is available in [`index.html`](index.html). It reads the generated [`status.json`](status.json).

## Automation

The workflow `.github/workflows/devops-signal.yml` refreshes the dashboard hourly and can also be run manually. The collector is `scripts/update-devops-signal.py`.

The collector discovers public, non-archived repositories automatically. It records the latest Actions workflow state and, for failed runs, captures failed job and step names when the GitHub API exposes them. It does not expose secrets or raw private logs.