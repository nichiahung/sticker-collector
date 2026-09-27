"""sticker_store.py — 貼紙紀錄單一資料源 (純標準函式庫)

所有讀寫都經過這裡：REST API (sticker_api.py) 與根目錄 CLI (stickers.py)
共用同一份 data.json，行為與資料格式永遠一致。

資料檔: backend/data.json (可用環境變數 STICKER_DATA_FILE 指到別處，測試用)
  {
    "stickers": {"<id>": {"label": "星星", "emoji": "⭐", "points": 1,
                          "rarity": "common",     # 可選: common|rare|epic，缺省＝未分級
                          "condition": "準備好用品"}},  # 可選: 行為目標描述（給大人看），缺省＝無
    "rewards":  {"<id>": {"label": "小獎勵", "cost": 10,
                          "shop_weeks": 2,         # 可選: 每幾週開一次店，缺省＝隨時可兌
                          "last_shop_ts": "..."}},  # 開店日 anchor＝首次兌獎時間（首兌寫入後不變）
    "children": {
      "<name>": {
        "display": "顯示名", "emoji": "🙂", "score": 0,
        "stickers": {"<stickerId>": 1},     # 動態 key；目錄刪除後計數仍保留
        "log":     [{"ts", "sticker", "label", "count", "points"}],  # points = 本筆總分
        "rewards": [{"ts", "reward", "label", "cost"}]
      }
    }
  }

舊資料相容（_load 容忍，不改寫舊條目）:
  - 頂層沒有 stickers / rewards 區塊 → seed 星星/彩虹/金色 與 小獎勵/大獎勵。
    只在區塊「不存在」時 seed，所以使用者刪掉的預設項不會被復活。
  - 舊 log 用 kind/earned、舊兌換用 kind → 讀取時視為 sticker/points、reward。

錯誤約定: 找不到 (小朋友/貼紙/獎品) → KeyError；輸入不合法 → ValueError。
"""
import datetime
import json
import os
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.environ.get("STICKER_DATA_FILE") or os.path.join(BASE_DIR, "data.json")

SEED_STICKERS = {
    "star": {"label": "星星", "emoji": "⭐", "points": 1},
    "rainbow": {"label": "彩虹", "emoji": "🌈", "points": 2},
    "gold": {"label": "金色", "emoji": "🏆", "points": 5},
}
SEED_REWARDS = {
    "small": {"label": "小獎勵", "cost": 10},
    "big": {"label": "大獎勵", "cost": 30},
}
RARITIES = ("common", "rare", "epic")  # 貼紙稀有度（可選欄位，缺省＝未分級）
DEFAULT_EMOJI = "🙂"          # 小朋友預設圖示
DEFAULT_STICKER_EMOJI = "🎟️"  # 即興貼紙預設圖示
RECENT_LIMIT = 20            # 明細最近幾筆
MAX_TEXT = 50

_lock = threading.Lock()  # 保護 API 執行緒的 read-modify-write


def _now():
    return datetime.datetime.now().astimezone()


def _now_iso():
    return _now().isoformat(timespec="seconds")


def _seeded(seed):
    return {k: dict(v) for k, v in seed.items()}


def _new_record(display=None, emoji=None):
    return {
        "display": display,
        "emoji": emoji or DEFAULT_EMOJI,
        "score": 0,
        "stickers": {},
        "log": [],
        "rewards": [],
    }


def _load():
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            db = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        db = {}
    if not isinstance(db, dict):
        db = {}
    if "stickers" not in db:
        db["stickers"] = _seeded(SEED_STICKERS)
    if "rewards" not in db:
        db["rewards"] = _seeded(SEED_REWARDS)
    db.setdefault("children", {})
    return db


def _save(db):
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)  # 原子寫入


# ---- 驗證 / 正規化 ---------------------------------------------------------

def _slug(text):
    """小寫、去空白與符號，只留中英數字。"""
    return "".join(ch for ch in str(text).lower() if ch.isalnum())


def _clean_label(label):
    if not isinstance(label, str) or not label.strip():
        raise ValueError("label required")
    label = label.strip()
    if len(label) > MAX_TEXT:
        raise ValueError(f"label too long (max {MAX_TEXT})")
    return label


