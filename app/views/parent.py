from flask import (Blueprint, flash, g, jsonify, redirect, render_template,
                   request, url_for)

from ..db import get_db
from ..models import (AVATARS, COLORS, PARENT_AVATARS, REPEAT_CHOICES,
                      STOCK_PERIODS, STOCK_SCOPES, adjust_points, check_password,
                      parse_subtasks,
                      create_kid, create_parent, decide_quest_claim,
                      decide_redemption, get_quest, get_reward, get_user,
                      history_for, list_kids, list_parents, list_quests,
                      list_rewards, oid, pending_claims, pending_redemptions,
                      recent_activity, redemptions_for, set_kid_pin,
                      add_channel, get_channel, remove_channel,
                      update_channel,
                      set_parent_password, stock_label, stock_mode,
                      update_parent)
from ..notify import (CHANNELS, channel_summary, compose, deliver,
                      signal_groups,
                      events_for, mark_all_read, notify, notify_many,
                      recent)
from .helpers import as_int, check_goal_reached, parent_required, safe_next

bp = Blueprint("parent", __name__, url_prefix="/parent")

QUICK_AWARDS = [10, 25, 50, 100]


@bp.get("/")
@parent_required
def dashboard():
    db = get_db()
    kids = list_kids(db)
    return render_template(
        "parent/dashboard.html",
        kids=kids,
        quick=QUICK_AWARDS,
        activity=recent_activity(db, limit=12),
        redemptions=pending_redemptions(db),
        claims=pending_claims(db),
    )


# ---------------------------------------------------------------------------
# points
# ---------------------------------------------------------------------------

@bp.post("/award")
@parent_required
def award():
    db = get_db()
    kid_id = request.form.get("kid_id", "")
    amount = as_int(request.form.get("amount"), default=0, low=-1000, high=1000)
    reason = request.form.get("reason", "").strip()[:120]

    # The "Take away" button reuses the same amount box.
    if request.form.get("negate"):
        amount = -abs(amount)

    if amount == 0:
        flash("Pick an amount first.", "warn")
        return redirect(safe_next(url_for("parent.dashboard")))

    kid, _ = adjust_points(db, kid_id, amount, reason, g.user,
                           kind="award" if amount > 0 else "deduct")
    if not kid:
        flash("Couldn't find that child.", "error")
    else:
        if amount > 0:
            notify(db, kid, "points_awarded", f"⭐ You got {amount} points!",
                   compose(reason and f"For: {reason}",
                           f"From {g.user['name']}",
                           f"You now have {kid.get('points', 0)} points"))
            check_goal_reached(db, kid["_id"])
        verb = "Gave" if amount > 0 else "Took"
        flash(f"{verb} {abs(amount)} points {'to' if amount > 0 else 'from'} {kid['name']}.",
              "success")
    return redirect(safe_next(url_for("parent.dashboard")))


@bp.get("/kid/<kid_id>")
@parent_required
def kid_detail(kid_id):
    db = get_db()
    kid = get_user(db, kid_id)
    if not kid or kid["role"] != "kid":
        flash("Couldn't find that child.", "error")
        return redirect(url_for("parent.dashboard"))
    return render_template(
        "parent/kid_detail.html",
        kid=kid,
        quick=QUICK_AWARDS,
        history=history_for(db, kid["_id"], limit=60),
        redemptions=redemptions_for(db, kid["_id"], limit=20),
        avatars=AVATARS,
    )


# ---------------------------------------------------------------------------
# approvals
# ---------------------------------------------------------------------------

@bp.get("/approvals")
@parent_required
def approvals():
    db = get_db()
    return render_template(
        "parent/approvals.html",
        redemptions=pending_redemptions(db),
        claims=pending_claims(db),
    )


