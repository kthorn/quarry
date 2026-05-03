# DECISIONS

## Package Name: Quarry

**Date:** 2026-04-05

**Decision:** Renamed package from "jobhound" to "quarry"

**Rationale:** User preferred "quarry" as the package/project name

**Status:** Completed

---

## LLM: Use OpenRouter or Bedrock

**Date:** 2026-04-05

**Decision:** Access LLMs via OpenRouter or AWS Bedrock (preferred) instead of direct Anthropic API

**Rationale:**

- Avoids direct API dependency
- Bedrock preferred for privacy/control
- OpenRouter as fallback for easier setup

**Status:** Pending implementation - will update config in M1

---

## Dedup Strategy: Deferred

**Date:** 2026-04-05

**Decision:** Defer dedup implementation details until job search results can be evaluated

**Rationale:**

- Title-based dedup (title_hash) may not be sufficient for roles like "Scientist II" with multiple openings
- ATS systems provide internal job IDs (source_id) that could be more precise
- Need to see what data actually comes back from Indeed/Greenhouse/Lever before committing

**Status:** Deferred - will revisit after M2 (Crawlers) when real data is available

---

## Config: Env Vars Override YAML

**Date:** 2026-04-05

**Decision:** Environment variables always take precedence over config.yaml values

**Rationale:**

- Allows deployment-specific overrides without modifying checked-in config
- Follows 12-factor app convention
- User can set ANTHROPIC_API_KEY etc. in environment without editing config

**Status:** Implemented in load_config()

---

## Keyword Blocklist: Removed for MVP

**Date:** 2026-04-05

**Decision:** Remove keyword blocklist filtering for MVP

**Rationale:**

- Simplifies MVP - fewer config items to manage
- Can add back later based on actual noise seen in results
- Similarity threshold provides basic filtering

**Status:** Completed - removed from config and plan

---

## Multi-User Architecture: Shared Catalog + Per-User Data

**Date:** 2026-04-29 (completed 2026-05-03)

**Decision:** Split the database into shared catalog tables (companies, job_postings, locations) and per-user tables (labels, status, similarity scores, settings). All foreign keys use `ON DELETE CASCADE`.

**Rationale:**

- Positive/negative labels must be per-user — User A marking a posting as "applied" must not affect User B's view
- Embedding similarity depends on each user's ideal role description
- Watchlist (which companies to track) is per-user not global
- Enables multi-user support from day one with zero extra code path in single-user mode

**Status:** Implemented (all 4 phases complete)

---

## Per-User Labels: Composite UNIQUE on (user_id, posting_id, signal)

**Date:** 2026-04-29

**Decision:** `user_labels` uses `UNIQUE(user_id, posting_id, signal)` instead of a simple unique label per posting.

**Rationale:**

- A user can have both `positive` and `applied` signals on the same posting (they're different signals)
- Prevents double-positive bugs (can't insert two `positive` labels for the same user+posting)
- Different users can independently rate the same posting (positive vs negative)

**Status:** Implemented

---

## SQLAlchemy 2.0 + Alembic for ORM and Migrations

**Date:** 2026-04-29

**Decision:** Adopt SQLAlchemy 2.0 Mapped[] classes as the ORM layer and Alembic for schema migrations. Keep ORM models (`quarry/store/models.py`) separate from Pydantic API models (`quarry/models.py`).

**Rationale:**

- Rejected SQLModel because it forces 1:1 DB-to-API mapping, which the schema change broke (fields moved between tables)
- Separate models provide flexibility: ORM models mirror DB schema; Pydantic models serve API boundaries
- Alembic autogenerate provides auditable schema migration history
- `PRAGMA foreign_keys = ON` enforced via SQLAlchemy event listener on every connection

**Status:** Implemented (17 ORM model classes; Alembic configured)

---

## Phased Rollout: DDL → ORM → CRUD → Callers

**Date:** 2026-04-29

**Decision:** Execute the schema rebuild in four sequential phases instead of one monolithic PR.

**Rationale:**

- **Debugging surface area:** Phase 1 isolates DDL correctness. Phase 2 isolates ORM configuration. Phase 3 isolates query translation. Phase 4 isolates caller plumbing. If something breaks, you know which phase introduced it.
- **Reversibility:** Each phase can be reverted independently. If ORM caused unexpected issues, fall back to raw SQL while keeping new schema.
- **Alembic baseline:** Phase 1's raw DDL serves as the reviewable spec; Phase 2's autogenerate captures it as the authoritative migration.

**Status:** All four phases complete

---

## Default User ID=1 for Single-User Mode

**Date:** 2026-04-29

**Decision:** Until authentication is implemented, all operations default to `user_id=1`. A default user is seeded on `init_db()` via `INSERT OR IGNORE INTO users (id, email, name) VALUES (1, 'default@local', 'Default User')`.

**Rationale:**

- Multi-user schema capability from day one without auth infrastructure
- All per-user methods accept `user_id: int = 1` default, making single-user code paths identical to multi-user
- Zero code bifurcation — no `if multi_user: else: single_user` anywhere

**Status:** Implemented
