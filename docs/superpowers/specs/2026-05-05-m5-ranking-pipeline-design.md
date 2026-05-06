# M5: Ranking Pipeline & Agent Tool Loop — Design Spec

> **Date:** 2026-05-05
> **Status:** Refined
> **Goal:** Replace single-dimension similarity scoring with a configurable, per-user ranking pipeline that supports multiple scorers, collects training data via UI labels, and provides a foundation for future agentic optimization.

---

## 1. Problem Statement

The current system scores job postings using only **cosine similarity** between a posting's embedding and the user's `ideal_role_description` embedding. This produces noisy, generic rankings — e.g., a "Machine Learning Scientist, Marketing" role at an AI company scores high on semantic similarity despite being a poor fit. There is no way to:

- Combine multiple signals (similarity + keyword rules + learned preferences + LLM assessment)
- Collect explicit user feedback (labels) to train a personalized classifier
- Experiment interactively with different scoring strategies
- Evolve scoring over time via an agentic loop

This spec addresses the first layer: the **scoring framework** itself. The agentic loop (strategy reflection, tool calls, automatic retraining) builds on top of it and is a follow-up milestone.

---

## 2. Goals

1. **Pluggable scorer framework**: Register and combine multiple scorers (similarity, keyword heuristic, classifier, LLM enrichment)
2. **Per-user configurable pipelines**: Each user has a ranking config stored in the database; scorers can be enabled/disabled and weighted interactively
3. **Label collection via UI**: +/- buttons on each posting to record positive/negative labels
4. **Classifier training**: Logistic regression on posting embeddings, trained on user labels, stored per-user
5. **LLM enrichment**: Optional LLM-based fit assessment with caching
6. **Composite score tracking**: Store per-pipeline composite scores for fast querying and A/B comparison
7. **Multi-user compatible**: All tables and methods accept `user_id`; the schema already supports this

---

## 3. Architecture

### 3.1 Package structure

```
quarry/rank/
├── __init__.py              # public API: run_pipeline, get_default_config
├── config.py                # Pydantic: RankingConfig, StepConfig
├── context.py               # PipelineContext, PipelineResult
├── pipeline.py              # RankingPipeline: orchestrates steps
├── base.py                  # Abstract base classes: Step, RankingFilter, FeatureExtractor, Scorer
├── aggregation.py           # Built-in aggregators (weighted_average, max, etc.)
├── registry.py              # Scorer registry: register(), build_step(), list_registered()
└── scorers/
    ├── __init__.py          # exports all built-in scorers
    ├── similarity.py        # SimilarityScorer: reads user_similarity_scores
    ├── keyword.py           # KeywordHeuristicScorer: configurable keyword rules
    ├── classifier.py        # ClassifierScorer: logistic regression on embeddings
    └── llm.py               # LLMEnrichmentScorer: LLM fit assessment with caching
```

### 3.2 Step types

| Type               | Interface                                       | Purpose                                                       | Example                                     |
| ------------------ | ----------------------------------------------- | ------------------------------------------------------------- | ------------------------------------------- |
| `RankingFilter`    | `check(posting, context) -> bool`               | Hard reject postings                                          | `MinScoreFilter(threshold=0.5)`             |
| `FeatureExtractor` | `extract(posting, context) -> dict[str, float]` | Add computed features to context                              | `KeywordFeatureExtractor`                   |
| `Scorer`           | `score(posting, context) -> float`              | Produce a 0-1 score; reads posting, features, or prior scores | `SimilarityScorer`, `WeightedAverageScorer` |

All steps receive the same `PipelineContext`, which accumulates features and scores as the pipeline progresses. This lets a scorer act as an aggregator by reading `context.scores` (e.g., `WeightedAverageScorer`).

> **Naming note:** The step type is called `RankingFilter` (not `Filter`) to avoid confusion with the existing `FILTER_STEPS` in `quarry/pipeline/filter.py`, which are post-processing hard filters (pass/fail) on raw job postings. Ranking filters operate within the scoring pipeline and are conceptually distinct.

### 3.3 Context object

