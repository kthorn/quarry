# Configuring Role Matching

How to tune `config.yaml` for effective job filtering, and why each setting works the way it does.

## How Similarity Scoring Works

1. Your `ideal_role_description` is embedded once using `sentence-transformers/all-MiniLM-L6-v2` → a 384-dim vector, L2-normalized
2. Each job posting is embedded by concatenating `title + description + location` through the same model
3. Similarity = cosine similarity between the two vectors (range -1 to 1; in practice 0 to 1 for this use case)
4. Postings below `similarity_threshold` are filtered out

Since both vectors are L2-normalized (`normalize_embeddings=True`), cosine similarity is equivalent to the dot product.

## Writing `ideal_role_description`

The model detects **semantic similarity** — paraphrase-level relatedness, not keyword matching. "People Analytics Lead" and "HR Technology Director" will score as somewhat similar even with no shared words. Conversely, "Director of Facilities" scores low despite sharing "Director" with your target.

### What works

- **Concrete role language** — "Director or VP", "Head of", "building from scratch" strongly pulls the embedding toward senior roles with scope
- **Specific technical terms** — "dbt", "SQL", "Workday", "HRIS" attracts postings containing those tools
- **Redundancy with variation** — repeating core concepts with different phrasings ("building", "leading", "heading up", "creating from scratch") broadens the semantic signal
- **Action-oriented descriptions** — "Defining analytics strategy and building the data infrastructure" embeds more usefully than "interested in analytics strategy"

### What doesn't work

- **Negation** — "not interested in individual contributor roles" embeds *closer* to "individual contributor roles". Put exclusions in `keyword_blocklist` instead
- **Abstract preferences** — "Strong preference for companies doing interesting technical work" is too vague to influence the embedding meaningly. Replace with specifics: "Series B-C SaaS company scaling people analytics"
- **Describing what you want about the role** — "I want a role where I can build" embeds differently than "Role involves building". Use the latter style
- **Long lists of responsibilities you don't want** — every word you add pulls the embedding toward that word's meaning, even with "no" or "not" in front

### Example

```yaml
ideal_role_description: |
  Director or VP of People Analytics at a growth-stage technology company.
  Leading and building the People Analytics function from the ground up.
  Involves defining strategy, building data infrastructure, and developing
  the analytics team. Hands-on with SQL, Python, and modern data stack
  tools like dbt while providing strategic leadership to the organization.
```

## Choosing `similarity_threshold`

This is the minimum cosine similarity for a posting to pass the filter. Lower = more results, higher = fewer.

| Threshold | Behavior |
|-----------|----------|
| 0.20–0.30 | Very permissive. Lots of false positives, but won't miss things |
| 0.35–0.45 | Balanced. Catches reasonably related roles with some noise |
| 0.50–0.60 | Strict. Only close semantic matches pass |
| 0.70+ | Very strict. Near-exact phrasing matches only |

The default is `0.35`. To find the right value for your description:

1. Run `python -m quarry.agent run-once` — this writes a `crawl_log_YYYYMMDD_HHMM.csv` with every posting and its similarity score
2. Open the CSV and sort by `similarity_score` descending
3. Identify the score where relevant roles start dropping off — that's your threshold
4. Update `similarity_threshold` in `config.yaml` and re-run

## Using `keyword_blocklist`

The blocklist is a hard filter applied **before** similarity scoring. Any posting whose title, description, or location contains a blocklisted phrase (case-insensitive substring match) is rejected regardless of similarity score.

This is the right place for things the embedding can't express:

```yaml
keyword_blocklist:
  - intern
  - contract
  - fellowship
  - adjunct
  - part-time
  - volunteer
```

Do **not** put these in `ideal_role_description` — the embedding model doesn't understand negation.

## Crawl Log

Each `run-once` produces a CSV file `crawl_log_YYYYMMDD_HHMM.csv` with every posting encountered:

| Column | Description |
|--------|-------------|
| `title` | Job posting title |
| `source` | Company name (direct crawl) or `"search"` (JobSpy) |
| `url` | Direct link to the posting |
| `location` | Job location |
| `similarity_score` | Cosine similarity to your ideal role (0–1) |
| `status` | `new`, `duplicate`, `duplicate_url`, `blocklist`, or `low_similarity` |

Use this to tune your threshold and blocklist: sort by score to find the cutoff point, and scan low-score postings for blocklist candidates.

---

## All `config.yaml` Parameters

### Core

| Parameter | Default | Description |
|-----------|---------|-------------|
| `db_path` | `./quarry.db` | Path to the SQLite database. Created if it doesn't exist. Can be relative or absolute. |
| `seed_file` | `./seed_data.yaml` | Path to the YAML file loaded by `python -m quarry.agent tools seed`. See `seed_data.yaml` for format. |

### Role targeting

