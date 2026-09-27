"""Sticker Collector — 貼紙紀錄系統 CLI (相容層)

注意：本檔已是 compat shim。真正的單一資料源在 backend/sticker_store.py
(backend/data.json)，REST API (backend/sticker_api.py) 與本 CLI 共用同一份資料。

貼紙與獎品都是目錄（可增刪），也可即興記錄目錄外的貼紙。預設 seed：
  貼紙：⭐ 星星(1分) / 🌈 彩虹(2分) / 🏆 金色(5分)
  獎品：small 小獎勵(10分) / big 大獎勵(30分)
兌換會扣對應分數，防止重複領。

相容接口：
  get_children() -> [name, ...]
  add_sticker(name, kind="star", count=1) -> 新總分 (int)
      kind 為目錄貼紙 id；即興貼紙改傳 label=、points=（kind 會被忽略）
  claim_reward(name, kind="small") -> True 成功 / False 不足
      kind 為獎品目錄 id；小朋友或獎品不存在會丟 KeyError
  show(name) -> 狀態 dict (含 points、rewards_available 舊別名)
  STICKER_SCORE / STICKER_EMOJI / SMALL_REWARD / BIG_REWARD 為 seed 值別名
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))  # 確保 root 可 import backend 套件

from backend import sticker_store as _store  # noqa: E402

# ---- 相容常數（seed 值別名；實際分值以 data.json 目錄為準）-------------------
STICKER_SCORE = {k: v["points"] for k, v in _store.SEED_STICKERS.items()}
STICKER_EMOJI = {k: v["emoji"] for k, v in _store.SEED_STICKERS.items()}
SMALL_REWARD = _store.SEED_REWARDS["small"]["cost"]
BIG_REWARD = _store.SEED_REWARDS["big"]["cost"]
DATA = _store.DATA_FILE  # 舊腳本若引用 stickers.DATA 仍可讀到路徑


def get_children():
    """全部小朋友的名字清單。"""
    return [c["name"] for c in _store.list_children()]


def add_sticker(name, kind="star", count=1, label=None, points=None):
    """給某位小朋友記貼紙（目錄 id 或即興 label+points），回傳新總分。"""
    if label is not None:
        return _store.record_sticker(name, label=label, points=points, count=count)
    return _store.record_sticker(name, sticker_id=kind, count=count)


def claim_reward(name, kind="small"):
    """兌換獎品（依目錄 cost）。成功回 True，不足回 False。"""
    return _store.claim_reward(name, kind)["claimed"]


def show(name):
    """回傳某位小朋友的狀態字典（points、rewards_available 為舊介面別名）。"""
    rec = _store.get_child(name)
    if rec is None:
        return None
    out = dict(rec)
    out["points"] = rec["score"]
    out["rewards_available"] = rec["rewards_affordable"]
    return out


if __name__ == "__main__":
    # 小 CLI：python stickers.py [名字]  → 印出該名狀態，或全部
    import json

    if len(sys.argv) > 1:
        print(json.dumps(show(sys.argv[1]) or {"error": "找不到小朋友"},
                         ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"children": _store.list_children()},
                         ensure_ascii=False, indent=2))
