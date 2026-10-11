from flask import (Blueprint, flash, g, jsonify, redirect, render_template, request,
                   session, url_for)

from ..db import get_db
from ..models import (THEMES, annotate_rewards, claim_quest, get_quest,
                      period_key, toggle_subtask,
                      get_reward, goal_for, history_for, list_rewards,
                      quests_for_kid, redeem, redemptions_for, set_kid_goal,
                      set_kid_theme, theme_for)
from ..models import get_user, list_parents
from ..notify import compose, mark_all_read, notify_many, recent
from .helpers import kid_required, local_now

bp = Blueprint("kid", __name__, url_prefix="/me")


@bp.get("/")
@kid_required
def home():
    db = get_db()
    kid = g.user
    now = local_now()
    quests = quests_for_kid(db, kid, now)
    rewards = annotate_rewards(db, list_rewards(db), kid, now)

    goal, chosen = goal_for(db, kid, rewards)
    balance = kid.get("points", 0)

    return render_template(
        "kid/home.html",
        kid=kid,
        quests=quests,
        open_quests=[q for q in quests if q["state"] == "open"],
        goal=goal,
        goal_chosen=chosen,
        goal_reached=bool(goal and balance >= goal["cost"]),
        affordable=[r for r in rewards if r["cost"] <= balance and not r["sold_out"]],
        history=history_for(db, kid["_id"], limit=8),
    )


@bp.get("/shop")
@kid_required
def shop():
    db = get_db()
    return render_template(
        "kid/shop.html",
        kid=g.user,
        rewards=annotate_rewards(db, list_rewards(db), g.user, local_now()),
        goal_id=g.user.get("goal_reward_id"),
        pending=[r for r in redemptions_for(db, g.user["_id"], limit=20)
                 if r["status"] == "pending"],
    )


@bp.post("/shop/<reward_id>/buy")
@kid_required
def buy(reward_id):
    db = get_db()
    reward = get_reward(db, reward_id)
    if not reward or not reward.get("active"):
        flash("That reward isn't available.", "error")
        return redirect(url_for("kid.shop"))

    _, error = redeem(db, g.user, reward, local_now())
    if error:
        flash(error, "error")
    else:
        left = (get_user(db, g.user["_id"]) or {}).get("points", 0)
        notify_many(
            db, list_parents(db), "approval_waiting",
            f"{reward.get('emoji', '')} {g.user['name']} bought {reward['title']}".strip(),
            compose(
                f"Cost: {reward['cost']} points",
                f"{g.user['name']} now has {left} points left",
                reward.get("description"),
                "Hand it over, then mark it Given in Questly.",
            ))
        session["celebrate"] = f"You got {reward['title']}! Ask a grown-up to hand it over."
    return redirect(url_for("kid.shop"))


@bp.post("/quests/<quest_id>/done")
@kid_required
def finish_quest(quest_id):
    db = get_db()
    quest = get_quest(db, quest_id)
    if not quest or not quest.get("active"):
        flash("That quest has gone away.", "error")
        return redirect(url_for("kid.home"))

    assigned = quest.get("assigned_to") or []
    if assigned and g.user["_id"] not in assigned:
        flash("That quest isn't yours.", "error")
        return redirect(url_for("kid.home"))

    _, error = claim_quest(db, quest, g.user, local_now())
    if error:
        flash(error, "warn")
    else:
        notify_many(
            db, list_parents(db), "approval_waiting",
            f"{quest.get('emoji', '')} {g.user['name']} finished {quest['title']}".strip(),
            compose(
                f"Quest: {quest['title']} ({quest.get('repeat', 'daily')})",
                f"Worth {quest['points']} points",
                f"{g.user['name']} has {g.user.get('points', 0)} points right now",
                "Approve it in Questly to pay out.",
            ))
        session["celebrate"] = f"Nice one! {quest['points']} points on the way once it's checked."
    return redirect(url_for("kid.home"))


@bp.post("/goal/<reward_id>")
@kid_required
def set_goal(reward_id):
    """Save up for a particular reward. Posting 'clear' goes back to automatic."""
    db = get_db()
    if reward_id == "clear":
        set_kid_goal(db, g.user["_id"], None)
        flash("Back to showing whatever's closest.", "info")
        return redirect(request.form.get("next") or url_for("kid.shop"))

    reward = get_reward(db, reward_id)
    if not reward or not reward.get("active"):
        flash("That reward isn't available.", "error")
    else:
        set_kid_goal(db, g.user["_id"], reward["_id"])
        flash(f"Saving up for {reward['emoji']} {reward['title']}!", "success")
    return redirect(request.form.get("next") or url_for("kid.shop"))


@bp.get("/theme")
@kid_required
def theme():
    return render_template("kid/theme.html", kid=g.user, themes=THEMES,
                           current=theme_for(g.user)["key"])


@bp.post("/theme")
@kid_required
def choose_theme():
    if set_kid_theme(get_db(), g.user["_id"], request.form.get("theme", "")):
        session["celebrate"] = "Nice pick! Your colours are updated."
    else:
        flash("That's not one of the themes.", "error")
    return redirect(url_for("kid.theme"))


@bp.post("/quests/<quest_id>/step/<subtask_id>")
@kid_required
def tick_step(quest_id, subtask_id):
    """Tick or untick one step of a quest."""
    db = get_db()
    quest = get_quest(db, quest_id)
    is_ajax = (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or (request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html)
    )
    if not quest or not quest.get("active"):
        if is_ajax:
            return jsonify({"ok": False, "error": "That quest has gone away."}), 404
        flash("That quest has gone away.", "error")
        return redirect(url_for("kid.home"))

    assigned = quest.get("assigned_to") or []
    if assigned and g.user["_id"] not in assigned:
        if is_ajax:
            return jsonify({"ok": False, "error": "That quest isn't yours."}), 403
        flash("That quest isn't yours.", "error")
        return redirect(url_for("kid.home"))

    repeat = quest.get("repeat", "daily")
    if repeat in ("weekday", "weekdays") and local_now().weekday() >= 5:
        if is_ajax:
            return jsonify({"ok": False, "error": "This quest is only available on weekdays."}), 400
        flash("This quest is only available on weekdays.", "warn")
        return redirect(url_for("kid.home"))

    key = period_key(repeat, local_now())
    done = toggle_subtask(db, quest, g.user, key, subtask_id)
    subtasks = quest.get("subtasks") or []
    all_done = bool(subtasks and len(done) >= len(subtasks))

    if is_ajax:
        return jsonify({
            "ok": True,
            "quest_id": quest_id,
            "subtask_id": subtask_id,
            "ticked": subtask_id in done,
            "steps_done": len(done),
            "steps_total": len(subtasks),
            "steps_left": max(0, len(subtasks) - len(done)),
            "all_done": all_done,
        })

    if all_done:
        return redirect(url_for("kid.home") + f"#done-{quest['_id']}")
    return redirect(url_for("kid.home") + f"#step-{quest['_id']}-{subtask_id}")


@bp.get("/news")
@kid_required
def news():
    db = get_db()
    items = recent(db, g.user["_id"], limit=50)
    mark_all_read(db, g.user["_id"])
    return render_template("kid/news.html", kid=g.user, items=items)


@bp.get("/stuff")
@kid_required
def stuff():
    db = get_db()
    return render_template(
        "kid/stuff.html",
        kid=g.user,
        history=history_for(db, g.user["_id"], limit=100),
        redemptions=redemptions_for(db, g.user["_id"], limit=50),
    )