def _clean_emoji(emoji, default):
    if isinstance(emoji, str) and emoji.strip():
        return emoji.strip()[:16]
    return default


def _clean_rarity(rarity):
    """None＝未指定（不寫入欄位）；其餘必須是 RARITIES 之一。"""
    if rarity is None:
        return None
    if rarity not in RARITIES:
        raise ValueError(f"rarity must be one of {', '.join(RARITIES)}")
    return rarity


def _clean_condition(condition):
    """None＝未指定；空字串＝清除（update 用）；其餘為去空白字串（長度上限同 label）。"""
    if condition is None:
        return None
    if not isinstance(condition, str):
        raise ValueError("condition must be a string")
    condition = condition.strip()
    if len(condition) > MAX_TEXT:
        raise ValueError(f"condition too long (max {MAX_TEXT})")
    return condition


def _clean_shop_weeks(weeks):
    """None＝未指定；0＝清除（update 用，回到隨時可兌）；其餘為正整數週數。"""
    if weeks is None or (weeks == 0 and not isinstance(weeks, bool)):  # bool 一律走 _clean_int 被擋
        return weeks
    return _clean_int(weeks, "shop_weeks", 1)


def _clean_int(value, field, minimum):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field} must be int >= {minimum}")
    return value


def _clean_name(name):
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name required")
    return name


def _item_id(id, label):
    item_id = _slug(id if id else label)
    if not item_id:
        raise ValueError("id must contain letters or digits")
    return item_id


def _items(catalog):
    return [{"id": k, **v} for k, v in catalog.items()]


# ---- 歷史條目讀取（新舊格式皆可）------------------------------------------

def _label_of(catalog, item_id, entry):
    return entry.get("label") or catalog.get(item_id, {}).get("label") or item_id


def _read_log(entry, stickers):
    sid = entry.get("sticker") or entry.get("kind")
    return {
        "ts": entry.get("ts"),
        "sticker": sid,
        "label": _label_of(stickers, sid, entry),
        "count": entry.get("count", 1),
        "points": entry.get("points", entry.get("earned", 0)),
    }


def _read_redeem(entry, rewards):
    rid = entry.get("reward") or entry.get("kind")
    return {
        "ts": entry.get("ts"),
        "reward": rid,
        "label": _label_of(rewards, rid, entry),
        "cost": entry.get("cost", 0),
    }


def _recent(entries, read, catalog):
    return [read(e, catalog) for e in reversed(entries[-RECENT_LIMIT:])]


def public_view(name, rec, db, detail=False):
    """對外檢視。detail=True 另含最近收受 log 與兌換歷史 reward_log（新→舊）。"""
    score = rec.get("score", 0)
    counts = {sid: 0 for sid in db["stickers"]}
    counts.update(rec.get("stickers", {}))
    view = {
        "name": name,
        "display": rec.get("display") or name,
        "emoji": rec.get("emoji") or DEFAULT_EMOJI,
        "score": score,
        "stickers": counts,
        "rewards_affordable": {
            rid: score // r["cost"] for rid, r in db["rewards"].items() if r.get("cost", 0) > 0
        },
    }
    if detail:
        view["log"] = _recent(rec.get("log", []), _read_log, db["stickers"])
        view["reward_log"] = _recent(rec.get("rewards", []), _read_redeem, db["rewards"])
    return view


# ---- 小朋友 ----------------------------------------------------------------

def list_children():
    """全部小朋友的狀態清單（精簡，不含明細）。"""
    with _lock:
        db = _load()
    return [public_view(name, rec, db) for name, rec in db["children"].items()]


def get_child(name):
    """單一小朋友狀態（含最近明細）；不存在回 None。"""
    with _lock:
        db = _load()
    rec = db["children"].get(name)
    return public_view(name, rec, db, detail=True) if rec else None


def create_kid(name, display=None, emoji=None):
    """登記小朋友（已存在則原樣回傳，具冪等性）。"""
    _clean_name(name)
    with _lock:
        db = _load()
        if name not in db["children"]:
            db["children"][name] = _new_record(display, emoji)
            _save(db)
        return public_view(name, db["children"][name], db)


# ---- 貼紙目錄 --------------------------------------------------------------

def list_stickers():
    with _lock:
        db = _load()
    return _items(db["stickers"])


