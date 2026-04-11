# Career-Ops Learnings

Analysis of [santifer/career-ops](https://github.com/santifer/career-ops) for potential adoption into Quarry.

## Overview

Career-ops is an AI-powered job search pipeline built on Claude Code. It was used by the author to evaluate 740+ job offers, generate 100+ tailored CVs, and land a Head of Applied AI role.

**Key difference from Quarry:**
- Career-ops: Interactive Claude Code sessions, YAML/Markdown files, manual workflow
- Quarry: Automated Python pipeline, SQLite database, scheduled crawls

---

## #1: Structured Multi-Dimensional Scoring

### Career-ops Approach

**6 Blocks (A-F) per evaluation:**

| Block | Content |
|-------|---------|
| A) Role Summary | Archetype, domain, function, seniority, remote, TL;DR |
| B) CV Match | Requirement → CV line mapping, gaps with mitigation strategies |
| C) Level Strategy | Detected level vs natural level, positioning advice |
| D) Comp & Demand | Salary research via WebSearch (Glassdoor, Levels.fyi, Blind) |
| E) Personalization | Top 5 CV changes + Top 5 LinkedIn changes to maximize match |
| F) Interview Prep | 6-10 STAR+R stories mapped to JD requirements, case study recommendation |

**Global Score (1-5) from weighted dimensions:**

| Dimension | What it measures |
|-----------|-----------------|
| Match con CV | Skills, experience, proof points alignment |
| North Star alignment | How well the role fits user's target archetypes |
| Comp | Salary vs market (5=top quartile, 1=well below) |
| Cultural signals | Company culture, growth, stability, remote policy |
| Red flags | Blockers, warnings (negative adjustments) |

**Score interpretation:**
- 4.5+ → Strong match, recommend applying immediately
- 4.0-4.4 → Good match, worth applying
- 3.5-3.9 → Decent but not ideal, apply only if specific reason
- Below 3.5 → Recommend against applying

**Archetype Detection (6 types):**

| Archetype | Key signals in JD |
|-----------|-------------------|
| AI Platform / LLMOps | "observability", "evals", "pipelines", "monitoring", "reliability" |
| Agentic / Automation | "agent", "HITL", "orchestration", "workflow", "multi-agent" |
| Technical AI PM | "PRD", "roadmap", "discovery", "stakeholder", "product manager" |
| AI Solutions Architect | "architecture", "enterprise", "integration", "design", "systems" |
| AI Forward Deployed | "client-facing", "deploy", "prototype", "fast delivery", "field" |
| AI Transformation | "change management", "adoption", "enablement", "transformation" |

### Quarry Current State

```python
fit_score: int          # single score
role_tier: "reach" | "match" | "strong_match"
similarity_score: float # embedding-based
classifier_score: float # ML classifier
fit_reason: str         # text explanation
key_requirements: str   # text
```

### Adoption Potential: HIGH for data model, MEDIUM for evaluation logic

**Directly adoptable:**

| Career-ops concept | Quarry implementation | Effort |
|-------------------|----------------------|--------|
| Archetype detection | Add `archetype` field to `job_postings` | Low |
| Score dimensions | Add columns: `match_score`, `alignment_score`, `comp_score`, `culture_score`, `red_flags` | Low |
| Gap analysis | Add `gaps` TEXT field with JSON format | Low |
| Level strategy | Add `level_detected`, `level_strategy` fields | Low |
| Interview prep | Add `interview_prep` field | Low |

**Needs adaptation:**

1. **Archetypes are hardcoded for AI roles**
   - Make configurable in `config.yaml` or new `archetypes` table
   - User defines their own: e.g., "Backend Engineer", "Data Scientist", "DevOps"

2. **6-block evaluation is interactive**
   - Designed for Claude Code sessions, not automated enrichment
   - Adapt as structured LLM prompt that outputs JSON

3. **Comp research requires WebSearch**
   - Quarry doesn't have WebSearch integrated
   - Use LLM reasoning from JD text (less accurate but automated)
   - Or add `comp_estimate`, `comp_range`, `comp_notes` fields for manual/semi-automated population

### Recommended Schema Changes

