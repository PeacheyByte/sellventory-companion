# item_dialog.py
import os
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk, ImageOps
from database import Database

PREV_W, PREV_H = 360, 270

class ItemDialog:
    def __init__(self, parent, db: Database, local_id: int, on_saved=None):
        self.db = db
        self.local_id = local_id
        self.on_saved = on_saved
        self.item = db.get_item(local_id)

        self.top = tk.Toplevel(parent)
        self.top.title(f"Edit Item {local_id}")
        self.top.transient(parent)
        self.top.geometry("720x560")

        # SAFE show/grab sequence (prevents “grab failed: window not viewable”)
        self.top.withdraw()
        self.top.update_idletasks()
        self.top.deiconify()
        try:
            self.top.grab_set()
        except Exception:
            pass

        self._thumb_img = None

        frm = ttk.Frame(self.top, padding=10)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1); frm.rowconfigure(0, weight=1)

        # Preview
        self.canvas = tk.Canvas(frm, width=PREV_W, height=PREV_H, highlightthickness=1, relief="solid")
        self.canvas.grid(row=0, column=0, rowspan=6, sticky="n", padx=(0,12))
        self._render_thumb()

        # Fields
        row = 0
        ttk.Label(frm, text="Title:").grid(row=row, column=1, sticky="w")
        self.title_var = tk.StringVar(value=self.item.get("title",""))
        ttk.Entry(frm, textvariable=self.title_var, width=40).grid(row=row, column=2, sticky="ew", pady=2)

        row+=1
        ttk.Label(frm, text="Description:").grid(row=row, column=1, sticky="w")
        self.desc_var = tk.StringVar(value=self.item.get("description",""))
        ttk.Entry(frm, textvariable=self.desc_var, width=40).grid(row=row, column=2, sticky="ew", pady=2)

        row+=1
        ttk.Label(frm, text="Storage:").grid(row=row, column=1, sticky="w")
        self.storage_var = tk.StringVar(value=self.item.get("storage",""))
        ttk.Entry(frm, textvariable=self.storage_var, width=30).grid(row=row, column=2, sticky="w", pady=2)

        row+=1
        ttk.Label(frm, text="Tags (comma separated):").grid(row=row, column=1, sticky="w")
        self.tags_var = tk.StringVar(value=self.item.get("tags",""))
        ttk.Entry(frm, textvariable=self.tags_var, width=40).grid(row=row, column=2, sticky="ew", pady=2)

        row+=1
        ttk.Label(frm, text="Bought Price ($):").grid(row=row, column=1, sticky="w")
        bp = (self.item.get("boughtPriceCents") or 0)/100.0
        self.bought_var = tk.StringVar(value=f"{bp:.2f}")
        ttk.Entry(frm, textvariable=self.bought_var, width=12).grid(row=row, column=2, sticky="w", pady=2)

        row+=1
        ttk.Label(frm, text="Sale Price ($):").grid(row=row, column=1, sticky="w")
        sp = self.item.get("salePriceCents")
        self.sale_var = tk.StringVar(value=f"{(sp or 0)/100.0:.2f}" if sp is not None else "")
        ttk.Entry(frm, textvariable=self.sale_var, width=12).grid(row=row, column=2, sticky="w", pady=2)

        row+=1
        ttk.Label(frm, text="Sold Price ($):").grid(row=row, column=1, sticky="w")
        soldp = self.item.get("soldPriceCents")
        self.sold_var = tk.StringVar(value=f"{(soldp or 0)/100.0:.2f}" if soldp is not None else "")
        ttk.Entry(frm, textvariable=self.sold_var, width=12).grid(row=row, column=2, sticky="w", pady=2)

        row+=1
        ttk.Label(frm, text="Date Bought (yyyy-mm-dd):").grid(row=row, column=1, sticky="w")
        self.date_bought_var = tk.StringVar(value=self.item.get("dateBought",""))
        ttk.Entry(frm, textvariable=self.date_bought_var, width=16).grid(row=row, column=2, sticky="w", pady=2)

        row+=1
        ttk.Label(frm, text="Sold Date (yyyy-mm-dd):").grid(row=row, column=1, sticky="w")
        self.sold_date_var = tk.StringVar(value=self.item.get("soldDate",""))
        ttk.Entry(frm, textvariable=self.sold_date_var, width=16).grid(row=row, column=2, sticky="w", pady=2)

        btns = ttk.Frame(frm)
        btns.grid(row=row+1, column=0, columnspan=3, pady=(12,0))
        ttk.Button(btns, text="Save", command=self.on_save).pack(side="left", padx=6)
        ttk.Button(btns, text="Cancel", command=self.top.destroy).pack(side="left", padx=6)

    def _render_thumb(self):
        self.canvas.delete("all")
        path = self.db.image_path(self.item.get("image_name"))
        if not path or not os.path.exists(path):
            self.canvas.create_text(PREV_W//2, PREV_H//2, text="(no image)"); return
        try:
            im = Image.open(path); im = ImageOps.exif_transpose(im); im.thumbnail((PREV_W, PREV_H))
            self._thumb_img = ImageTk.PhotoImage(im)
            self.canvas.create_image(PREV_W//2, PREV_H//2, image=self._thumb_img, anchor="center")
        except Exception:
            self.canvas.create_text(PREV_W//2, PREV_H//2, text="(image error)")

    def on_save(self):
        try:
            upd = {
                "title": self.title_var.get().strip(),
                "description": self.desc_var.get().strip(),
                "storage": self.storage_var.get().strip(),
                "tags": self.tags_var.get().strip(),
                "dateBought": self.date_bought_var.get().strip(),
                "soldDate": self.sold_date_var.get().strip(),
            }
            try: upd["boughtPriceCents"] = int(float(self.bought_var.get())*100)
            except: upd["boughtPriceCents"] = 0
            try: upd["salePriceCents"] = int(float(self.sale_var.get())*100) if self.sale_var.get() else None
            except: upd["salePriceCents"] = None
            try: upd["soldP]()
