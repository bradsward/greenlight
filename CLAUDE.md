# Working on greenlight

- GitHub `master` is the source of truth. The user works from more than one
  computer: whenever a session pushes changes, remind them to `git pull` on
  their other machine.
- Tests are plain scripts, not pytest: `python tests/<name>.py`. CI runs
  the list in `.github/workflows/tests.yml`; add new test files there.
- Use a venv (`python -m venv .venv && .venv/bin/pip install -e ".[dev]"`);
  the fixtures need a current `mcp` SDK (`mcp.server.mcpserver`).
- Record user-facing changes in CHANGELOG.md, and engineering decisions in
  the next `notes/dayN.md`.
