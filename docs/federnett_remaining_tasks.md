# Federnett Remaining Tasks

Last updated: 2026-02-09

This file is the execution backlog for unresolved work after `1.4.1`.
Reference roadmap: `docs/federnett_roadmap.md`.

## P0 - Stability and UX (next sprint)

- [ ] Guide Agent answer quality hardening
  - Scope: prioritize Federnett UI actions over raw CLI instructions in responses.
  - Add stronger system policy: "UI-first guidance, CLI only when explicitly requested."
  - Acceptance: simple queries (e.g., version/help/options) return direct answers with source lines.

- [ ] Guide Agent safe action mode (read-only + dry-run)
  - Scope: allow safe actions (`list runs`, `list templates`, `preview config`, `dry-run command`) from chat.
  - Must block write/delete/network-side-effect actions by default.
  - Acceptance: every blocked action returns explicit reason and allowed alternative.

- [ ] Guide Agent conversation continuity
  - Scope: multi-turn context memory per run/session with reset.
  - Storage target: `site/runs/<run>/report_notes/help_history.json`.
  - Acceptance: follow-up questions resolve references to prior turns.

- [ ] Live Logs path linking
  - Scope: when log prints file paths (`Wrote ...`), make them clickable to open File Preview directly.
  - Acceptance: one-click open from log to preview panel.

- [ ] Live Logs markdown readability mode refinement
  - Scope: improve table/list rendering and line-wrap behavior in markdown mode.
  - Acceptance: no malformed layout for long table rows; readable on standard 1080p width.

- [ ] File Preview density controls
  - Scope: add preview height presets (`compact/normal/tall`) and fit behavior.
  - Acceptance: user can adjust without excessive page scrolling.

## P1 - Identity, Permissions, and Personalization

- [ ] Account/session foundation
  - Local first: account, login/logout, settings profile.
  - Session handling: secure cookie/token, per-user settings isolation.

- [ ] Role and permission model
  - Roles: admin/editor/viewer (minimum).
  - Enforce policy for profile editing, posting, and action execution.

- [ ] Agent Profile ownership scopes
  - built-in (read-only), user-private, org-shared.
  - Preserve reproducibility by separating persona preset vs identity metadata.

- [ ] Memory connector gate design
  - Add connector stubs (vector/file/sql) behind authZ checks.
  - Add bounded retrieval contract (top-k + token budget + source metadata required).

## P2 - Federlicht Report Hub evolution

- [ ] Posting workflow
  - Lifecycle: draft -> review -> published -> archived.
  - Keep current auto-scan as fallback ingestion mode.

- [ ] Collaboration primitives
  - Section-level comments, update requests, and patch history.
  - Link revisions to report metadata and stage workflow snapshots.

- [ ] GitLab Pages compatibility plan
  - Constraint: static hosting cannot run server-side auth/session logic.
  - Strategy: split architecture into
    - static read portal (Pages)
    - API/control plane (separate backend service).

## P3 - Pipeline performance and async strategy

- [ ] Safe parallelization audit
  - Identify independent I/O-heavy substeps (index reads, metadata parsing, non-mutating scans).
  - Keep model-call stages serialized when shared context mutation exists.

- [ ] Log stream ordering guarantees
  - Add stage/task ids and monotonic sequence numbers for merged streams.
  - Acceptance: no interleaved unreadable stage logs.

- [ ] Context overflow resilience validation
  - Validate across scout/evidence/writer/quality with:
    - `max_input_tokens`
    - `max_tool_chars`
    - reducer fallback
    - large PDF/PPTX/docx/xlsx cases.

## Open decisions

- [ ] Decide whether to bump release to `1.4.2` after P0 completion, or batch into `1.5.0`.
- [ ] Decide default policy for `progress_chars` in Federnett:
  - keep conservative default (`800`)
  - or raise for debug-oriented runs (`1600`/`2400`).