def create_sticker(id=None, label=None, emoji=None, points=None, rarity=None, condition=None):
    """建立貼紙類型；id 省略時由 label 轉 slug。同 id 已存在則原樣回傳（冪等）。
    rarity（common|rare|epic）、condition（行為目標描述）可選；省略或空白則不寫入該欄位。"""
    label = _clean_label(label)
    points = _clean_int(points, "points", 0)
    rarity = _clean_rarity(rarity)
    condition = _clean_condition(condition)
    sid = _item_id(id, label)
    with _lock:
        db = _load()
        if sid not in db["stickers"]:
            db["stickers"][sid] = {
                "label": label,
                "emoji": _clean_emoji(emoji, DEFAULT_STICKER_EMOJI),
                "points": points,
            }
            if rarity:
                db["stickers"][sid]["rarity"] = rarity
            if condition:
                db["stickers"][sid]["condition"] = condition
            _save(db)
        return {"id": sid, **db["stickers"][sid]}


def update_sticker(id, label=None, emoji=None, points=None, rarity=None, condition=None):
    """部分更新；只改有傳的欄位（condition 傳空字串＝清除）。不存在 → KeyError。
    舊紀錄不受影響（log 已存 label/points）。"""
    changes = {}
    if label is not None:
        changes["label"] = _clean_label(label)
    if emoji is not None:
        changes["emoji"] = _clean_emoji(emoji, DEFAULT_STICKER_EMOJI)
    if points is not None:
        changes["points"] = _clean_int(points, "points", 0)
    if rarity is not None:
        changes["rarity"] = _clean_rarity(rarity)
    condition = _clean_condition(condition)
    with _lock:
        db = _load()
        if id not in db["stickers"]:
            raise KeyError(f"找不到貼紙: {id}")
        db["stickers"][id].update(changes)
        if condition:
            db["stickers"][id]["condition"] = condition
        elif condition == "":
            db["stickers"][id].pop("condition", None)
        _save(db)
        return {"id": id, **db["stickers"][id]}


def delete_sticker(id):
    """刪目錄項；小朋友已累積的計數與 log 保留。不存在 → KeyError。"""
    with _lock:
        db = _load()
        if id not in db["stickers"]:
            raise KeyError(f"找不到貼紙: {id}")
        del db["stickers"][id]
        _save(db)


# ---- 獎品目錄 --------------------------------------------------------------

def _last_shop_day(reward, tz):
    """上次開店日（依 tz 換算的 date）；從沒開過店 → None。"""
    ts = reward.get("last_shop_ts")
    if not ts:
        return None
    last = datetime.datetime.fromisoformat(ts)
    return (last.astimezone(tz) if last.tzinfo else last).date()


SHOP_GRACE_DAYS = 3  # 開店日起算的寬限天數（含開店日當天共 4 天）


def _shop_status(reward, now):
    """有 shop_weeks 的獎品 → (is_open, next_shop 日期或 None)；無 shop_weeks → None。

    家庭級固定開店日：anchor＝last_shop_ts（首次兌獎日），開店日＝anchor + n×(shop_weeks×7 天)，
    n≥0；now 落在「某開店日 ~ 開店日+3 天」（以日為單位、含兩端）內＝開店中。
    逾期自動捲到下一窗，anchor 不漂移。next_shop＝今天之後的第一個開店日。
    從沒兌過（無 anchor）→ (False, None)：尚無開店日，首次兌獎日即開店日。
    """
    weeks = reward.get("shop_weeks")
    if not weeks:
        return None
    anchor = _last_shop_day(reward, now.tzinfo)
    if anchor is None:
        return False, None
    period = weeks * 7
    elapsed = (now.date() - anchor).days
    if elapsed < 0:  # 時鐘早於 anchor：尚未到第一個開店日
        return False, anchor
    n = elapsed // period
    return elapsed - n * period <= SHOP_GRACE_DAYS, anchor + datetime.timedelta(days=(n + 1) * period)


def list_rewards(now=None):
    """獎品目錄；有 shop_weeks 的項目另附計算欄位 shop_open（bool）與 next_shop
    （今天之後的下一個開店日 ISO 日期；尚無開店日＝None）。"""
    with _lock:
        db = _load()
    now = now or _now()
    items = _items(db["rewards"])
    for item in items:
        status = _shop_status(item, now)
        if status:
            item["shop_open"] = status[0]
            item["next_shop"] = status[1].isoformat() if status[1] else None
    return items