```sql
-- Add to job_postings table
ALTER TABLE job_postings ADD COLUMN archetype TEXT;
ALTER TABLE job_postings ADD COLUMN match_score REAL;
ALTER TABLE job_postings ADD COLUMN alignment_score REAL;
ALTER TABLE job_postings ADD COLUMN comp_score REAL;
ALTER TABLE job_postings ADD COLUMN culture_score REAL;
ALTER TABLE job_postings ADD COLUMN red_flags TEXT;  -- JSON array
ALTER TABLE job_postings ADD COLUMN gaps TEXT;       -- JSON array of {gap, mitigation}
ALTER TABLE job_postings ADD COLUMN level_detected TEXT;
ALTER TABLE job_postings ADD COLUMN level_strategy TEXT;
ALTER TABLE job_postings ADD COLUMN interview_prep TEXT;  -- JSON with STAR stories
```

---

## #7: Pre-configured Portal List

### Career-ops Approach

**`portals.yml` structure:**

```yaml
title_filter:
  positive:
    - "AI"
    - "ML"
    - "LLM"
    - "Agent"
    - "Solutions Architect"
    # ... 30+ keywords
  negative:
    - "Junior"
    - "Intern"
    - ".NET"
    - "Java "
    # ... 20+ keywords
  seniority_boost:
    - "Senior"
    - "Staff"
    - "Principal"
    - "Lead"
    - "Head"
    - "Director"

search_queries:
  - name: Ashby — AI PM
    query: 'site:jobs.ashbyhq.com "AI Product Manager" remote'
    enabled: true
  - name: Greenhouse — SA & FDE
    query: 'site:boards.greenhouse.io "Solutions Architect" OR "Forward Deployed" AI remote'
    enabled: true
  # ... 19 total queries

tracked_companies:
  - name: Anthropic
    careers_url: https://job-boards.greenhouse.io/anthropic
    api: https://boards-api.greenhouse.io/v1/boards/anthropic/jobs
    enabled: true
    
  - name: OpenAI
    careers_url: https://openai.com/careers
    scan_method: websearch
    scan_query: 'site:openai.com/careers "Solutions"'
    enabled: true
    
  - name: ElevenLabs
    careers_url: https://jobs.ashbyhq.com/elevenlabs
    scan_method: websearch
    notes: "Voice AI TTS leader."
    enabled: true
    
  # ... 45+ companies total
```

**Company categories included:**
- AI Labs: Anthropic, OpenAI, Mistral, Cohere, LangChain, Pinecone
- Voice AI: ElevenLabs, PolyAI, Parloa, Hume AI, Deepgram, Vapi, Bland AI
- AI Platforms: Retool, Airtable, Vercel, Temporal, Glean, Arize AI
- Contact Center: Ada, LivePerson, Sierra, Decagon, Talkdesk, Genesys
- Enterprise: Salesforce, Twilio, Gong, Dialpad
- LLMOps: Langfuse, Weights & Biases, Lindy, Cognigy, Speechmatics
- Automation: n8n, Zapier, Make.com
- European: Factorial, Attio, Tinybird, Clarity AI, Travelperk
- DACH: Aleph Alpha, DeepL, Celonis, Contentful, N26, Trade Republic
- UK/Ireland: Wayve, Isomorphic Labs, Synthesia, Faculty
- Nordics: Lovable, Legora, Spotify, Vinted
- France: Hugging Face, Photoroom, Pigment

### Quarry Current State

```python
# companies table
name, domain, careers_url, ats_type, ats_slug, active, crawl_priority

# search_queries table
query_text, site, active, added_by
```

### Adoption Potential: VERY HIGH

**Directly importable:**

| Career-ops | Quarry | Action |
|------------|--------|--------|
| `tracked_companies` (45+ companies) | `companies` table | Import as seed data |
| `api` field | `ats_slug` + `ats_type="greenhouse"` | Already supported |
| `search_queries` (19 queries) | `search_queries` table | Import directly |
| `title_filter.positive` | New table or config | Add |
| `title_filter.negative` | New table or config | Add |

**Needs adaptation:**

1. **`scan_method` and `scan_query`**
   - Career-ops uses for websearch fallback
   - Quarry crawlers are more structured (GreenhouseCrawler, LeverCrawler, etc.)
   - May not need these fields

2. **`title_filter` is global**
   - Career-ops has one filter for all
   - Quarry could make per-user or per-search-query for flexibility

### Recommended Schema Changes

```sql
-- Add title_filters table
CREATE TABLE title_filters (
    id INTEGER PRIMARY KEY,
    filter_type TEXT,  -- 'positive', 'negative', 'seniority_boost'
    keyword TEXT,
    weight REAL DEFAULT 1.0,
    added_by TEXT DEFAULT 'seed',
    active BOOLEAN DEFAULT TRUE
);

CREATE INDEX idx_title_filters_type ON title_filters(filter_type);
```

