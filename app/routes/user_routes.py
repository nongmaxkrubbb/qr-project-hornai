from flask import Blueprint, render_template, request, redirect, url_for, jsonify, session

from app.database import get_supabase
from app.utils import next_order_number, make_qr_base64, orders_ahead, avg_prep_seconds, iso

user_bp = Blueprint('user', __name__)

CART_SESSION_KEY = "cart"  # { menu_item_id(str): quantity(int) }


def _get_cart():
    return session.get(CART_SESSION_KEY, {})


def _save_cart(cart):
    session[CART_SESSION_KEY] = cart
    session.modified = True


_cache_first_branch = None
_cache_first_branch_time = 0

def _first_active_branch():
    global _cache_first_branch, _cache_first_branch_time
    import time
    if _cache_first_branch and time.time() - _cache_first_branch_time < 300:
        return _cache_first_branch
        
    supabase = get_supabase()
    res = supabase.table("branches").select("id").eq("is_active", True).order("created_at").limit(1).execute()
    branch_id = res.data[0]["id"] if res.data else None
    
    _cache_first_branch = branch_id
    _cache_first_branch_time = time.time()
    return branch_id


_cache_menus = {}

@user_bp.route("/")
@user_bp.route("/b/<branch_id>")
def index(branch_id=None):
    if branch_id is None:
        branch_id = _first_active_branch()
        if not branch_id:
            return "ยังไม่มีร้านที่ตั้งค่าไว้ในระบบ", 500

    import time
    now = time.time()
    
    if branch_id in _cache_menus and now - _cache_menus[branch_id]['time'] < 60:
        categories = _cache_menus[branch_id]['data']
    else:
        supabase = get_supabase()
        res = supabase.table("menu_items").select("*") \
            .eq("branch_id", branch_id).eq("is_available", True) \
            .order("category").order("name").execute()
        items = res.data
    
        categories = {}
        for item in items:
            categories.setdefault(item["category"], []).append(item)
            
        _cache_menus[branch_id] = {'time': now, 'data': categories}

    cart = _get_cart()
    cart_count = sum(cart.values())

    return render_template(
        "index.html", categories=categories, branch_id=branch_id, cart_count=cart_count
    )


@user_bp.route("/cart/add", methods=["POST"])
def cart_add():
    menu_item_id = request.form.get("menu_item_id")
    branch_id = request.form.get("branch_id")
    cart = _get_cart()
    cart[menu_item_id] = cart.get(menu_item_id, 0) + 1
    _save_cart(cart)
    return redirect(url_for("user.index", branch_id=branch_id))


@user_bp.route("/cart/remove", methods=["POST"])
def cart_remove():
    menu_item_id = request.form.get("menu_item_id")
    branch_id = request.form.get("branch_id")
    cart = _get_cart()
    if menu_item_id in cart:
        cart[menu_item_id] -= 1
        if cart[menu_item_id] <= 0:
            del cart[menu_item_id]
        _save_cart(cart)
    return redirect(url_for("user.cart_view", branch_id=branch_id))


@user_bp.route("/cart")
def cart_view():
    branch_id = request.args.get("branch_id")
    cart = _get_cart()
    supabase = get_supabase()

    lines = []
    total = 0
    if cart:
        ids = list(cart.keys())
        res = supabase.table("menu_items").select("*").in_("id", ids).execute()
        rows = {str(r["id"]): r for r in res.data}
        for item_id, qty in cart.items():
            item = rows.get(item_id)
            if not item:
                continue
            subtotal = float(item["price"]) * qty
            total += subtotal
            lines.append({"item": item, "qty": qty, "subtotal": subtotal})

    if branch_id is None and lines:
        branch_id = str(lines[0]["item"]["branch_id"])
    elif branch_id is None:
        branch_id = _first_active_branch()

    return render_template("cart.html", lines=lines, total=total, branch_id=branch_id)