def create_reward(id=None, label=None, cost=None, shop_weeks=None):
    """建立獎品；id 省略時由 label 轉 slug。同 id 已存在則原樣回傳（冪等）。
    shop_weeks 可選（正整數，每幾週開一次店）；省略或 0 則不寫入＝隨時可兌。"""
    label = _clean_label(label)
    cost = _clean_int(cost, "cost", 1)
    shop_weeks = _clean_shop_weeks(shop_weeks)
    rid = _item_id(id, label)
    with _lock:
        db = _load()
        if rid not in db["rewards"]:
            db["rewards"][rid] = {"label": label, "cost": cost}
            if shop_weeks:
                db["rewards"][rid]["shop_weeks"] = shop_weeks
            _save(db)
        return {"id": rid, **db["rewards"][rid]}


def update_reward(id, label=None, cost=None, shop_weeks=None):
    """部分更新；只改有傳的欄位（shop_weeks 傳 0＝清除，回到隨時可兌）。不存在 → KeyError。"""
    changes = {}
    if label is not None:
        changes["label"] = _clean_label(label)
    if cost is not None:
        changes["cost"] = _clean_int(cost, "cost", 1)
    shop_weeks = _clean_shop_weeks(shop_weeks)
    with _lock:
        db = _load()
        if id not in db["rewards"]:
            raise KeyError(f"找不到獎品: {id}")
        db["rewards"][id].update(changes)
        if shop_weeks:
            db["rewards"][id]["shop_weeks"] = shop_weeks
        elif shop_weeks == 0:
            db["rewards"][id].pop("shop_weeks", None)
        _save(db)
        return {"id": id, **db["rewards"][id]}


def delete_reward(id):
    with _lock:
        db = _load()
        if id not in db["rewards"]:
            raise KeyError(f"找不到獎品: {id}")
        del db["rewards"][id]
        _save(db)


# ---- 記貼紙 / 換獎品 -------------------------------------------------------

def _sticker_for_label(db, label, points, emoji):
    """即興貼紙：label 已在目錄就用該項（沿用目錄分值），否則自動建立目錄項。"""
    for sid, s in db["stickers"].items():
        if s["label"].strip().casefold() == label.casefold():
            return sid
    if points is None:
        raise ValueError("points required for a sticker not in the catalog")
    base = _slug(label) or "sticker"
    sid, n = base, 2
    while sid in db["stickers"]:
        sid, n = f"{base}{n}", n + 1
    db["stickers"][sid] = {
        "label": label,
        "emoji": _clean_emoji(emoji, DEFAULT_STICKER_EMOJI),
        "points": points,
    }
    return sid


def record_sticker_entry(name, sticker_id=None, label=None, points=None, count=1,
                         display=None, emoji=None, sticker_emoji=None):
    """記貼紙（新名字自動建檔），回傳 log 條目加 total_score。

    sticker_id → 目錄貼紙；否則 label(+points) → 即興。
    display/emoji 是新小朋友的顯示名/圖示；sticker_emoji 是自動建立的目錄項圖示。
    """
    _clean_name(name)
    count = _clean_int(count, "count", 1)
    if sticker_id is None:
        label = _clean_label(label)
        if points is not None:
            points = _clean_int(points, "points", 0)
    with _lock:
        db = _load()
        if sticker_id is None:
            sticker_id = _sticker_for_label(db, label, points, sticker_emoji)
        elif sticker_id not in db["stickers"]:
            raise KeyError(f"找不到貼紙: {sticker_id}")
        sticker = db["stickers"][sticker_id]
        earned = sticker["points"] * count
        rec = db["children"].setdefault(name, _new_record(display, emoji))
        counts = rec.setdefault("stickers", {})
        counts[sticker_id] = counts.get(sticker_id, 0) + count
        rec["score"] = rec.get("score", 0) + earned
        entry = {"ts": _now_iso(), "sticker": sticker_id, "label": sticker["label"],
                 "count": count, "points": earned}
        rec.setdefault("log", []).append(entry)
        _save(db)
        return {**entry, "emoji": sticker["emoji"], "total_score": rec["score"]}


