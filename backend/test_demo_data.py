"""test_demo_data.py — 驗證出貨的 demo 預設資料 backend/data.json（唯讀，不寫檔）

執行: python backend/test_demo_data.py   → 全部斷言通過印 PASS
"""
import json
import os

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
RANGES = {"common": (1, 2), "rare": (3, 4), "epic": (5, 5)}  # 分數跟稀有度掛鉤
FOIL_MIN = 5  # 同一張 >= 此數 → 小孩頁金框（frontend KID_FOIL_MIN）


def main():
    with open(DATA, encoding="utf-8") as f:
        db = json.load(f)
    cat = db["stickers"]

    assert len(cat) == 12, len(cat)
    assert {"star", "rainbow", "gold"} <= set(cat)
    assert (cat["star"]["points"], cat["rainbow"]["points"], cat["gold"]["points"]) == (1, 2, 5)
    counts = {}
    for sid, s in cat.items():
        r = s["rarity"]
        lo, hi = RANGES[r]
        assert lo <= s["points"] <= hi, (sid, r, s["points"])
        counts[r] = counts.get(r, 0) + 1
    assert counts == {"common": 7, "rare": 3, "epic": 2}, counts
    assert len({s["emoji"] for s in cat.values()}) == 12  # emoji 互異

    for name in ("Kris", "jasper"):
        kid = db["children"][name]
        gaps = [sid for sid in cat if kid["stickers"].get(sid, 0) == 0]
        assert 2 <= len(gaps) <= 3, (name, gaps)
        # score 與 log 自洽（log 條目新舊格式皆可讀）
        total = sum(e.get("points", e.get("earned", 0)) for e in kid["log"])
        assert total == kid["score"], (name, total, kid["score"])
    # 既有 Kris 三筆舊 log 原樣保留在最前面
    kris = db["children"]["Kris"]
    assert [e.get("kind") for e in kris["log"][:3]] == ["star", "rainbow", "gold"]
    assert max(kris["stickers"].values()) >= FOIL_MIN  # 金框展示案例
    # C2-①：12 種目錄都有行為目標；C2-②：大獎勵兩週開店、小獎勵隨兌
    assert all(s["condition"].strip() for s in cat.values())
    assert db["rewards"]["big"]["shop_weeks"] == 2 and "shop_weeks" not in db["rewards"]["small"]
    print("PASS")


if __name__ == "__main__":
    main()