@user_bp.route("/checkout", methods=["POST"])
def checkout():
    branch_id = request.form.get("branch_id")
    student_name = request.form.get("student_name", "").strip()
    room_no = request.form.get("room_no", "").strip()
    note = request.form.get("note", "").strip()
    payment_method = request.form.get("payment_method", "cash")

    cart = _get_cart()
    if not student_name or not cart:
        return redirect(url_for("user.cart_view", branch_id=branch_id))

    supabase = get_supabase()

    ids = list(cart.keys())
    res = supabase.table("menu_items").select("*").in_("id", ids).execute()
    rows = {str(r["id"]): r for r in res.data}

    order_lines = []
    total = 0
    for item_id, qty in cart.items():
        item = rows.get(item_id)
        if not item:
            continue
        subtotal = float(item["price"]) * qty
        total += subtotal
        order_lines.append((item["id"], item["name"], item["price"], qty))

    if not order_lines:
        return redirect(url_for("user.index", branch_id=branch_id))

    order_code = next_order_number(branch_id)
    
    order_data = {
        "order_code": order_code,
        "branch_id": branch_id,
        "student_name": student_name,
        "room_no": room_no or None,
        "note": note or None,
        "status": "waiting" if payment_method == "cash" else "pending_payment",
        "payment_method": payment_method,
        "payment_status": "pending",
        "total_price": total
    }
    res_order = supabase.table("orders").insert(order_data).execute()
    order_id = res_order.data[0]["id"]

    order_items_data = [
        {
            "order_id": order_id,
            "menu_item_id": menu_item_id,
            "item_name": name,
            "unit_price": price,
            "quantity": qty
        }
        for menu_item_id, name, price, qty in order_lines
    ]
    supabase.table("order_items").insert(order_items_data).execute()

    _save_cart({})
    
    if payment_method == "promptpay":
        return redirect(url_for("user.payment_page", order_id=order_id))

    status_url = url_for("user.status_page", order_id=order_id, _external=True)
    qr_b64 = make_qr_base64(status_url)

    return render_template(
        "ticket.html",
        order_code=order_code,
        order_id=order_id,
        qr_b64=qr_b64,
        status_url=status_url,
    )


@user_bp.route("/order/<int:order_id>")
def status_page(order_id):
    return render_template("status.html", order_id=order_id)


@user_bp.route("/api/order_status/<int:order_id>")
def api_order_status(order_id):
    supabase = get_supabase()
    res = supabase.table("orders").select("*, order_items(item_name, unit_price, quantity)").eq("id", order_id).execute()
    order = res.data[0] if res.data else None
    
    if not order:
        return jsonify({"error": "ไม่พบออเดอร์นี้"}), 404

    items = order.get("order_items", [])

    ahead = orders_ahead(order) if order["status"] in ("waiting", "preparing") else 0
    avg_secs = avg_prep_seconds(order["branch_id"])
    eta_minutes = round((ahead * avg_secs) / 60) if order["status"] in ("waiting", "preparing") else 0

    return jsonify(
        {
            "order_code": order["order_code"],
            "status": order["status"],
            "student_name": order["student_name"],
            "room_no": order["room_no"],
            "orders_ahead": ahead,
            "eta_minutes": eta_minutes,
            "total_price": float(order["total_price"]),
            "items": [
                {"name": i["item_name"], "quantity": i["quantity"], "unit_price": float(i["unit_price"])}
                for i in items
            ],
            "created_at": iso(order["created_at"]),
        }
    )

@user_bp.route("/payment/<int:order_id>")
def payment_page(order_id):
    supabase = get_supabase()
    res = supabase.table("orders").select("*").eq("id", order_id).execute()
    if not res.data:
        return "Order not found", 404
        
    order = res.data[0]
    import os
    from app.utils import generate_promptpay_qr_base64
    
    promptpay_id = os.getenv("PROMPTPAY_ID", "0000000000") # กำหนดค่า default ถ้าไม่มีใน .env
    qr_b64 = generate_promptpay_qr_base64(promptpay_id, float(order["total_price"]))
    
    return render_template("payment.html", order=order, qr_b64=qr_b64, promptpay_id=promptpay_id)

import uuid
@user_bp.route("/payment/<int:order_id>/upload", methods=["POST"])
def upload_slip(order_id):
    file = request.files.get("slip")
    if not file or not file.filename:
        return "กรุณาแนบสลิป", 400
        
    file_bytes = file.read()
    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'jpg'
    filename = f"slip_{order_id}_{uuid.uuid4().hex[:8]}.{ext}"
    
    supabase = get_supabase()
    
    # Upload to Supabase Storage
    try:
        supabase.storage.from_("slips").upload(filename, file_bytes, {"content-type": file.content_type})
        slip_url = supabase.storage.from_("slips").get_public_url(filename)
        
        # Update order status
        supabase.table("orders").update({
            "payment_status": "verifying",
            "slip_url": slip_url,
            "status": "waiting" # กลับเข้าคิว
        }).eq("id", order_id).execute()
        
    except Exception as e:
        print("Error uploading slip:", e)
        return "เกิดข้อผิดพลาดในการอัปโหลดสลิป กรุณาลองใหม่", 500
        
    status_url = url_for("user.status_page", order_id=order_id, _external=True)
    from app.utils import make_qr_base64
    qr_b64 = make_qr_base64(status_url)
    
    return render_template(
        "ticket.html",
        order_code=request.form.get("order_code", ""),
        order_id=order_id,
        qr_b64=qr_b64,
        status_url=status_url,
    )
