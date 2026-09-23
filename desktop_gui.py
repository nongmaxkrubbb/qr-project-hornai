#!/usr/bin/env python3
"""
desktop_gui.py — คิวอิ่ม (Q-Im) Desktop Application
พัฒนาด้วย Python GUI ล้วน 100% (Tkinter + ttk)
ไม่ต้องเปิดผ่านเว็บเบราว์เซอร์ ไม่ต้องติดตั้ง GUI library ภายนอกเพิ่มเติม

การใช้งาน:
    python desktop_gui.py
"""

import os
import sys
import time
import threading
from datetime import datetime
from decimal import Decimal
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

# โหลดตัวแปรสภาพแวดล้อม (.env)
from dotenv import load_dotenv
load_dotenv()

# เชื่อมต่อ Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY", "")

try:
    from supabase import create_client
    sb_client = create_client(SUPABASE_URL, SUPABASE_KEY) if (SUPABASE_URL and SUPABASE_KEY) else None
except Exception as e:
    sb_client = None


class QImDesktopApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("คิวอิ่ม (Q-Im) — Kitchen & POS Desktop Manager")
        self.geometry("1200x800")
        self.minsize(980, 650)

        # Theme Colors
        self.colors = {
            "bg_dark": "#0f172a",
            "bg_card": "#ffffff",
            "bg_main": "#f1f5f9",
            "primary": "#2563eb",
            "success": "#10b981",
            "warning": "#f59e0b",
            "danger": "#ef4444",
            "text_dark": "#1e293b",
            "text_muted": "#64748b",
        }
        self.configure(bg=self.colors["bg_main"])

        # Data State
        self.branches = []
        self.selected_branch_id = None
        self.orders = []
        self.menu_items = []
        self.cart = {}  # item_id -> {"item": dict, "qty": int}
        self.auto_refresh_enabled = True
        self.last_order_ids = set()

        # Build UI
        self._setup_styles()
        self._build_header()
        self._build_tabs()
        self._build_statusbar()

        # โหลดข้อมูลเริ่มต้น
        self.after(200, self._load_initial_data)

        # เริ่มต้น Background Polling Loop
        self._start_background_sync()

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure(".", font=("Helvetica", 12))
        style.configure("Header.TFrame", background=self.colors["bg_dark"])
        style.configure("Status.TFrame", background="#e2e8f0")
        style.configure("Card.TFrame", background="#ffffff", relief="flat")
        
        # Notebook / Tabs
        style.configure("TNotebook", background=self.colors["bg_main"], borderwidth=0)
        style.configure("TNotebook.Tab", font=("Helvetica", 12, "bold"), padding=[16, 8])
        style.map("TNotebook.Tab", background=[("selected", "#ffffff")], foreground=[("selected", self.colors["primary"])])

        # Buttons
        style.configure("Primary.TButton", font=("Helvetica", 11, "bold"), background=self.colors["primary"], foreground="#ffffff", padding=6)
        style.map("Primary.TButton", background=[("active", "#1d4ed8")])

        style.configure("Success.TButton", font=("Helvetica", 11, "bold"), background=self.colors["success"], foreground="#ffffff", padding=6)
        style.map("Success.TButton", background=[("active", "#059669")])

        style.configure("Warning.TButton", font=("Helvetica", 11, "bold"), background=self.colors["warning"], foreground="#ffffff", padding=6)
        style.map("Warning.TButton", background=[("active", "#d97706")])

        style.configure("Danger.TButton", font=("Helvetica", 11, "bold"), background=self.colors["danger"], foreground="#ffffff", padding=6)
        style.map("Danger.TButton", background=[("active", "#dc2626")])

    def _build_header(self):
        header = tk.Frame(self, bg=self.colors["bg_dark"], height=64)
        header.pack(fill="x", side="top")

        # App Logo & Title
        title_box = tk.Frame(header, bg=self.colors["bg_dark"])
        title_box.pack(side="left", padx=20, pady=12)

        logo_lbl = tk.Label(title_box, text="🍲 คิวอิ่ม", font=("Helvetica", 18, "bold"), fg="#38bdf8", bg=self.colors["bg_dark"])
        logo_lbl.pack(side="left")

        subtitle_lbl = tk.Label(title_box, text=" | Desktop Manager", font=("Helvetica", 13), fg="#94a3b8", bg=self.colors["bg_dark"])
        subtitle_lbl.pack(side="left", padx=(4, 0))

        # Right Controls: Branch Selector & Refresh
        ctrl_box = tk.Frame(header, bg=self.colors["bg_dark"])
        ctrl_box.pack(side="right", padx=20, pady=12)

        branch_lbl = tk.Label(ctrl_box, text="สาขา / ร้าน:", font=("Helvetica", 11), fg="#cbd5e1", bg=self.colors["bg_dark"])
        branch_lbl.pack(side="left", padx=(0, 6))

        self.branch_var = tk.StringVar()
        self.branch_combo = ttk.Combobox(ctrl_box, textvariable=self.branch_var, state="readonly", width=24)
        self.branch_combo.pack(side="left", padx=(0, 12))
        self.branch_combo.bind("<<ComboboxSelected>>", self._on_branch_selected)

        self.btn_refresh = tk.Button(
            ctrl_box, text="🔄 รีเฟรช", font=("Helvetica", 11, "bold"),
            bg="#334155", fg="#ffffff", activebackground="#475569", activeforeground="#ffffff",
            relief="flat", padx=10, pady=4, cursor="hand2", command=self.refresh_data
        )
        self.btn_refresh.pack(side="left")

    def _build_tabs(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=(8, 0))

        # Tab 1: Kitchen Display System (KDS)
        self.tab_kitchen = tk.Frame(self.notebook, bg=self.colors["bg_main"])
        self.notebook.add(self.tab_kitchen, text="  🍳 จัดการคิวครัว (KDS)  ")
        self._build_kitchen_tab()

        # Tab 2: Walk-in POS (สั่งอาหารหน้าร้าน)
        self.tab_pos = tk.Frame(self.notebook, bg=self.colors["bg_main"])
        self.notebook.add(self.tab_pos, text="  🛍️ สั่งอาหารหน้าร้าน (POS)  ")
        self._build_pos_tab()

        # Tab 3: Order History / ประวัติออเดอร์
        self.tab_history = tk.Frame(self.notebook, bg=self.colors["bg_main"])
        self.notebook.add(self.tab_history, text="  📊 สรุปยอดและประวัติ  ")
        self._build_history_tab()

    # -------------------------------------------------------------
    # TAB 1: KITCHEN DISPLAY SYSTEM (KDS)
    # -------------------------------------------------------------
    def _build_kitchen_tab(self):
        # Summary Counter Bar
        counter_bar = tk.Frame(self.tab_kitchen, bg=self.colors["bg_main"])
        counter_bar.pack(fill="x", padx=10, pady=8)

        self.badge_waiting = self._create_badge(counter_bar, "⏳ รอทำ", "0", self.colors["warning"])
        self.badge_preparing = self._create_badge(counter_bar, "🍳 กำลังปรุง", "0", self.colors["primary"])
        self.badge_ready = self._create_badge(counter_bar, "🔔 พร้อมรับ", "0", self.colors["success"])
        self.badge_pending_pay = self._create_badge(counter_bar, "💰 รอชำระ", "0", self.colors["text_muted"])

        # Main Split View: Left (Queue List) / Right (Order Detail & Actions)
        split_frame = tk.Frame(self.tab_kitchen, bg=self.colors["bg_main"])
        split_frame.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        # Left Frame: Treeview Orders Table
        left_frame = tk.Frame(split_frame, bg="#ffffff", bd=1, relief="solid")
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 6))

        # Treeview Columns
        columns = ("id", "queue", "customer", "items", "amount", "status", "time")
        self.tree_orders = ttk.Treeview(left_frame, columns=columns, show="headings", selectmode="browse")
        
        self.tree_orders.heading("id", text="#บิล")
        self.tree_orders.heading("queue", text="คิวที่")
        self.tree_orders.heading("customer", text="ลูกค้า/ประเภท")
        self.tree_orders.heading("items", text="รายการอาหาร")
        self.tree_orders.heading("amount", text="ยอดรวม (฿)")
        self.tree_orders.heading("status", text="สถานะ")
        self.tree_orders.heading("time", text="เวลาสั่ง")

        self.tree_orders.column("id", width=60, anchor="center")
        self.tree_orders.column("queue", width=70, anchor="center")
        self.tree_orders.column("customer", width=110, anchor="w")
        self.tree_orders.column("items", width=260, anchor="w")
        self.tree_orders.column("amount", width=90, anchor="e")
        self.tree_orders.column("status", width=110, anchor="center")
        self.tree_orders.column("time", width=80, anchor="center")

        tree_scroll = ttk.Scrollbar(left_frame, orient="vertical", command=self.tree_orders.yview)
        self.tree_orders.configure(yscrollcommand=tree_scroll.set)

        self.tree_orders.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")
        self.tree_orders.bind("<<TreeviewSelect>>", self._on_order_selected)

        # Right Frame: Action & Details Panel
        self.right_frame = tk.Frame(split_frame, bg="#ffffff", bd=1, relief="solid", width=340)
        self.right_frame.pack(side="right", fill="y", padx=(6, 0))
        self.right_frame.pack_propagate(False)

        # Detail Widgets in Right Frame
        detail_header = tk.Label(self.right_frame, text="📋 รายละเอียดออเดอร์", font=("Helvetica", 13, "bold"), bg="#ffffff", fg=self.colors["text_dark"])
        detail_header.pack(fill="x", padx=12, pady=(12, 6))

        self.lbl_selected_order = tk.Label(self.right_frame, text="กรุณาเลือกออเดอร์ในตาราง", font=("Helvetica", 11), bg="#ffffff", fg=self.colors["text_muted"])
        self.lbl_selected_order.pack(fill="x", padx=12, pady=4)

        self.txt_order_items = tk.Text(self.right_frame, height=12, font=("Helvetica", 11), bg="#f8fafc", bd=1, relief="solid", wrap="word")
        self.txt_order_items.pack(fill="both", expand=True, padx=12, pady=6)
        self.txt_order_items.config(state="disabled")

        # Action Buttons Container
        actions_box = tk.Frame(self.right_frame, bg="#ffffff")
        actions_box.pack(fill="x", padx=12, pady=12)

        self.btn_start_prep = tk.Button(
            actions_box, text="▶️ เริ่มทำอาหาร (Preparing)", font=("Helvetica", 11, "bold"),
            bg=self.colors["primary"], fg="#ffffff", relief="flat", pady=6, cursor="hand2",
            command=lambda: self._trigger_order_action("start")
        )
        self.btn_start_prep.pack(fill="x", pady=3)

        self.btn_mark_ready = tk.Button(
            actions_box, text="🔔 พร้อมเสิร์ฟ (Ready)", font=("Helvetica", 11, "bold"),
            bg=self.colors["success"], fg="#ffffff", relief="flat", pady=6, cursor="hand2",
            command=lambda: self._trigger_order_action("ready")
        )
        self.btn_mark_ready.pack(fill="x", pady=3)

        self.btn_mark_complete = tk.Button(
            actions_box, text="✅ ส่งมอบสำเร็จ (Complete)", font=("Helvetica", 11, "bold"),
            bg="#16a34a", fg="#ffffff", relief="flat", pady=6, cursor="hand2",
            command=lambda: self._trigger_order_action("complete")
        )
        self.btn_mark_complete.pack(fill="x", pady=3)

        self.btn_cancel_order = tk.Button(
            actions_box, text="❌ ยกเลิกออเดอร์", font=("Helvetica", 10),
            bg="#f87171", fg="#ffffff", relief="flat", pady=4, cursor="hand2",
            command=lambda: self._trigger_order_action("cancel")
        )
        self.btn_cancel_order.pack(fill="x", pady=(6, 0))

    def _create_badge(self, parent, label_text, count_text, color):
        frame = tk.Frame(parent, bg="#ffffff", bd=1, relief="solid", padx=12, pady=6)
        frame.pack(side="left", padx=6)

        title = tk.Label(frame, text=label_text, font=("Helvetica", 10, "bold"), fg=self.colors["text_muted"], bg="#ffffff")
        title.pack(anchor="w")

        count_lbl = tk.Label(frame, text=count_text, font=("Helvetica", 16, "bold"), fg=color, bg="#ffffff")
        count_lbl.pack(anchor="w")
        return count_lbl

    # -------------------------------------------------------------
    # TAB 2: WALK-IN POS (สั่งอาหารหน้าร้าน)
    # -------------------------------------------------------------
    def _build_pos_tab(self):
        pos_split = tk.Frame(self.tab_pos, bg=self.colors["bg_main"])
        pos_split.pack(fill="both", expand=True, padx=10, pady=10)

        # Left: Menu Items Grid
        menu_frame = tk.Frame(pos_split, bg="#ffffff", bd=1, relief="solid")
        menu_frame.pack(side="left", fill="both", expand=True, padx=(0, 8))

        menu_header = tk.Label(menu_frame, text="🍲 รายการเมนูอาหาร (คลิกเพื่อเพิ่มลงตะกร้า)", font=("Helvetica", 13, "bold"), bg="#ffffff", fg=self.colors["text_dark"])
        menu_header.pack(fill="x", padx=12, pady=10)

        # Menu Canvas with Scrollbar
        self.menu_canvas = tk.Canvas(menu_frame, bg="#ffffff", highlightthickness=0)
        menu_scroll = ttk.Scrollbar(menu_frame, orient="vertical", command=self.menu_canvas.yview)
        self.menu_grid_inner = tk.Frame(self.menu_canvas, bg="#ffffff")

        self.menu_grid_inner.bind(
            "<Configure>", lambda e: self.menu_canvas.configure(scrollregion=self.menu_canvas.bbox("all"))
        )
        self.menu_canvas.create_window((0, 0), window=self.menu_grid_inner, anchor="nw")
        self.menu_canvas.configure(yscrollcommand=menu_scroll.set)

        self.menu_canvas.pack(side="left", fill="both", expand=True, padx=10, pady=6)
        menu_scroll.pack(side="right", fill="y")

        # Right: Cart & Order Checkout
        cart_frame = tk.Frame(pos_split, bg="#ffffff", bd=1, relief="solid", width=360)
        cart_frame.pack(side="right", fill="y")
        cart_frame.pack_propagate(False)

        cart_title = tk.Label(cart_frame, text="🛒 ตะกร้าสั่งซื้อหน้าร้าน", font=("Helvetica", 13, "bold"), bg="#ffffff", fg=self.colors["text_dark"])
        cart_title.pack(fill="x", padx=12, pady=(12, 6))

        # Cart Table
        cart_cols = ("name", "qty", "price")
        self.tree_cart = ttk.Treeview(cart_frame, columns=cart_cols, show="headings", height=8)
        self.tree_cart.heading("name", text="เมนู")
        self.tree_cart.heading("qty", text="จน.")
        self.tree_cart.heading("price", text="รวม (฿)")
        self.tree_cart.column("name", width=160, anchor="w")
        self.tree_cart.column("qty", width=40, anchor="center")
        self.tree_cart.column("price", width=70, anchor="e")
        self.tree_cart.pack(fill="x", padx=12, pady=6)

        # Cart Adjust Controls
        cart_ctrl = tk.Frame(cart_frame, bg="#ffffff")
        cart_ctrl.pack(fill="x", padx=12, pady=2)
        tk.Button(cart_ctrl, text="➕ เพิ่ม", font=("Helvetica", 9), command=self._cart_add_selected).pack(side="left", padx=2)
        tk.Button(cart_ctrl, text="➖ ลด", font=("Helvetica", 9), command=self._cart_decrease_selected).pack(side="left", padx=2)
        tk.Button(cart_ctrl, text="🗑️ ล้างตะกร้า", font=("Helvetica", 9), fg="red", command=self._cart_clear).pack(side="right", padx=2)

        # Customer Note & Type
        meta_frame = tk.Frame(cart_frame, bg="#ffffff")
        meta_frame.pack(fill="x", padx=12, pady=8)

        tk.Label(meta_frame, text="ชื่อลูกค้า / หมายเหตุ:", font=("Helvetica", 10), bg="#ffffff").pack(anchor="w")
        self.ent_customer_note = tk.Entry(meta_frame, font=("Helvetica", 11))
        self.ent_customer_note.insert(0, "ลูกค้าหน้าร้าน (Walk-in)")
        self.ent_customer_note.pack(fill="x", pady=(2, 6))

        # Total Price
        self.lbl_cart_total = tk.Label(cart_frame, text="ยอดรวม: ฿0.00", font=("Helvetica", 15, "bold"), fg=self.colors["primary"], bg="#ffffff")
        self.lbl_cart_total.pack(fill="x", padx=12, pady=8)

        # Submit Order Button
        self.btn_submit_order = tk.Button(
            cart_frame, text="💳 บันทึกออเดอร์หน้าร้าน (ส่งเข้าครัว)", font=("Helvetica", 12, "bold"),
            bg=self.colors["success"], fg="#ffffff", relief="flat", pady=10, cursor="hand2",
            command=self._submit_walkin_order
        )
        self.btn_submit_order.pack(fill="x", padx=12, pady=12)

    # -------------------------------------------------------------
    # TAB 3: HISTORY & STATS
    # -------------------------------------------------------------
    def _build_history_tab(self):
        hist_frame = tk.Frame(self.tab_history, bg=self.colors["bg_main"])
        hist_frame.pack(fill="both", expand=True, padx=12, pady=12)

        header_lbl = tk.Label(hist_frame, text="📜 ประวัติออเดอร์ที่เสร็จสิ้น/ยกเลิกล่าสุด", font=("Helvetica", 13, "bold"), bg=self.colors["bg_main"])
        header_lbl.pack(anchor="w", pady=(0, 8))

        cols = ("id", "queue", "customer", "items", "amount", "status", "date")
        self.tree_history = ttk.Treeview(hist_frame, columns=cols, show="headings")
        self.tree_history.heading("id", text="#บิล")
        self.tree_history.heading("queue", text="คิว")
        self.tree_history.heading("customer", text="ลูกค้า")
        self.tree_history.heading("items", text="รายการ")
        self.tree_history.heading("amount", text="ยอดเงิน (฿)")
        self.tree_history.heading("status", text="สถานะ")
        self.tree_history.heading("date", text="เวลา")

        self.tree_history.column("id", width=60, anchor="center")
        self.tree_history.column("queue", width=60, anchor="center")
        self.tree_history.column("customer", width=120, anchor="w")
        self.tree_history.column("items", width=340, anchor="w")
        self.tree_history.column("amount", width=90, anchor="e")
        self.tree_history.column("status", width=100, anchor="center")
        self.tree_history.column("date", width=120, anchor="center")

        h_scroll = ttk.Scrollbar(hist_frame, orient="vertical", command=self.tree_history.yview)
        self.tree_history.configure(yscrollcommand=h_scroll.set)

        self.tree_history.pack(side="left", fill="both", expand=True)
        h_scroll.pack(side="right", fill="y")

    def _build_statusbar(self):
        status_bar = tk.Frame(self, bg="#e2e8f0", height=28)
        status_bar.pack(fill="x", side="bottom")

        self.lbl_status = tk.Label(status_bar, text="พร้อมทำงาน", font=("Helvetica", 10), bg="#e2e8f0", fg="#475569")
        self.lbl_status.pack(side="left", padx=12)

        self.lbl_clock = tk.Label(status_bar, text="", font=("Helvetica", 10), bg="#e2e8f0", fg="#475569")
        self.lbl_clock.pack(side="right", padx=12)
        self._update_clock()

    def _update_clock(self):
        now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        self.lbl_clock.config(text=f"🕒 {now_str}")
        self.after(1000, self._update_clock)

    # -------------------------------------------------------------
    # DATA HANDLING & SUPABASE INTEGRATION
    # -------------------------------------------------------------
    def _load_initial_data(self):
        """โหลดสาขาทั้งหมดจาก Supabase ใน Thread แยก"""
        self.set_status("กำลังเชื่อมต่อฐานข้อมูล...")
        threading.Thread(target=self._fetch_branches_thread, daemon=True).start()

    def _fetch_branches_thread(self):
        if not sb_client:
            self.set_status("❌ ไม่พบการตั้งค่า SUPABASE ใน .env")
            return

        try:
            res = sb_client.table("branches").select("id, name, is_active").order("name").execute()
            self.branches = res.data or []
            self.after(0, self._populate_branches)
        except Exception as e:
            self.set_status(f"❌ ดึงข้อมูลสาขาผิดพลาด: {str(e)[:40]}")

    def _populate_branches(self):
        if not self.branches:
            self.branch_combo["values"] = ["(ไม่พบสาขา)"]
            return

        names = [b["name"] for b in self.branches]
        self.branch_combo["values"] = names
        self.branch_combo.current(0)
        self.selected_branch_id = self.branches[0]["id"]
        self.set_status(f"เลือกสาขา: {self.branches[0]['name']}")

        # โหลดออเดอร์และเมนูของสาขานี้
        self.refresh_data()

    def _on_branch_selected(self, event):
        idx = self.branch_combo.current()
        if idx >= 0 and idx < len(self.branches):
            self.selected_branch_id = self.branches[idx]["id"]
            self.set_status(f"เปลี่ยนสาขาเป็น: {self.branches[idx]['name']}")
            self.refresh_data()

    def refresh_data(self):
        if not self.selected_branch_id or not sb_client:
            return
        self.btn_refresh.config(text="⏳ กำลังโหลด...")
        threading.Thread(target=self._fetch_branch_data_thread, daemon=True).start()

    def _fetch_branch_data_thread(self):
        b_id = self.selected_branch_id
        try:
            # ดึงออเดอร์ Active และประวัติ
            active_res = sb_client.table("orders").select("*, order_items(*)").eq("branch_id", b_id)\
                .in_("status", ["pending_payment", "waiting", "preparing", "ready"])\
                .order("created_at").execute()

            hist_res = sb_client.table("orders").select("*, order_items(*)").eq("branch_id", b_id)\
                .in_("status", ["completed", "cancelled"])\
                .order("created_at", desc=True).limit(30).execute()

            # ดึงเมนูอาหาร
            menu_res = sb_client.table("menu_items").select("*").eq("branch_id", b_id).eq("is_available", True).execute()

            self.orders = active_res.data or []
            history_orders = hist_res.data or []
            self.menu_items = menu_res.data or []

            self.after(0, lambda: self._update_ui_data(self.orders, history_orders, self.menu_items))
        except Exception as e:
            self.set_status(f"❌ รีเฟรชผิดพลาด: {str(e)[:40]}")
            self.after(0, lambda: self.btn_refresh.config(text="🔄 รีเฟรช"))

    def _update_ui_data(self, orders, history, menu_items):
        self.btn_refresh.config(text="🔄 รีเฟรช")
        self.set_status(f"อัปเดตข้อมูลล่าสุด: {datetime.now().strftime('%H:%M:%S')}")

        # 1. อัปเดตตารางออเดอร์ KDS
        self.tree_orders.delete(*self.tree_orders.get_children())
        counts = {"waiting": 0, "preparing": 0, "ready": 0, "pending_payment": 0}

        status_map = {
            "pending_payment": "🟡 รอชำระเงิน",
            "waiting": "⏳ รอทำอาหาร",
            "preparing": "🍳 กำลังปรุง",
            "ready": "🔔 พร้อมเสิร์ฟ",
            "completed": "✅ เสร็จสิ้น",
            "cancelled": "❌ ยกเลิก",
        }

        current_ids = set()
        for o in orders:
            current_ids.add(o["id"])
            st = o.get("status", "")
            if st in counts:
                counts[st] += 1

            # รวมรายการอาหาร
            items_text = ", ".join([f"{it['item_name']} x{it['quantity']}" for it in o.get("order_items", [])])
            if not items_text:
                items_text = "(ไม่มีรายการ)"

            created_time = o.get("created_at", "")
            if "T" in created_time:
                created_time = created_time.split("T")[1][:5]

            self.tree_orders.insert(
                "", "end", iid=str(o["id"]),
                values=(
                    o["id"],
                    o.get("queue_number") or "-",
                    o.get("customer_name") or ("Walk-in" if o.get("is_walkin") else "Online"),
                    items_text,
                    f"{float(o.get('total_amount', 0)):.2f}",
                    status_map.get(st, st),
                    created_time,
                )
            )

        # ตรวจจับออเดอร์ใหม่แล้วส่งเสียงเตือน
        new_ids = current_ids - self.last_order_ids
        if new_ids and self.last_order_ids:
            try:
                self.bell()  # เสียงแจ้งเตือนของระบบ
            except Exception:
                pass
        self.last_order_ids = current_ids

        # อัปเดตตัวเลขนับ
        self.badge_waiting.config(text=str(counts["waiting"]))
        self.badge_preparing.config(text=str(counts["preparing"]))
        self.badge_ready.config(text=str(counts["ready"]))
        self.badge_pending_pay.config(text=str(counts["pending_payment"]))

        # 2. อัปเดตประวัติ History
        self.tree_history.delete(*self.tree_history.get_children())
        for h in history:
            items_text = ", ".join([f"{it['item_name']} x{it['quantity']}" for it in h.get("order_items", [])])
            h_time = h.get("created_at", "")
            if "T" in h_time:
                h_time = h_time.replace("T", " ")[:16]
            self.tree_history.insert(
                "", "end",
                values=(
                    h["id"],
                    h.get("queue_number") or "-",
                    h.get("customer_name") or "Walk-in",
                    items_text,
                    f"{float(h.get('total_amount', 0)):.2f}",
                    status_map.get(h.get("status"), h.get("status")),
                    h_time,
                )
            )

        # 3. อัปเดตเมนูในหน้า POS
        self._render_menu_cards(menu_items)

    def _on_order_selected(self, event):
        selected = self.tree_orders.selection()
        if not selected:
            return
        order_id = int(selected[0])
        order = next((o for o in self.orders if o["id"] == order_id), None)
        if not order:
            return

        self.lbl_selected_order.config(
            text=f"ออเดอร์ #{order['id']} (คิว: {order.get('queue_number') or '-'}) | {order.get('status')}"
        )

        self.txt_order_items.config(state="normal")
        self.txt_order_items.delete("1.0", "end")

        self.txt_order_items.insert("end", f"ลูกค้า: {order.get('customer_name') or 'หน้าร้าน'}\n")
        self.txt_order_items.insert("end", f"หมายเหตุ: {order.get('notes') or '-'}\n")
        self.txt_order_items.insert("end", "-" * 32 + "\n")
        for it in order.get("order_items", []):
            self.txt_order_items.insert("end", f"• {it['item_name']} x{it['quantity']} — ฿{float(it['unit_price']):.2f}\n")
            if it.get("options"):
                self.txt_order_items.insert("end", f"   ตัวเลือก: {it['options']}\n")
        self.txt_order_items.insert("end", "-" * 32 + "\n")
        self.txt_order_items.insert("end", f"ยอดรวม: ฿{float(order.get('total_amount', 0)):.2f}\n")
        self.txt_order_items.config(state="disabled")

    def _trigger_order_action(self, action):
        selected = self.tree_orders.selection()
        if not selected:
            messagebox.showwarning("แจ้งเตือน", "กรุณาเลือกออเดอร์ที่ต้องการดำเนินการก่อนครับ")
            return
        order_id = int(selected[0])

        status_target = {
            "start": "preparing",
            "ready": "ready",
            "complete": "completed",
            "cancel": "cancelled",
        }.get(action)

        if action == "cancel":
            reason = simpledialog.askstring("ยกเลิกออเดอร์", "ระบุเหตุผลในการยกเลิก:")
            if not reason:
                return

        def _do_update():
            try:
                sb_client.table("orders").update({"status": status_target}).eq("id", order_id).execute()
                self.after(0, self.refresh_data)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("ผิดพลาด", f"ไม่สามารถบันทึกสถานะได้: {e}"))

        threading.Thread(target=_do_update, daemon=True).start()

    # -------------------------------------------------------------
    # POS CART & ORDERING FUNCTIONS
    # -------------------------------------------------------------
    def _render_menu_cards(self, menu_items):
        for widget in self.menu_grid_inner.winfo_children():
            widget.destroy()

        if not menu_items:
            tk.Label(self.menu_grid_inner, text="(ไม่พบรายการเมนูที่เปิดขาย)", font=("Helvetica", 11), bg="#ffffff").pack(padx=20, pady=20)
            return

        # Render Cards (3 columns)
        cols = 3
        for idx, item in enumerate(menu_items):
            r = idx // cols
            c = idx % cols

            card = tk.Frame(self.menu_grid_inner, bg="#f8fafc", bd=1, relief="solid", padx=10, pady=8)
            card.grid(row=r, column=c, padx=6, pady=6, sticky="nsew")

            name_lbl = tk.Label(card, text=item["name"], font=("Helvetica", 11, "bold"), bg="#f8fafc", fg=self.colors["text_dark"], wraplength=140)
            name_lbl.pack(anchor="w")

            price_lbl = tk.Label(card, text=f"฿{float(item['price']):.2f}", font=("Helvetica", 11), bg="#f8fafc", fg=self.colors["primary"])
            price_lbl.pack(anchor="w", pady=(2, 6))

            add_btn = tk.Button(
                card, text="➕ สั่งจานนี้", font=("Helvetica", 10),
                bg=self.colors["primary"], fg="#ffffff", relief="flat", padx=6, pady=2, cursor="hand2",
                command=lambda it=item: self._add_to_cart(it)
            )
            add_btn.pack(fill="x")

    def _add_to_cart(self, item):
        item_id = item["id"]
        if item_id in self.cart:
            self.cart[item_id]["qty"] += 1
        else:
            self.cart[item_id] = {"item": item, "qty": 1}
        self._refresh_cart_view()

    def _cart_add_selected(self):
        sel = self.tree_cart.selection()
        if sel:
            item_id = sel[0]
            if item_id in self.cart:
                self.cart[item_id]["qty"] += 1
                self._refresh_cart_view()

    def _cart_decrease_selected(self):
        sel = self.tree_cart.selection()
        if sel:
            item_id = sel[0]
            if item_id in self.cart:
                self.cart[item_id]["qty"] -= 1
                if self.cart[item_id]["qty"] <= 0:
                    del self.cart[item_id]
                self._refresh_cart_view()

    def _cart_clear(self):
        self.cart.clear()
        self._refresh_cart_view()

    def _refresh_cart_view(self):
        self.tree_cart.delete(*self.tree_cart.get_children())
        total = 0.0
        for item_id, data in self.cart.items():
            it = data["item"]
            qty = data["qty"]
            subtotal = float(it["price"]) * qty
            total += subtotal
            self.tree_cart.insert("", "end", iid=str(item_id), values=(it["name"], qty, f"{subtotal:.2f}"))

        self.lbl_cart_total.config(text=f"ยอดรวม: ฿{total:.2f}")

    def _submit_walkin_order(self):
        if not self.cart:
            messagebox.showwarning("แจ้งเตือน", "กรุณาเลือกรายการอาหารใส่ตะกร้าก่อนครับ")
            return
        if not self.selected_branch_id:
            messagebox.showwarning("แจ้งเตือน", "กรุณาเลือกสาขาก่อนครับ")
            return

        note = self.ent_customer_note.get().strip()
        total_amount = sum(float(d["item"]["price"]) * d["qty"] for d in self.cart.values())

        def _do_submit():
            try:
                # 1. สร้างบิล Order
                order_payload = {
                    "branch_id": self.selected_branch_id,
                    "customer_name": note or "Walk-in หน้าร้าน",
                    "status": "waiting",
                    "payment_status": "paid",
                    "payment_method": "cash",
                    "total_amount": total_amount,
                    "notes": note,
                }
                order_res = sb_client.table("orders").insert(order_payload).execute()
                new_order_id = order_res.data[0]["id"]

                # 2. บันทึกรายการอาหาร Order Items
                items_payload = []
                for d in self.cart.values():
                    items_payload.append({
                        "order_id": new_order_id,
                        "menu_item_id": d["item"]["id"],
                        "item_name": d["item"]["name"],
                        "quantity": d["qty"],
                        "unit_price": float(d["item"]["price"]),
                    })
                sb_client.table("order_items").insert(items_payload).execute()

                def _success_ui():
                    messagebox.showinfo("สำเร็จ", f"สร้างออเดอร์ #{new_order_id} ส่งเข้าห้องครัวเรียบร้อยแล้ว!")
                    self._cart_clear()
                    self.notebook.select(0)  # สลับกลับไปหน้า KDS
                    self.refresh_data()

                self.after(0, _success_ui)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("ผิดพลาด", f"ไม่สามารถบันทึกออเดอร์ได้: {e}"))

        threading.Thread(target=_do_submit, daemon=True).start()

    # -------------------------------------------------------------
    # BACKGROUND POLLING & STATUS
    # -------------------------------------------------------------
    def _start_background_sync(self):
        def _sync_worker():
            while True:
                time.sleep(5)  # โพลล์ข้อมูลทุกๆ 5 วินาที
                if self.auto_refresh_enabled and self.selected_branch_id:
                    self._fetch_branch_data_thread()

        t = threading.Thread(target=_sync_worker, daemon=True)
        t.start()

    def set_status(self, text):
        self.lbl_status.config(text=text)


if __name__ == "__main__":
    app = QImDesktopApp()
    app.mainloop()
