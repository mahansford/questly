"""Domain operations. Everything that touches points goes through here so the
ledger in `transactions` always matches the cached balance on the kid's doc."""

from datetime import datetime, timedelta, timezone

from bson import ObjectId
from bson.errors import InvalidId
from werkzeug.security import check_password_hash, generate_password_hash

AVATARS = [
    "\U0001f98a", "\U0001f43c", "\U0001f984", "\U0001f42f", "\U0001f438",
    "\U0001f419", "\U0001f996", "\U0001f428", "\U0001f989", "\U0001f41d",
    "\U0001f42c", "\U0001f981", "\U0001f427", "\U0001f430", "\U0001f435",
    "\U0001f994", "\U0001f43b", "\U0001f414", "\U0001f420", "\U0001f9a9",
]

PARENT_AVATARS = [
    "\U0001f9d1", "\U0001f469", "\U0001f468", "\U0001f9d4", "\U0001f475",
    "\U0001f474", "\U0001f478", "\U0001f934", "\U0001f977", "\U0001f9b8",
    "\U0001f9d9", "\U0001f9da", "\U0001f43b", "\U0001f98a", "\U0001f981",
    "\U0001f989", "\U0001f43a", "\U0001f428", "\U0001f996", "\U0001f419",
]

COLORS = [
    ("grape", "#7c4dff"),
    ("bubblegum", "#ff4d94"),
    ("mint", "#12d6a0"),
    ("sky", "#28c8f5"),
    ("sunshine", "#ffb300"),
    ("tangerine", "#ff7043"),
    ("berry", "#e040fb"),
    ("lime", "#8bc34a"),
]

REPEAT_CHOICES = ["daily", "weekday", "weekdays", "weekly", "once"]

STOCK_PERIODS = ["daily", "weekly", "monthly"]
STOCK_SCOPES = ["child", "family"]

# Each theme sets the accent colour a child sees everywhere, plus the three
# background blobs. `accent` is mirrored onto the child's `color` field so the
# grown-up views keep identifying them the same way.
THEMES = [
    {"key": "grape",      "label": "Grape",      "emoji": "\U0001f347",
     "accent": "#7c4dff", "blobs": ("#c9b6ff", "#ffc2dd", "#b9f3e4")},
    {"key": "bubblegum",  "label": "Bubblegum",  "emoji": "\U0001f36c",
     "accent": "#ff4d94", "blobs": ("#ffc2dd", "#ffe0b3", "#e6c9ff")},
    {"key": "ocean",      "label": "Ocean",      "emoji": "\U0001f30a",
     "accent": "#0ea5e9", "blobs": ("#a5e8ff", "#b6d8ff", "#bff5e6")},
    {"key": "jungle",     "label": "Jungle",     "emoji": "\U0001f334",
     "accent": "#12b76a", "blobs": ("#bdf0cf", "#e2f5a9", "#a8e6f0")},
    {"key": "sunset",     "label": "Sunset",     "emoji": "\U0001f305",
     "accent": "#f97316", "blobs": ("#ffd6a5", "#ffb3c6", "#ffe9b0")},
    {"key": "space",      "label": "Space",      "emoji": "\U0001f680",
     "accent": "#6366f1", "blobs": ("#c7c9ff", "#d9c2ff", "#a9c7ff")},
    {"key": "dino",       "label": "Dino",       "emoji": "\U0001f996",
     "accent": "#65a30d", "blobs": ("#d9f0a3", "#c7ecc0", "#f2e8a0")},
    {"key": "unicorn",    "label": "Unicorn",    "emoji": "\U0001f984",
     "accent": "#d946ef", "blobs": ("#f5c2ff", "#c2e0ff", "#ffe0f0")},
]

THEMES_BY_KEY = {t["key"]: t for t in THEMES}
DEFAULT_THEME = "grape"


def theme_for(user):
    """The theme a child has chosen, falling back to the default."""
    return THEMES_BY_KEY.get((user or {}).get("theme"), THEMES_BY_KEY[DEFAULT_THEME])


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def now():
    return datetime.now(timezone.utc)


def oid(value):
    """Coerce to ObjectId, or None when the value isn't a valid id."""
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError):
        return None


def period_key(repeat, local_now):
    """Which bucket a claim or purchase falls into, in the family's local time."""
    if repeat in ("daily", "weekday", "weekdays"):
        return local_now.strftime("%Y-%m-%d")
    if repeat == "weekly":
        year, week, _ = local_now.isocalendar()
        return f"{year}-W{week:02d}"
    if repeat == "monthly":
        return local_now.strftime("%Y-%m")
    return "once"


