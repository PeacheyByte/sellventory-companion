# merge_zip.py
import os, glob, zipfile, tempfile, shutil, hashlib, sqlite3, time, uuid
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from database import Database, DBError

def _now_ms() -> int:
    return int(time.time() * 1000)

def _sha1(path: str) -> Optional[str]:
    try:
        h = hashlib.sha1()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None

def _best_image_source(extracted_root: str) -> Optional[str]:
    return Database._guess_images_dir(extracted_root)

def _open_incoming_db(extracted_root: str) -> str:
    cands = []
    for ext in ("*.db", "*.sqlite", "*.sqlite3"):
        cands += glob.glob(os.path.join(extracted_root, ext))
    if not cands:
        for ext in ("*.db", "*.sqlite", "*.sqlite3"):
            cands += glob.glob(os.path.join(extracted_root, "**", ext), recursive=True)
    if not cands:
        raise DBError("No SQLite DB found in the imported archive.")
    return cands[0]

def _rows_map(conn: sqlite3.Connection, table: str, cols: Dict[str, Optional[str]]) -> Dict[str, Dict[str, Any]]:
    want = {
        "id":       cols.get("id") or "id",
        "name":     cols.get("name"),
        "location": cols.get("location"),
        "buy_price": cols.get("buy_price"),
        "sold_price": cols.get("sold_price"),
        "sold_date": cols.get("sold_date"),
        "image_name": "image_name" if cols.get("image_name") or "image_name" else None,
        "legacy_image": cols.get("image"),
        "image_hash": "image_hash" if cols.get("image_hash") or "image_hash" else None,
        "updated_at": "updated_at" if cols.get("updated_at") or "updated_at" else None,
        "deleted_at": "deleted_at" if cols.get("deleted_at") or "deleted_at" else None,
    }

    select_cols = []
    for k, c in want.items():
        if c:
            select_cols.append(f"{c} AS {k}")
    sql = f"SELECT {', '.join(select_cols)} FROM {table}"
    rows = conn.execute(sql).fetchall()

    out = {}
    for r in rows:
        d = dict(r)
        if not d.get("id"):
            d["id"] = str(uuid.uuid4())
        out[d["id"]] = d
    return out

def _resolve_incoming_image_path(inc_row: Dict[str, Any], imgs_root: Optional[str], inc_db_path: str) -> Optional[str]:
    name = inc_row.get("image_name")
    if name:
        if imgs_root:
            p = os.path.join(imgs_root, name)
            if os.path.exists(p): return p
        p2 = os.path.join(os.path.dirname(inc_db_path), name)
        if os.path.exists(p2): return p2
    leg = inc_row.get("legacy_image")
    if leg:
        if os.path.isabs(leg) and os.path.exists(leg): return leg
        if imgs_root:
            p = os.path.join(imgs_root, os.path.basename(leg))
            if os.path.exists(p): return p
        p2 = os.path.join(os.path.dirname(inc_db_path), os.path.basename(leg))
        if os.path.exists(p2): return p2
    return None

def _local_images_dir(db: Database) -> str:
    return db.images_dir()

def _copy_image_into_local(src_path: str, db: Database, prefer_name: Optional[str]) -> Tuple[str, Optional[str]]:
    h = _sha1(src_path)
    ext = os.path.splitext(prefer_name or os.path.basename(src_path))[1] or ".jpg"
    out_name = (h + ext) if h else (prefer_name or os.path.basename(src_path))
    dest = os.path.join(_local_images_dir(db), out_name)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if not os.path.exists(dest):
        shutil.copy2(src_path, dest)
    return out_name, h

def _upsert_local(conn: sqlite3.Connection, table: str, local_cols: Dict[str, Optional[str]], incoming: Dict[str, Any]) -> None:
    col_map = {
        "id":        local_cols.get("id") or "id",
        "name":      local_cols.get("name"),
        "location":  local_cols.get("location"),
        "buy_price": local_cols.get("buy_price"),
        "sold_price":local_cols.get("sold_price"),
        "sold_date": local_cols.get("sold_date") or "sold_date",
        "image_name":"image_name" if local_cols.get("image_name") or "image_name" else None,
        "image_hash":"image_hash" if local_cols.get("image_hash") or "image_hash" else None,
        "updated_at":"updated_at",
        "deleted_at":"deleted_at",
    }

    fields, values = [], []
    for k, col in col_map.items():
        if not col: 
            continue
        if k in incoming:
            fields.append(col)
            values.append(incoming[k])

    if local_cols.get("id"):
        idcol = col_map["id"]
        set_clause = ", ".join([f"{c}=?" for c in fields if c != idcol])
        params = [incoming[k] for k, c in col_map.items() if c and c != idcol and k in incoming]
        params.append(incoming["id"])
        conn.execute(f"UPDATE {table} SET {set_clause} WHERE {idcol}=?", params)
        if conn.total_changes:
            return

    placeholders = ",".join(["?"] * len(fields))
    conn.execute(f"INSERT OR IGNORE INTO {table}({', '.join(fields)}) VALUES({placeholders})", values)

