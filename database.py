# database.py
import os, sqlite3, zipfile, tempfile, shutil

class DBError(Exception):
    pass

class Database:
    def __init__(self, db_path: str):
        if not os.path.exists(db_path):
            raise DBError(f"Database not found at {db_path}")
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row

    # ----------------- Constructors -----------------
    @classmethod
    def from_folder(cls, folder: str) -> "Database":
        dbfile = os.path.join(folder, "sellventory.db")
        if not os.path.exists(dbfile):
            raise DBError("sellventory.db not found in the selected folder.")
        return cls(dbfile)

    @classmethod
    def from_zip(cls, zip_path: str) -> "Database":
        tmpdir = tempfile.mkdtemp(prefix="sellv_zip_")
        try:
            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(tmpdir)
            return cls.from_folder(tmpdir)
        except Exception as e:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise DBError(f"Failed to open zip: {e}")

    # ----------------- Queries -----------------
    def list_items(self):
        cur = self._conn.execute("SELECT * FROM items ORDER BY local_id DESC")
        return [dict(r) for r in cur.fetchall()]

    def get_item(self, local_id: int) -> dict | None:
        cur = self._conn.execute("SELECT * FROM items WHERE local_id = ?", (local_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def update_item(self, local_id: int, fields: dict) -> None:
        if not fields:
            return
        cols = []
        vals = []
        for k, v in fields.items():
            cols.append(f"{k} = ?")
            vals.append(v)
        vals.append(local_id)
        sql = f"UPDATE items SET {', '.join(cols)} WHERE local_id = ?"
        self._conn.execute(sql, tuple(vals))
        self._conn.commit()

    def image_path(self, image_name: str | None) -> str | None:
        if not image_name:
            return None
        img_dir = os.path.join(os.path.dirname(self.db_path), "images")
        path = os.path.join(img_dir, image_name)
        return path if os.path.exists(path) else None

    def distinct_storages(self):
        cur = self._conn.execute(
            "SELECT DISTINCT TRIM(storage) AS s FROM items WHERE TRIM(storage) <> '' ORDER BY s"
        )
        return [r["s"] for r in cur.fetchall() if r["s"]]

    def tag_suggestions(self):
        cur = self._conn.execute("SELECT tags FROM items")
        tags = set()
        for r in cur.fetchall():
            if r["tags"]:
                for t in r["tags"].split(","):
                    t = t.strip()
                    if t: tags.add(t)
        return sorted(tags)

    # ----------------- Bulk helpers for Tools -----------------
    def replace_storage(self, old_value: str, new_value: str) -> int:
        cur = self._conn.execute(
            "UPDATE items SET storage = ? WHERE TRIM(storage) = TRIM(?)",
            (new_value, old_value)
        )
        self._conn.commit()
        return cur.rowcount

    def delete_storage(self, value: str) -> int:
        cur = self._conn.execute(
            "UPDATE items SET storage = '' WHERE TRIM(storage) = TRIM(?)",
            (value,)
        )
        self._conn.commit()
        return cur.rowcount

    def rename_tag(self, old_tag: str, new_tag: str) -> int:
        cur = self._conn.execute("SELECT local_id, tags FROM items")
        rows = cur.fetchall()
        changed = 0
        for r in rows:
            tags = [t.strip() for t in (r["tags"] or "").split(",") if t.strip()]
            if old_tag in tags:
                tags = [new_tag if t == old_tag else t for t in tags]
                uniq = []
                for t in tags:
                    if t and t not in uniq: uniq.append(t)
                self._conn.execute(
                    "UPDATE items SET tags = ? WHERE local_id = ?",
                    (",".join(uniq), r["local_id"])
                )
                changed += 1
        self._conn.commit()
        return changed

    def delete_tag(self, tag: str) -> int:
        cur = self._conn.execute("SELECT local_id, tags FROM items")
        rows = cur.fetchall()
        changed = 0
        for r in rows:
            tags = [t.strip() for t in (r["tags"] or "").split(",") if t.strip()]
            if tag in tags:
                tags = [t for t in tags if t != tag]
                self._conn.execute(
                    "UPDATE items SET tags = ? WHERE local_id = ?",
                    (",".join(tags), r["local_id"])
                )
                changed += 1
        self._conn.commit()
        return changed
