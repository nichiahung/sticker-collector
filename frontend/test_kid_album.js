// test_kid_album.js — 小孩頁貼紙冊純邏輯（kidAlbum：分頁數、全集判定）自測
// 執行: node frontend/test_kid_album.js   → 全部斷言通過印 PASS
// 從 index.html 的 KID_ALBUM_BEGIN/END 區塊抽出 kidAlbum 直接跑，不需瀏覽器。
const fs = require("fs");
const path = require("path");
const assert = require("assert");

const html = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
const block = html.split("// KID_ALBUM_BEGIN")[1].split("// KID_ALBUM_END")[0];
const kidAlbum = new Function("KID_SLOTS", `${block}; return kidAlbum;`)(12);

const cat = Array.from({ length: 12 }, (_, i) => ({ id: `s${i}`, emoji: "⭐" }));
// 給 n 張：第一種吃剩的，前 11 種各 1 張，其餘塞第 0 種（只影響總張數）
const withTotal = n => ({ ...Object.fromEntries(cat.slice(0, Math.min(n, 12)).map(s => [s.id, 1])),
                          ...(n > 12 ? { s0: n - 11 } : {}) });

// ② 滿 12 張才出第 2 頁
assert.strictEqual(kidAlbum(cat, {}).pageCount, 1, "0 張 → 1 頁（全剪影）");
assert.strictEqual(kidAlbum(cat, {}).missing.length, 12);
assert.strictEqual(kidAlbum(cat, withTotal(11)).pageCount, 1, "11 張 → 1 頁");
assert.strictEqual(kidAlbum(cat, withTotal(12)).pageCount, 1, "12 張 → 1 頁（滿頁，無空頁）");
assert.strictEqual(kidAlbum(cat, withTotal(13)).pageCount, 2, "13 張 → 2 頁");
assert.strictEqual(kidAlbum(cat, withTotal(24)).pageCount, 2, "24 張 → 2 頁");
assert.strictEqual(kidAlbum(cat, withTotal(25)).pageCount, 3, "25 張 → 3 頁");
// 滿 12 張 + 有缺口：缺口剪影落在（唯一的）第 1 頁
const kris12 = { ...Object.fromEntries(cat.slice(0, 10).map(s => [s.id, 1])), s0: 3 };  // 10 種、共 12 張
assert.strictEqual(kidAlbum(cat, kris12).pasted.length, 12);
assert.strictEqual(kidAlbum(cat, kris12).pageCount, 1);
assert.strictEqual(kidAlbum(cat, kris12).missing.length, 2);
// 滿頁沒空槽 → 缺口剪影不消失，改進「還缺」列（滿頁＋缺口同屏）
const p12 = kidAlbum(cat, kris12).pages[0];
assert.strictEqual(p12.cells.length, 12);
assert.strictEqual(p12.slotGhosts.length, 0);
assert.deepStrictEqual(p12.rowGhosts.map(s => s.id), ["s10", "s11"]);
// 11 張、缺 1 種：剪影進最後 1 個空槽，不用還缺列
const p11 = kidAlbum(cat, withTotal(11)).pages[0];
assert.strictEqual(p11.slotGhosts.length, 1);
assert.strictEqual(p11.rowGhosts.length, 0);
// 0 張：12 種缺口剪影剛好填滿 12 槽
const p0 = kidAlbum(cat, {}).pages[0];
assert.strictEqual(p0.slotGhosts.length, 12);
assert.strictEqual(p0.rowGhosts.length, 0);
// 13 張（缺 0 種以外情形）：剪影只在最後一頁，第 1 頁無剪影
const k13 = kidAlbum(cat, { ...Object.fromEntries(cat.slice(0, 10).map(s => [s.id, 1])), s0: 4 });  // 10 種、13 張
assert.strictEqual(k13.pageCount, 2);
assert.strictEqual(k13.pages[0].slotGhosts.length + k13.pages[0].rowGhosts.length, 0);
assert.strictEqual(k13.pages[1].cells.length, 1);
assert.strictEqual(k13.pages[1].slotGhosts.length, 2);

// ③ 全集：每一種 ≥1
assert.strictEqual(kidAlbum(cat, withTotal(12)).complete, true, "擁有全部 12 種 → 全集");
assert.strictEqual(kidAlbum(cat, withTotal(11)).complete, false, "缺 1 種 → 非全集");
assert.strictEqual(kidAlbum(cat, {}).complete, false);
assert.strictEqual(kidAlbum([], {}).complete, false, "空目錄不算全集");
// 目錄已刪但仍有計數的貼紙：不影響全集判定，仍要貼上
const orphan = { ...withTotal(12), gone: 2 };
assert.strictEqual(kidAlbum(cat, orphan).complete, true);
assert.strictEqual(kidAlbum(cat, orphan).pasted.length, 14);
assert.strictEqual(kidAlbum(cat, orphan).pageCount, 2);

// 反向：出貨 demo 資料（Kris／jasper）都不是全集
const db = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "backend", "data.json"), "utf8"));
const demoCat = Object.entries(db.stickers).map(([id, s]) => ({ id, ...s }));
for (const name of ["Kris", "jasper"]) {
  const a = kidAlbum(demoCat, db.children[name].stickers);
  assert.strictEqual(a.complete, false, `${name} 不該是全集`);
  assert.ok(a.missing.length >= 1, name);
}
console.log("PASS");
