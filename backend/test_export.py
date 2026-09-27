"""test_export.py — Excel 匯出自測 (stdlib only，不碰真實 data.json)

執行: python backend/test_export.py   → 全部斷言通過印 PASS
"""
import http.client
import io
import json
import os
import sys
import tempfile
import threading
import urllib.parse
import zipfile
from http.server import ThreadingHTTPServer
from xml.etree import ElementTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import export_xlsx  # noqa: E402
import sticker_api  # noqa: E402
import sticker_store as store  # noqa: E402

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

# 含一筆舊形狀 log（kind/earned）與一筆舊兌換（kind），驗證舊相容
LEGACY = {
    "children": {
        "小美": {"display": "美美", "emoji": "🐣", "score": 4,
                 "stickers": {"star": 1, "rainbow": 2}, "rewards": [],
                 "log": [{"ts": "2026-09-25T16:24:39+08:00", "kind": "star", "count": 1, "earned": 1},
                         {"ts": "2026-09-25T16:24:40+08:00", "sticker": "rainbow", "label": "彩虹",
                          "count": 2, "points": 4}]},
        "Kris": {"display": None, "emoji": "🙂", "score": 0,
                 "stickers": {"gold": 3}, "log": [],
                 "rewards": [{"ts": "2026-09-26T09:00:00+08:00", "kind": "small", "cost": 10}]},
    }
}


def use_data(tmp, content):
    store.DATA_FILE = os.path.join(tmp, "data.json")
    with open(store.DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(content, f, ensure_ascii=False)


def raises(exc, fn, *args):
    try:
        fn(*args)
    except exc:
        return True
    return False


def sheets(data):
    """xlsx bytes → {sheet 名: [[cell 文字, ...], ...]}（依 workbook 順序）。"""
    z = zipfile.ZipFile(io.BytesIO(data))
    wb = ElementTree.fromstring(z.read("xl/workbook.xml"))
    out = {}
    for i, s in enumerate(wb.find("m:sheets", NS), 1):
        ws = ElementTree.fromstring(z.read(f"xl/worksheets/sheet{i}.xml"))
        out[s.get("name")] = [
            ["".join(c.itertext()) for c in row.findall("m:c", NS)]
            for row in ws.find("m:sheetData", NS)]
    return out


def test_export_rows():
    with tempfile.TemporaryDirectory() as tmp:
        use_data(tmp, LEGACY)
        before = open(store.DATA_FILE, "rb").read()
        allr = store.export_rows()
        assert [r["name"] for r in allr["log"]] == ["小美", "小美"]
        assert [(r["label"], r["count"], r["points"]) for r in allr["log"]] == [("星星", 1, 1), ("彩虹", 2, 4)]
        assert [(r["name"], r["label"], r["cost"]) for r in allr["redeems"]] == [("Kris", "小獎勵", 10)]
        assert allr["summary"] == [
            {"name": "小美", "display": "美美", "score": 4, "total_stickers": 3},
            {"name": "Kris", "display": "Kris", "score": 0, "total_stickers": 3}]
        one = store.export_rows("Kris")
        assert one["log"] == [] and len(one["redeems"]) == 1 and len(one["summary"]) == 1
        assert raises(KeyError, store.export_rows, "nobody")
        assert open(store.DATA_FILE, "rb").read() == before  # 只讀不寫


def test_xlsx_bytes():
    with tempfile.TemporaryDirectory() as tmp:
        use_data(tmp, LEGACY)
        data = export_xlsx.build_xlsx(store.export_rows(), include_name=True)
        assert data[:2] == b"PK"
        z = zipfile.ZipFile(io.BytesIO(data))
        assert z.testzip() is None and "[Content_Types].xml" in z.namelist()
        s = sheets(data)
        assert list(s) == ["收受明細", "兌換歷史", "總覽"]
        assert s["收受明細"][0] == ["小孩", "時間", "貼紙", "數量", "得分"]
        assert s["收受明細"][1][0] == "小美" and s["收受明細"][1][2:] == ["星星", "1", "1"]
        assert s["兌換歷史"][0] == ["小孩", "時間", "獎品", "扣分"]
        assert s["兌換歷史"][1][0] == "Kris" and s["兌換歷史"][1][3] == "10"
        assert s["總覽"][0] == ["小孩", "顯示名", "總分", "貼紙總數"]
        assert s["總覽"][1] == ["小美", "美美", "4", "3"]
        # 單人：明細表不含小孩欄
        one = sheets(export_xlsx.build_xlsx(store.export_rows("小美"), include_name=False))
        assert one["收受明細"][0] == ["時間", "貼紙", "數量", "得分"]
        assert len(one["總覽"]) == 2


def test_xlsx_escapes_text():
    rows = {"log": [{"name": "a", "ts": None, "label": "<b>&\"x\"\x01", "count": 1, "points": 1}],
            "redeems": [], "summary": []}
    s = sheets(export_xlsx.build_xlsx(rows, include_name=False))
    assert s["收受明細"][1] == ["", "<b>&\"x\"", "1", "1"]  # 特殊字元原樣、控制字元剔除


def test_api():
    with tempfile.TemporaryDirectory() as tmp:
        use_data(tmp, LEGACY)
        server = ThreadingHTTPServer(("127.0.0.1", 0), sticker_api.StickerHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            def get(path):
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
                conn.request("GET", path)
                r = conn.getresponse()
                body = r.read()
                conn.close()
                return r.status, r.getheader("Content-Type"), r.getheader("Content-Disposition"), body

            status, ctype, disp, body = get("/export.xlsx")
            assert status == 200 and ctype == XLSX_TYPE and body[:2] == b"PK"
            assert 'filename="' in disp and "filename*=UTF-8''" in disp
            disp.encode("ascii")  # header 必須純 ASCII
            assert "收受明細" in sheets(body) and sheets(body)["收受明細"][0][0] == "小孩"

            status, ctype, disp, body = get("/" + urllib.parse.quote("小美") + "/export.xlsx")
            assert status == 200 and ctype == XLSX_TYPE and body[:2] == b"PK"
            assert urllib.parse.quote("小美") in disp
            disp.encode("ascii")
            assert sheets(body)["收受明細"][0][0] == "時間"

            assert get("/nobody/export.xlsx")[0] == 404
            assert get("/bad%20name/export.xlsx")[0] == 400
            assert get("/children")[1].startswith("application/json")  # 既有路由不受影響
        finally:
            server.shutdown()
            server.server_close()


def main():
    test_export_rows()
    test_xlsx_bytes()
    test_xlsx_escapes_text()
    test_api()
    print("PASS")


if __name__ == "__main__":
    main()