| Parameter | Default | Description |
|-----------|---------|-------------|
| `ideal_role_description` | `""` | **Required.** Free-text description of your target role. Embedded as the reference vector for similarity scoring. See the [guidance above](#writing-ideal_role_description) for how to write this effectively. |
| `similarity_threshold` | `0.35` | Minimum cosine similarity for a posting to pass the filter. See the [threshold guide](#choosing-similarity_threshold). |
| `dedup_window_days` | `90` | How long (in days) before a previously-seen posting with the same title hash + company is treated as new again. Prevents seeing the same reposted job every cycle. |
| `keyword_blocklist` | `[]` | List of phrases that hard-reject a posting (case-insensitive substring match on title + description + location). Applied before similarity scoring. See [using keyword_blocklist](#using-keyword_blocklist). |

### Crawling schedule

| Parameter | Default | Description |
|-----------|---------|-------------|
| `crawl_hour` | `8` | Local hour for the daily JobSpy search. Only used by the scheduler. |
| `crawl_schedule_cron` | `"0 7 * * *"` | Cron expression for JobSpy broad search. Defaults to 7 AM daily. |
| `careers_crawl_cron` | `"0 8 * * 1"` | Cron expression for company watchlist crawls. Defaults to 8 AM every Monday. |
| `reflection_after_crawl` | `true` | Whether the agent runs a reflection cycle after each crawl (proposes search strategy updates based on results). |

### Notifications

| Parameter | Default | Description |
|-----------|---------|-------------|
| `digest_time` | `"08:30"` | Time (HH:MM, local) when the daily digest is generated by the scheduler. |

### LLM provider

| Parameter | Default | Description |
|-----------|---------|-------------|
| `llm_provider` | `"bedrock"` | Which LLM backend to use for enrichment/reflection. `"bedrock"` (AWS) or `"openrouter"`. |
| `aws_region` | `"us-east-1"` | AWS region for Bedrock. Only used when `llm_provider: bedrock`. |
| `aws_profile` | `null` | AWS CLI profile name. If set, used for Bedrock auth. If unset, falls back to default credential chain (env vars, instance profile, etc.). |
| `openrouter_api_key` | `""` | API key for OpenRouter. Only used when `llm_provider: openrouter`. Can also be set via `OPENROUTER_API_KEY` env var. |
| `openrouter_model` | `"anthropic/claude-3-sonnet"` | Model identifier for OpenRouter. See [openrouter.ai/models](https://openrouter.ai/models) for options. |
| `max_reflection_tokens` | `2048` | Max output tokens for the agent's reflection calls. Higher = more detailed strategy suggestions, but slower and more expensive. |

### Embeddings

| Parameter | Default | Description |
|-----------|---------|-------------|
| `embedding_model` | `"all-MiniLM-L6-v2"` | Sentence-transformers model name for local embedding. Downloaded and cached on first use. Common alternatives: `all-mpnet-base-v2` (better quality, slower), `all-MiniLM-L12-v2` (balanced). |
| `embedding_provider` | `"local"` | `"local"` uses sentence-transformers (no API key needed). `"openai"` uses OpenAI embeddings (requires `openai_api_key`). |
| `openai_api_key` | `""` | API key for OpenAI embeddings. Only used when `embedding_provider: openai`. Can also be set via `OPENAI_API_KEY` env var. |

### User profile

| Parameter | Default | Description |
|-----------|---------|-------------|
| `user_profile` | `""` | Free-text description of your background, target roles, and dealbreakers. Used by the LLM enrichment agent (not the embedding filter). This is where you put qualitative preferences the embedding can't capture — "5+ years of management experience required", "must be in healthcare or fintech", "no relocation". |

### Digest

| Parameter | Default | Description |
|-----------|---------|-------------|
| `digest_top_n` | `20` | Maximum number of postings included in the digest. Sorted by similarity score, highest first. |

### JobSpy broad search

| Parameter | Default | Description |
|-----------|---------|-------------|
| `jobspy_sites` | `["indeed", "glassdoor", "google", "zip_recruiter", "linkedin"]` | Which job boards to search. Each activity searches all sites for each search query. Remove sites you don't want. `linkedin` is rate-limited and unreliable without proxies. |
| `jobspy_results_wanted` | `20` | Max results per search query, per site. Total results = `results_wanted × sites × queries`. Higher = more coverage but slower. |
| `jobspy_hours_old` | `168` | Only return postings newer than this many hours. Default is 7 days. Lower values (e.g., `24`) for daily runs; higher (e.g., `720` = 30 days) for first runs. |
| `jobspy_location` | `""` | Location filter. Empty string = no filter. Examples: `"Remote"`, `"San Francisco"`, `"US"`, `"New York, NY"`. |

### Crawler behavior (company watchlist)

These apply to the Greenhouse/Lever/Ashby/generic careers page crawlers, not JobSpy.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_retries` | `3` | Number of retry attempts for failed HTTP requests. Uses exponential backoff starting at `retry_base_delay`. |
| `retry_base_delay` | `2` | Base delay in seconds for exponential backoff. First retry waits `2s`, second `4s`, third `8s`. |
| `max_concurrent_per_host` | `3` | Max simultaneous connections to a single host. Prevents overwhelming small company servers. |
| `request_timeout` | `10` | HTTP request timeout in seconds. Increase for slow career pages (e.g., large Greenhouse boards). |
| `max_response_bytes` | `1048576` | Maximum response body size (1 MB default). Responses larger than this are discarded to avoid memory issues on pages that return huge HTML. |
| `max_redirects` | `5` | Maximum HTTP redirects to follow. Prevents redirect loops. |

### Environment variable overrides

All config values can be overridden with environment variables using the uppercase field name. For example:

```bash
SIMILARITY_THRESHOLD=0.45 python -m quarry.agent run-once
EMBEDDING_MODEL=all-mpnet-base-v2 python -m quarry.agent run-once
```

List values use comma-separated strings:

```bash
JOBSPY_SITES=indeed,google python -m quarry.agent run-once
```

Priority (highest to lowest): **env vars > config.yaml > defaults**.