```python
class PipelineContext(BaseModel):
    features: dict[str, float] = {}
    scores: dict[str, float] = {}
    final_score: float = 0.0
    dropped: bool = False
    drop_reason: str | None = None

    # Injected by the pipeline before execution:
    # db: Database — database handle for scorers that need it
    # user_id: int — current user for per-user lookups
```

> **Note:** `db` and `user_id` are set as instance attributes (not Pydantic fields) on the context object before pipeline execution begins. Scorers access them via `context.db` and `context.user_id`. This avoids threading model-managed resources through the Pydantic validation layer.

### 3.4 Pipeline execution flow

```
For each posting:
  1. Create empty PipelineContext
  2. For each step in config.steps (in order):
     a. If RankingFilter: call check(). If False → context.dropped = True; break
     b. If FeatureExtractor: merge results into context.features
     c. If Scorer: compute score, store in context.scores[step.name]
  3. context.final_score = context.scores[config.final_scorer_name] or 0.0
  4. Return PipelineResult(posting, context)
```

Ranking filters run first, then feature extractors, then scorers. The pipeline **reorders** steps by type regardless of their position in `config.steps`: all RankingFilter steps execute first (in config order), then all FeatureExtractor steps, then all Scorer steps. This guarantees features are always populated before any scorer runs. **If a user's config order differs from the execution order, the pipeline logs a warning listing the reordered steps** to avoid silent surprises. The final score is the output of the designated "final" scorer (typically a composite aggregator).

**Multi-role steps:** A single class can implement multiple interfaces (e.g., `KeywordHeuristicScorer` implements both `FeatureExtractor` and `Scorer`). The pipeline dispatches each role independently based on the step config's `step_type`. If a keyword heuristic should both extract features and produce a score, it appears as **two entries** in `config.steps` — one with `step_type="feature"` and another with `step_type="scorer"` — both referencing the same `name="keyword_heuristic"`. The registry returns the same instance for both, and the pipeline calls the appropriate method on each pass.

---

## 4. Database Schema

### 4.1 New tables

#### `pipeline_configs`

Stores ranking configurations per user. The active config is the one with `is_active = 1` for that user.

| Column        | Type                               | Notes                                                   |
| ------------- | ---------------------------------- | ------------------------------------------------------- |
| `id`          | INTEGER PK                         |                                                         |
| `user_id`     | INTEGER NOT NULL FK → users(id)    | ON DELETE CASCADE                                       |
| `config_hash` | TEXT NOT NULL UNIQUE               | SHA256(config_json)[:16] for dedup                      |
| `config_json` | TEXT NOT NULL                      | Full RankingConfig JSON                                 |
| `description` | TEXT                               | Human-readable name, e.g. "v2: classifier + similarity" |
| `created_at`  | DATETIME DEFAULT CURRENT_TIMESTAMP |                                                         |
| `is_active`   | BOOLEAN DEFAULT 0                  | Exactly one active per user                             |

#### `user_ranking_scores`

Stores composite and component scores per posting, per pipeline config.

| Column               | Type                                       | Notes                                  |
| -------------------- | ------------------------------------------ | -------------------------------------- |
| `id`                 | INTEGER PK                                 |                                        |
| `user_id`            | INTEGER NOT NULL FK → users(id)            | ON DELETE CASCADE                      |
| `posting_id`         | INTEGER NOT NULL FK → job_postings(id)     | ON DELETE CASCADE                      |
| `pipeline_config_id` | INTEGER NOT NULL FK → pipeline_configs(id) | ON DELETE CASCADE                      |
| `composite_score`    | REAL NOT NULL                              | Final aggregated score                 |
| `component_scores`   | TEXT                                       | JSON dict of individual scorer outputs |
| `computed_at`        | DATETIME DEFAULT CURRENT_TIMESTAMP         |                                        |

**Constraints:**

- `UNIQUE(user_id, posting_id, pipeline_config_id)`

**Indexes:**

- `idx_ranking_user_posting` on `(user_id, posting_id)`
- `idx_ranking_config` on `(pipeline_config_id)`
- `idx_ranking_score` on `(user_id, composite_score)`

> **Alembic note:** When using `alembic revision --autogenerate` with custom index names, verify that the generated migration calls `op.create_index('idx_ranking_user_posting', ...)` with the correct names — ensure Alembic is configured to detect named indexes (`target_metadata = Base.metadata` in `alembic/env.py`).