def period_started(period, local_now):
    """The moment the current period began, as an aware UTC datetime."""
    if period in ("daily", "weekday", "weekdays"):
        start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "weekly":
        start = (local_now - timedelta(days=local_now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0)
    elif period == "monthly":
        start = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        return None
    return start.astimezone(timezone.utc)


# --------------------------------------------------------------------------
# users
# --------------------------------------------------------------------------

def get_user(db, user_id):
    _id = oid(user_id)
    return db.users.find_one({"_id": _id}) if _id else None


def list_kids(db):
    return list(db.users.find({"role": "kid"}).sort("name", 1))


def list_parents(db):
    return list(db.users.find({"role": "parent"}).sort("name", 1))


def has_any_parent(db):
    return db.users.count_documents({"role": "parent"}, limit=1) > 0


def create_parent(db, name, email, password):
    doc = {
        "role": "parent",
        "name": name.strip(),
        "email": email.strip().lower(),
        "password_hash": generate_password_hash(password),
        "avatar": "\U0001f9d1",
        "created_at": now(),
    }
    return db.users.insert_one(doc).inserted_id


def create_kid(db, name, avatar, color, pin=None, points=0):
    doc = {
        "role": "kid",
        "name": name.strip(),
        "avatar": avatar or AVATARS[0],
        "color": color or COLORS[0][1],
        "pin_hash": generate_password_hash(pin) if pin else None,
        "points": int(points),
        "lifetime_points": int(points),
        "created_at": now(),
    }
    return db.users.insert_one(doc).inserted_id


def verify_parent(db, email, password):
    user = db.users.find_one({"role": "parent", "email": email.strip().lower()})
    if user and check_password_hash(user["password_hash"], password):
        return user
    return None


def verify_kid_pin(kid, pin):
    if not kid.get("pin_hash"):
        return True  # no PIN set: tap the avatar and you're in
    return bool(pin) and check_password_hash(kid["pin_hash"], pin)


def check_password(user, password):
    """Is this the user's current password?"""
    if not user or not user.get("password_hash"):
        return False
    return check_password_hash(user["password_hash"], password)


def update_parent(db, parent_id, name=None, email=None, avatar=None):
    """Update a grown-up's profile. Returns (ok, error_message)."""
    _id = oid(parent_id)
    if not _id:
        return False, "Couldn't find that account."

    changes = {}

    if name is not None:
        name = name.strip()[:40]
        if not name:
            return False, "A name can't be blank."
        changes["name"] = name

    if email is not None:
        email = email.strip().lower()
        if "@" not in email or len(email) < 5:
            return False, "That doesn't look like an email address."
        clash = db.users.find_one({"email": email, "_id": {"$ne": _id}})
        if clash:
            return False, "Another account already uses that email."
        changes["email"] = email

    if avatar:
        changes["avatar"] = avatar[:8]

    if not changes:
        return False, "Nothing to change."

    result = db.users.update_one({"_id": _id, "role": "parent"}, {"$set": changes})
    if not result.matched_count:
        return False, "Couldn't find that account."
    return True, None


def set_parent_password(db, parent_id, password):
    """Returns (ok, error_message)."""
    _id = oid(parent_id)
    if not _id:
        return False, "Couldn't find that account."
    if len(password or "") < 8:
        return False, "Use a password of at least 8 characters."
    result = db.users.update_one(
        {"_id": _id, "role": "parent"},
        {"$set": {"password_hash": generate_password_hash(password)}},
    )
    if not result.matched_count:
        return False, "Couldn't find that account."
    return True, None


def add_channel(db, user_id, channel_type, config, events=None):
    """Attach a delivery channel to someone. Returns the new channel's id."""
    import uuid
    channel = {
        "id": uuid.uuid4().hex[:12],
        "type": channel_type,
        "config": config,
        "events": events or [],
        "enabled": True,
        "created_at": now(),
    }
    db.users.update_one({"_id": oid(user_id)}, {"$push": {"channels": channel}})
    return channel


def update_channel(db, user_id, channel_id, config, events, enabled=True):
    """Change a channel in place. Blank values keep whatever was there, so a
    secret can stay hidden in the form and still survive an edit."""
    existing = get_channel(db, user_id, channel_id)
    if not existing:
        return False
    merged = dict(existing.get("config", {}))
    merged.update({k: v for k, v in config.items() if v})
    db.users.update_one(
        {"_id": oid(user_id), "channels.id": channel_id},
        {"$set": {"channels.$.config": merged,
                  "channels.$.events": events or [],
                  "channels.$.enabled": bool(enabled)}},
    )
    return True


def remove_channel(db, user_id, channel_id):
    db.users.update_one({"_id": oid(user_id)},
                        {"$pull": {"channels": {"id": channel_id}}})


def get_channel(db, user_id, channel_id):
    user = db.users.find_one({"_id": oid(user_id)}, {"channels": 1})
    for c in (user or {}).get("channels", []):
        if c.get("id") == channel_id:
            return c
    return None


def set_kid_theme(db, kid_id, theme_key):
    """A child picks their own look. The accent is mirrored onto `color` so
    grown-up screens keep identifying them consistently."""
    theme = THEMES_BY_KEY.get(theme_key)
    if not theme:
        return False
    db.users.update_one(
        {"_id": oid(kid_id), "role": "kid"},
        {"$set": {"theme": theme["key"], "color": theme["accent"]}},
    )
    return True


def set_kid_goal(db, kid_id, reward_id):
    """Track a particular reward, or pass None to go back to automatic."""
    db.users.update_one(
        {"_id": oid(kid_id), "role": "kid"},
        {"$set": {"goal_reward_id": oid(reward_id) if reward_id else None,
                  "goal_notified": False}},
    )


def goal_for(db, kid, rewards):
    """The reward a child is saving for. Their chosen one if it's still in the
    shop, otherwise the cheapest they can't yet afford."""
    chosen_id = kid.get("goal_reward_id")
    if chosen_id:
        for r in rewards:
            if r["_id"] == chosen_id:
                return r, True
    balance = kid.get("points", 0)
    return next((r for r in rewards if r["cost"] > balance), None), False


def set_kid_pin(db, kid_id, pin):
    db.users.update_one(
        {"_id": oid(kid_id)},
        {"$set": {"pin_hash": generate_password_hash(pin) if pin else None}},
    )


# --------------------------------------------------------------------------
# points ledger
# --------------------------------------------------------------------------

def adjust_points(db, kid_id, delta, reason, actor, kind="award"):
    """Apply a point change and write a ledger entry. Returns (kid, entry) or
    (None, None) when the kid does not exist. Balance never goes below zero."""
    _id = oid(kid_id)
    if not _id:
        return None, None

    delta = int(delta)
    if delta < 0:
        # Clamp a deduction to whatever the kid actually has.
        current = db.users.find_one({"_id": _id}, {"points": 1})
        if not current:
            return None, None
        delta = -min(-delta, int(current.get("points", 0)))

    inc = {"points": delta}
    if delta > 0:
        inc["lifetime_points"] = delta

    kid = db.users.find_one_and_update(
        {"_id": _id, "role": "kid"}, {"$inc": inc}, return_document=True
    )
    if not kid:
        return None, None

    entry = {
        "kid_id": _id,
        "kid_name": kid["name"],
        "delta": delta,
        "reason": reason or ("Points awarded" if delta >= 0 else "Points removed"),
        "kind": kind,
        "actor_id": actor.get("_id") if actor else None,
        "actor_name": actor.get("name") if actor else "Questly",
        "balance_after": kid.get("points", 0),
        "created_at": now(),
    }
    db.transactions.insert_one(entry)
    return kid, entry


def history_for(db, kid_id, limit=50):
    _id = oid(kid_id)
    if not _id:
        return []
    return list(
        db.transactions.find({"kid_id": _id}).sort("created_at", -1).limit(limit)
    )


def recent_activity(db, limit=25):
    return list(db.transactions.find().sort("created_at", -1).limit(limit))


# --------------------------------------------------------------------------
# rewards + redemptions
# --------------------------------------------------------------------------

def list_rewards(db, active_only=True):
    query = {"active": True} if active_only else {}
    return list(db.rewards.find(query).sort([("cost", 1), ("title", 1)]))


def get_reward(db, reward_id):
    _id = oid(reward_id)
    return db.rewards.find_one({"_id": _id}) if _id else None


def stock_mode(reward):
    """Normalised stock mode, tolerating rewards created before periodic
    stock existed (they only ever had a plain `stock` number or None)."""
    mode = reward.get("stock_mode")
    if mode in ("unlimited", "fixed", "periodic"):
        return mode
    return "unlimited" if reward.get("stock") is None else "fixed"


def stock_used(db, reward, kid, local_now):
    """How many of this reward's periodic allowance have already gone."""
    since = period_started(reward.get("stock_period", "daily"), local_now)
    query = {
        "reward_id": reward["_id"],
        "status": {"$in": ["pending", "approved"]},
        "created_at": {"$gte": since},
    }
    if reward.get("stock_scope", "child") == "child" and kid:
        query["kid_id"] = kid["_id"]
    return db.redemptions.count_documents(query)


def stock_left(db, reward, kid, local_now):
    """How many are still available, or None when unlimited."""
    mode = stock_mode(reward)
    if mode == "unlimited":
        return None
    if mode == "fixed":
        return max(0, int(reward.get("stock") or 0))
    limit = int(reward.get("stock_limit") or 0)
    return max(0, limit - stock_used(db, reward, kid, local_now))


def stock_label(reward):
    """Human wording for the shop and admin lists."""
    mode = stock_mode(reward)
    if mode == "unlimited":
        return None
    if mode == "fixed":
        return f"{int(reward.get('stock') or 0)} left"
    per = {"daily": "a day", "weekly": "a week", "monthly": "a month"}.get(
        reward.get("stock_period", "daily"), "a day")
    who = "each" if reward.get("stock_scope", "child") == "child" else "to share"
    return f"{int(reward.get('stock_limit') or 0)} {per} {who}"


def annotate_rewards(db, rewards, kid, local_now):
    """Attach `left` and `label` so templates don't run queries."""
    out = []
    for r in rewards:
        r = dict(r)
        r["left"] = stock_left(db, r, kid, local_now)
        r["stock_text"] = stock_label(r)
        r["sold_out"] = r["left"] is not None and r["left"] <= 0
        out.append(r)
    return out


def redeem(db, kid, reward, local_now=None):
    """Take the points immediately and queue the reward for parent approval.
    Returns (redemption, error_message)."""
    cost = int(reward["cost"])
    mode = stock_mode(reward)
    local_now = local_now or datetime.now(timezone.utc)

    # Claim a fixed item off the shelf first, conditionally, so two kids racing
    # for the last one can't both win it.
    if mode == "fixed":
        claimed = db.rewards.find_one_and_update(
            {"_id": reward["_id"], "stock": {"$gt": 0}}, {"$inc": {"stock": -1}}
        )
        if not claimed:
            return None, "That one is sold out for now."
    elif mode == "periodic":
        if stock_left(db, reward, kid, local_now) <= 0:
            return None, _periodic_sold_out(reward)

    # Same trick for the points: only succeeds if the kid can actually afford
    # it, so two fast taps can never overdraw the balance.
    updated = db.users.find_one_and_update(
        {"_id": kid["_id"], "role": "kid", "points": {"$gte": cost}},
        {"$inc": {"points": -cost}},
        return_document=True,
    )
    if not updated:
        if mode == "fixed":  # couldn't pay after all — put it back on the shelf
            db.rewards.update_one({"_id": reward["_id"]}, {"$inc": {"stock": 1}})
        return None, "Not enough points for that yet — keep going!"

    doc = {
        "kid_id": kid["_id"],
        "kid_name": kid["name"],
        "kid_avatar": kid.get("avatar"),
        "reward_id": reward["_id"],
        "reward_title": reward["title"],
        "reward_emoji": reward.get("emoji", "\U0001f381"),
        "cost": cost,
        "status": "pending",
        "created_at": now(),
        "decided_at": None,
        "decided_by": None,
    }
    doc["_id"] = db.redemptions.insert_one(doc).inserted_id

    # A counted allowance can't be claimed atomically, so verify afterwards and
    # unwind if two purchases landed at once.
    if mode == "periodic":
        limit = int(reward.get("stock_limit") or 0)
        if stock_used(db, reward, kid, local_now) > limit:
            db.redemptions.delete_one({"_id": doc["_id"]})
            db.users.update_one({"_id": kid["_id"]}, {"$inc": {"points": cost}})
            return None, _periodic_sold_out(reward)

    db.transactions.insert_one({
        "kid_id": kid["_id"],
        "kid_name": kid["name"],
        "delta": -cost,
        "reason": f"Bought {reward['title']}",
        "kind": "redeem",
        "actor_id": kid["_id"],
        "actor_name": kid["name"],
        "balance_after": updated.get("points", 0),
        "created_at": now(),
    })
    return doc, None


def _periodic_sold_out(reward):
    per = {"daily": "today", "weekly": "this week", "monthly": "this month"}.get(
        reward.get("stock_period", "daily"), "right now")
    if reward.get("stock_scope", "child") == "family":
        return f"All gone {per} — someone got there first!"
    return f"You've had all of those {per}. Try again soon!"


def decide_redemption(db, redemption_id, approve, actor):
    """Approve (hand it over) or reject (refund the points) a redemption."""
    _id = oid(redemption_id)
    if not _id:
        return None

    red = db.redemptions.find_one_and_update(
        {"_id": _id, "status": "pending"},
        {"$set": {
            "status": "approved" if approve else "rejected",
            "decided_at": now(),
            "decided_by": actor.get("name"),
        }},
        return_document=True,
    )
    if not red:
        return None

    if not approve:
        adjust_points(
            db, red["kid_id"], red["cost"],
            f"Refund for {red['reward_title']}", actor, kind="refund",
        )
        # Only fixed stock needs putting back; a periodic allowance frees up
        # on its own because rejected redemptions stop being counted.
        reward = db.rewards.find_one({"_id": red.get("reward_id")})
        if reward and stock_mode(reward) == "fixed":
            db.rewards.update_one({"_id": reward["_id"]}, {"$inc": {"stock": 1}})
    return red


def pending_redemptions(db):
    return list(db.redemptions.find({"status": "pending"}).sort("created_at", 1))


def redemptions_for(db, kid_id, limit=30):
    _id = oid(kid_id)
    if not _id:
        return []
    return list(
        db.redemptions.find({"kid_id": _id}).sort("created_at", -1).limit(limit)
    )


# --------------------------------------------------------------------------
# quests
# --------------------------------------------------------------------------

def list_quests(db, active_only=True):
    query = {"active": True} if active_only else {}
    return list(db.quests.find(query).sort([("title", 1)]))


def get_quest(db, quest_id):
    _id = oid(quest_id)
    return db.quests.find_one({"_id": _id}) if _id else None


def parse_subtasks(raw, existing=None):
    """Turn one-per-line text into subtask records. Ids are preserved for
    lines that haven't changed, so ticking survives an edit to the wording of
    a *different* step."""
    import uuid
    by_text = {t.get("text"): t.get("id") for t in (existing or [])}
    out, seen = [], set()
    for line in (raw or "").splitlines():
        text = line.strip()[:120]
        if not text or text in seen:
            continue
        seen.add(text)
        out.append({"id": by_text.get(text) or uuid.uuid4().hex[:8], "text": text})
        if len(out) >= 12:
            break
    return out


def quest_progress(db, quest, kid, key):
    """Which subtasks this child has ticked for this period."""
    doc = db.quest_progress.find_one(
        {"quest_id": quest["_id"], "kid_id": kid["_id"], "period": key})
    return set((doc or {}).get("done", []))


def toggle_subtask(db, quest, kid, key, subtask_id):
    """Tick or untick one step. Returns the resulting set of ticked ids."""
    valid = {t["id"] for t in quest.get("subtasks", [])}
    if subtask_id not in valid:
        return quest_progress(db, quest, kid, key)

    done = quest_progress(db, quest, kid, key)
    op = "$pull" if subtask_id in done else "$addToSet"
    db.quest_progress.update_one(
        {"quest_id": quest["_id"], "kid_id": kid["_id"], "period": key},
        {op: {"done": subtask_id}, "$set": {"updated_at": now()}},
        upsert=True,
    )
    return quest_progress(db, quest, kid, key)


def clear_progress(db, quest, kid, key):
    db.quest_progress.delete_one(
        {"quest_id": quest["_id"], "kid_id": kid["_id"], "period": key})


def quest_times(quest):
    """How many times this quest can be done in one period."""
    return max(1, int(quest.get("times_per_period") or 1))


def quest_claims_in_period(db, quest, kid, key):
    """Claims that count toward the limit — rejected ones don't."""
    return list(db.quest_claims.find({
        "quest_id": quest["_id"], "kid_id": kid["_id"], "period": key,
        "status": {"$in": ["pending", "approved"]},
    }))


def quests_for_kid(db, kid, local_now):
    """Active quests assigned to this kid, annotated with how many times
    they've done it this period and whether another go is available.
    Sorted so quests yet to be marked as done appear at the top."""
    out = []
    for quest in list_quests(db, active_only=True):
        assigned = quest.get("assigned_to") or []
        if assigned and kid["_id"] not in assigned:
            continue

        repeat = quest.get("repeat", "daily")
        # Weekday-only quests are hidden on weekends (Saturday=5, Sunday=6)
        if repeat in ("weekday", "weekdays") and local_now.weekday() >= 5:
            continue

        key = period_key(repeat, local_now)
        limit = quest_times(quest)
        claims = quest_claims_in_period(db, quest, kid, key)
        approved = sum(1 for c in claims if c["status"] == "approved")
        pending = sum(1 for c in claims if c["status"] == "pending")

        quest = dict(quest)
        subtasks = quest.get("subtasks") or []
        ticked = quest_progress(db, quest, kid, key) if subtasks else set()
        quest["ticked"] = ticked
        quest["steps_done"] = len(ticked)
        quest["steps_total"] = len(subtasks)
        quest["steps_left"] = max(0, len(subtasks) - len(ticked))
        quest["period"] = key
        quest["limit"] = limit
        quest["done_count"] = approved
        quest["pending_count"] = pending
        quest["used"] = approved + pending
        if quest["used"] < limit:
            quest["state"] = "open"
        elif pending:
            quest["state"] = "pending"
        else:
            quest["state"] = "done"
        out.append(quest)

    state_order = {"open": 0, "pending": 1, "done": 2}
    out.sort(key=lambda q: (state_order.get(q.get("state"), 99), (q.get("title") or "").lower()))
    return out


def claim_quest(db, quest, kid, local_now):
    """Kid marks a quest as done; it waits for a parent to approve. A quest
    may allow several goes per period."""
    from pymongo.errors import DuplicateKeyError

    repeat = quest.get("repeat", "daily")
    if repeat in ("weekday", "weekdays") and local_now.weekday() >= 5:
        return None, "This quest is only available on weekdays."

    key = period_key(repeat, local_now)
    limit = quest_times(quest)
    used = len(quest_claims_in_period(db, quest, kid, key))
    if used >= limit:
        return None, _quest_all_done(quest, limit)

    subtasks = quest.get("subtasks") or []
    if subtasks:
        left = len(subtasks) - len(quest_progress(db, quest, kid, key))
        if left > 0:
            return None, (f"{left} step{'s' if left > 1 else ''} still to do "
                          "before you can finish this one.")

    # Next free slot. Rejected claims keep their slot so the numbering stays
    # unique, which is what lets the index guard against a double tap.
    highest = db.quest_claims.find_one(
        {"quest_id": quest["_id"], "kid_id": kid["_id"], "period": key},
        sort=[("seq", -1)], projection={"seq": 1},
    )
    seq = int((highest or {}).get("seq") or 0) + 1 if highest else 0

    base = {
        "quest_id": quest["_id"],
        "kid_id": kid["_id"],
        "kid_name": kid["name"],
        "kid_avatar": kid.get("avatar"),
        "quest_title": quest["title"],
        "quest_emoji": quest.get("emoji", "✅"),
        "points": int(quest["points"]),
        "period": key,
        "status": "pending",
        "created_at": now(),
        "decided_at": None,
        "decided_by": None,
    }
    for attempt in range(3):                 # lose a race, take the next slot
        doc = dict(base, seq=seq + attempt)
        try:
            db.quest_claims.insert_one(doc)
            # A repeatable quest starts its steps over for the next go.
            if subtasks:
                clear_progress(db, quest, kid, key)
            return doc, None
        except DuplicateKeyError:
            continue
    return None, "That didn't go through — try again."


def _quest_all_done(quest, limit):
    per = {"daily": "today", "weekday": "today", "weekdays": "today", "weekly": "this week"}.get(
        quest.get("repeat", "daily"), "already")
    if limit == 1:
        return "You've already sent that one in."
    return f"You've done that {limit} times {per} — that's the lot!"


def decide_quest_claim(db, claim_id, approve, actor):
    _id = oid(claim_id)
    if not _id:
        return None

    claim = db.quest_claims.find_one_and_update(
        {"_id": _id, "status": "pending"},
        {"$set": {
            "status": "approved" if approve else "rejected",
            "decided_at": now(),
            "decided_by": actor.get("name"),
        }},
        return_document=True,
    )
    if not claim:
        return None

    if approve:
        adjust_points(
            db, claim["kid_id"], claim["points"],
            f"Quest: {claim['quest_title']}", actor, kind="quest",
        )
    return claim


def pending_claims(db):
    return list(db.quest_claims.find({"status": "pending"}).sort("created_at", 1))


def pending_count(db):
    return (
        db.redemptions.count_documents({"status": "pending"})
        + db.quest_claims.count_documents({"status": "pending"})
    )
