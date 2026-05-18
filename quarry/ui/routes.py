import logging
import threading
from typing import Literal

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from quarry.models import UserWatchlistItem
from quarry.settings_service import UserSettingsService
from quarry.store.db import Database

logger = logging.getLogger(__name__)

bp = Blueprint("ui", __name__, template_folder="templates")

USER_ID = 1  # Single-user mode until auth is added

VALID_STATUSES = ["new", "seen", "applied", "rejected", "archived"]
VALID_INTERESTS = ["all", "interested", "untagged", "not_interested"]
INTEREST_LABELS = {
    "all": "All",
    "interested": "Interested",
    "untagged": "Untagged",
    "not_interested": "Not Interested",
}
STATUS_TO_SIGNAL = {
    "applied": "applied",
    "rejected": "negative",
    "seen": "negative",
    "archived": "skip",
}


def get_db() -> Database:
    return current_app.config["DB"]


@bp.route("/")
def index():
    return redirect(url_for("ui.postings"))


@bp.route("/postings")
def postings():
    status = request.args.get("status", "new")
    if status not in VALID_STATUSES:
        status = "new"
    interest = request.args.get("interest", "all")
    if interest not in VALID_INTERESTS:
        interest = "all"
    page = request.args.get("page", 1, type=int)
    if page < 1:
        page = 1
    q = request.args.get("q", "")

    db = get_db()
    per_page = current_app.config["PER_PAGE"]
    offset = (page - 1) * per_page

    results = db.get_postings_with_scores(
        user_id=USER_ID,
        status=status,
        limit=per_page + 1,
        offset=offset,
        search=q if q else None,
        interest=interest if interest != "all" else None,
    )
    has_next = len(results) > per_page
    results = results[:per_page]

    counts = {
        s: db.count_postings_by_watchlist(
            user_id=USER_ID, status=s, interest=interest if interest != "all" else None
        )
        for s in VALID_STATUSES
    }

    label_count = int(db.get_user_setting(USER_ID, "labels_since_last_train") or "0")

    return render_template(
        "postings.html",
        results=results,
        status=status,
        interest=interest,
        page=page,
        has_next=has_next,
        counts=counts,
        valid_statuses=VALID_STATUSES,
        valid_interests=VALID_INTERESTS,
        interest_labels=INTEREST_LABELS,
        q=q,
        label_count=label_count,
    )


@bp.route("/label/<int:posting_id>", methods=["POST"])
def label(posting_id):
    db = get_db()
    posting = db.get_posting_by_id(posting_id)
    if posting is None:
        return "Posting not found", 404

    status = request.form.get("status", "")
    signal = request.form.get("signal", "")

    # Handle status change (existing behavior)
    if status and status in VALID_STATUSES:
        db.update_posting_status(posting_id, status, user_id=USER_ID)
        # Auto-derive signal from status for backward compat
        notes = request.form.get("notes", "").strip()
        derived_signal: Literal["applied", "negative", "skip"] = STATUS_TO_SIGNAL.get(
            status, "skip"
        )  # type: ignore[assignment]
        label = UserLabel(
            user_id=USER_ID,
            posting_id=posting_id,
            signal=derived_signal,
            notes=notes or None,
            label_source="user",
        )
        db.insert_label(label, user_id=USER_ID)
    elif signal in ("positive", "negative"):
        # Interest-only label (no status change)
        signal_typed: Literal["positive", "negative"] = signal  # type: ignore[assignment]
        label = UserLabel(
            user_id=USER_ID,
            posting_id=posting_id,
            signal=signal_typed,
            label_source="user",
        )
        db.insert_label(label, user_id=USER_ID)
    else:
        return "Invalid status or signal", 400

    return_status = request.args.get("return_status", "new")
    return_q = request.args.get("q", "")
    return_interest = request.args.get("return_interest", "all")
    return redirect(
        url_for(
            "ui.postings",
            status=return_status,
            q=return_q,
            interest=return_interest,
        )
        + f"#posting-{posting_id}"
    )