> **Relation to existing score tables:** `user_ranking_scores` stores **pipeline-level** composite scores (aggregated from multiple scorers according to the active config). The existing per-scorer tables (`user_similarity_scores`, `user_classifier_scores`) remain as the individual scorer outputs. The pipeline reads component scores from their respective tables (e.g., `SimilarityScorer` reads from `user_similarity_scores`) and writes the final composite to `user_ranking_scores`. This avoids duplication — the JSON `component_scores` field is a snapshot at compute time for debugging/A/B comparison, while the per-scorer tables remain the canonical source for individual scores.

### 4.2 ORM models

Add `PipelineConfig` and `UserRankingScore` to `quarry/store/models.py`. Alembic migration required.

### 4.3 Pydantic models

```python
class StepConfig(BaseModel):
    step_type: Literal["ranking_filter", "feature", "scorer"]
    name: str                # registry key, e.g. "similarity"
    params: dict[str, Any] = {}
    enabled: bool = True

class RankingConfig(BaseModel):
    id: int | None = None    # PipelineConfig row ID, populated when loaded from DB
    steps: list[StepConfig]
    final_scorer_name: str = "similarity"  # which scorer's output is final_score
```

**`RankingConfig` vs `PipelineConfig`:** The Pydantic `RankingConfig` represents the **inner JSON payload** (the steps and final scorer name). The ORM `PipelineConfig` wraps this with metadata (`id`, `config_hash`, `description`, `is_active`, `created_at`). When loaded from the DB, `RankingConfig.id` is set from `PipelineConfig.id`. The ORM's `config_json` column stores the JSON serialization of `RankingConfig` (excluding `id`, which is an ORM column).

**Config storage and sync strategy:** The `pipeline_configs` table is the **canonical source of truth** for the active ranking config. The `user_settings.ranking_config` key serves as a **draft/working copy** for the UI config editor. The sync flow:

1. User edits config in UI → saved to `user_settings.ranking_config` (draft)
2. User "activates" the draft → inserted as new row in `pipeline_configs` with `is_active=1`; previous active config for user is set to `is_active=0`
3. Pipeline execution reads from `pipeline_configs` (not `user_settings`)
4. Stale detection (§9.3) compares the active `pipeline_configs.config_hash` against `user_settings.ranking_config` hash — if they differ, the UI shows a "scores may be stale" banner because the draft hasn't been re-computed yet
5. **JSON handling:** When reading/writing `user_settings.ranking_config`, serialize `RankingConfig` via `.model_dump_json()` on write and `RankingConfig.model_validate_json()` on read. `get_user_settings_raw()` returns raw strings — a helper method `get_ranking_config_draft(user_id)` handles deserialization.
6. **Draft lifecycle:** The initial draft is created on first UI load (if absent, clone the active config from `pipeline_configs` or use the default). The UI config editor writes changes back to `user_settings.ranking_config` via a new API endpoint. If `user_settings.ranking_config` contains invalid JSON, the `get_ranking_config_draft()` helper catches the `ValidationError` and falls back to the default config with a logged warning.

---

## 5. Scorer Implementations

### 5.1 `SimilarityScorer` (port from existing code)

Reads pre-computed similarity from `user_similarity_scores` table.

```python
@register("similarity")
class SimilarityScorer(Scorer):
    def score(self, posting, context) -> float:
        score = context.db.get_similarity_score(context.user_id, posting.id)
        return score if score is not None else 0.0
```

> **Requires new DB method:** `db.get_similarity_score(user_id, posting_id)` does not exist yet. The existing code only reads similarity scores through the multi-join in `get_postings_with_scores()`. This single-posting lookup method must be added to `quarry/store/db.py` (see §14).

### 5.2 `KeywordHeuristicScorer`

Configurable keyword rules with weights. Produces both features and a score.

