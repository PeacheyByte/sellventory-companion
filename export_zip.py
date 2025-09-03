# export_zip.py
import os, json, shutil, sqlite3, zipfile, tempfile, time
from typing import Dict, Optional, Set
from database import Database, DBError

def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def _gather_referenced_images(db: Database) -> Set[str]:
    """
    Returns absolute file paths for images that exist on disk and are referenced by the DB.
    Prefers image_name (fixed images dir). Falls back to legacy path basename next to DB.
    """
    paths: Set[str] = set()
    if not db.table:
        return paths

    # Prefer modern columns if present
    cols = db.cols
    has_image_name = bool(cols.get("image_name"))
    has_legacy     = bool(cols.get("image"))

    select_cols = []
    if has_image_name: select_cols.append("image_name")
    if has_legacy:     select_cols.append(f"{cols['image']} AS legacy_path")

    if not select_cols:
        return paths

    sql = f"SELECT {', '.join(select_cols)} FROM {db.table}"
    for r in db.conn.execute(sql):
        # image_name path inside fixed images dir
        if has_image_name and r["image_name"]:
            p = os.path.join(db.images_dir(), r["image_name"])
            if os.path.exists(p): paths.add(p)

        # legacy fallback (basename next to DB)
        if has_legacy and "legacy_path" in r.keys() and r["legacy_path"]:
            base = os.path.basename(r["legacy_path"])
            p2 = os.path.join(os.path.dirname(db.db_path), base)
            if os.path.exists(p2): paths.add(p2)

    return paths

def _safe_copy_db(src: str, dest: str) -> None:
    """
    Make a compact, consistent copy of the SQLite DB for the export.
    """
    # Approach: just copy the file; keep it simple & robust.
    shutil.copy2(src, dest)

def export_zip_from_local(db: Database, out_zip_path: str) -> Dict[str, int]:
    """
    Writes a ZIP containing:
      - the SQLite DB file at the ZIP root (same filename as local)
      - images/ (only referenced images)
      - manifest.json with metadata
    Returns stats dict.
    """
    if not db or not db.table:
        raise DBError("No database open.")

    tmpdir = tempfile.mkdtemp(prefix="sv_export_")
    stats = {"images": 0, "db_bytes": 0, "image_bytes": 0}

    try:
        # 1) Copy DB
        db_name = os.path.basename(db.db_path)
        db_out  = os.path.join(tmpdir, db_name)
        _safe_copy_db(db.db_path, db_out)
        stats["db_bytes"] = os.path.getsize(db_out)

        # 2) Copy referenced images to tmp/images/
        export_images_dir = os.path.join(tmpdir, "images")
        os.makedirs(export_images_dir, exist_ok=True)

        images = _gather_referenced_images(db)
        for abs_src in images:
            name = os.path.basename(abs_src)  # unique enough (we name by hash typically)
            dest = os.path.join(export_images_dir, name)
            if not os.path.exists(dest):
                shutil.copy2(abs_src, dest)
                stats["images"] += 1
                stats["image_bytes"] += os.path.getsize(dest)

        # 3) Manifest
        manifest = {
            "tool": "Sellventory-Companion",
            "version": 1,
            "exported_at": _now_iso(),
            "db_filename": db_name,
            "images_dir": "images",
            "counts": stats,
        }
        with open(os.path.join(tmpdir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        # 4) Write ZIP
        os.makedirs(os.path.dirname(out_zip_path) or ".", exist_ok=True)
        with zipfile.ZipFile(out_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            # db at root
            z.write(db_out, db_name)
            # images/
            if os.path.isdir(export_images_dir):
                for fname in os.listdir(export_images_dir):
                    z.write(os.path.join(export_images_dir, fname), os.path.join("images", fname))
            # manifest
            z.write(os.path.join(tmpdir, "manifest.json"), "manifest.json")

        return stats
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
