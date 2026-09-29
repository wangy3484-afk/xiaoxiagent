# Operations Strategy Agent

An evidence-based operations strategy assistant for acquisition, retention,
campaign, and content operations. Product requirements and implementation
tracking live under `openspec/changes/build-operations-strategy-agent/`.

## Backend quick check

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m ruff check backend
.venv\Scripts\python -m mypy backend/src backend/tests
.venv\Scripts\python -m pytest
```

The worker is supported in Linux containers for development and production.