```python
@register("keyword_heuristic")
class KeywordHeuristicScorer(FeatureExtractor, Scorer):
    rules: list[dict]  # [{"pattern": "senior", "field": "title", "weight": 2}, ...]

    def extract(self, posting, context):
        features = {}
        for rule in self.rules:
            text = (getattr(posting, rule["field"], "") or "").lower()
            match = rule["pattern"].lower() in text
            features[f"kw_{rule['pattern']}"] = float(match)
        return features

    def score(self, posting, context):
        raw = sum(
            rule.get("weight", 0) * context.features.get(f"kw_{rule['pattern']}", 0)
            for rule in self.rules
        )
        return _normalize_to_01(raw)  # sigmoid or clamp
```

`_normalize_to_01()` is a module-level helper in `quarry/rank/scorers/keyword.py` that applies `1 / (1 + exp(-x))` (sigmoid) to map unbounded keyword scores into [0, 1].

```python
def _normalize_to_01(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))
```

> **Type safety:** For stronger validation at config load time, define a Pydantic `KeywordRule(pattern: str, field: str, weight: float)` model and use `params.rules: list[KeywordRule]` instead of `list[dict]`. This catches missing fields at config-parse time rather than at scorer runtime.

### 5.3 `ClassifierScorer`

Logistic regression on posting embeddings + optional keyword features. Trains on `user_labels` (signal `positive` / `negative`).

```python
@register("classifier")
class ClassifierScorer(Scorer):
    model: LogisticRegression | None = None
    model_version_id: int | None = None
    min_training_labels: int = 10  # from step params

    def fit(self, labels: list[UserLabel], postings: list[JobPosting]):
        """Train on labels. Called by CLI train command."""
        from quarry.pipeline.embedder import deserialize_embedding
        from quarry.pipeline.embedder import get_embedding_dim

        X = []
        y = []
        for label in labels:
            posting = ...  # lookup by label.posting_id
            emb = deserialize_embedding(posting.embedding, dim=get_embedding_dim())
            # Optional: append keyword features
            features = []  # or [context.features[k] for k in feature_keys]
            X.append(np.concatenate([emb, features]))
            y.append(1 if label.signal == "positive" else 0)

        clf = LogisticRegression()
        scores = cross_val_score(clf, X, y, cv=5, scoring="roc_auc")
        clf.fit(X, y)
        # Save model to disk, insert ClassifierVersion row, store model_version_id
        self.model = clf

    def score(self, posting, context) -> float:
        from quarry.pipeline.embedder import deserialize_embedding

        if self.model is None:
            log.warning("Classifier not trained")
            return 0.0
        emb = deserialize_embedding(posting.embedding, dim=get_embedding_dim())
        prob = self.model.predict_proba(emb.reshape(1, -1))[0][1]
        return float(prob)
```

**Cold-start:** Returns `0.0` with a logged warning until `fit()` has been called with `>= min_training_labels`.

### 5.4 `LLMEnrichmentScorer`

Calls LLM to assess posting fit against user profile. Results cached in `user_enriched_postings`.

```python
@register("llm_enrichment")
class LLMEnrichmentScorer(Scorer):
    def score(self, posting, context) -> float:
        enriched = context.db.get_enriched_posting(context.user_id, posting.id)
        if enriched and enriched.fit_score is not None:
            return enriched.fit_score / 10.0  # normalize 0-10 → 0-1

        fit_score, role_tier, fit_reason, key_reqs = self._call_llm(posting)
        context.db.save_enriched_posting(context.user_id, posting.id, fit_score, role_tier, fit_reason, key_reqs)
        return fit_score / 10.0
```

> **Requires new DB methods:** `db.get_enriched_posting(user_id, posting_id)` and `db.save_enriched_posting(...)` do not exist yet. The `user_enriched_postings` ORM table is defined in `quarry/store/models.py` (≈line 484), but has zero CRUD methods in `db.py`. Both must be added (see §14).
>
> **LLM client dependency:** The `_call_llm()` method requires an LLM client (Bedrock or OpenRouter). The `config.yaml` already has `llm_provider`, `openrouter_api_key`, etc. keys. A lightweight LLM client wrapper (≈50 lines) must be built; it is not part of this milestone but is a prerequisite for the `llm_enrichment` scorer to function.
>
> **`key_requirements` serialization:** The Pydantic `EnrichedPosting.key_requirements` is `list[str]` but the ORM stores it as `Text` (JSON string). `save_enriched_posting` must `json.dumps(key_reqs)` on write and `get_enriched_posting` must `json.loads()` on read.
>
> **`fit_score` validation:** The ORM defines `fit_score: Mapped[Optional[int]]` with no CHECK constraint. The scorer divides by 10.0 assuming a 0–10 integer scale. Clamp the result to [0.0, 1.0] after division to handle unexpected LLM outputs.