@bp.post("/approvals/redemption/<redemption_id>")
@parent_required
def decide_redemption_route(redemption_id):
    approve = request.form.get("decision") == "approve"
    red = decide_redemption(get_db(), redemption_id, approve, g.user)
    if not red:
        flash("That request was already dealt with.", "warn")
    elif approve:
        notify(get_db(), red["kid_id"], "purchase_approved",
               f"{red['reward_emoji']} {red['reward_title']} is yours!",
               compose(f"{g.user['name']} has handed it over. Enjoy!",
                       f"It cost you {red['cost']} points."))
        flash(f"Marked '{red['reward_title']}' as handed over to {red['kid_name']}.", "success")
    else:
        db = get_db()
        notify(db, red["kid_id"], "purchase_rejected",
               f"{red['reward_title']} wasn't approved",
               f"Your {red['cost']} points have been put back.")
        check_goal_reached(db, red["kid_id"])
        flash(f"Turned down '{red['reward_title']}' — {red['cost']} points refunded.", "info")
    return redirect(safe_next(url_for("parent.approvals")))


@bp.post("/approvals/quest/<claim_id>")
@parent_required
def decide_claim_route(claim_id):
    approve = request.form.get("decision") == "approve"
    claim = decide_quest_claim(get_db(), claim_id, approve, g.user)
    if not claim:
        flash("That request was already dealt with.", "warn")
    elif approve:
        db = get_db()
        notify(db, claim["kid_id"], "quest_approved",
               f"{claim['quest_emoji']} {claim['quest_title']} approved!",
               compose(f"You earned {claim['points']} points.",
                       f"Approved by {g.user['name']}."))
        check_goal_reached(db, claim["kid_id"])
        flash(f"{claim['kid_name']} earned {claim['points']} points for "
              f"'{claim['quest_title']}'.", "success")
    else:
        notify(get_db(), claim["kid_id"], "quest_rejected",
               f"{claim['quest_title']} was sent back",
               "Have another go and mark it done again.")
        flash(f"Sent '{claim['quest_title']}' back to {claim['kid_name']}.", "info")
    return redirect(safe_next(url_for("parent.approvals")))


# ---------------------------------------------------------------------------
# rewards
# ---------------------------------------------------------------------------

def _stock_fields(form, existing=None):
    """Read the stock controls off the reward form into storable fields."""
    mode = form.get("stock_mode")
    if mode not in ("unlimited", "fixed", "periodic"):
        # No explicit mode: infer from whether a plain stock number was sent,
        # so a form without the newer controls still behaves as it used to.
        mode = "fixed" if form.get("stock", "").strip() else "unlimited"

    fields = {"stock_mode": mode, "stock": None,
              "stock_limit": None, "stock_period": None, "stock_scope": None}

    if mode == "fixed":
        default = (existing or {}).get("stock") or 0
        fields["stock"] = as_int(form.get("stock"), default=default, low=0, high=9999)
    elif mode == "periodic":
        fields["stock_limit"] = as_int(form.get("stock_limit"), default=1, low=1, high=999)
        period = form.get("stock_period", "daily")
        fields["stock_period"] = period if period in STOCK_PERIODS else "daily"
        scope = form.get("stock_scope", "child")
        fields["stock_scope"] = scope if scope in STOCK_SCOPES else "child"
    return fields


@bp.get("/rewards")
@parent_required
def rewards():
    db = get_db()
    rewards = [dict(r, stock_text=stock_label(r), mode=stock_mode(r))
               for r in list_rewards(db, active_only=False)]
    return render_template("parent/rewards.html", rewards=rewards,
                           periods=STOCK_PERIODS, scopes=STOCK_SCOPES)


@bp.post("/rewards")
@parent_required
def create_reward():
    db = get_db()
    title = request.form.get("title", "").strip()[:80]
    if not title:
        flash("Give the reward a name.", "error")
        return redirect(url_for("parent.rewards"))

    doc = {
        "title": title,
        "description": request.form.get("description", "").strip()[:240],
        "emoji": (request.form.get("emoji", "").strip() or "\U0001f381")[:4],
        "cost": as_int(request.form.get("cost"), default=10, low=1, high=100000),
        "active": True,
    }
    doc.update(_stock_fields(request.form))
    db.rewards.insert_one(doc)
    notify_many(db, list_kids(db), "shop_new",
                f"{doc['emoji']} New in the shop: {title}",
                compose(f"Costs {doc['cost']} points",
                        doc.get("description"),
                        stock_label(doc) and f"Available: {stock_label(doc)}"))
    flash(f"Added '{title}' to the shop.", "success")
    return redirect(url_for("parent.rewards"))


