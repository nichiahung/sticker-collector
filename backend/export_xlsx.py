"""export_xlsx.py — 貼紙紀錄匯出成 .xlsx (純標準函式庫：zipfile + 字串拼 XML)

build_xlsx(rows, include_name) -> bytes
  rows 為 sticker_store.export_rows() 的結果 {"log", "redeems", "summary"}。
  三張表：收受明細（時間/貼紙/數量/得分）、兌換歷史（時間/獎品/扣分）、總覽（小孩/顯示名/總分/貼紙總數）。
  include_name=True（全體匯出）時，收受明細與兌換歷史最前面多一欄「小孩」；總覽固定含小孩欄。
文字一律用 inlineStr（不建 sharedStrings），數字用數值格；標題列粗體。
"""
import io
import re
import zipfile
from xml.sax.saxutils import escape

CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_BAD_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")  # XML 1.0 不允許的字元


def _col(i):
    """0-based 欄序 → A, B, ..., Z, AA。"""
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(ref, value, style=0):
    st = f' s="{style}"' if style else ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}"{st}><v>{value}</v></c>'
    text = escape(_BAD_CHARS.sub("", "" if value is None else str(value)))
    return f'<c r="{ref}"{st} t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


def _sheet_xml(headers, rows):
    lines = []
    for r, (values, style) in enumerate([(headers, 1)] + [(row, 0) for row in rows], 1):
        cells = "".join(_cell(f"{_col(c)}{r}", v, style) for c, v in enumerate(values))
        lines.append(f'<row r="{r}">{cells}</row>')
    return (_XML + f'<worksheet xmlns="{_MAIN}"><sheetViews><sheetView workbookViewId="0">'
            '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
            f'<cols><col min="1" max="{len(headers)}" width="18" customWidth="1"/></cols>'
            f'<sheetData>{"".join(lines)}</sheetData></worksheet>')


def _fmt_ts(ts):
    """2026-09-25T16:24:39+08:00 → 2026-09-25 16:24:39（保留當地時間，去掉時區尾巴）。"""
    return ts[:19].replace("T", " ") if ts else ""


def build_xlsx(rows, include_name=False):
    who = ["小孩"] if include_name else []
    log = [([r["name"]] if include_name else []) + [_fmt_ts(r["ts"]), r["label"], r["count"], r["points"]]
           for r in rows["log"]]
    redeems = [([r["name"]] if include_name else []) + [_fmt_ts(r["ts"]), r["label"], r["cost"]]
               for r in rows["redeems"]]
    summary = [[r["name"], r["display"], r["score"], r["total_stickers"]] for r in rows["summary"]]
    sheets = [
        ("收受明細", who + ["時間", "貼紙", "數量", "得分"], log),
        ("兌換歷史", who + ["時間", "獎品", "扣分"], redeems),
        ("總覽", ["小孩", "顯示名", "總分", "貼紙總數"], summary),
    ]
    n = len(sheets)
    parts = {
        "[Content_Types].xml": _XML + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                      for i in range(1, n + 1)) + "</Types>",
        "_rels/.rels": _XML + f'<Relationships xmlns="{_PKG_REL}"><Relationship Id="rId1" '
            f'Type="{_REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": _XML + f'<workbook xmlns="{_MAIN}" xmlns:r="{_REL}"><sheets>'
            + "".join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
                      for i, (name, _, _) in enumerate(sheets, 1)) + "</sheets></workbook>",
        "xl/_rels/workbook.xml.rels": _XML + f'<Relationships xmlns="{_PKG_REL}">'
            + "".join(f'<Relationship Id="rId{i}" Type="{_REL}/worksheet" Target="worksheets/sheet{i}.xml"/>'
                      for i in range(1, n + 1))
            + f'<Relationship Id="rId{n + 1}" Type="{_REL}/styles" Target="styles.xml"/></Relationships>',
        "xl/styles.xml": _XML + f'<styleSheet xmlns="{_MAIN}"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
            '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs></styleSheet>',
    }
    for i, (_, headers, body) in enumerate(sheets, 1):
        parts[f"xl/worksheets/sheet{i}.xml"] = _sheet_xml(headers, body)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, xml in parts.items():
            z.writestr(name, xml.encode("utf-8"))
    return buf.getvalue()