### 5.5 `WeightedAverageScorer` (composite aggregator)

```python
@register("weighted_average")
class WeightedAverageScorer(Scorer):
    weights: dict[str, float]  # {"similarity": 0.6, "keyword_heuristic": 0.4}

    def score(self, posting, context) -> float:
        total_weight = sum(self.weights.values())
        if total_weight == 0:
            return 0.0
        score = 0.0
        for name in self.weights:
            if name in context.scores:
                score += self.weights[name] * context.scores[name]
            else:
                log.warning(f"Expected scorer '{name}' not in context.scores; using 0.0")
        return score / total_weight
```

> **Missing scorer handling:** If a scorer is skipped due to an exception (§11), its score won't be in `context.scores`. The weighted average warns and treats missing scorers as 0.0 rather than silently computing an incorrect average with fewer components.

### 5.6 `RankingPipeline.load_for_user()` classmethod

Constructs a fully initialized pipeline for a user from the active config:

```python
class RankingPipeline:
    @classmethod
    def load_for_user(cls, db: Database, user_id: int = 1) -> "RankingPipeline":
        """Load the active pipeline config for a user and build all steps from the registry."""
        config = db.get_active_pipeline_config(user_id)
        if config is None:
            config = get_default_config()
        steps = [build_step(step) for step in config.steps if step.enabled]
        pipeline = cls(steps=steps, config=config, db=db, user_id=user_id)
        return pipeline

    def run(self, posting) -> PipelineResult:
        """Execute the pipeline on a single posting."""
        context = PipelineContext()
        context.db = self.db          # Inject DB handle for scorers
        context.user_id = self.user_id  # Inject user_id for scorers

        for step in self.steps:
            if isinstance(step, RankingFilter):
                if not step.check(posting, context):
                    context.dropped = True
                    break
            elif isinstance(step, FeatureExtractor):
                context.features.update(step.extract(posting, context))
            elif isinstance(step, Scorer):
                context.scores[step.name] = step.score(posting, context)

        context.final_score = context.scores.get(self.config.final_scorer_name, 0.0)
        return PipelineResult(posting=posting, context=context)
```

This is the primary entry point used by the scheduler (§9.1) and CLI `recompute` command (§8).

---

## 6. Default Ranking Config

```json
{
  "steps": [
    {
      "step_type": "scorer",
      "name": "similarity",
      "params": {},
      "enabled": true
    }
  ],
  "final_scorer_name": "similarity"
}
```

All other scorers available via registry but disabled by default. User enables them through UI/CLI. This avoids broken/inoperative scorers until they are properly configured or trained.

---

## 7. UI Changes — Label Collection

### 7.1 Postings list page (`/postings`)

Each posting card gets two small buttons, **in addition to** the existing Applied/Pass/Archive buttons:

- **👍 Interested** — records `signal="positive"` in `user_labels`
- **👎 Not Interested** — records `signal="negative"` in `user_labels`

If already labeled, show the current label with option to change.

### 7.2 API endpoint (modify existing)

An endpoint at `/label/<int:posting_id>` already exists in `quarry/ui/routes.py:79`. Extend it to also accept a `signal` parameter for interest labeling, keeping the existing `status` parameter for status changes:

```python
@bp.route("/label/<int:posting_id>", methods=["POST"])
def label(posting_id: int):
    # Existing: status update (applied / rejected / archived)
    status = request.form.get("status", "")
    if status:
        # ... existing status handling ...

    # New: interest label (positive / negative)
    signal = request.form.get("signal", "")
    if signal in ("positive", "negative"):
        label = UserLabel(
            user_id=USER_ID, posting_id=posting_id,
            signal=signal, label_source="user"
        )
        db.insert_label(label, user_id=USER_ID)

    return redirect(request.referrer or url_for("ui.postings"))
```

### 7.3 Label display

