import logging
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

from quarry.models import UserLabel, UserWatchlistItem
from quarry.store.db import Database

logger = logging.getLogger(__name__)

bp = Blueprint("ui", __name__, template_folder="templates")

USER_ID = 1  # Single-user mode until auth is added

VALID_STATUSES = ["new", "seen", "applied", "rejected", "archived"]
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
    )
    has_next = len(results) > per_page
    results = results[:per_page]

    counts = {
        s: db.count_postings_by_watchlist(user_id=USER_ID, status=s)
        for s in VALID_STATUSES
    }

    label_count = int(db.get_user_setting(USER_ID, "labels_since_last_train") or "0")

    return render_template(
        "postings.html",
        results=results,
        status=status,
        page=page,
        has_next=has_next,
        counts=counts,
        valid_statuses=VALID_STATUSES,
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
    return redirect(url_for("ui.postings", status=return_status, q=return_q))


@bp.route("/retrain", methods=["POST"])
def retrain():
    from quarry.rank.train import train_classifier

    db = get_db()
    return_status = request.form.get("return_status", "new")
    return_q = request.form.get("q", "")

    result = train_classifier(db=db, user_id=USER_ID, min_labels=5)

    if "error" in result:
        flash(result["error"])
    else:
        flash(
            f"Classifier trained on {result['training_samples']} labels "
            f"(AUC: {result['cv_auc_mean']:.2f})."
        )

    return redirect(url_for("ui.postings", status=return_status, q=return_q))


@bp.route("/scan", methods=["POST"])
def scan():
    from quarry.agent.scheduler import run_once

    db = get_db()
    return_status = request.form.get("return_status", "new")
    return_q = request.form.get("q", "")

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

    return redirect(url_for("ui.postings", status=return_status, q=return_q))


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
    return redirect(url_for("ui.companies"))


@bp.route("/companies/<int:company_id>/toggle", methods=["POST"])
def toggle_company(company_id):
    db = get_db()
    watchlist = db.get_watchlist(user_id=USER_ID, active_only=False)
    item = next((w for w in watchlist if w.company_id == company_id), None)
    if item is None:
        return "Company not in watchlist", 404
    item.active = not item.active
    db.upsert_watchlist_item(item)
    return redirect(url_for("ui.companies"))


@bp.route("/log")
def log():
    db = get_db()
    actions = db.get_agent_actions(limit=100)
    return render_template("log.html", actions=actions)