@bp.route("/retrain", methods=["POST"])
def retrain():
    from quarry.rank.train import train_classifier

    db = get_db()
    return_status = request.form.get("return_status", "new")
    return_q = request.form.get("q", "")
    return_interest = request.form.get("return_interest", "all")

    result = train_classifier(db=db, user_id=USER_ID, min_labels=5)

    if "error" in result:
        flash(result["error"])
    else:
        flash(
            f"Classifier trained on {result['training_samples']} labels "
            f"(AUC: {result['cv_auc_mean']:.2f})."
        )

    return redirect(
        url_for(
            "ui.postings",
            status=return_status,
            q=return_q,
            interest=return_interest,
        )
    )


@bp.route("/scan", methods=["POST"])
def scan():
    from quarry.agent.scheduler import run_once

    db = get_db()
    return_status = request.form.get("return_status", "new")
    return_q = request.form.get("q", "")
    return_interest = request.form.get("return_interest", "all")

    try:
        summary = run_once(db, user_id=USER_ID)
        flash(
            f"Scan complete: {summary.get('total_new', 0)} new, "
            f"{summary.get('total_duplicates', 0)} duplicates, "
            f"{summary.get('total_filtered', 0)} filtered, "
            f"{summary.get('companies_crawled', 0)} companies, "
            f"{summary.get('companies_errored', 0)} errors."
        )
    except Exception as e:
        logger.exception("Scan failed")
        flash(f"Scan failed: {e}")

    return redirect(
        url_for(
            "ui.postings",
            status=return_status,
            q=return_q,
            interest=return_interest,
        )
    )


@bp.route("/companies")
def companies():
    db = get_db()

    # Active companies (watchlist where active=True)
    active = db.get_watchlist_companies(user_id=USER_ID, active=True)

    # Inactive non-search companies (e.g., manually deactivated)
    inactive = [
        c
        for c in db.get_watchlist_companies(user_id=USER_ID, active=False)
        if c.get("added_reason") != "search"
    ]

    # Discovered via search (watchlist where active=False, added_reason="search")
    discovered = db.get_watchlist_companies(
        user_id=USER_ID, active=False, added_reason="search"
    )

    return render_template(
        "companies.html",
        active=active,
        inactive=inactive,
        discovered=discovered,
    )


@bp.route("/companies/<int:company_id>/activate", methods=["POST"])
def activate_company(company_id):
    """Activate a discovered company, resolving it first if needed."""
    db = get_db()
    company = db.get_company(company_id)
    if company is None:
        return "Company not found", 404
    assert company.id is not None

    if company.resolve_status != "resolved":
        from quarry.resolve.pipeline import resolve_company_sync

        company = resolve_company_sync(company, db=db)
    assert company.id is not None

    # Mark watchlist entry as active, preserving existing provenance
    existing_wl = db.get_watchlist_item(user_id=USER_ID, company_id=company.id)
    db.upsert_watchlist_item(
        UserWatchlistItem(
            user_id=USER_ID,  # TODO: replace with auth
            company_id=company.id,
            active=True,
            added_reason=existing_wl.added_reason if existing_wl else "search",
            crawl_priority=existing_wl.crawl_priority if existing_wl else 5,
            notes=existing_wl.notes if existing_wl else None,
        )
    )

    # Defer description generation if missing
    if not company.description:

        def _generate_in_background(cid: int):
            try:
                from quarry.resolve.description import generate_company_description

                c = db.get_company(cid)
                if c and not c.description:
                    desc, source = generate_company_description(c)
                    db.update_company_description(cid, desc, source)
            except Exception:
                db.update_company_description(cid, None, "pending")

        db.update_company_description(company.id, None, "pending")
        threading.Thread(
            target=_generate_in_background,
            args=(company.id,),
            daemon=True,
        ).start()

    return redirect(url_for("ui.companies"))


@bp.route("/companies/<int:company_id>/toggle", methods=["POST"])
def toggle_company(company_id):
    db = get_db()
    watchlist = db.get_watchlist(user_id=USER_ID, active_only=False)
    item = next((w for w in watchlist if w.company_id == company_id), None)
    if item is None:
        return "Company not in watchlist", 404
    item.active = not item.active
    # When a user explicitly deactivates a search-discovered company,
    # change added_reason so the scheduler deny list treats it as
    # user-rejected rather than never-reviewed.
    if not item.active and item.added_reason == "search":
        item.added_reason = "deactivated"
    db.upsert_watchlist_item(item)
    return redirect(url_for("ui.companies"))