- Show label badge on each posting ("✓ Interested" / "✗ Not Interested")
- Add filter tab: "labeled" to see all labeled postings
- Labels are visible in the labels table for review/undo

---

## 8. CLI Commands

New module: `python -m quarry.rank` (entry point: `quarry/rank/__main__.py`, following the codebase convention where all `python -m quarry.X` subcommands use `__main__.py`, not `cli.py`)

| Command                     | Purpose                                                                                                   |
| --------------------------- | --------------------------------------------------------------------------------------------------------- |
| `list-scorers`              | Show all registered scorers and their enabled status                                                      |
| `config get`                | Print current ranking config                                                                              |
| `config set --json '{...}'` | Update ranking config                                                                                     |
| `train`                     | Train classifier on current labels. Saves model, inserts ClassifierVersion, writes user_classifier_scores |
| `evaluate`                  | Cross-validation report (accuracy, precision, recall, ROC-AUC)                                            |
| `recompute`                 | Re-run pipeline on all postings for current config, write user_ranking_scores                             |

---

## 9. Integration Points

### 9.1 Scheduler (`quarry/agent/scheduler.py`)

After crawl completes, run the ranking pipeline on all new postings:

```python
from quarry.rank.pipeline import RankingPipeline

pipeline = RankingPipeline.load_for_user(db, user_id=1)
for posting in new_postings:
    result = pipeline.run(posting)
    db.upsert_ranking_score(
        user_id=1,
        posting_id=posting.id,
        pipeline_config_id=pipeline.config.id,
        composite_score=result.context.final_score,
        component_scores=result.context.scores,
    )
```

### 9.2 Digest (`quarry/digest/digest.py`)

`build_digest()` joins on `user_ranking_scores` for the active pipeline config, falling back to `user_similarity_scores` if no ranking score exists.

> **Test dependency:** `tests/test_digest.py` is currently skipped (`pytestmark = pytest.mark.skip`) and uses an obsolete `JobPosting(similarity_score=...)` constructor from before the multi-user refactor. This test file must be unskipped and rewritten to use the current `JobPosting` model and ranking scores before digest changes can be verified.

### 9.3 UI queries (`quarry/store/db.py`)

`get_postings_with_scores()` updated to:

1. Find active `pipeline_config_id` for user
2. LEFT JOIN `user_ranking_scores` on `(user_id, posting_id, pipeline_config_id)`
3. Fall back to `user_similarity_scores` if no ranking score
4. Order by `composite_score DESC`

Show "scores may be stale" banner when `pipeline_configs.config_hash` differs from the user's current `user_settings.ranking_config` hash.

> **Complexity note:** The current `get_postings_with_scores()` already LEFT JOINs 4 tables (`user_posting_status`, `user_similarity_scores`, `user_classifier_scores`, `user_enriched_postings`). Adding a 5th JOIN for `user_ranking_scores` with config-hash-based fallback logic makes this a non-trivial refactoring. The staleness check also requires cross-referencing two tables (`pipeline_configs` and `user_settings`). Consider extracting ranking score resolution into a helper method rather than inlining in the main query.

---

## 10. Training Lifecycle & Cold-Start

### 10.1 Lifecycle

```
1. User labels N postings via UI (+/- buttons)
2. CLI `quarry rank train` or automatic trigger when labels >= threshold
3. Fetch positive + negative labels from user_labels
4. Fetch embeddings for labeled postings from job_postings.embedding
5. Train LogisticRegression with 5-fold cross-val
6. Save model to `quarry/models/classifier_<user_id>_v<N>.pkl`; insert ClassifierVersion with cv_auc, cv_accuracy, etc.
7. Mark new version active, compute classifier scores for all postings
8. Log to agent_actions
```

> **Model persistence:** Models are saved as pickle files in `quarry/models/` (create the directory if missing). File naming: `classifier_<user_id>_v<version_id>.pkl`. The `ClassifierVersion.model_path` column stores the relative path. Old model files are not automatically deleted — cleanup is deferred to a future housekeeping task.

### 10.2 Cold-start behavior

| Labels | Action                                               |
| ------ | ---------------------------------------------------- |
| 0      | Return 0.0, log warning                              |
| 1–9    | Return 0.0, log "insufficient labels for training"   |
| 10–19  | Train but warn if < min_training_labels (default 20) |
| 20+    | Normal training                                      |

