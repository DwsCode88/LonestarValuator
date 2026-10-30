"""SQLite persistence for reports, items and comps."""
from __future__ import annotations

import sqlite3
from dataclasses import fields
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from .models import Comp, Item

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT UNIQUE,
    customer_name TEXT DEFAULT '',
    customer_email TEXT DEFAULT '',
    customer_phone TEXT DEFAULT '',
    customer_address TEXT DEFAULT '',
    purpose TEXT DEFAULT 'General Appraisal',
    notes TEXT DEFAULT '',
    status TEXT DEFAULT 'Draft',
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER REFERENCES reports(id) ON DELETE CASCADE,
    position INTEGER DEFAULT 0,
    game TEXT, name TEXT, set_name TEXT, number TEXT, variant TEXT, language TEXT,
    graded INTEGER DEFAULT 0, condition TEXT, grader TEXT, grade TEXT, cert TEXT,
    qty INTEGER DEFAULT 1, image_path TEXT, image_url TEXT, notes TEXT,
    value_override REAL, override_note TEXT,
    fmv REAL, low REAL, high REAL, confidence TEXT, n_sales INTEGER DEFAULT 0, trend TEXT,
    valued_at TEXT, tcg_product_id TEXT, pc_product_id TEXT
);
CREATE TABLE IF NOT EXISTS comps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER REFERENCES items(id) ON DELETE CASCADE,
    source TEXT, kind TEXT, title TEXT, price REAL, sale_date TEXT, condition TEXT,
    url TEXT, included INTEGER DEFAULT 1, manual INTEGER DEFAULT 0, note TEXT
);
CREATE INDEX IF NOT EXISTS ix_items_report ON items(report_id);
CREATE INDEX IF NOT EXISTS ix_comps_item ON comps(item_id);
"""

ITEM_COLS = [f.name for f in fields(Item) if f.name not in ("id",)]
REPORT_FIELDS = ["number", "customer_name", "customer_email", "customer_phone",
                 "customer_address", "purpose", "notes", "status", "show_replacement", "replacement_pct"]

# columns added after v1.0.0 – applied to existing databases on open
MIGRATIONS = {
    "items": [("year", "TEXT DEFAULT ''"), ("pop_total", "INTEGER"), ("pop_higher", "INTEGER"),
              ("pop_source", "TEXT DEFAULT ''"), ("cert_desc", "TEXT DEFAULT ''")],
    "reports": [("show_replacement", "INTEGER DEFAULT 0"), ("replacement_pct", "REAL")],
}


class DB:
    def __init__(self, path: Path):
        self.path = path
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            have = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            for name, decl in cols:
                if name not in have:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
                    if name == "show_replacement":
                        self.conn.execute("UPDATE reports SET show_replacement=1 WHERE purpose='Insurance'")
        self.conn.commit()

    # ---------- reports ----------
    def next_number(self, prefix: str) -> str:
        year = date.today().year
        row = self.conn.execute("SELECT COUNT(*) FROM reports WHERE number LIKE ?",
                                (f"{prefix}-{year}-%",)).fetchone()
        n = row[0] + 1
        while True:
            num = f"{prefix}-{year}-{n:04d}"
            if not self.conn.execute("SELECT 1 FROM reports WHERE number=?", (num,)).fetchone():
                return num
            n += 1

    def create_report(self, prefix: str = "LSV", **kw) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        data = {k: kw.get(k, "") for k in REPORT_FIELDS if k != "number"}
        data["purpose"] = data["purpose"] or "General Appraisal"
        data["status"] = data["status"] or "Draft"
        data["show_replacement"] = int(bool(kw.get("show_replacement") or data["purpose"] == "Insurance"))
        data["replacement_pct"] = kw.get("replacement_pct")
        cur = self.conn.execute(
            f"INSERT INTO reports (number, {', '.join(data)}, created_at, updated_at) "
            f"VALUES (?, {', '.join('?' * len(data))}, ?, ?)",
            (kw.get("number") or self.next_number(prefix), *data.values(), now, now))
        self.conn.commit()
        return cur.lastrowid

    def update_report(self, rid: int, **kw):
        kw = {k: v for k, v in kw.items() if k in REPORT_FIELDS}
        if not kw:
            return
        kw["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self.conn.execute(f"UPDATE reports SET {', '.join(f'{k}=?' for k in kw)} WHERE id=?",
                          (*kw.values(), rid))
        self.conn.commit()

    def get_report(self, rid: int) -> Optional[dict]:
        r = self.conn.execute("SELECT * FROM reports WHERE id=?", (rid,)).fetchone()
        return dict(r) if r else None

    def list_reports(self, search: str = "") -> list[dict]:
        q = """SELECT r.*, COUNT(i.id) AS n_items,
                      COALESCE(SUM(COALESCE(i.value_override, i.fmv, 0) * i.qty), 0) AS total
               FROM reports r LEFT JOIN items i ON i.report_id = r.id"""
        args: tuple = ()
        if search:
            q += " WHERE r.number LIKE ? OR r.customer_name LIKE ? OR r.notes LIKE ?"
            like = f"%{search}%"
            args = (like, like, like)
        q += " GROUP BY r.id ORDER BY r.updated_at DESC"
        return [dict(r) for r in self.conn.execute(q, args)]

    def delete_report(self, rid: int):
        self.conn.execute("DELETE FROM reports WHERE id=?", (rid,))
        self.conn.commit()

    def duplicate_report(self, rid: int, prefix: str) -> int:
        rep = self.get_report(rid)
        new_id = self.create_report(prefix, **{k: rep[k] for k in REPORT_FIELDS if k != "number"})
        for item in self.items(rid):
            comps = self.comps(item.id)
            item.id = None
            item.report_id = new_id
            iid = self.save_item(item)
            self.replace_comps(iid, comps)
        return new_id

    def touch(self, rid: int):
        self.conn.execute("UPDATE reports SET updated_at=? WHERE id=?",
                          (datetime.now().isoformat(timespec="seconds"), rid))
        self.conn.commit()

    # ---------- items ----------
    def items(self, rid: int) -> list[Item]:
        rows = self.conn.execute("SELECT * FROM items WHERE report_id=? ORDER BY position, id", (rid,))
        return [self._row_to_item(r) for r in rows]

    def get_item(self, iid: int) -> Optional[Item]:
        r = self.conn.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
        return self._row_to_item(r) if r else None

    @staticmethod
    def _row_to_item(r) -> Item:
        d = {k: r[k] for k in r.keys() if k in ITEM_COLS or k == "id"}
        d["graded"] = bool(d.get("graded"))
        for k in ("game", "name", "set_name", "number", "variant", "language", "condition",
                  "grader", "grade", "cert", "image_path", "image_url", "notes", "override_note",
                  "confidence", "trend", "valued_at", "tcg_product_id", "pc_product_id",
                  "year", "pop_source", "cert_desc"):
            if d.get(k) is None:
                d[k] = ""
        d["n_sales"] = d.get("n_sales") or 0
        d["qty"] = d.get("qty") or 1
        return Item(**d)

    def save_item(self, item: Item) -> int:
        data = {k: getattr(item, k) for k in ITEM_COLS}
        data["graded"] = int(bool(item.graded))
        if item.id:
            self.conn.execute(f"UPDATE items SET {', '.join(f'{k}=?' for k in data)} WHERE id=?",
                              (*data.values(), item.id))
        else:
            pos = self.conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM items WHERE report_id=?",
                                    (item.report_id,)).fetchone()[0]
            cur = self.conn.execute(
                f"INSERT INTO items ({', '.join(data)}, position) VALUES ({', '.join('?' * len(data))}, ?)",
                (*data.values(), pos))
            item.id = cur.lastrowid
        self.conn.commit()
        if item.report_id:
            self.touch(item.report_id)
        return item.id

    def delete_item(self, iid: int):
        self.conn.execute("DELETE FROM items WHERE id=?", (iid,))
        self.conn.commit()

    # ---------- comps ----------
    def comps(self, iid: int) -> list[Comp]:
        out = []
        for r in self.conn.execute("SELECT * FROM comps WHERE item_id=? ORDER BY sale_date DESC, id", (iid,)):
            d = None
            if r["sale_date"]:
                try:
                    d = date.fromisoformat(r["sale_date"])
                except ValueError:
                    d = None
            out.append(Comp(id=r["id"], item_id=r["item_id"], source=r["source"], kind=r["kind"],
                            title=r["title"] or "", price=r["price"], sale_date=d,
                            condition=r["condition"] or "", url=r["url"] or "",
                            included=bool(r["included"]), manual=bool(r["manual"]),
                            note=r["note"] or ""))
        return out

    def replace_comps(self, iid: int, comps: list[Comp]):
        self.conn.execute("DELETE FROM comps WHERE item_id=?", (iid,))
        self.conn.executemany(
            "INSERT INTO comps (item_id, source, kind, title, price, sale_date, condition, url, "
            "included, manual, note) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [(iid, c.source, c.kind, c.title, c.price,
              c.sale_date.isoformat() if c.sale_date else None, c.condition, c.url,
              int(c.included), int(c.manual), c.note) for c in comps])
        self.conn.commit()