@bp.route("/companies/<int:company_id>/description", methods=["POST"])
def update_description(company_id):
    """Update a company's description from the UI."""
    db = get_db()
    company = db.get_company(company_id)
    if company is None:
        return "Company not found", 404

    description = request.form.get("description", "").strip()
    db.update_company_description(company_id, description or None, "manual")
    flash(f"Description updated for {company.name}")
    return redirect(url_for("ui.companies"))


@bp.route("/companies/<int:company_id>/regenerate", methods=["POST"])
def regenerate_description(company_id):
    """Regenerate a company's description from the UI."""
    db = get_db()
    company = db.get_company(company_id)
    if company is None:
        return "Company not found", 404

    try:
        from quarry.resolve.description import generate_company_description

        desc, source = generate_company_description(company)
        db.update_company_description(company_id, desc, source)
        flash(f"Description regenerated for {company.name} ({source})")
    except Exception as e:
        db.update_company_description(company_id, None, "pending")
        flash(f"Description generation failed for {company.name}: {e}")

    return redirect(url_for("ui.companies"))


@bp.route("/settings")
def settings():
    db = get_db()
    ss = UserSettingsService(db, user_id=USER_ID)

    section = request.args.get("section", "search-queries")

    # Load all current values
    search_queries = db.get_all_search_queries(user_id=USER_ID)
    ideal_role = ss.get_ideal_role_description()
    similarity = ss.get_similarity_threshold()
    kw_bl = ss.get_keyword_blocklist()
    title_kw = ss.get_title_keywords()
    location_f = ss.get_location_filter()
    jobspy = ss.get_jobspy_config()

    # Build defaults for empty configs (for template rendering)
    if kw_bl is None:
        from quarry.config import KeywordBlocklistConfig

        kw_bl = KeywordBlocklistConfig()
    if title_kw is None:
        from quarry.config import TitleKeywordConfig

        title_kw = TitleKeywordConfig()
    if location_f is None:
        from quarry.config import LocationFilterConfig

        location_f = LocationFilterConfig()

    # Known job board sites for checkboxes
    from quarry.crawlers.jobspy_client import SITE_NAME_TO_SOURCE_TYPE

    known_sites = list(SITE_NAME_TO_SOURCE_TYPE.keys())

    return render_template(
        "settings.html",
        section=section,
        search_queries=search_queries,
        ideal_role=ideal_role,
        similarity=similarity,
        kw_bl=kw_bl,
        title_kw=title_kw,
        location_f=location_f,
        jobspy=jobspy,
        known_sites=known_sites,
    )


@bp.route("/settings/queries/add", methods=["POST"])
def settings_queries_add():
    db = get_db()
    query_text = request.form.get("query_text", "").strip()
    reason = request.form.get("reason", "").strip() or None

    if not query_text:
        flash("Query text is required.")
        return redirect(url_for("ui.settings", section="search-queries"))

    from quarry.models import UserSearchQuery

    try:
        sq = UserSearchQuery(
            user_id=USER_ID,
            query_text=query_text,
            active=True,
            added_reason=reason,
        )
        db.insert_search_query(sq, user_id=USER_ID)
        flash(f"Added search query: {query_text}")
    except Exception:
        flash("Query already exists.")

    return redirect(url_for("ui.settings", section="search-queries"))


@bp.route("/settings/queries/<int:query_id>/retire", methods=["POST"])
def settings_queries_retire(query_id):
    db = get_db()
    reason = request.form.get("reason", "").strip() or None
    db.deactivate_search_query(query_id, user_id=USER_ID, retired_reason=reason)
    flash("Query retired.")
    return redirect(url_for("ui.settings", section="search-queries"))


@bp.route("/settings/role-description", methods=["POST"])
def settings_role_description():
    db = get_db()
    ss = UserSettingsService(db, user_id=USER_ID)
    text = request.form.get("description", "").strip()

    try:
        ss.set_ideal_role_description(text)
        flash("Ideal role description saved.")
    except Exception as e:
        flash(f"Error saving role description: {e}")

    return redirect(url_for("ui.settings", section="role-description"))