def _soft_delete(conn: sqlite3.Connection, table: str, idcol: str, row_id: str, when_ms: int) -> None:
    conn.execute(
        f"UPDATE {table} SET deleted_at=?, updated_at=? WHERE {idcol}=?",
        (when_ms, when_ms, row_id)
    )

def merge_zip_into_local(zip_or_db_path: str, db: Database) -> Dict[str, int]:
    """
    Merge behavior tweak:
      - Apply tombstones ONLY if the item already exists locally.
      - Ignore deletions for items unknown to the local DB.
    """
    stats = {"inserted": 0, "updated": 0, "deleted": 0, "images_copied": 0, "skipped": 0}
    tempdir = None
    try:
        source_db_path = zip_or_db_path
        extracted_root = None

        if zip_or_db_path.lower().endswith(".zip"):
            tempdir = tempfile.mkdtemp(prefix="sv_merge_")
            with zipfile.ZipFile(zip_or_db_path, "r") as z:
                z.extractall(tempdir)
            extracted_root = tempdir
            source_db_path = _open_incoming_db(extracted_root)

        incoming_db = Database(source_db_path)
        inc_conn = incoming_db.conn
        inc_table = incoming_db.table
        inc_cols  = incoming_db.cols

        incoming = _rows_map(inc_conn, inc_table, inc_cols)

        loc_conn = db.conn
        loc_table = db.table
        loc_cols  = db.cols

        local = _rows_map(loc_conn, loc_table, loc_cols)

        imgs_root = _best_image_source(extracted_root or os.path.dirname(source_db_path))
        idcol = (loc_cols.get("id") or "id")

        for rid, rin in incoming.items():
            rloc = local.get(rid)

            # --- TOMBSONE HANDLING (changed) ---
            if rin.get("deleted_at"):
                # Only apply delete if the item exists locally.
                if rloc is not None:
                    # and only if the incoming tombstone is not older than our local update
                    if not rloc.get("updated_at") or rin["deleted_at"] >= (rloc.get("updated_at") or 0):
                        _soft_delete(loc_conn, loc_table, idcol, rid, rin["deleted_at"])
                        stats["deleted"] += 1
                    else:
                        stats["skipped"] += 1
                else:
                    # Unknown item → ignore deletion
                    stats["skipped"] += 1
                continue

            # Insert
            if rloc is None:
                src_img = _resolve_incoming_image_path(rin, imgs_root, source_db_path)
                if src_img and os.path.exists(src_img):
                    name, h = _copy_image_into_local(src_img, db, rin.get("image_name"))
                    rin["image_name"], rin["image_hash"] = name, h
                    stats["images_copied"] += 1
                if not rin.get("updated_at"):
                    rin["updated_at"] = _now_ms()
                _upsert_local(loc_conn, loc_table, loc_cols, rin)
                stats["inserted"] += 1
                continue

            # Both exist → updated_at comparison
            in_upd = rin.get("updated_at") or 0
            lc_upd = rloc.get("updated_at") or 0
            if in_upd > lc_upd:
                src_img = _resolve_incoming_image_path(rin, imgs_root, source_db_path)
                if src_img and os.path.exists(src_img):
                    in_hash = rin.get("image_hash") or _sha1(src_img)
                    lc_hash = rloc.get("image_hash")
                    if in_hash and in_hash != lc_hash:
                        name, h = _copy_image_into_local(src_img, db, rin.get("image_name"))
                        rin["image_name"], rin["image_hash"] = name, h
                        stats["images_copied"] += 1
                _upsert_local(loc_conn, loc_table, loc_cols, rin)
                stats["updated"] += 1
            elif in_upd == lc_upd:
                changed = False
                merged = dict(rloc)
                for key in ("sold_date", "sold_price", "name", "location", "buy_price"):
                    v_in = rin.get(key)
                    v_lc = rloc.get(key)
                    if v_in is not None and (v_lc is None or str(v_lc) == "" or v_in != v_lc):
                        merged[key] = v_in
                        changed = True
                src_img = _resolve_incoming_image_path(rin, imgs_root, source_db_path)
                if src_img and os.path.exists(src_img):
                    in_hash = rin.get("image_hash") or _sha1(src_img)
                    lc_hash = rloc.get("image_hash")
                    if in_hash and in_hash != lc_hash:
                        name, h = _copy_image_into_local(src_img, db, rin.get("image_name"))
                        merged["image_name"], merged["image_hash"] = name, h
                        changed = True
                        stats["images_copied"] += 1
                if changed:
                    merged["id"] = rid
                    merged["updated_at"] = _now_ms()
                    _upsert_local(loc_conn, loc_table, loc_cols, merged)
                    stats["updated"] += 1
                else:
                    stats["skipped"] += 1
            else:
                stats["skipped"] += 1

        loc_conn.commit()
        return stats
    finally:
        if tempdir:
            shutil.rmtree(tempdir, ignore_errors=True)
