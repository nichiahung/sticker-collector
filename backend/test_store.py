"""test_store.py — sticker_store 自測 (stdlib only，不碰真實 data.json)

執行: python backend/test_store.py   → 全部斷言通過印 PASS
"""
import datetime
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sticker_store as store  # noqa: E402

# 舊形狀（遷移前的 data.json 內容：小美 0 分、Kris 8 分 + 3 筆 kind/earned log）
LEGACY = {
    "children": {
        "小美": {"display": "小美", "emoji": "🐣", "score": 0,
                 "stickers": {"star": 0, "rainbow": 0, "gold": 0}, "log": [], "rewards": []},
        "Kris": {"display": "Kris", "emoji": "🐣", "score": 8,
                 "stickers": {"star": 1, "rainbow": 1, "gold": 1},
                 "log": [
                     {"ts": "2026-09-25T16:24:39+08:00", "kind": "star", "count": 1, "earned": 1},
                     {"ts": "2026-09-25T16:24:40+08:00", "kind": "rainbow", "count": 1, "earned": 2},
                     {"ts": "2026-09-25T16:24:41+08:00", "kind": "gold", "count": 1, "earned": 5},
                 ],
                 "rewards": []},
    }
}


def raises(exc, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc:
        return True
    return False


def use_data(tmp, content=None):
    """把 store 指到 tmp 內的新資料檔（content=None 表示檔案不存在）。"""
    store.DATA_FILE = os.path.join(tmp, "data.json")
    if content is not None:
        with open(store.DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False)


def test_seed_on_empty(tmp):
    use_data(tmp)
    assert {s["id"] for s in store.list_stickers()} == {"star", "rainbow", "gold"}
    assert {r["id"]: r["cost"] for r in store.list_rewards()} == {"small": 10, "big": 30}


def test_legacy_migration_keeps_data(tmp):
    use_data(tmp, LEGACY)
    kris = store.get_child("Kris")
    assert kris["score"] == 8 and kris["stickers"]["gold"] == 1
    assert [(e["sticker"], e["label"], e["points"]) for e in kris["log"]] == [
        ("gold", "金色", 5), ("rainbow", "彩虹", 2), ("star", "星星", 1)]  # 新→舊
    assert store.get_child("小美")["score"] == 0
    assert kris["rewards_affordable"] == {"small": 0, "big": 0}
    assert {s["id"] for s in store.list_stickers()} >= {"star", "rainbow", "gold"}
    # 寫回後舊資料與舊 log 原樣保留
    store.migrate()
    with open(store.DATA_FILE, encoding="utf-8") as f:
        raw = json.load(f)
    assert raw["children"]["Kris"] == LEGACY["children"]["Kris"]
    assert raw["children"]["小美"] == LEGACY["children"]["小美"]
    assert set(raw["stickers"]) == {"star", "rainbow", "gold"}
    assert set(raw["rewards"]) == {"small", "big"}


def test_catalog_crud(tmp):
    use_data(tmp)
    a = store.create_sticker(label="Blue Ribbon", points=3)
    assert a["id"] == "blueribbon" and a["emoji"] == store.DEFAULT_STICKER_EMOJI
    assert store.create_sticker("blueribbon", "ignored", "🎀", 99) == a  # 同 id 冪等
    assert store.create_sticker(id="Big Star", label="大星星", emoji="🌟", points=4)["id"] == "bigstar"
    assert store.update_sticker("blueribbon", emoji="🎀", points=4) == \
        {"id": "blueribbon", "label": "Blue Ribbon", "emoji": "🎀", "points": 4}
    assert raises(KeyError, store.update_sticker, "nope", label="x")
    assert raises(ValueError, store.create_sticker, label="x", points=-1)
    assert raises(ValueError, store.create_sticker, label="  ", points=1)
    assert raises(ValueError, store.create_sticker, label="x", points=True)
    assert raises(ValueError, store.create_sticker, id="!!", label="x", points=1)

    r = store.create_reward(label="冰淇淋", cost=15)
    assert r == {"id": "冰淇淋", "label": "冰淇淋", "cost": 15}
    assert store.update_reward("冰淇淋", cost=20)["cost"] == 20
    assert raises(ValueError, store.create_reward, label="x", cost=0)
    store.delete_reward("冰淇淋")
    assert raises(KeyError, store.delete_reward, "冰淇淋")
    assert "冰淇淋" not in {x["id"] for x in store.list_rewards()}


def test_rarity_optional(tmp):
    use_data(tmp)
    assert "rarity" not in store.create_sticker(label="無分級", points=1)  # 缺省後向相容
    a = store.create_sticker(id="drg", label="龍", emoji="🐉", points=5, rarity="epic")
    assert a["rarity"] == "epic" and store.list_stickers()[-1]["rarity"] == "epic"
    assert store.update_sticker("drg", rarity="rare")["rarity"] == "rare"
    assert store.update_sticker("drg", points=4)["rarity"] == "rare"  # 沒傳就不動
    assert raises(ValueError, store.create_sticker, label="x", points=1, rarity="legendary")
    assert raises(ValueError, store.update_sticker, "drg", rarity="")


def test_condition_optional(tmp):
    use_data(tmp)
    assert "condition" not in store.create_sticker(label="無條件", points=1)  # 缺省後向相容
    assert "condition" not in store.create_sticker(label="空白條件", points=1, condition="  ")
    a = store.create_sticker(id="prep", label="準備", points=1, condition=" 準備好明天用品 ")
    assert a["condition"] == "準備好明天用品" and store.list_stickers()[-1]["condition"] == "準備好明天用品"
    assert store.update_sticker("prep", points=2)["condition"] == "準備好明天用品"  # 沒傳就不動
    assert store.update_sticker("prep", condition="作業全對")["condition"] == "作業全對"
    assert "condition" not in store.update_sticker("prep", condition="")  # 空字串＝清除
    assert raises(ValueError, store.create_sticker, label="x", points=1, condition=5)
    assert raises(ValueError, store.create_sticker, label="x", points=1, condition="長" * 51)
    # 無 condition 的舊項照常記貼紙
    assert store.record_sticker("Amy", "star") == 1


def test_shop_weeks_optional(tmp):
    use_data(tmp)
    assert "shop_weeks" not in store.create_reward(label="隨兌獎", cost=1)  # 缺省後向相容
    assert "shop_weeks" not in store.create_reward(label="零", cost=1, shop_weeks=0)
    r = store.create_reward(id="shop", label="開店獎", cost=1, shop_weeks=2)
    assert r["shop_weeks"] == 2
    assert store.update_reward("shop", cost=2)["shop_weeks"] == 2  # 沒傳就不動
    assert store.update_reward("shop", shop_weeks=3)["shop_weeks"] == 3
    assert "shop_weeks" not in store.update_reward("shop", shop_weeks=0)  # 0＝清除
    for bad in (-1, True, "2", 1.5):
        assert raises(ValueError, store.create_reward, label="x", cost=1, shop_weeks=bad)
    assert raises(KeyError, store.update_reward, "nope", shop_weeks=1)


TZ8 = datetime.timezone(datetime.timedelta(hours=8))


def day(m, d, h=10):
    return datetime.datetime(2026, m, d, h, 0, tzinfo=TZ8)


def shop_view(now, rid="shop"):
    return next(r for r in store.list_rewards(now=now) if r["id"] == rid)


def open_shop(tmp, weeks=2):
    """兩週店，Amy 15 分；9/1 首兌定下 anchor → 開店日 9/1、9/15、9/29…（窗＝當日~+3 天）。"""
    use_data(tmp)
    store.create_reward(id="shop", label="開店獎", cost=1, shop_weeks=weeks)
    store.record_sticker("Amy", "gold", count=3)
    assert store.claim_reward("Amy", "shop", now=day(9, 1))["claimed"] is True


def test_claim_shop_weeks(tmp):
    use_data(tmp)
    store.create_reward(id="shop", label="開店獎", cost=1, shop_weeks=2)
    store.record_sticker("Amy", "gold", count=3)  # 15 分

    # 首兌放行並寫入 anchor；同日可批量兌，anchor 不動
    assert store.claim_reward("Amy", "shop", now=day(9, 1))["claimed"] is True
    assert shop_view(day(9, 1))["last_shop_ts"] == "2026-09-01T10:00:00+08:00"
    assert store.claim_reward("Amy", "shop", now=day(9, 1, 20))["claimed"] is True
    assert shop_view(day(9, 1))["last_shop_ts"] == "2026-09-01T10:00:00+08:00"
    # 窗外被擋：回 shop_closed + 下一開店日；不扣分、不寫兌換紀錄
    score = store.get_child("Amy")["score"]
    n_log = len(store.get_child("Amy")["reward_log"])
    for closed in (day(9, 5), day(9, 14, 23)):
        assert store.claim_reward("Amy", "shop", now=closed) ==             {"claimed": False, "reason": "shop_closed", "next_shop": "2026-09-15"}
    assert store.get_child("Amy")["score"] == score and len(store.get_child("Amy")["reward_log"]) == n_log
    closed_view = shop_view(day(9, 14))
    assert (closed_view["shop_open"], closed_view["next_shop"]) == (False, "2026-09-15")
    # 下個開店日再開門；兌獎不會把 anchor 往後推
    assert store.claim_reward("Amy", "shop", now=day(9, 15, 0))["claimed"] is True
    assert shop_view(day(9, 16))["last_shop_ts"] == "2026-09-01T10:00:00+08:00"
    assert store.claim_reward("Amy", "shop", now=day(9, 20))["next_shop"] == "2026-09-29"
    # 分數不足不會誤寫 anchor
    store.create_reward(id="dear", label="貴", cost=999, shop_weeks=1)
    assert store.claim_reward("Amy", "dear", now=day(9, 1))["reason"] == "insufficient"
    assert "last_shop_ts" not in shop_view(day(9, 1), "dear")


def test_shop_overdue_rolls_to_next_window(tmp):  # (a)
    open_shop(tmp)
    # 開店日 9/15 整窗都沒來換 → 9/20 關門，next 是 9/29（不是永久開門，anchor 也沒漂移）
    v = shop_view(day(9, 20))
    assert (v["shop_open"], v["next_shop"], v["last_shop_ts"]) == (False, "2026-09-29", "2026-09-01T10:00:00+08:00")
    # 錯過多個週期（10/20）：捲到 n=3 的 10/13 之後 → 下個是 10/27，仍是 anchor+nP
    v = shop_view(day(10, 20))
    assert (v["shop_open"], v["next_shop"]) == (False, "2026-10-27")
    # 下一窗（9/29~10/2）準時開門
    assert shop_view(day(9, 30))["shop_open"] is True
    assert store.claim_reward("Amy", "shop", now=day(9, 30))["claimed"] is True
    assert shop_view(day(10, 20))["last_shop_ts"] == "2026-09-01T10:00:00+08:00"  # 兌獎不動 anchor


def test_shop_window_boundaries(tmp):  # (b)
    open_shop(tmp)
    # 窗＝開店日當天 ~ +3 天（含兩端，以日為單位）；9/15 窗＝9/15 00:00 ~ 9/18 23:59
    for t, expect in [(day(9, 14, 23), False), (day(9, 15, 0), True), (day(9, 18, 23), True),
                      (day(9, 19, 0), False)]:
        assert shop_view(t)["shop_open"] is expect, t
    assert store.claim_reward("Amy", "shop", now=day(9, 18, 23))["claimed"] is True
    assert store.claim_reward("Amy", "shop", now=day(9, 19, 0))["reason"] == "shop_closed"
    # 開店窗內 next_shop＝再下一個開店日
    assert shop_view(day(9, 16))["next_shop"] == "2026-09-29"


def test_shop_family_shared_anchor(tmp):  # (c)
    open_shop(tmp)  # Amy 9/1 首兌定 anchor
    store.record_sticker("Kris", "gold", count=1)
    # Kris 從沒兌過，也照同一個家庭開店日：9/2 在窗內可兌，anchor 不因他改動
    assert store.claim_reward("Kris", "shop", now=day(9, 2))["claimed"] is True
    assert shop_view(day(9, 2))["last_shop_ts"] == "2026-09-01T10:00:00+08:00"
    # 窗外 Kris 同樣被擋，且看到跟 Amy 一樣的 next_shop
    store.record_sticker("Kris", "gold", count=1)
    assert store.claim_reward("Kris", "shop", now=day(9, 10)) ==         {"claimed": False, "reason": "shop_closed", "next_shop": "2026-09-15"}
    assert store.claim_reward("Amy", "shop", now=day(9, 10))["next_shop"] == "2026-09-15"


def test_shop_no_anchor_closed(tmp):  # (d)
    use_data(tmp)
    store.create_reward(id="shop", label="開店獎", cost=1, shop_weeks=2)
    v = shop_view(day(9, 1))
    assert (v["shop_open"], v["next_shop"]) == (False, None)  # 尚無開店日
    assert "last_shop_ts" not in v
    # 首次兌獎日即開店日：不被擋，並寫入 anchor
    store.record_sticker("Amy", "gold")
    assert store.claim_reward("Amy", "shop", now=day(9, 3))["claimed"] is True
    v = shop_view(day(9, 3))
    assert (v["shop_open"], v["next_shop"], v["last_shop_ts"]) == (True, "2026-09-17", "2026-09-03T10:00:00+08:00")


def test_shop_no_weeks_always_open(tmp):  # (e)
    use_data(tmp)
    store.create_reward(id="free", label="隨兌", cost=1)
    store.record_sticker("Amy", "gold", count=2)
    assert store.claim_reward("Amy", "free", now=day(9, 1))["claimed"] is True
    assert store.claim_reward("Amy", "free", now=day(9, 20, 11))["claimed"] is True
    assert not {"shop_weeks", "shop_open", "next_shop", "last_shop_ts"} & set(shop_view(day(9, 1), "free"))


def test_delete_keeps_counts_and_seed_not_resurrected(tmp):
    use_data(tmp)
    store.record_sticker("Amy", "star", count=2)
    store.delete_sticker("star")
    assert "star" not in {s["id"] for s in store.list_stickers()}  # 重新 _load 後仍不在
    amy = store.get_child("Amy")
    assert amy["stickers"]["star"] == 2 and amy["score"] == 2
    assert amy["log"][0]["label"] == "星星"  # log 自帶 label，目錄刪了仍可讀
    assert raises(KeyError, store.record_sticker, "Amy", "star")  # 已不在目錄，不能再記


def test_record_catalog_and_impromptu(tmp):
    use_data(tmp)
    assert store.record_sticker("Amy", "gold") == 5
    assert store.record_sticker("Amy", "star", count=3) == 8
    # 即興：目錄外的新貼紙 → 自動建目錄項 (預設 🎟️)
    assert store.record_sticker("Amy", label="蓋章", points=2, count=2) == 12
    made = [s for s in store.list_stickers() if s["label"] == "蓋章"]
    assert len(made) == 1 and made[0]["emoji"] == store.DEFAULT_STICKER_EMOJI and made[0]["points"] == 2
    # 再記同 label → 沿用同一目錄項，不重複建立
    assert store.record_sticker("Amy", label=" 蓋章 ", points=2) == 14
    assert len([s for s in store.list_stickers() if s["label"] == "蓋章"]) == 1
    # label 對到既有目錄項 → 用目錄分值
    assert store.record_sticker("Amy", label="星星", points=99) == 15
    amy = store.get_child("Amy")
    assert amy["score"] == 15 and amy["stickers"][made[0]["id"]] == 3 and amy["stickers"]["star"] == 4
    assert [(e["label"], e["count"], e["points"]) for e in amy["log"]][:2] == \
        [("星星", 1, 1), ("蓋章", 1, 2)]
    assert set(amy["log"][0]) == {"ts", "sticker", "label", "count", "points"}
    # 不同 label 但 slug 撞名 → 加後綴，不覆蓋
    store.record_sticker("Amy", label="A B", points=1)
    store.record_sticker("Amy", label="AB", points=1)
    assert {"ab", "ab2"} <= {s["id"] for s in store.list_stickers()}
    # 新名字自動建檔
    store.record_sticker("Zed", "star", display="Zed", emoji="🦊")
    assert store.get_child("Zed")["emoji"] == "🦊"
    # 錯誤
    assert raises(KeyError, store.record_sticker, "Amy", "nope")
    assert raises(ValueError, store.record_sticker, "Amy", label="全新", count=1)  # 缺 points
    assert raises(ValueError, store.record_sticker, "Amy", "star", count=0)
    assert raises(ValueError, store.record_sticker, "Amy")  # 兩種形狀都沒給
    assert raises(ValueError, store.record_sticker, "", "star")


def test_claim_reward(tmp):
    use_data(tmp)
    assert raises(KeyError, store.claim_reward, "Nobody", "small")  # 小朋友不存在
    store.record_sticker("Amy", "gold", count=1)  # 5 分
    res = store.claim_reward("Amy", "small")
    assert res == {"claimed": False, "reason": "insufficient", "score": 5, "cost": 10}
    assert store.get_child("Amy")["score"] == 5 and store.get_child("Amy")["reward_log"] == []
    store.record_sticker("Amy", "gold", count=1)  # 10 分
    assert store.get_child("Amy")["rewards_affordable"] == {"small": 1, "big": 0}
    res = store.claim_reward("Amy", "small")
    assert res == {"claimed": True, "reward": "small", "label": "小獎勵", "cost": 10, "score": 0}
    assert raises(KeyError, store.claim_reward, "Amy", "nope")  # 獎品不存在
    hist = store.get_child("Amy")["reward_log"]
    assert len(hist) == 1 and (hist[0]["reward"], hist[0]["label"], hist[0]["cost"]) == ("small", "小獎勵", 10)
    assert store.list_reward_history("Amy")[0]["name"] == "Amy"
    # 改目錄 cost 後以新 cost 計；刪掉的獎品不能兌換
    store.create_reward(label="貼圖本", cost=3)
    store.record_sticker("Amy", "star", count=3)
    assert store.claim_reward("Amy", "貼圖本")["score"] == 0
    store.delete_reward("small")
    assert raises(KeyError, store.claim_reward, "Amy", "small")


def test_legacy_reward_history_readable(tmp):
    legacy = json.loads(json.dumps(LEGACY))
    legacy["children"]["Kris"]["rewards"] = [{"kind": "small", "cost": 10, "ts": "2026-09-25T17:00:00+08:00"}]
    use_data(tmp, legacy)
    hist = store.get_child("Kris")["reward_log"]
    assert (hist[0]["reward"], hist[0]["label"], hist[0]["cost"]) == ("small", "小獎勵", 10)
    assert store.list_reward_history()[0]["reward"] == "small"


def test_stickers_compat_layer(tmp):
    use_data(tmp, LEGACY)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, root)
    import importlib
    stickers = importlib.import_module("stickers")
    # stickers.py 匯入的是 backend.sticker_store（另一個 module 物件），DATA_FILE 各自指向
    stickers._store.DATA_FILE = store.DATA_FILE
    assert stickers.get_children() == ["小美", "Kris"]
    assert stickers.add_sticker("Kris", "star") == 9
    assert stickers.add_sticker("Kris", label="即興", points=1, count=2) == 11
    assert stickers.claim_reward("Kris", "small") is True
    assert stickers.claim_reward("Kris", "big") is False
    s = stickers.show("Kris")
    assert s["points"] == 1 and s["score"] == 1 and s["rewards_available"] == s["rewards_affordable"]
    assert stickers.show("不存在") is None
    assert stickers.STICKER_SCORE == {"star": 1, "rainbow": 2, "gold": 5}
    assert (stickers.SMALL_REWARD, stickers.BIG_REWARD) == (10, 30)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    original = store.DATA_FILE
    try:
        for t in tests:
            with tempfile.TemporaryDirectory() as tmp:
                t(tmp)
            print(f"ok   {t.__name__}")
    finally:
        store.DATA_FILE = original
    print("PASS")


if __name__ == "__main__":
    main()