@bp.post("/rewards/<reward_id>")
@parent_required
def update_reward(reward_id):
    db = get_db()
    reward = get_reward(db, reward_id)
    if not reward:
        flash("Couldn't find that reward.", "error")
        return redirect(url_for("parent.rewards"))

    action = request.form.get("action")
    if action == "toggle":
        db.rewards.update_one({"_id": reward["_id"]},
                              {"$set": {"active": not reward.get("active", True)}})
        flash(f"'{reward['title']}' is now "
              f"{'hidden from' if reward.get('active') else 'back in'} the shop.", "info")
    elif action == "delete":
        db.rewards.delete_one({"_id": reward["_id"]})
        # Don't leave anyone saving up for something that no longer exists.
        db.users.update_many({"goal_reward_id": reward["_id"]},
                             {"$set": {"goal_reward_id": None}})
        flash(f"Removed '{reward['title']}'.", "info")
    else:
        changes = {
            "title": request.form.get("title", reward["title"]).strip()[:80] or reward["title"],
            "description": request.form.get("description", "").strip()[:240],
            "emoji": (request.form.get("emoji", "").strip() or "\U0001f381")[:4],
            "cost": as_int(request.form.get("cost"), default=reward["cost"], low=1, high=100000),
        }
        changes.update(_stock_fields(request.form, reward))
        db.rewards.update_one({"_id": reward["_id"]}, {"$set": changes})
        flash(f"Updated '{reward['title']}'.", "success")
    return redirect(url_for("parent.rewards"))


# ---------------------------------------------------------------------------
# quests
# ---------------------------------------------------------------------------

@bp.get("/quests")
@parent_required
def quests():
    db = get_db()
    return render_template("parent/quests.html",
                           quests=list_quests(db, active_only=False),
                           kids=list_kids(db),
                           repeats=[r for r in REPEAT_CHOICES if r != "weekdays"])


@bp.post("/quests")
@parent_required
def create_quest():
    db = get_db()
    title = request.form.get("title", "").strip()[:80]
    if not title:
        flash("Give the quest a name.", "error")
        return redirect(url_for("parent.quests"))

    repeat = request.form.get("repeat", "daily")
    if repeat == "weekdays":
        repeat = "weekday"
    assigned = [oid(v) for v in request.form.getlist("assigned_to")]
    db.quests.insert_one({
        "title": title,
        "emoji": (request.form.get("emoji", "").strip() or "⭐")[:4],
        "points": as_int(request.form.get("points"), default=5, low=1, high=1000),
        "repeat": repeat if repeat in REPEAT_CHOICES else "daily",
        "times_per_period": as_int(request.form.get("times_per_period"),
                                   default=1, low=1, high=20),
        "description": request.form.get("description", "").strip()[:240],
        "subtasks": parse_subtasks(request.form.get("subtasks", "")),
        "assigned_to": [a for a in assigned if a],
        "active": True,
    })
    flash(f"Added the quest '{title}'.", "success")
    return redirect(url_for("parent.quests"))