def record_sticker(name, sticker_id=None, label=None, points=None, count=1,
                   display=None, emoji=None, sticker_emoji=None):
    """同 record_sticker_entry，只回傳新總分。"""
    return record_sticker_entry(name, sticker_id, label, points, count,
                                display, emoji, sticker_emoji)["total_score"]


def claim_reward(name, reward_id, now=None):
    """換獎品（扣分制，依目錄 cost）。now 可注入（時區感知 datetime，測試用），預設系統時間。

    成功: {"claimed": True, "reward", "label", "cost", "score"(扣後)}
    不足: {"claimed": False, "reason": "insufficient", "score", "cost"}
    未開店（有 shop_weeks 且不在開店日窗內）:
          {"claimed": False, "reason": "shop_closed", "next_shop": "YYYY-MM-DD"}
    小朋友或獎品不存在: KeyError。
    有 shop_weeks 的獎品「從未兌過」時放行首兌，並寫入 last_shop_ts＝now（首次兌獎日即開店日）；
    之後 anchor 不動。
    """
    now = now or _now()
    with _lock:
        db = _load()
        rec = db["children"].get(name)
        if rec is None:
            raise KeyError(f"找不到小朋友: {name}")
        reward = db["rewards"].get(reward_id)
        if reward is None:
            raise KeyError(f"找不到獎品: {reward_id}")
        status = _shop_status(reward, now)
        if status and status[1] is not None and not status[0]:  # 有 anchor 且在窗外
            return {"claimed": False, "reason": "shop_closed", "next_shop": status[1].isoformat()}
        cost = reward["cost"]
        score = rec.get("score", 0)
        if score < cost:
            return {"claimed": False, "reason": "insufficient", "score": score, "cost": cost}
        rec["score"] = score - cost
        ts = now.isoformat(timespec="seconds")
        rec.setdefault("rewards", []).append(
            {"ts": ts, "reward": reward_id, "label": reward["label"], "cost": cost}
        )
        if status and status[1] is None:  # 首兌：定下家庭開店日
            reward["last_shop_ts"] = ts
        _save(db)
        return {"claimed": True, "reward": reward_id, "label": reward["label"],
                "cost": cost, "score": rec["score"]}


def list_reward_history(name=None):
    """兌換歷史（舊→新）；name=None 回傳全部小朋友。"""
    with _lock:
        db = _load()
    out = []
    for n in ([name] if name else list(db["children"])):
        rec = db["children"].get(n)
        if not rec:
            continue
        for r in rec.get("rewards", []):
            out.append({"name": n, **_read_redeem(r, db["rewards"])})
    return out


def export_rows(name=None):
    """匯出用的列資料（只讀不寫，舊格式經 _read_log/_read_redeem 容忍）。

    回傳 {"log": [{name, ts, label, count, points}], "redeems": [{name, ts, label, cost}],
          "summary": [{name, display, score, total_stickers}]}，明細舊→新；
    name=None＝全部小朋友，指定但不存在 → KeyError。total_stickers＝目前各貼紙計數加總。
    """
    with _lock:
        db = _load()
    if name is not None and name not in db["children"]:
        raise KeyError(f"找不到小朋友: {name}")
    out = {"log": [], "redeems": [], "summary": []}
    for n in ([name] if name is not None else list(db["children"])):
        rec = db["children"][n]
        out["log"] += [{"name": n, **_read_log(e, db["stickers"])} for e in rec.get("log", [])]
        out["redeems"] += [{"name": n, **_read_redeem(e, db["rewards"])} for e in rec.get("rewards", [])]
        out["summary"].append({"name": n, "display": rec.get("display") or n,
                               "score": rec.get("score", 0),
                               "total_stickers": sum(rec.get("stickers", {}).values())})
    return out


# ---- 維護 ------------------------------------------------------------------

def migrate():
    """讀入（自動遷移舊形狀、seed 目錄）後寫回；既有小朋友資料與歷史原樣保留。"""
    with _lock:
        _save(_load())


def reset():
    """清空全部資料並重新 seed 目錄（測試用）。"""
    with _lock:
        _save({"stickers": _seeded(SEED_STICKERS), "rewards": _seeded(SEED_REWARDS),
               "children": {}})
