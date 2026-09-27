"""
sticker_api.py - 貼紙紀錄 REST API (stdlib only, no dependencies)

資料層在 sticker_store.py (單一資料源, backend/data.json)，本檔只做 HTTP 路由。

Endpoints:
  GET    /                       -> serve ../frontend/index.html
  GET    /children               -> 全部小朋友狀態 (含 rewards_affordable)
  GET    /<name>                 -> 單一小朋友狀態 + 最近明細 (log 收受 / reward_log 兌換)
  GET    /<name>/rewards         -> 該小朋友兌換歷史
  GET    /export.xlsx            -> 全部小朋友匯出 Excel (收受明細/兌換歷史/總覽，明細表含小孩欄)
  GET    /<name>/export.xlsx     -> 單一小朋友匯出 Excel (明細表不含小孩欄；找不到 404)
  GET    /stickers               -> 貼紙目錄
  POST   /stickers               -> 建貼紙 {"id"?, "label", "emoji"?, "points", "rarity"?, "condition"?}
  PUT    /stickers/<id>          -> 改貼紙 {"label"?, "emoji"?, "points"?, "rarity"?, "condition"?}
                                    (condition 傳 "" = 清除)
  DELETE /stickers/<id>          -> 刪貼紙 (小朋友已累積的計數保留)
  GET    /rewards                -> 獎品目錄 (有 shop_weeks 的項目附 shop_open / next_shop)
  POST   /rewards                -> 建獎品 {"id"?, "label", "cost", "shop_weeks"?}
  PUT    /rewards/<id>           -> 改獎品 {"label"?, "cost"?, "shop_weeks"?} (shop_weeks 傳 0 = 清除)
  DELETE /rewards/<id>           -> 刪獎品
  POST   /kids                   -> 登記小朋友 {"name","display","emoji"}
  POST   /<name>/sticker         -> 記貼紙，兩種形狀，count 預設 1:
                                      {"sticker":"<id>"}              目錄貼紙
                                      {"label":"..","points":n}       即興 (自動併入目錄)
  POST   /<name>/reward/<id>     -> 兌換獎品 (依目錄 cost 扣分；不足回 400；
                                    有 shop_weeks 且未開店回 400 {"error":"shop_closed","next_shop":"YYYY-MM-DD"})

錯誤一律 JSON {"error": ...}：輸入不合法 400、找不到 404。
/children /stickers /rewards /kids 為保留字，不能當小朋友名字。

Run:
  python sticker_api.py            # listens on 0.0.0.0:8000
  PORT=9000 python sticker_api.py  # override port
"""
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote, urlsplit

import export_xlsx
import sticker_store as store

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_INDEX = os.path.join(os.path.dirname(BASE_DIR), "frontend", "index.html")

_NAME_RE = r"[A-Za-z0-9_一-鿿-]{1,50}"
_RESERVED_NAMES = {"children", "stickers", "rewards", "kids"}
_CATALOGS = {  # kind -> (create, update, delete)
    "stickers": (store.create_sticker, store.update_sticker, store.delete_sticker),
    "rewards": (store.create_reward, store.update_reward, store.delete_reward),
}