@bp.post("/quests/<quest_id>")
@parent_required
def update_quest(quest_id):
    db = get_db()
    quest = get_quest(db, quest_id)
    if not quest:
        flash("Couldn't find that quest.", "error")
        return redirect(url_for("parent.quests"))

    action = request.form.get("action")
    if action == "toggle":
        db.quests.update_one({"_id": quest["_id"]},
                             {"$set": {"active": not quest.get("active", True)}})
        flash(f"'{quest['title']}' is now "
              f"{'paused' if quest.get('active') else 'active'}.", "info")
    elif action == "delete":
        db.quests.delete_one({"_id": quest["_id"]})
        db.quest_claims.delete_many({"quest_id": quest["_id"], "status": "pending"})
        flash(f"Removed '{quest['title']}'.", "info")
    else:
        repeat = request.form.get("repeat", quest.get("repeat", "daily"))
        if repeat == "weekdays":
            repeat = "weekday"
        assigned = [oid(v) for v in request.form.getlist("assigned_to")]
        db.quests.update_one({"_id": quest["_id"]}, {"$set": {
            "title": request.form.get("title", quest["title"]).strip()[:80] or quest["title"],
            "emoji": (request.form.get("emoji", "").strip() or "⭐")[:4],
            "points": as_int(request.form.get("points"), default=quest["points"], low=1, high=1000),
            "repeat": repeat if repeat in REPEAT_CHOICES else "daily",
            "times_per_period": as_int(request.form.get("times_per_period"),
                                       default=quest.get("times_per_period", 1),
                                       low=1, high=20),
            "description": request.form.get("description", "").strip()[:240],
            "subtasks": parse_subtasks(request.form.get("subtasks", ""),
                                       quest.get("subtasks")),
            "assigned_to": [a for a in assigned if a],
        }})
        flash(f"Updated '{quest['title']}'.", "success")
    return redirect(url_for("parent.quests"))


# ---------------------------------------------------------------------------
# family
# ---------------------------------------------------------------------------

@bp.get("/family")
@parent_required
def family():
    db = get_db()
    return render_template("parent/family.html",
                           kids=list_kids(db),
                           parents=list_parents(db),
                           avatars=AVATARS,
                           colors=COLORS,
                           channels=CHANNELS,
                           kid_events=events_for("kid"),
                           summary=channel_summary)


@bp.post("/family/kids")
@parent_required
def add_kid():
    db = get_db()
    name = request.form.get("name", "").strip()[:40]
    if not name:
        flash("What's their name?", "error")
        return redirect(url_for("parent.family"))

    pin = request.form.get("pin", "").strip()
    if pin and not (pin.isdigit() and 4 <= len(pin) <= 6):
        flash("A PIN needs to be 4-6 digits (or leave it blank).", "error")
        return redirect(url_for("parent.family"))

    create_kid(db, name,
               request.form.get("avatar") or AVATARS[0],
               request.form.get("color") or COLORS[0][1],
               pin=pin or None,
               points=as_int(request.form.get("points"), default=0, low=0, high=100000))
    flash(f"{name} is in! They can log in from the front page.", "success")
    return redirect(url_for("parent.family"))


@bp.post("/family/kids/<kid_id>")
@parent_required
def update_kid(kid_id):
    db = get_db()
    kid = get_user(db, kid_id)
    if not kid or kid["role"] != "kid":
        flash("Couldn't find that child.", "error")
        return redirect(url_for("parent.family"))

    action = request.form.get("action")
    if action == "delete":
        db.users.delete_one({"_id": kid["_id"]})
        db.transactions.delete_many({"kid_id": kid["_id"]})
        db.redemptions.delete_many({"kid_id": kid["_id"]})
        db.quest_claims.delete_many({"kid_id": kid["_id"]})
        flash(f"Removed {kid['name']} and their history.", "info")
        return redirect(url_for("parent.family"))

    if action == "pin":
        pin = request.form.get("pin", "").strip()
        if pin and not (pin.isdigit() and 4 <= len(pin) <= 6):
            flash("A PIN needs to be 4-6 digits (or leave it blank for none).", "error")
        else:
            set_kid_pin(db, kid["_id"], pin or None)
            flash(f"{kid['name']}'s PIN {'updated' if pin else 'removed'}.", "success")
        return redirect(url_for("parent.family"))

    db.users.update_one({"_id": kid["_id"]}, {"$set": {
        "name": request.form.get("name", kid["name"]).strip()[:40] or kid["name"],
        "avatar": request.form.get("avatar") or kid.get("avatar"),
        "color": request.form.get("color") or kid.get("color"),
    }})
    flash("Saved.", "success")
    return redirect(url_for("parent.family"))