### 10.3 Retraining trigger

- Config `retrain_label_threshold: int = 20` (stored in `user_settings`)
- **Tracking mechanism:** A `labels_since_last_train` counter is maintained in `user_settings`. It is incremented in `db.insert_label()` whenever a new label with `signal IN ('positive', 'negative')` is inserted. The `insert_label()` method is extended to: (a) increment the counter, (b) check against the threshold, (c) set `retrain_pending = true` in `user_settings` if threshold is reached.
- **Scheduler hook:** `run_once()` in `quarry/agent/scheduler.py` already has distinct phases (search, resolve, crawl). A new phase is added after crawl: check `retrain_pending` for each active user; if true, **import and call the train function directly** (e.g., `from quarry.rank.pipeline import train_classifier` — matching the existing scheduler pattern which uses direct Python imports, never subprocess calls) and clear the flag. The scheduler does not need a separate timer — this runs inline during the normal crawl cycle. **Exception isolation:** The training phase is wrapped in its own try/except so a failed `LogisticRegression.fit()` does not crash the crawl cycle or prevent score computation for other postings.
- **Atomicity:** The `insert_label()` extension (label insert + counter increment + `retrain_pending` flag) runs inside a single `session_scope()` block, ensuring all three operations commit or rollback atomically. Do NOT open nested `session_scope()` blocks, which would deadlock under SQLite's single-writer model.
- **Default values:** `labels_since_last_train` defaults to `"0"` and `retrain_pending` defaults to `"false"` (stored as strings in `user_settings.value`, which is `Text`). If either key is absent (legacy users), `insert_label()` treats them as `"0"` / `"false"`. A migration seeds these keys for existing users.
- **Counter reset:** The `train` CLI command resets `labels_since_last_train` to 0 after successful training.

---

## 11. Error Handling

| Scenario                           | Behavior                                                                                  |
| ---------------------------------- | ----------------------------------------------------------------------------------------- |
| Scorer raises exception            | Pipeline catches, logs error, skips that scorer's score, continues with remaining scorers |
| Classifier not trained             | Returns 0.0, logs warning                                                                 |
| LLM API error                      | Returns 0.0, logs error, does not cache failure                                           |
| Invalid ranking config JSON        | Pydantic validation error on load; fallback to default config                             |
| No active pipeline config          | Fallback to similarity scorer only (backward compatible)                                  |
| Config hash mismatch at query time | UI shows stale scores banner; query falls back to similarity                              |
| Missing embedding for posting      | Scorer returns 0.0, logs warning                                                          |

---

## 12. Testing Strategy

| Component                | Test approach                                                                                   |
| ------------------------ | ----------------------------------------------------------------------------------------------- |
| Scorer registry          | Test `register`, `build_step`, `list_registered()` roundtrip                                    |
| Pipeline execution       | Mock scorers, test ordering, filter early-exit, context accumulation                            |
| KeywordHeuristicScorer   | Parametrized: pattern match in title/description, weight calculation, normalization to 0-1      |
| ClassifierScorer         | Mock `LogisticRegression`, test `fit()` → `score()` roundtrip. Test cold-start (0 labels → 0.0) |
| LLMEnrichmentScorer      | Mock LLM client, test caching (second call returns cached score without LLM call)               |
| Config serialization     | Round-trip: `RankingConfig` → JSON → `RankingConfig`                                            |
| DB integration           | Test `upsert_ranking_score`, `get_postings_with_scores` with pipeline_config join               |
| UI labeling              | Flask test client: POST `/label/<id>`, verify `user_labels` row                                 |
| Pipeline stale detection | Change config, verify old scores are ignored, fallback to similarity                            |

All tests use in-memory SQLite via existing test fixtures. No live LLM calls or sentence-transformers inference in unit tests.

---

## 13. Deferred Features

These are acknowledged in the architecture but not implemented in this milestone:

