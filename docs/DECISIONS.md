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