@bp.post("/family/parents")
@parent_required
def add_parent():
    db = get_db()
    name = request.form.get("name", "").strip()[:40]
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not name or "@" not in email:
        flash("Need a name and a valid email address.", "error")
    elif len(password) < 8:
        flash("Use a password of at least 8 characters.", "error")
    elif db.users.find_one({"email": email}):
        flash("Someone already uses that email.", "error")
    else:
        create_parent(db, name, email, password)
        flash(f"{name} can now log in as a grown-up.", "success")
    return redirect(url_for("parent.family"))


@bp.get("/news")
@parent_required
def news():
    db = get_db()
    items = recent(db, g.user["_id"], limit=50)
    mark_all_read(db, g.user["_id"])
    return render_template("parent/news.html", items=items)


# ---------------------------------------------------------------------------
# notification channels
# ---------------------------------------------------------------------------

def _channel_owner(db, owner_id):
    """A grown-up may manage their own channels and any child's, but not
    another grown-up's — those are personal."""
    if str(owner_id) == str(g.user["_id"]):
        return g.user
    target = get_user(db, owner_id)
    if target and target["role"] == "kid":
        return target
    return None


def _owner_redirect(owner):
    if owner["role"] == "kid":
        return redirect(url_for("parent.family") + f"#kid-{owner['_id']}")
    return redirect(url_for("parent.account"))


@bp.post("/signal/groups")
@parent_required
def lookup_signal_groups():
    """Ask a Signal bridge which groups a number belongs to, so the group id
    can be picked from a list rather than copied by hand."""
    groups, error = signal_groups(request.form.get("api_url", "").strip(),
                                  request.form.get("number", "").strip())
    return jsonify(groups=groups, error=error)


@bp.post("/channels/<owner_id>")
@parent_required
def add_channel_route(owner_id):
    db = get_db()
    owner = _channel_owner(db, owner_id)
    if not owner:
        flash("You can only set up your own channels, or a child's.", "error")
        return redirect(url_for("parent.account"))

    kind = request.form.get("type", "")
    spec = CHANNELS.get(kind)
    if not spec:
        flash("Pick a notification type.", "error")
        return _owner_redirect(owner)

    config, missing = {}, []
    for key, label, _t, required, _ph, _help in spec["fields"]:
        value = request.form.get(f"{kind}__{key}", "").strip()
        if value:
            config[key] = value
        elif required:
            missing.append(label)
    if missing:
        flash(f"{spec['label']} needs: {', '.join(missing)}.", "error")
        return _owner_redirect(owner)

    allowed = set(events_for(owner["role"]))
    events = [e for e in request.form.getlist("events") if e in allowed]

    channel = add_channel(db, owner["_id"], kind, config, events)
    ok, detail = deliver(channel, "Questly is connected",
                         f"Notifications for {owner['name']} will arrive here.")
    if ok:
        flash(f"{spec['label']} connected — a test message is on its way.", "success")
    else:
        flash(f"Saved, but the test message failed: {detail}", "warn")
    return _owner_redirect(owner)


@bp.post("/channels/<owner_id>/<channel_id>/edit")
@parent_required
def edit_channel(owner_id, channel_id):
    db = get_db()
    owner = _channel_owner(db, owner_id)
    channel = get_channel(db, owner_id, channel_id) if owner else None
    if not channel:
        flash("Couldn't find that channel.", "error")
        return redirect(url_for("parent.account"))

    spec = CHANNELS.get(channel["type"], {})
    config = {}
    for key, _label, _t, _req, _ph, _help in spec.get("fields", []):
        config[key] = request.form.get(f"{channel['type']}__{key}", "").strip()

    allowed = set(events_for(owner["role"]))
    events = [e for e in request.form.getlist("events") if e in allowed]
    enabled = bool(request.form.get("enabled"))

    update_channel(db, owner["_id"], channel_id, config, events, enabled)
    flash(f"Updated {owner['name']}'s {spec.get('label', 'channel')}.", "success")
    return _owner_redirect(owner)


