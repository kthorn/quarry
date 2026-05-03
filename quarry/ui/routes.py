from typing import Literal

from flask import Blueprint, current_app, redirect, render_template, request, url_for

from quarry.models import UserLabel
from quarry.store.db import Database

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

    db = get_db()
    per_page = current_app.config["PER_PAGE"]
    offset = (page - 1) * per_page

    results = db.get_postings_with_scores(
        user_id=USER_ID,
        status=status,
        limit=per_page + 1,
        offset=offset,
    )
    has_next = len(results) > per_page
    results = results[:per_page]

    counts = {
        s: db.count_postings_by_watchlist(user_id=USER_ID, status=s)
        for s in VALID_STATUSES
    }

    return render_template(
        "postings.html",
        results=results,
        status=status,
        page=page,
        has_next=has_next,
        counts=counts,
        valid_statuses=VALID_STATUSES,
    )


@bp.route("/label/<int:posting_id>", methods=["POST"])
def label(posting_id):
    status = request.form.get("status", "")
    if status not in VALID_STATUSES:
        return "Invalid status", 400

    db = get_db()
    posting = db.get_posting_by_id(posting_id)
    if posting is None:
        return "Posting not found", 404

    db.update_posting_status(posting_id, status, user_id=USER_ID)

    notes = request.form.get("notes", "").strip()
    signal: Literal["applied", "negative", "skip"] = STATUS_TO_SIGNAL.get(
        status, "skip"
    )  # type: ignore[assignment]
    label = UserLabel(
        user_id=USER_ID,
        posting_id=posting_id,
        signal=signal,
        notes=notes or None,
        label_source="user",
    )
    db.insert_label(label, user_id=USER_ID)

    return_status = request.args.get("return_status", "new")
    return redirect(url_for("ui.postings", status=return_status))


@bp.route("/companies")
def companies():
    db = get_db()
    watchlist = db.get_watchlist(user_id=USER_ID, active_only=False)
    active_items = [w for w in watchlist if w.active]
    inactive_items = [w for w in watchlist if not w.active]

    active = []
    for wi in active_items:
        c = db.get_company(wi.company_id)
        if c:
            active.append(c)
    inactive = []
    for wi in inactive_items:
        c = db.get_company(wi.company_id)
        if c:
            inactive.append(c)

    return render_template("companies.html", active=active, inactive=inactive)


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