class StickerHandler(BaseHTTPRequestHandler):
    # ---- helpers -----------------------------------------------------------
    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        """讀 JSON 物件 body；不合法時已回 400 並回傳 None。"""
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b""
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            body = None
        if not isinstance(body, dict):
            self._send_json(400, {"error": "invalid JSON body (object expected)"})
            return None
        return body

    def _name(self, m):
        name = unquote(m.group("name"))
        if re.fullmatch(_NAME_RE, name):
            return name
        self._send_json(400, {"error": "invalid name"})
        return None

    def _guard(self, fn):
        """store 的 KeyError → 404、ValueError → 400。"""
        try:
            fn()
        except KeyError as e:
            self._send_json(404, {"error": str(e.args[0]) if e.args else "not found"})
        except ValueError as e:
            self._send_json(400, {"error": str(e)})

    # ---- GET ---------------------------------------------------------------
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/children":
            self._send_json(200, {"children": store.list_children()})
            return
        if path == "/stickers":
            self._send_json(200, {"stickers": store.list_stickers()})
            return
        if path == "/rewards":
            self._send_json(200, {"rewards": store.list_rewards()})
            return
        if path == "/export.xlsx":  # 排在泛用 /<name> 之前
            self._guard(self._send_xlsx)
            return
        m = re.fullmatch(r"/(?P<name>[^/]+)/export\.xlsx", path)
        if m:
            name = self._name(m)
            if name:
                self._guard(lambda: self._send_xlsx(name))
            return
        m = re.fullmatch(r"/(?P<name>[^/]+)/rewards", path)
        if m:
            name = unquote(m.group("name"))
            self._send_json(200, {"name": name,
                                  "rewards": store.list_reward_history(name)})
            return
        m = re.fullmatch(r"/(?P<name>[^/]+)", path)
        if m:
            name = unquote(m.group("name"))
            rec = store.get_child(name)
            if rec is None:
                self._send_json(404, {"error": f"child '{name}' not found"})
            else:
                self._send_json(200, rec)
            return
        # fallback: serve frontend
        self._send_frontend()

    def _send_xlsx(self, name=None):
        """匯出 xlsx；name=None＝全部。Content-Disposition 附 ASCII 備用檔名 + filename*=UTF-8。"""
        body = export_xlsx.build_xlsx(store.export_rows(name), include_name=name is None)
        ascii_name = re.sub(r"[^A-Za-z0-9_-]+", "", name or "all")  # 中文名字剔光 → 備用檔名 stickers.xlsx
        fallback = f"stickers-{ascii_name}.xlsx" if ascii_name else "stickers.xlsx"
        utf8_name = quote(f"貼紙紀錄-{name or '全部'}.xlsx")
        self.send_response(200)
        self.send_header("Content-Type", export_xlsx.CONTENT_TYPE)
        self.send_header("Content-Disposition",
                         f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{utf8_name}")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_frontend(self):
        try:
            with open(FRONTEND_INDEX, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except FileNotFoundError:
            self._send_json(404, {"error": "frontend/index.html not found"})

    # ---- POST --------------------------------------------------------------
    def do_POST(self):
        path = urlsplit(self.path).path
        if path == "/kids":
            self._handle_kids()
            return
        if path in ("/stickers", "/rewards"):
            self._handle_catalog_create(path[1:])
            return
        m = re.fullmatch(r"/(?P<name>[^/]+)/sticker", path)
        if m:
            self._handle_sticker(m)
            return
        m = re.fullmatch(r"/(?P<name>[^/]+)/reward/(?P<reward>[^/]+)", path)
        if m:
            self._handle_reward(m)
            return
        self._send_json(404, {"error": "not found"})

    def _handle_kids(self):
        body = self._body()
        if body is None:
            return
        name = body.get("name")
        if (not isinstance(name, str) or not re.fullmatch(_NAME_RE, name)
                or name in _RESERVED_NAMES):
            self._send_json(400, {"error": "name required (1-50 chars, not a reserved word)"})
            return
        self._send_json(201, store.create_kid(name, body.get("display"), body.get("emoji")))

    def _handle_sticker(self, m):
        name = self._name(m)
        body = self._body() if name else None
        if body is None:
            return
        sticker_id = body.get("sticker")
        if sticker_id is None and "label" not in body:
            self._send_json(400, {"error": "need {sticker:<id>} or {label, points}"})
            return

        def run():
            e = store.record_sticker_entry(
                name, sticker_id=sticker_id, label=body.get("label"),
                points=body.get("points"), count=body.get("count", 1),
                display=body.get("display"), emoji=body.get("emoji"),
                sticker_emoji=body.get("sticker_emoji"))
            self._send_json(201, {
                "name": name, "sticker": e["sticker"], "label": e["label"],
                "emoji": e["emoji"], "count": e["count"],
                "points_earned": e["points"], "total_score": e["total_score"],
            })
        self._guard(run)

    def _handle_reward(self, m):
        name = self._name(m)
        if name is None:
            return
        reward_id = unquote(m.group("reward"))

        def run():
            result = store.claim_reward(name, reward_id)
            if result.get("reason") == "shop_closed":
                self._send_json(400, {"error": "shop_closed", "next_shop": result["next_shop"]})
                return
            if not result["claimed"]:
                self._send_json(400, {
                    "error": "insufficient score",
                    "current_score": result["score"],
                    "cost": result["cost"],
                })
                return
            self._send_json(200, {
                "name": name,
                "reward": reward_id,
                "label": result["label"],
                "points_deducted": result["cost"],
                "remaining_score": result["score"],
            })
        self._guard(run)

    def _handle_catalog_create(self, kind):
        body = self._body()
        if body is None:
            return
        create = _CATALOGS[kind][0]
        fields = ("id", "label", "emoji", "points", "rarity", "condition") if kind == "stickers" \
            else ("id", "label", "cost", "shop_weeks")
        self._guard(lambda: self._send_json(201, create(**{k: body.get(k) for k in fields})))

    # ---- PUT / DELETE ------------------------------------------------------
    def _catalog_route(self):
        m = re.fullmatch(r"/(?P<kind>stickers|rewards)/(?P<id>[^/]+)",
                         urlsplit(self.path).path)
        if m:
            return m.group("kind"), unquote(m.group("id"))
        self._send_json(404, {"error": "not found"})
        return None, None

    def do_PUT(self):
        kind, item_id = self._catalog_route()
        body = self._body() if kind else None
        if body is None:
            return
        update = _CATALOGS[kind][1]
        fields = ("label", "emoji", "points", "rarity", "condition") if kind == "stickers" \
            else ("label", "cost", "shop_weeks")
        self._guard(lambda: self._send_json(
            200, update(item_id, **{k: body.get(k) for k in fields})))

    def do_DELETE(self):
        kind, item_id = self._catalog_route()
        if kind is None:
            return

        def run():
            _CATALOGS[kind][2](item_id)
            self._send_json(200, {"deleted": item_id})
        self._guard(run)

    # silence default stderr logging noise
    def log_message(self, fmt, *args):
        pass


def main():
    port = int(os.environ.get("PORT", 8000))
    server = ThreadingHTTPServer(("0.0.0.0", port), StickerHandler)
    print(f"sticker-api listening on 0.0.0.0:{port}")
    print(f"  data: {store.DATA_FILE}")
    print(f"  frontend served at GET / : {FRONTEND_INDEX}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")


if __name__ == "__main__":
    main()