@bp.route("/settings/similarity", methods=["POST"])
def settings_similarity():
    db = get_db()
    ss = UserSettingsService(db, user_id=USER_ID)
    try:
        value = float(request.form.get("threshold", "0.0"))
        value = max(0.0, min(1.0, value))
        ss.set_similarity_threshold(value)
        flash(f"Similarity threshold set to {value:.2f}.")
    except (ValueError, TypeError):
        flash("Invalid threshold value.")

    return redirect(url_for("ui.settings", section="similarity"))


@bp.route("/settings/blocklist", methods=["POST"])
def settings_blocklist():
    db = get_db()
    ss = UserSettingsService(db, user_id=USER_ID)

    keywords_text = request.form.get("keywords", "")
    passlist_text = request.form.get("passlist", "")

    keywords = [k.strip() for k in keywords_text.split("\n") if k.strip()]
    passlist = [p.strip() for p in passlist_text.split("\n") if p.strip()]

    from quarry.config import KeywordBlocklistConfig

    ss.set_keyword_blocklist(
        KeywordBlocklistConfig(keywords=keywords, passlist=passlist)
    )
    flash("Keyword blocklist saved.")
    return redirect(url_for("ui.settings", section="blocklist"))


@bp.route("/settings/title-keywords", methods=["POST"])
def settings_title_keywords():
    db = get_db()
    ss = UserSettingsService(db, user_id=USER_ID)

    text = request.form.get("keywords", "")
    keywords = [k.strip() for k in text.split("\n") if k.strip()]

    from quarry.config import TitleKeywordConfig

    ss.set_title_keywords(TitleKeywordConfig(keywords=keywords))
    flash("Title keywords saved.")
    return redirect(url_for("ui.settings", section="title-keywords"))


@bp.route("/settings/location", methods=["POST"])
def settings_location():
    db = get_db()
    ss = UserSettingsService(db, user_id=USER_ID)

    cities_text = request.form.get("target_location", "")
    accept_remote = request.form.get("accept_remote") == "on"
    nearby_radius_str = request.form.get("nearby_radius", "")
    states_text = request.form.get("accept_states", "")
    regions_text = request.form.get("accept_regions", "")

    cities = [c.strip() for c in cities_text.split("\n") if c.strip()]
    states = [s.strip() for s in states_text.split("\n") if s.strip()]
    regions = [r.strip() for r in regions_text.split("\n") if r.strip()]
    nearby_radius = int(nearby_radius_str) if nearby_radius_str.strip() else None

    from quarry.config import LocationFilterConfig

    ss.set_location_filter(
        LocationFilterConfig(
            target_location=cities,
            accept_remote=accept_remote,
            nearby_radius=nearby_radius,
            accept_states=states,
            accept_regions=regions,
        )
    )
    flash("Location filter saved.")
    return redirect(url_for("ui.settings", section="location"))


@bp.route("/settings/jobspy", methods=["POST"])
def settings_jobspy():
    db = get_db()
    ss = UserSettingsService(db, user_id=USER_ID)

    sites = request.form.getlist("sites")
    try:
        results_wanted = int(request.form.get("results_wanted", "20"))
        hours_old = int(request.form.get("hours_old", "168"))
    except (ValueError, TypeError):
        flash("Invalid number value.")
        return redirect(url_for("ui.settings", section="jobspy"))

    # Validate site names
    from quarry.crawlers.jobspy_client import SITE_NAME_TO_SOURCE_TYPE

    valid_sites = [s for s in sites if s in SITE_NAME_TO_SOURCE_TYPE]

    ss.set_jobspy_config(
        sites=valid_sites, results_wanted=results_wanted, hours_old=hours_old
    )
    flash("Job board settings saved.")
    return redirect(url_for("ui.settings", section="jobspy"))


@bp.route("/log")
def log():
    db = get_db()
    actions = db.get_agent_actions(limit=100)
    return render_template("log.html", actions=actions)