@bp.post("/channels/<owner_id>/<channel_id>/test")
@parent_required
def test_channel(owner_id, channel_id):
    db = get_db()
    owner = _channel_owner(db, owner_id)
    channel = get_channel(db, owner_id, channel_id) if owner else None
    if not channel:
        flash("Couldn't find that channel.", "error")
        return redirect(url_for("parent.account"))
    ok, detail = deliver(channel, "Questly test",
                         f"If {owner['name']} can read this, it's working.")
    flash("Test message sent." if ok else f"Test failed: {detail}",
          "success" if ok else "error")
    return _owner_redirect(owner)


@bp.post("/channels/<owner_id>/<channel_id>/delete")
@parent_required
def delete_channel(owner_id, channel_id):
    db = get_db()
    owner = _channel_owner(db, owner_id)
    if not owner:
        flash("Couldn't find that channel.", "error")
        return redirect(url_for("parent.account"))
    remove_channel(db, owner["_id"], channel_id)
    flash("Channel removed.", "info")
    return _owner_redirect(owner)


# ---------------------------------------------------------------------------
# your own account
# ---------------------------------------------------------------------------

@bp.get("/account")
@parent_required
def account():
    return render_template("parent/account.html",
                           me=g.user,
                           avatars=PARENT_AVATARS,
                           channels=CHANNELS,
                           events=events_for("parent"),
                           summary=channel_summary)


@bp.post("/account/profile")
@parent_required
def update_profile():
    ok, error = update_parent(
        get_db(), g.user["_id"],
        name=request.form.get("name", ""),
        email=request.form.get("email", ""),
        avatar=request.form.get("avatar") or None,
    )
    flash(error if error else "Saved.", "error" if error else "success")
    return redirect(url_for("parent.account"))


@bp.post("/account/password")
@parent_required
def change_password():
    db = get_db()
    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")

    if not check_password(g.user, current):
        flash("Your current password wasn't right.", "error")
    elif new != confirm:
        flash("The two new passwords don't match.", "error")
    else:
        ok, error = set_parent_password(db, g.user["_id"], new)
        flash(error if error else "Password changed.",
              "error" if error else "success")
    return redirect(url_for("parent.account"))


@bp.post("/family/parents/<parent_id>/password")
@parent_required
def reset_parent_password(parent_id):
    """Either grown-up can reset the other's password. Confirming with your
    own password stops someone using an unlocked session to take over."""
    db = get_db()
    target = get_user(db, parent_id)

    if not target or target["role"] != "parent":
        flash("Couldn't find that account.", "error")
        return redirect(url_for("parent.family"))
    if target["_id"] == g.user["_id"]:
        return redirect(url_for("parent.account"))

    if not check_password(g.user, request.form.get("your_password", "")):
        flash("Confirm with your own password to reset someone else's.", "error")
        return redirect(url_for("parent.family"))

    ok, error = set_parent_password(db, target["_id"],
                                    request.form.get("new_password", ""))
    if error:
        flash(error, "error")
    else:
        flash(f"Set a new password for {target['name']}. Let them know.", "success")
    return redirect(url_for("parent.family"))


@bp.post("/family/parents/<parent_id>/delete")
@parent_required
def remove_parent(parent_id):
    db = get_db()
    target = get_user(db, parent_id)
    if not target or target["role"] != "parent":
        flash("Couldn't find that account.", "error")
    elif target["_id"] == g.user["_id"]:
        flash("You can't remove your own account while you're using it.", "warn")
    elif db.users.count_documents({"role": "parent"}) <= 1:
        flash("There has to be at least one grown-up account.", "warn")
    else:
        db.users.delete_one({"_id": target["_id"]})
        flash(f"Removed {target['name']}.", "info")
    return redirect(url_for("parent.family"))
