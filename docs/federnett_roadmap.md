# Federnett Product Roadmap (Proposed)

This roadmap captures the next implementation phases for:
- account/login
- personalized agent profiles
- report hub posting/collaboration
- safe agentic assistant actions

## Phase 1: Safe Interactive Assistant (Near-term)

Goal: keep the current `Guide Agent` read-only and reliable.

- Add `action policy` layer:
  - `mode=read_only` (default)
  - allowed actions: list runs, list templates, inspect config, dry-run command preview
  - blocked actions: file write/delete, process execution, network side effects
- Add structured tool responses:
  - action result cards (`type`, `status`, `details`, `next_step`)
  - explicit "not permitted" explanation when action blocked
- Persist chat history per run:
  - `site/runs/<run>/report_notes/help_history.json`

## Phase 2: Identity and Workspace Profiles

Goal: separate reproducible presets from personalized identity context.

- Add local account/session model:
  - `users.json` (local dev mode)
  - session token cookie (HttpOnly, SameSite=Lax)
- Add profile ownership scope:
  - built-in profile (read-only)
  - user profile (private)
  - org profile (shared within org)
- Keep profile split:
  - `persona/system prompt` (style, rules)
  - `author identity` (display only)
  - `memory connector` (disabled until authZ is in place)

## Phase 3: Memory/DB Connector (Permissioned)

Goal: optional retrieval without breaking context limits.

- Add connector abstraction:
  - `vector_db`, `file_rag`, `sql_knowledge` providers
- Enforce bounded retrieval:
  - top-k + token budget + citation metadata required
- Access control:
  - API key scope or certificate-based claims
  - per-profile allowlist to data sources

## Phase 4: Federlicht Report Hub Posting

Goal: move from auto-scan only to publish workflow.

- Add report lifecycle:
  - draft -> review -> published -> archived
- Add posting metadata:
  - author, organization, agent profile id, model, stages, evidence snapshot hash
- Add collaboration:
  - comment thread per report
  - patch/update requests linked to sections
- Keep compatibility:
  - existing auto-scan remains as fallback ingestion mode

## Phase 5: Multi-Agent Collaboration

Goal: controlled orchestration for refinement and debate.

- Add role agents:
  - writer, critic, verifier, planner
- Add explicit stage contracts:
  - input schema / output schema per stage
- Add run checkpointing:
  - resumable from stage state + cache signature

## Non-goals (for now)

- No unrestricted shell execution from the Guide Agent.
- No silent file mutation from UI assistant flows.
- No implicit memory DB access without authN/authZ.