| Feature                          | Rationale                                                                                                                                                                                                                        |
| -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Swappable embedding model**    | Embedding model is currently system-wide (`config.yaml`). Making it a pipeline component requires caching multiple embeddings per posting (different dimensions per model). Deferred until we want to A/B test embedding models. |
| **Agent tool loop**              | The agentic reflection loop (strategy adaptation, automatic retraining, adding/removing companies/queries) is the next milestone. This spec provides the foundation it needs.                                                    |
| **Real-time pipeline execution** | Pipeline runs batch-style after crawl. Deferred: per-posting pipeline on demand for single-posting scoring.                                                                                                                      |
| **Cross-validation UI**          | Visual comparison of two pipeline configs. Deferred: can compare via SQL queries for now.                                                                                                                                        |

---

## 14. Files to Create / Modify

### New files

- `quarry/rank/__init__.py`
- `quarry/rank/config.py`
- `quarry/rank/context.py`
- `quarry/rank/pipeline.py`
- `quarry/rank/base.py`
- `quarry/rank/registry.py`
- `quarry/rank/aggregation.py`
- `quarry/rank/scorers/__init__.py`
- `quarry/rank/scorers/similarity.py`
- `quarry/rank/scorers/keyword.py`
- `quarry/rank/scorers/classifier.py`
- `quarry/rank/scorers/llm.py`
- `quarry/rank/__main__.py` — CLI entry point (NOT `cli.py`) following codebase convention
- `tests/test_rank_pipeline.py`
- `tests/test_rank_scorers.py`
- `tests/test_rank_classifier.py`

### Modified files

- `quarry/store/models.py` — add `PipelineConfig`, `UserRankingScore` ORM classes
- `quarry/store/db.py` — add these new methods:
  - `get_similarity_score(user_id, posting_id)` — single-posting similarity lookup (for `SimilarityScorer`)
  - `get_enriched_posting(user_id, posting_id)` — single-posting enrichment lookup (for `LLMEnrichmentScorer`)
  - `save_enriched_posting(user_id, posting_id, fit_score, role_tier, fit_reason, key_reqs)` — write enrichment result (for `LLMEnrichmentScorer`)
  - `get_labels_for_user(user_id)` — fetch all `UserLabel` rows with posting embeddings via a single JOIN query (avoid N+1 per-label posting lookups in `ClassifierScorer.fit()`). Query shape:
    ```python
    select(ORMLabel, ORMPosting.embedding)
        .join(ORMPosting, ORMLabel.posting_id == ORMPosting.id)
        .where(ORMLabel.user_id == user_id, ORMLabel.signal.in_(['positive', 'negative']))
    ```
  - `upsert_ranking_score(user_id, posting_id, pipeline_config_id, composite_score, component_scores)`
  - `get_active_pipeline_config(user_id)` — return active `RankingConfig` for user
  - Update `get_postings_with_scores()` to join `user_ranking_scores` with config-hash fallback
  - Extend `insert_label()` to increment `labels_since_last_train` counter and set `retrain_pending` flag
- `quarry/agent/scheduler.py` — call ranking pipeline after crawl; add retraining phase
- `quarry/digest/digest.py` — use ranking scores instead of raw similarity
- `quarry/ui/routes.py` — extend existing `/label/<id>` endpoint to also accept `signal` param
- `quarry/ui/templates/postings.html` — add Interested/Not Interested buttons
- `alembic/versions/` — new migration for pipeline_configs + user_ranking_scores (auto-generated via `alembic revision --autogenerate -m "add_ranking_pipeline"`; `revises = "4596e16062f9"`)

---

## 15. Verification Checklist

After implementation:

- [ ] `python -m pytest tests/test_rank_*.py -v` — all tests pass
- [ ] `python -m pytest tests/ -q` — no regressions (433+ tests as of 2026-05-05)
- [ ] `ruff check .` — clean
- [ ] `pyright quarry/` — clean
- [ ] `alembic upgrade head` — migration applies cleanly
- [ ] `python -m quarry.agent run-once` — pipeline runs, stores ranking scores
- [ ] `python -m quarry.rank list-scorers` — shows registered scorers
- [ ] `python -m quarry.rank config get` — shows default config (similarity only)
- [ ] UI: +/- buttons appear on postings, labels persist in DB
- [ ] `python -m quarry.rank train` — trains classifier on labels, stores scores
- [ ] Digest reads composite scores and sorts correctly