### Seed Data to Import

**Companies (45+):** See `portals.example.yml` for full list. Key fields:
- name, careers_url, ats_type (greenhouse/ashby/lever/generic)
- ats_slug (for API access)
- notes (context about the company)

**Search queries (19):**
- Ashby: AI PM, Solutions Architect, AI Engineer, Agentic, No-Code & Automation
- Greenhouse: AI PM, SA & FDE, AI Engineer, No-Code & Automation
- Lever: AI PM, AI Roles
- Wellfound: AI PM
- Workable: AI Roles
- Voice AI: FDE & SA, AI Engineer
- Contact Center AI: SA & SE
- FDE specific (cross-portal)
- RemoteFront: AI & Automation
- GTM Engineer: All portals

---

## Other Learnings

### #2: Interview Story Bank

Career-ops accumulates STAR+R stories across evaluations in `interview-prep/story-bank.md`. Over time builds 5-10 master stories adaptable to any behavioral question.

**Adoption:** Add `interview_stories` table to store reusable stories per user.

### #3: Compensation Research

Career-ops does comp research via WebSearch (Glassdoor, Levels.fyi, Blind) as part of evaluation.

**Adoption:** Add `comp_estimate`, `comp_range`, `comp_notes` fields. Populate via LLM reasoning or manual entry.

### #4: Level Strategy

Career-ops evaluates how to position yourself for the role (e.g., "sell senior without lying", "if downleveled, negotiate review at 6 months").

**Adoption:** Add `level_strategy` field with positioning advice.

### #5: Batch Processing

Career-ops uses `claude -p` workers for parallel evaluation of 10+ offers.

**Adoption:** Add batch enrichment mode with parallel workers. Quarry currently processes sequentially.

### #6: Pipeline Integrity Tools

Career-ops has CLI tools:
- `dedup-tracker.mjs` - deduplicate tracker entries
- `merge-tracker.mjs` - merge batch additions
- `normalize-statuses.mjs` - canonicalize status values
- `doctor.mjs` - health checks
- `verify-pipeline.mjs` - integrity verification

**Adoption:** Add similar CLI commands to `quarry.store` module.

### #8: Dashboard/TUI

Career-ops has Go TUI (Bubble Tea) with 6 filter tabs, 4 sort modes, grouped/flat view.

**Adoption:** Consider adding TUI for quick terminal browsing. Quarry has Flask web UI.

### #9: Human-in-the-Loop Emphasis

Career-ops explicitly states "AI evaluates, you decide. The system never submits an application."

**Adoption:** Make workflow clearer in Quarry - AI enriches, user labels, system learns.

### #10: Proof Points / Article Digest

Career-ops has `article-digest.md` for detailed proof points from portfolio.

**Adoption:** Add structured proof points table for better enrichment context. Quarry has `user_profile` string.

---

## Implementation Priority

| Item | Effort | Value | Priority |
|------|--------|-------|----------|
| Company seed data (45+ companies) | Low | High | **P0** |
| Search queries (19 queries) | Low | High | **P0** |
| Title filter table | Low | Medium | **P1** |
| Scoring dimensions (5 fields) | Low | High | **P1** |
| Archetype detection | Medium | High | **P1** |
| 6-block evaluation prompt | Medium | High | **P2** |
| Gap analysis field | Low | Medium | **P2** |
| Level strategy fields | Low | Medium | **P2** |
| Interview prep field | Low | Medium | **P2** |
| Pipeline integrity CLI tools | Medium | Medium | **P3** |
| Interview story bank | Medium | Medium | **P3** |
| Compensation fields | Low | Medium | **P3** |
| Batch processing | High | Medium | **P4** |
| Dashboard TUI | High | Low | **P5** |
| Comp research via WebSearch | High | Medium | **Skip** |

---

## References

- Career-ops repo: https://github.com/santifer/career-ops
- Author's case study: https://santifer.io/career-ops-system
- Key files to reference:
  - `modes/oferta.md` - evaluation prompt template
  - `modes/_shared.md` - scoring system, archetypes, rules
  - `templates/portals.example.yml` - company list, search queries, title filters
  - `CLAUDE.md` - system instructions, data contract, pipeline integrity
