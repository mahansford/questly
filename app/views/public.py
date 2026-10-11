import os

from flask import (Blueprint, current_app, g, jsonify, redirect,
                   render_template, send_from_directory, url_for)

from ..db import get_db
from ..models import has_any_parent, list_kids

bp = Blueprint("public", __name__)


@bp.get("/")
def index():
    db = get_db()
    if not has_any_parent(db):
        return redirect(url_for("auth.setup"))
    if g.user:
        return redirect(url_for("parent.dashboard") if g.user["role"] == "parent"
                        else url_for("kid.home"))
    return redirect(url_for("public.who"))


@bp.get("/who")
def who():
    db = get_db()
    if not has_any_parent(db):
        return redirect(url_for("auth.setup"))
    return render_template("auth/who.html", kids=list_kids(db))


@bp.get("/favicon.ico")
def favicon():
    """Browsers ask for this regardless of the <link> tags; answer it so the
    logs stay clean."""
    return send_from_directory(
        os.path.join(current_app.root_path, "static", "icons"),
        "favicon-32.png",
        mimetype="image/png",
    )


@bp.get("/sw.js")
def service_worker():
    """Serve the PWA service worker from root scope with Service-Worker-Allowed."""
    response = send_from_directory(
        os.path.join(current_app.root_path, "static"),
        "sw.js",
        mimetype="application/javascript",
    )
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


@bp.get("/healthz")
def healthz():
    try:
        get_db().command("ping")
    except Exception as exc:  # pragma: no cover - surfaced to docker healthcheck
        return jsonify(status="degraded", mongo=str(exc)), 503
    return jsonify(status="ok")
