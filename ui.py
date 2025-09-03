# ui.py
import os, shutil, zipfile, csv, io, sys, datetime as dt
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from PIL import Image, ImageTk, ImageOps

from database import Database, DBError
from settings import load_config, save_config, ensure_app_dir, APP_DIR

# optional Excel export
try:
    from openpyxl.workbook import Workbook
except Exception:
    Workbook = None

# optional date picker
try:
    from tkcalendar import DateEntry
except Exception:
    DateEntry = None  # fallback to Entry

# optional charts
try:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
except Exception:
    Figure = None
    FigureCanvasTkAgg = None

THUMB_W, THUMB_H = 160, 120
BASE_PREV_W, BASE_PREV_H = 360, 270
CARD_W = 260

LIB_DIR = os.path.join(APP_DIR, "library")

PALETTE_LIGHT = {"bg":"#ffffff","fg":"#111111","muted":"#555555","card":"#f2f2f2","border":"#d0d0d0"}
PALETTE_DARK  = {"bg":"#141414","fg":"#eaeaea","muted":"#b0b0b0","card":"#242424","border":"#2c2c2c"}

class SellventoryApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Sellventory Companion")
        self.root.geometry("1180x760")
        self.root.minsize(1000, 640)

        self.style = ttk.Style()
        try: self.style.theme_use("clam")
        except tk.TclError: pass
        for k in ("TButton","TEntry","TCombobox","TLabel","TMenubutton","TFrame","Treeview"):
            self.style.configure(k, padding=4)

        self.theme = tk.StringVar(value="light")
        self.palette = dict(PALETTE_LIGHT)

        self.db: Database|None = None
        self.items = []
        self.filtered = []
        self.view_mode = tk.StringVar(value="gallery")
        self.thumb_cache = {}

        self._zoom = 1.0
        self._prev_w = BASE_PREV_W
        self._prev_h = BASE_PREV_H

        ensure_app_dir()
        os.makedirs(LIB_DIR, exist_ok=True)

        self._build_menu()
        self._build_layout()
        self._apply_theme()
        self._refresh_filters()

        cfg = load_config()
        if cfg.library_dir and self._has_db(cfg.library_dir):
            try:
                self.db = Database.from_folder(cfg.library_dir)
                self.reload_items()
            except Exception:
                pass

    # ---------------- Menus ----------------
    def _build_menu(self):
        m = tk.Menu(self.root); self.root.config(menu=m)

        filem = tk.Menu(m, tearoff=0)
        filem.add_command(label="Import .zip", command=self.on_import_zip)
        filem.add_command(label="Import Folder", command=self.on_import_folder)
        filem.add_separator()
        filem.add_command(label="Export ZIP…", command=self.on_export_zip)
        filem.add_command(label="Export CSV…", command=self.on_export_csv)
        filem.add_command(label="Export Excel (.xlsx)…", command=self.on_export_xlsx)
        filem.add_separator()
        filem.add_command(label="Refresh", command=self.reload_items)
        filem.add_separator()
        filem.add_command(label="Exit", command=self.root.quit)
        m.add_cascade(label="File", menu=filem)

        viewm = tk.Menu(m, tearoff=0)
        viewm.add_radiobutton(label="Gallery", variable=self.view_mode, value="gallery", command=self._render_view)
        viewm.add_radiobutton(label="List",    variable=self.view_mode, value="list",    command=self._render_view)
        viewm.add_separator()
        viewm.add_radiobutton(label="Light", variable=self.theme, value="light", command=self._apply_theme)
        viewm.add_radiobutton(label="Dark",  variable=self.theme, value="dark",  command=self._apply_theme)
        m.add_cascade(label="View", menu=viewm)

        toolsm = tk.Menu(m, tearoff=0)
        toolsm.add_command(label="Simple Report…", command=self.on_simple_report)
        toolsm.add_separator()
        toolsm.add_command(label="Manage Locations…", command=self.on_manage_locations)
        toolsm.add_command(label="Manage Tags…", command=self.on_manage_tags)
        m.add_cascade(label="Tools", menu=toolsm)

        helpm = tk.Menu(m, tearoff=0)
        helpm.add_command(label="About", command=lambda: messagebox.showinfo(
            "Sellventory Companion", "Desktop edit-only companion.\nPhone app creates entries via camera."))
        m.add_cascade(label="Help", menu=helpm)

    # ---------------- Layout ----------------
    def _build_layout(self):
        self.main = ttk.Frame(self.root, padding=(10,10,10,10))
        self.main.pack(fill="both", expand=True)
        self.main.columnconfigure(0, weight=1)
        self.main.rowconfigure(2, weight=1)

        bar = ttk.Frame(self.main); bar.grid(row=0, column=0, sticky="ew", pady=(0,10))
        ttk.Button(bar, text="Dashboard", command=self.show_dashboard_embed).pack(side="left")
        ttk.Button(bar, text="Edit", command=self.on_edit_inline).pack(side="left", padx=(6,12))

        ttk.Label(bar, text="Search:").pack(side="left")
        self.search_var = tk.StringVar()
        ttk.Entry(bar, textvariable=self.search_var, width=28).pack(side="left", padx=(6,6))
        ttk.Button(bar, text="Clear", command=lambda:(self.search_var.set(""), self.apply_filters())).pack(side="left", padx=(0,12))

        ttk.Label(bar, text="View:").pack(side="left")
        ttk.Radiobutton(bar, text="Gallery", variable=self.view_mode, value="gallery", command=self._render_view).pack(side="left")
        ttk.Radiobutton(bar, text="List",    variable=self.view_mode, value="list",    command=self._render_view).pack(side="left", padx=(0,12))

        ttk.Label(bar, text="Location:").pack(side="left")
        self.storage_var = tk.StringVar(value="All")
        self.storage_cb = ttk.Combobox(bar, textvariable=self.storage_var, state="readonly", width=18)
        self.storage_cb.pack(side="left", padx=(6,12))

        ttk.Label(bar, text="Tag:").pack(side="left")
        self.tag_var = tk.StringVar(value="All")
        self.tag_cb = ttk.Combobox(bar, textvariable=self.tag_var, state="readonly", width=18)
        self.tag_cb.pack(side="left")

        self.search_var.trace_add("write", lambda *_: self.apply_filters())
        self.storage_cb.bind("<<ComboboxSelected>>", lambda _e: self.apply_filters())
        self.tag_cb.bind("<<ComboboxSelected>>",     lambda _e: self.apply_filters())

        self.content = ttk.Panedwindow(self.main, orient="horizontal")
        self.content.grid(row=2, column=0, sticky="nsew")

        self.left_wrap = ttk.Frame(self.content)
        self.left_wrap.columnconfigure(0, weight=1)
        self.left_wrap.rowconfigure(0, weight=1)
        self.content.add(self.left_wrap, weight=3)

        self.right_wrap = ttk.Frame(self.content)
        self.right_wrap.columnconfigure(0, weight=1)
        self.right_wrap.rowconfigure(0, weight=1)
        self.content.add(self.right_wrap, weight=4)

        # List (left side)
        self.list_wrap = ttk.Frame(self.left_wrap)
        self.list_wrap.grid(row=0, column=0, sticky="nsew")
        self.list_wrap.columnconfigure(0, weight=1)
        self.list_wrap.rowconfigure(0, weight=1)

        cols = ("local_id","title","storage","dateBought","boughtPrice","salePrice","soldPrice","soldDate")
        headers = ("ID","Title","Location","Date Bought","Bought Price","Sale Price","Sold Price","Sold Date")
        self.tree = ttk.Treeview(self.list_wrap, columns=cols, show="headings", selectmode="browse")
        for c, h, w in zip(cols, headers, (60,260,160,110,100,100,100,110)):
            self.tree.heading(c, text=h, command=lambda col=c: self._sort_by(col))
            self.tree.column(c, width=w, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        ttk.Scrollbar(self.list_wrap, orient="vertical", command=self.tree.yview).grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<ButtonRelease-1>", lambda e: self._update_editor_selection())
        self.tree.bind("<KeyRelease-Up>",   lambda e: self._update_editor_selection())
        self.tree.bind("<KeyRelease-Down>", lambda e: self._update_editor_selection())

        # Gallery
        self.gallery_wrap = ttk.Frame(self.left_wrap)
        self.gallery_canvas = tk.Canvas(self.gallery_wrap, highlightthickness=0)
        self.gallery_scroll = ttk.Scrollbar(self.gallery_wrap, orient="vertical", command=self.gallery_canvas.yview)
        self.gallery_canvas.configure(yscrollcommand=self.gallery_scroll.set)
        self.gallery_canvas.pack(side="left", fill="both", expand=True)
        self.gallery_scroll.pack(side="right", fill="y")
        self.gallery_inner = ttk.Frame(self.gallery_canvas)
        self.gallery_canvas.create_window((0,0), window=self.gallery_inner, anchor="nw")
        self.gallery_inner.bind("<Configure>", lambda _e: self.gallery_canvas.configure(scrollregion=self.gallery_canvas.bbox("all")))
        self.gallery_wrap.bind("<Configure>", lambda _e: self._render_view())

        # Right host (editor / dashboard)
        self.editor_host = ttk.Frame(self.right_wrap, padding=(0,0,0,0))
        self.editor_host.grid(row=0, column=0, sticky="nsew")

        self._render_view()

    # ---------------- Theme ----------------
    def _apply_theme(self):
        self.palette = dict(PALETTE_LIGHT if self.theme.get()=="light" else PALETTE_DARK)
        bg = self.palette["bg"]; fg = self.palette["fg"]

        self.root.configure(bg=bg)
        self.style.configure("TFrame", background=bg)
        self.style.configure("TLabel", background=bg, foreground=fg)
        self.style.configure("TButton", foreground=fg)
        self.style.configure("Card.TFrame", relief="groove", background=self.palette["card"])

        self.gallery_canvas.configure(bg=bg)
        self.style.configure("Treeview", background=bg, fieldbackground=bg, foreground=fg)
        self.style.map("Treeview",
            background=[("selected", "#4479ff" if self.theme.get()=="light" else "#3355cc")],
            foreground=[("selected", "#ffffff")],
        )

        self._render_view()
        self._update_editor_selection()

    # ---------------- Import/export ----------------
    def on_export_zip(self):
        if not os.path.isdir(LIB_DIR) or not self._has_db(LIB_DIR):
            messagebox.showwarning("Export ZIP", "No imported library to export yet."); return
        path = filedialog.asksaveasfilename(defaultextension=".zip", filetypes=[("Zip","*.zip")])
        if not path: return
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(os.path.join(LIB_DIR, "sellventory.db"), "sellventory.db")
            img_dir = os.path.join(LIB_DIR, "images")
            if os.path.isdir(img_dir):
                for root, _, files in os.walk(img_dir):
                    for fn in files:
                        ap = os.path.join(root, fn)
                        rp = os.path.relpath(ap, LIB_DIR)
                        z.write(ap, rp)
        messagebox.showinfo("Export", "ZIP export complete.")

    def on_export_csv(self):
        if not self.db: return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV","*.csv")])
        if not path: return
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["local_id","title","description","storage","dateBought","bought","sale","sold","soldDate","tags","image_name"])
            for it in (self.items or []):
                w.writerow([
                    it.get("local_id"), it.get("title",""), it.get("description",""), it.get("storage",""),
                    it.get("dateBought",""),
                    (it.get("boughtPriceCents") or 0)/100.0,
                    (it.get("salePriceCents")/100.0) if it.get("salePriceCents") is not None else "",
                    (it.get("soldPriceCents")/100.0) if it.get("soldPriceCents") is not None else "",
                    it.get("soldDate",""), it.get("tags",""), it.get("image_name",""),
                ])
        messagebox.showinfo("Export", "CSV export complete.")

    def on_export_xlsx(self):
        if not self.db: return
        if Workbook is None:
            messagebox.showwarning("Excel export", "openpyxl not installed."); return
        path = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel","*.xlsx")])
        if not path: return
        wb = Workbook(); ws = wb.active; ws.title = "Items"
        headers = ["local_id","title","description","storage","dateBought","bought","sale","sold","soldDate","tags","image_name"]
        ws.append(headers)
        for it in (self.items or []):
            ws.append([
                it.get("local_id"), it.get("title",""), it.get("description",""), it.get("storage",""),
                it.get("dateBought",""),
                (it.get("boughtPriceCents") or 0)/100.0,
                (it.get("salePriceCents")/100.0) if it.get("salePriceCents") is not None else None,
                (it.get("soldPriceCents")/100.0) if it.get("soldPriceCents") is not None else None,
                it.get("soldDate",""), it.get("tags",""), it.get("image_name",""),
            ])
        wb.save(path)
        messagebox.showinfo("Export", "Excel export complete.")

    # ---------------- Data & Filters ----------------
    def reload_items(self):
        if not self.db: return
        self.thumb_cache.clear()
        try:
            self.items = self.db.list_items()
        except Exception as e:
            messagebox.showerror("Load failed", str(e)); return
        self._refresh_filters()
        self.apply_filters()

    def _refresh_filters(self):
        storages = ["All"]; tags = ["All"]
        if self.db:
            storages += self.db.distinct_storages()
            tags     += self.db.tag_suggestions()
        self.storage_cb.configure(values=storages)
        self.tag_cb.configure(values=tags)
        if self.storage_var.get() not in storages: self.storage_var.set("All")
        if self.tag_var.get() not in tags: self.tag_var.set("All")

    def apply_filters(self):
        q  = (self.search_var.get() or "").strip().lower()
        st = self.storage_var.get(); tg = self.tag_var.get()

        def match(it):
            blob = " ".join([str(it.get("local_id","")), it.get("title",""),
                             it.get("storage",""), it.get("dateBought",""),
                             it.get("tags","")]).lower()
            if q and q not in blob: return False
            if st != "All" and (it.get("storage") or "") != st: return False
            if tg != "All":
                tset = {t.strip() for t in (it.get("tags") or "").split(",") if t.strip()}
                if tg not in tset: return False
            return True

        self.filtered = [it for it in self.items if match(it)]
        self._render_view()
        self._update_editor_selection()

    # ---------------- View rendering ----------------
    def _render_view(self):
        for w in (self.list_wrap, self.gallery_wrap): w.grid_remove()
        if self.view_mode.get() == "list":
            self.list_wrap.grid(row=0, column=0, sticky="nsew")
            self._render_list()
        else:
            self.gallery_wrap.grid(row=0, column=0, sticky="nsew")
            self._render_gallery()

    def _render_list(self):
        self.tree.delete(*self.tree.get_children())
        for it in self.filtered:
            self.tree.insert("", "end", iid=str(it["local_id"]), values=(
                it["local_id"], it.get("title",""), it.get("storage",""), it.get("dateBought",""),
                self._fmt_money(it.get("boughtPriceCents")),
                self._fmt_money(it.get("salePriceCents")),
                self._fmt_money(it.get("soldPriceCents")),
                it.get("soldDate",""),
            ))
        kids = self.tree.get_children()
        if kids:
            self.tree.selection_set(kids[0]); self.tree.see(kids[0])

    def _render_gallery(self):
        for w in self.gallery_inner.winfo_children(): w.destroy()
        wrap_w = self.gallery_wrap.winfo_width() or self.root.winfo_width()
        cols = max(1, wrap_w // (CARD_W + 20))

        def open_inline(local_id, _e=None):
            # stay in Gallery; just update right-side editor
            self._open_inline_editor_by_id(local_id)

        for idx, it in enumerate(self.filtered):
            r, c = divmod(idx, cols)
            frame = ttk.Frame(self.gallery_inner, style="Card.TFrame", padding=6)
            frame.grid(row=r, column=c, padx=8, pady=8, sticky="n")

            cnv = tk.Canvas(frame, width=THUMB_W, height=THUMB_H,
                            highlightthickness=1, bg=self.palette["bg"], highlightbackground=self.palette["border"])
            cnv.grid(row=0, column=0, sticky="n")
            img = self._thumb_for(it)
            if img: cnv.create_image(THUMB_W//2, THUMB_H//2, image=img, anchor="center")
            else:   cnv.create_text(THUMB_W//2, THUMB_H//2, text="(no image)", fill=self.palette["muted"])

            ttk.Label(frame, text=f"{it['local_id']} - {it.get('title','')}").grid(row=1, column=0, sticky="w", pady=(6,0))
            ttk.Label(frame, text=it.get("storage",""), foreground=self.palette["muted"]).grid(row=2, column=0, sticky="w")

            frame.bind("<Double-1>", lambda e, lid=it['local_id']: open_inline(lid))
            cnv.bind("<Double-1>",  lambda e, lid=it['local_id']: open_inline(lid))

    # --------- selection helpers ---------
    def _on_tree_select(self, _evt):
        self._update_editor_selection()

    def _update_editor_selection(self):
        if not self.db:
            self._clear_editor(); 
            return
        sel = self.tree.selection()
        if not sel:
            self._clear_editor(); 
            return
        try:
            lid = int(sel[0])
        except Exception:
            self._clear_editor(); 
            return
        self._open_inline_editor_by_id(lid)

    # ---------------- Inline Editor (VERTICAL: image on top, fields below) ----------------
    def _clear_editor(self):
        for w in self.editor_host.winfo_children():
            w.destroy()

    def on_edit_inline(self):
        self._update_editor_selection()

    def _open_inline_editor_by_id(self, local_id: int):
        if not self.db: return
        it = self.db.get_item(local_id)
        if not it: return

        self._clear_editor()
        editor = ttk.Frame(self.editor_host)
        editor.grid(row=0, column=0, sticky="nsew")
        editor.columnconfigure(0, weight=1)   # single column layout

        # top tools row
        tools = ttk.Frame(editor)
        tools.grid(row=0, column=0, sticky="ew", pady=(0,6))
        ttk.Label(tools, text="Details").pack(side="left")
        ttk.Button(tools, text="–", width=3, command=lambda:self._zoom_change(-0.1, editor, it)).pack(side="left", padx=(8,2))
        ttk.Button(tools, text="Reset", command=lambda:self._zoom_reset(editor, it)).pack(side="left", padx=2)
        ttk.Button(tools, text="+", width=3, command=lambda:self._zoom_change(+0.1, editor, it)).pack(side="left", padx=2)

        # image block
        img_frame = ttk.Frame(editor)
        img_frame.grid(row=1, column=0, sticky="n", padx=(0,0))
        self.preview = tk.Canvas(img_frame, width=self._prev_w, height=self._prev_h, highlightthickness=1)
        self.preview.grid(row=0, column=0, sticky="n")
        self._render_preview_image(it)

        # fields block (BELOW image)
        fields = ttk.Frame(editor)
        fields.grid(row=2, column=0, sticky="nsew", pady=(8,0))
        fields.columnconfigure(1, weight=1)

        row=0
        def L(t): ttk.Label(fields, text=t).grid(row=row, column=0, sticky="w", pady=2)
        def E(var, w=28):
            nonlocal row
            e = ttk.Entry(fields, textvariable=var, width=w)
            e.grid(row=row, column=1, sticky="ew", pady=2); row+=1; return e

        L("Title:");          v_title = tk.StringVar(value=it.get("title","")); E(v_title, 48)
        L("Description:");    v_desc  = tk.StringVar(value=it.get("description","")); E(v_desc, 48)

        L("Location:")
        loc_vals = [""] + (self.db.distinct_storages() if self.db else [])
        v_stor  = tk.StringVar(value=it.get("storage",""))
        loc_cb = ttk.Combobox(fields, textvariable=v_stor, state="readonly", values=loc_vals, width=32)
        loc_cb.grid(row=row, column=1, sticky="w", pady=2); row+=1

        L("Tags:")
        tag_line = ttk.Frame(fields); tag_line.grid(row=row, column=1, sticky="ew", pady=2)
        v_tags = tk.StringVar(value=it.get("tags",""))
        tag_disp = ttk.Entry(tag_line, textvariable=v_tags, state="readonly")
        tag_disp.pack(side="left", fill="x", expand=True)
        ttk.Button(tag_line, text="Choose…", command=lambda:self._choose_tags(v_tags)).pack(side="left", padx=6)
        row+=1

        def money_var_from_cents(c):
            if c is None: return tk.StringVar(value="")
            return tk.StringVar(value=f"{(c or 0)/100:.2f}")
        def wire_money(label, key):
            nonlocal row
            L(label)
            var = money_var_from_cents(it.get(key))
            ent = ttk.Entry(fields, textvariable=var, width=14)
            ent.grid(row=row, column=1, sticky="w", pady=2)
            def on_key(_e):
                s = "".join(ch for ch in var.get() if ch.isdigit())
                if not s: var.set("")
                else: var.set(f"{int(s)/100:.2f}")
            ent.bind("<KeyRelease>", on_key)
            row+=1
            return var

        v_b  = wire_money("Bought $:", "boughtPriceCents")
        v_s  = wire_money("Sale $:",   "salePriceCents")
        v_sp = wire_money("Sold $:",   "soldPriceCents")

        L("Date Bought yyyy-mm-dd:")
        v_db = tk.StringVar(value=it.get("dateBought",""))
        if DateEntry:
            de = DateEntry(fields, width=18, date_pattern="yyyy-mm-dd")
            try:
                if v_db.get():
                    y,m,d = map(int, v_db.get().split("-")); de.set_date(dt.date(y,m,d))
            except Exception: pass
            de.grid(row=row, column=1, sticky="w", pady=2)
            de.bind("<<DateEntrySelected>>", lambda _e: v_db.set(de.get_date().strftime("%Y-%m-%d")))
        else:
            ttk.Entry(fields, textvariable=v_db, width=18).grid(row=row, column=1, sticky="w", pady=2)
        row+=1

        L("Sold Date yyyy-mm-dd:")
        v_sd = tk.StringVar(value=it.get("soldDate",""))
        if DateEntry:
            de2 = DateEntry(fields, width=18, date_pattern="yyyy-mm-dd")
            try:
                if v_sd.get() and v_sd.get().lower()!="none":
                    y,m,d = map(int, v_sd.get().split("-")); de2.set_date(dt.date(y,m,d))
            except Exception: pass
            de2.grid(row=row, column=1, sticky="w", pady=2)
            de2.bind("<<DateEntrySelected>>", lambda _e: v_sd.set(de2.get_date().strftime("%Y-%m-%d")))
        else:
            ttk.Entry(fields, textvariable=v_sd, width=18).grid(row=row, column=1, sticky="w", pady=2)
        row+=1

        def auto_sold_date(*_a):
            val = v_sp.get().strip()
            if val and (not v_sd.get().strip() or v_sd.get().lower()=="none"):
                v_sd.set(dt.date.today().strftime("%Y-%m-%d"))
                if DateEntry and 'de2' in locals():
                    try: de2.set_date(dt.date.today())
                    except Exception: pass
        v_sp.trace_add("write", auto_sold_date)

        btns = ttk.Frame(fields); btns.grid(row=row, column=0, columnspan=2, pady=(8,0), sticky="w"); row+=1
        def save():
            try:
                upd = {
                    "title": v_title.get().strip(),
                    "description": v_desc.get().strip(),
                    "storage": v_stor.get().strip(),
                    "tags": v_tags.get().strip(),
                    "dateBought": v_db.get().strip(),
                    "soldDate": v_sd.get().strip(),
                }
                def cents_of(var):
                    s = var.get().strip()
                    if not s: return None
                    try: return int(round(float(s)*100))
                    except Exception: return None
                upd["boughtPriceCents"] = cents_of(v_b) or 0
                upd["salePriceCents"]   = cents_of(v_s)
                upd["soldPriceCents"]   = cents_of(v_sp)

                self.db.update_item(local_id, upd)
                self.reload_items()
                if self.tree.exists(str(local_id)):
                    self.tree.selection_set(str(local_id))
            except Exception as e:
                messagebox.showerror("Save failed", str(e))
        ttk.Button(btns, text="Save", command=save).pack(side="left")
        ttk.Button(btns, text="Close", command=self._clear_editor).pack(side="left", padx=6)

    def _zoom_reset(self, editor, item):
        self._zoom = 1.0
        self._prev_w, self._prev_h = BASE_PREV_W, BASE_PREV_H
        self.preview.config(width=self._prev_w, height=self._prev_h)
        self._render_preview_image(item)

    def _zoom_change(self, delta, editor, item):
        self._zoom = max(0.5, min(2.5, self._zoom + delta))
        self._prev_w = int(BASE_PREV_W * self._zoom)
        self._prev_h = int(BASE_PREV_H * self._zoom)
        self.preview.config(width=self._prev_w, height=self._prev_h)
        self._render_preview_image(item)

    def _render_preview_image(self, item):
        self.preview.delete("all")
        path = self.db.image_path(item.get("image_name")) if self.db else None
        if not path or not os.path.exists(path):
            self.preview.create_text(self._prev_w//2, self._prev_h//2, text="(no image)")
            return
        try:
            im = Image.open(path)
            im = ImageOps.exif_transpose(im)
            im.thumbnail((self._prev_w, self._prev_h))
            self._thumb_img = ImageTk.PhotoImage(im)
            self.preview.create_image(self._prev_w//2, self._prev_h//2, image=self._thumb_img, anchor="center")
        except Exception:
            self.preview.create_text(self._prev_w//2, self._prev_h//2, text="(image error)")

    # ---------------- Tags chooser ----------------
    def _choose_tags(self, v_tags: tk.StringVar):
        if not self.db: return
        all_tags = self.db.tag_suggestions()
        current = {t.strip() for t in (v_tags.get() or "").split(",") if t.strip()}

        win = tk.Toplevel(self.root); win.title("Tags"); win.transient(self.root)
        frm = ttk.Frame(win, padding=10); frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="Select tags:").pack(anchor="w", pady=(0,6))

        checks = []
        for t in all_tags:
            var = tk.BooleanVar(value=(t in current))
            cb = ttk.Checkbutton(frm, text=t, variable=var)
            cb.pack(anchor="w")
            checks.append((t, var))

        btns = ttk.Frame(frm); btns.pack(fill="x", pady=(8,0))
        def ok():
            chosen = [t for t,v in checks if v.get()]
            v_tags.set(", ".join(chosen))
            win.destroy()
        ttk.Button(btns, text="OK", command=ok).pack(side="left")
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="left", padx=6)

    # ---------------- Dashboard (embedded) ----------------
    def show_dashboard_embed(self):
        self._clear_editor()
        dash = ttk.Frame(self.editor_host)
        dash.grid(row=0, column=0, sticky="nsew")
        dash.columnconfigure(0, weight=1)

        filt = ttk.Frame(dash); filt.grid(row=0, column=0, sticky="ew", pady=(0,6))
        filt.columnconfigure(5, weight=1)

        ttk.Label(filt, text="Date From:").grid(row=0, column=0, sticky="w")
        self.df_var = tk.StringVar()
        self.dt_from = self._date_widget(filt, self.df_var); self.dt_from.grid(row=0, column=1, sticky="w", padx=(6,12))

        ttk.Label(filt, text="Date To:").grid(row=0, column=2, sticky="w")
        self.dt_var = tk.StringVar()
        self.dt_to = self._date_widget(filt, self.dt_var); self.dt_to.grid(row=0, column=3, sticky="w", padx=(6,12))

        ttk.Button(filt, text="Apply", command=self._refresh_dashboard).grid(row=0, column=4, sticky="w")
        ttk.Button(filt, text="Last 12 Months", command=self._set_last_12_months).grid(row=0, column=5, sticky="w", padx=(8,0))

        cards = ttk.Frame(dash); cards.grid(row=1, column=0, sticky="ew", pady=(2,6))
        for i in range(4): cards.columnconfigure(i, weight=1)

        self._card_quant = self._make_card_group(cards, "Quantities", 0)
        self._card_totals = self._make_card_group(cards, "Totals", 1)
        self._card_month  = self._make_card_group(cards, "This Month", 2)
        self._card_prev   = self._make_card_group(cards, "Previous Month", 3)

        charts = ttk.Frame(dash); charts.grid(row=2, column=0, sticky="nsew")
        dash.rowconfigure(2, weight=1)
        charts.columnconfigure(0, weight=1)

        if Figure is None:
            ttk.Label(charts, text="Install 'matplotlib' to see charts (pip install matplotlib).").grid(row=0, column=0, sticky="w")
            self.fig = self.canvas = self.fig2 = self.canvas2 = None
        else:
            self.fig = Figure(figsize=(6,2.6), dpi=100, facecolor=(0,0,0,0))
            self.ax = self.fig.add_subplot(111)
            self.ax.set_title("Monthly Trends"); self.ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.5); self.ax.axhline(0, color="black", linewidth=0.6)
            self.canvas = FigureCanvasTkAgg(self.fig, master=charts)
            self.canvas.get_tk_widget().grid(row=0, column=0, sticky="ew")

            self.fig2 = Figure(figsize=(6,2.2), dpi=100, facecolor=(0,0,0,0))
            self.ax2 = self.fig2.add_subplot(111)
            self.ax2.set_title("Monthly Profit"); self.ax2.grid(True, linestyle="--", linewidth=0.5, alpha=0.5); self.ax2.axhline(0, color="black", linewidth=0.6)
            self.canvas2 = FigureCanvasTkAgg(self.fig2, master=charts)
            self.canvas2.get_tk_widget().grid(row=1, column=0, sticky="ew", pady=(6,0))

        self._set_last_12_months()
        self._refresh_dashboard()

    def _date_widget(self, parent, var):
        if DateEntry:
            de = DateEntry(parent, width=12, date_pattern="yyyy-mm-dd")
            de.bind("<<DateEntrySelected>>", lambda _e: var.set(de.get_date().strftime("%Y-%m-%d")))
            return de
        else:
            return ttk.Entry(parent, textvariable=var, width=12)

    def _set_last_12_months(self):
        today = dt.date.today()
        start = (today.replace(day=1) - dt.timedelta(days=365)).replace(day=1)
        end = today
        if DateEntry and isinstance(self.dt_from, DateEntry):
            self.dt_from.set_date(start)
            self.dt_to.set_date(end)
        self.df_var.set(start.strftime("%Y-%m-%d"))
        self.dt_var.set(end.strftime("%Y-%m-%d"))

    def _make_card_group(self, parent, title, col):
        frame = ttk.Frame(parent, style="Card.TFrame", padding=8)
        frame.grid(row=0, column=col, sticky="nsew", padx=6)
        parent.columnconfigure(col, weight=1)
        ttk.Label(frame, text=title).grid(row=0, column=0, sticky="w", pady=(0,6))
        inner = ttk.Frame(frame); inner.grid(row=1, column=0, sticky="ew")
        for i in range(2): inner.columnconfigure(i, weight=1)
        return {"frame":frame, "inner":inner}

    def _fill_card(self, group, rows):
        inner = group["inner"]
        for w in inner.grid_slaves(): w.destroy()
        r=0
        for label, value in rows:
            ttk.Label(inner, text=label).grid(row=r, column=0, sticky="w")
            ttk.Label(inner, text=value, font=("TkDefaultFont", 10, "bold")).grid(row=r, column=1, sticky="e")
            r+=1

    def _refresh_dashboard(self):
        if not self.db: return
        def parse(s):
            try:
                y,m,d = map(int, s.split("-")); return dt.date(y,m,d)
            except Exception:
                return None
        dfrom = parse(self.df_var.get()) if hasattr(self, "df_var") else None
        dto   = parse(self.dt_var.get()) if hasattr(self, "dt_var") else None

        items = list(self.items)

        total = len(items)
        sold   = sum(1 for i in items if (i.get("soldDate") or "").strip() and (i.get("soldPriceCents") is not None))
        unsold = total - sold
        spent   = sum((i.get("boughtPriceCents") or 0) for i in items)/100.0
        revenue = sum((i.get("soldPriceCents") or 0) for i in items)/100.0
        profit  = sum(((i.get("soldPriceCents") or 0) - (i.get("boughtPriceCents") or 0)) for i in items)/100.0

        self._fill_card(self._card_quant, [("Items", f"{total}"), ("Sold", f"{sold}"), ("Unsold", f"{unsold}")])
        self._fill_card(self._card_totals, [("Spent", f"${spent:,.2f}"), ("Revenue", f"${revenue:,.2f}"), ("Profit", f"${profit:,.2f}")])

        today = dt.date.today()
        cur_first = today.replace(day=1)
        prev_last = cur_first - dt.timedelta(days=1)
        prev_first = prev_last.replace(day=1)

        def in_month(d, first, last): return (d and first <= d <= last)
        def parse_date(s):
            try: y,m,d = map(int, (s or "").split("-")); return dt.date(y,m,d)
            except Exception: return None

        cur_spent = cur_rev = cur_prof = 0.0
        prev_spent = prev_rev = prev_prof = 0.0
        for it in items:
            b = (it.get("boughtPriceCents") or 0)/100.0
            s = (it.get("soldPriceCents") or 0)/100.0
            bd = parse_date(it.get("dateBought",""))
            sd = parse_date(it.get("soldDate",""))
            if in_month(bd, cur_first, today): cur_spent += b
            if s and in_month(sd, cur_first, today): cur_rev += s; cur_prof += (s - (it.get("boughtPriceCents") or 0)/100.0)
            if in_month(bd, prev_first, prev_last): prev_spent += b
            if s and in_month(sd, prev_first, prev_last): prev_rev += s; prev_prof += (s - (it.get("boughtPriceCents") or 0)/100.0)

        self._fill_card(self._card_month, [("Spent", f"${cur_spent:,.2f}"), ("Revenue", f"${cur_rev:,.2f}"), ("Profit", f"${cur_prof:,.2f}")])
        self._fill_card(self._card_prev,  [("Spent", f"${prev_spent:,.2f}"), ("Revenue", f"${prev_rev:,.2f}"), ("Profit", f"${prev_prof:,.2f}")])

        if Figure is None: return

        if not dfrom or not dto:
            start = (today.replace(day=1) - dt.timedelta(days=365)).replace(day=1); end = today
        else:
            start, end = (dfrom, dto) if dfrom <= dto else (dto, dfrom)

        months = []
        cur = start.replace(day=1)
        while cur <= end:
            months.append(cur)
            y = cur.year + (1 if cur.month == 12 else 0)
            m = 1 if cur.month == 12 else (cur.month + 1)
            cur = dt.date(y,m,1)

        spent_m = [0.0]*len(months)
        rev_m   = [0.0]*len(months)
        worth_m = [0.0]*len(months)
        prof_m  = [0.0]*len(months)

        def month_index(d):
            if not d: return None
            head = d.replace(day=1)
            try: return months.index(head)
            except ValueError: return None

        for it in items:
            bd = parse_date(it.get("dateBought",""))
            bi = month_index(bd)
            if bi is not None: spent_m[bi] += (it.get("boughtPriceCents") or 0)/100.0
            sd = parse_date(it.get("soldDate",""))
            si = month_index(sd)
            if si is not None and it.get("soldPriceCents") is not None:
                s = (it.get("soldPriceCents") or 0)/100.0
                b = (it.get("boughtPriceCents") or 0)/100.0
                rev_m[si] += s; prof_m[si] += (s - b)
            li = month_index(bd)
            if li is not None and it.get("salePriceCents") is not None:
                worth_m[li] += (it.get("salePriceCents") or 0)/100.0

        self.ax.clear()
        self.ax.set_title("Monthly Trends"); self.ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.5); self.ax.axhline(0, color="black", linewidth=0.6)
        x = [m.strftime("%Y-%m") for m in months]
        self.ax.plot(x, spent_m, label="Spent")
        self.ax.plot(x, rev_m, label="Revenue")
        self.ax.plot(x, worth_m, label="Worth (Sale Price sum)")
        self.ax.legend(loc="upper left"); self.ax.tick_params(axis='x', labelrotation=35)
        self.canvas.draw_idle()

        self.ax2.clear()
        self.ax2.set_title("Monthly Profit"); self.ax2.grid(True, linestyle="--", linewidth=0.5, alpha=0.5); self.ax2.axhline(0, color="black", linewidth=0.6)
        self.ax2.plot(x, prof_m, label="Profit")
        self.ax2.legend(loc="upper left"); self.ax2.tick_params(axis='x', labelrotation=35)
        self.canvas2.draw_idle()

    # ---------------- Simple Report ----------------
    def on_simple_report(self):
        if not self.db: return
        total = len(self.items)
        sold   = sum(1 for i in self.items if (i.get("soldDate") or "").strip())
        unsold = total - sold
        spent   = sum((i.get("boughtPriceCents") or 0) for i in self.items)/100.0
        revenue = sum((i.get("soldPriceCents") or 0) for i in self.items)/100.0
        profit  = sum(((i.get("soldPriceCents") or 0) - (i.get("boughtPriceCents") or 0)) for i in self.items)/100.0

        f_total = len(self.filtered)
        f_sold   = sum(1 for i in self.filtered if (i.get("soldDate") or "").strip())
        f_unsold = f_total - f_sold
        f_spent   = sum((i.get("boughtPriceCents") or 0) for i in self.filtered)/100.0
        f_revenue = sum((i.get("soldPriceCents") or 0) for i in self.filtered)/100.0
        f_profit  = sum(((i.get("soldPriceCents") or 0) - (i.get("boughtPriceCents") or 0)) for i in self.filtered)/100.0

        report = io.StringIO()
        print("Sellventory – Simple Report", file=report)
        print("--------------------------------", file=report)
        print("Overall:", file=report)
        print(f"  Total items : {total}", file=report)
        print(f"  Sold        : {sold}", file=report)
        print(f"  Unsold      : {unsold}", file=report)
        print(f"  Total spent : ${spent:,.2f}", file=report)
        print(f"  Revenue     : ${revenue:,.2f}", file=report)
        print(f"  Gross profit: ${profit:,.2f}", file=report)
        print("", file=report)
        print("Filtered (current view):", file=report)
        print(f"  Total items : {f_total}", file=report)
        print(f"  Sold        : {f_sold}", file=report)
        print(f"  Unsold      : {f_unsold}", file=report)
        print(f"  Total spent : ${f_spent:,.2f}", file=report)
        print(f"  Revenue     : ${f_revenue:,.2f}", file=report)
        print(f"  Gross profit: ${f_profit:,.2f}", file=report)
        text = report.getvalue()

        win = tk.Toplevel(self.root); win.title("Simple Report"); win.geometry("560x460"); win.transient(self.root)
        frm = ttk.Frame(win, padding=10); frm.pack(fill="both", expand=True)
        txt = tk.Text(frm, wrap="word"); txt.pack(fill="both", expand=True)
        txt.insert("1.0", text); txt.configure(state="disabled")
        btns = ttk.Frame(frm); btns.pack(fill="x", pady=(6,0))
        def do_copy():
            try:
                self.root.clipboard_clear(); self.root.clipboard_append(text); self.root.update()
                messagebox.showinfo("Copied", "Report copied to clipboard.")
            except Exception as e:
                messagebox.showwarning("Copy", f"Could not copy:\n{e}")
        ttk.Frame(btns).pack(side="left", expand=True)
        ttk.Button(btns, text="Copy to Clipboard", command=do_copy).pack(side="left")
        ttk.Frame(btns).pack(side="left", expand=True)

    # ---------------- Manage Locations / Tags ----------------
    def on_manage_locations(self):
        if not self.db: return
        win = tk.Toplevel(self.root); win.title("Manage Locations"); win.geometry("420x380"); win.transient(self.root)
        frm = ttk.Frame(win, padding=10); frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="Locations").pack(anchor="w")
        lb = tk.Listbox(frm, height=12); lb.pack(fill="both", expand=True, pady=(6,6))
        def refresh():
            lb.delete(0, tk.END)
            for s in self.db.distinct_storages(): lb.insert(tk.END, s)
        refresh()
        btns = ttk.Frame(frm); btns.pack(fill="x")
        def add_loc():
            name = simpledialog.askstring("Add Location", "New location name:", parent=win)
            if name: messagebox.showinfo("Added", f"“{name}” will appear once assigned to an item.")
        def rename_loc():
            if not lb.curselection(): return
            old = lb.get(lb.curselection()[0])
            new = simpledialog.askstring("Rename Location", f"Rename “{old}” to:", parent=win, initialvalue=old)
            if not new or new == old: return
            n = self.db.replace_storage(old, new)
            messagebox.showinfo("Done", f"Updated {n} item(s)."); self.reload_items(); refresh()
        def delete_loc():
            if not lb.curselection(): return
            val = lb.get(lb.curselection()[0])
            if not messagebox.askyesno("Delete", f"Remove “{val}” from all items?"): return
            n = self.db.delete_storage(val)
            messagebox.showinfo("Done", f"Cleared from {n} item(s)."); self.reload_items(); refresh()
        ttk.Button(btns, text="Add", command=add_loc).pack(side="left")
        ttk.Button(btns, text="Rename", command=rename_loc).pack(side="left", padx=6)
        ttk.Button(btns, text="Delete", command=delete_loc).pack(side="left")

    def on_manage_tags(self):
        if not self.db: return
        win = tk.Toplevel(self.root); win.title("Manage Tags"); win.geometry("480x420"); win.transient(self.root)
        frm = ttk.Frame(win, padding=10); frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="Tags").pack(anchor="w")
        lb = tk.Listbox(frm, height=14); lb.pack(fill="both", expand=True, pady=(6,6))
        def refresh():
            lb.delete(0, tk.END)
            for t in self.db.tag_suggestions(): lb.insert(tk.END, t)
        refresh()
        btns = ttk.Frame(frm); btns.pack(fill="x")
        def add_tag():
            name = simpledialog.askstring("Add Tag", "New tag:", parent=win)
            if name: messagebox.showinfo("Added", f"“{name}” will appear once used.")
        def rename_tag():
            if not lb.curselection(): return
            old = lb.get(lb.curselection()[0])
            new = simpledialog.askstring("Rename Tag", f"Rename “{old}” to:", parent=win, initialvalue=old)
            if not new or new == old: return
            n = self.db.rename_tag(old, new)
            messagebox.showinfo("Done", f"Updated {n} item(s)."); self.reload_items(); refresh()
        def delete_tag():
            if not lb.curselection(): return
            tg = lb.get(lb.curselection()[0])
            if not messagebox.askyesno("Delete", f"Remove “{tg}” from all items?"): return
            n = self.db.delete_tag(tg)
            messagebox.showinfo("Done", f"Removed from {n} item(s)."); self.reload_items(); refresh()
        ttk.Button(btns, text="Add", command=add_tag).pack(side="left")
        ttk.Button(btns, text="Rename", command=rename_tag).pack(side="left", padx=6)
        ttk.Button(btns, text="Delete", command=delete_tag).pack(side="left")

    # ---------------- Helpers ----------------
    def _has_db(self, folder: str) -> bool:
        return os.path.exists(os.path.join(folder, "sellventory.db")) or \
               os.path.exists(os.path.join(folder, "databases", "sellventory.db"))

    def _thumb_for(self, item, w=THUMB_W, h=THUMB_H):
        if not self.db: return None
        path = self.db.image_path(item.get("image_name"))
        if not path: return None
        key = (path, w, h, self.theme.get())
        img = self.thumb_cache.get(key)
        if img: return img
        try:
            im = Image.open(path); im = ImageOps.exif_transpose(im); im.thumbnail((w, h))
            img = ImageTk.PhotoImage(im)
            self.thumb_cache[key] = img
            return img
        except Exception:
            return None

    @staticmethod
    def _fmt_money(cents):
        if cents is None: return ""
        try: return f"${cents/100:.2f}"
        except Exception: return ""

    # Column sorting for list view
    _sort_states = {}  # col -> bool
    def _sort_by(self, col):
        rev = self._sort_states.get(col, False)
        self._sort_states[col] = not rev

        def parse_money(s):
            s = (s or "").replace("$","").replace(",","").strip()
            if not s: return float("-inf")
            try: return float(s)
            except: return float("-inf")

        def parse_date(s):
            s = (s or "").strip()
            if not s or s.lower()=="none": return dt.date.min
            try:
                y,m,d = map(int, s.split("-")); return dt.date(y,m,d)
            except: return dt.date.min

        idx_map = {
            "local_id":0, "title":1, "storage":2, "dateBought":3,
            "boughtPrice":4, "salePrice":5, "soldPrice":6, "soldDate":7
        }
        rows = [(self.tree.set(k, col), k) for k in self.tree.get_children("")]
        if col in ("local_id",):
            rows.sort(key=lambda t: int(t[0]) if str(t[0]).isdigit() else -1, reverse=rev)
        elif col in ("boughtPrice","salePrice","soldPrice"):
            rows.sort(key=lambda t: parse_money(t[0]), reverse=rev)
        elif col in ("dateBought","soldDate"):
            rows.sort(key=lambda t: parse_date(t[0]), reverse=rev)
        else:
            rows.sort(key=lambda t: (t[0] or "").casefold(), reverse=rev)
        for i, (_, k) in enumerate(rows):
            self.tree.move(k, "", i)

    # ---------------- Importers ----------------
    def on_import_zip(self):
        path = filedialog.askopenfilename(title="Open Sellventory ZIP",
                                          filetypes=[("Zip files","*.zip"),("All files","*.*")])
        if not path: return
        self._reset_library()
        try:
            with zipfile.ZipFile(path, "r") as z:
                z.extractall(LIB_DIR)
        except Exception as e:
            messagebox.showerror("ZIP error", f"Failed to extract:\n{e}")
            return
        self._load_library(LIB_DIR)

    def on_import_folder(self):
        folder = filedialog.askdirectory(title="Select exported Sellventory folder")
        if not folder: return
        self._reset_library()
        try:
            db_src = self._find_db_in(folder)
            if not db_src:
                raise Exception("sellventory.db not found in that folder.")
            shutil.copy2(db_src, os.path.join(LIB_DIR, "sellventory.db"))
            img_src = os.path.join(folder, "images")
            if os.path.isdir(img_src):
                shutil.copytree(img_src, os.path.join(LIB_DIR, "images"), dirs_exist_ok=True)
        except Exception as e:
            messagebox.showerror("Import failed", str(e))
            return
        self._load_library(LIB_DIR)

    def _reset_library(self):
        if os.path.isdir(LIB_DIR):
            for name in os.listdir(LIB_DIR):
                p = os.path.join(LIB_DIR, name)
                try:
                    if os.path.isdir(p): shutil.rmtree(p)
                    else: os.remove(p)
                except Exception: pass

    def _find_db_in(self, folder: str) -> str | None:
        p1 = os.path.join(folder, "sellventory.db")
        if os.path.exists(p1): return p1
        p2 = os.path.join(folder, "databases", "sellventory.db")
        if os.path.exists(p2): return p2
        return None

    def _load_library(self, folder: str):
        nested = os.path.join(folder, "databases", "sellventory.db")
        if os.path.exists(nested):
            shutil.move(nested, os.path.join(folder, "sellventory.db"))
            try: shutil.rmtree(os.path.join(folder, "databases"))
            except Exception: pass
        try:
            self.db = Database.from_folder(folder)
        except DBError as e:
            messagebox.showerror("Open failed", str(e)); return
        cfg = load_config(); cfg.library_dir = folder; save_config(cfg)
        self.reload_items()

def main():
    root = tk.Tk()
    app = SellventoryApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
