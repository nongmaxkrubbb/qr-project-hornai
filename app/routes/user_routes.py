import hashlib
import io
import json
import warnings
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from PIL import Image, ImageOps, UnidentifiedImageError

from app.database import get_supabase
from app.services.errors import UserError
from app.services.orders import (
    PUBLIC_BRANCH_FIELDS, active_ahead, bounded_text, branch_accepting, call_rpc,
    create_order, estimate_wait, get_branch, get_order, money, parse_datetime,
    requested_slots, stable_access_token, token_hash, valid_uuid,
)
from app.utils import generate_promptpay_qr_base64, make_qr_base64

user_bp = Blueprint('user', __name__)
CART_KEY = 'cart_v2'


def _cart():
    return session.get(CART_KEY, {'branch_id': None, 'lines': {}})


def _save_cart(cart):
    session[CART_KEY] = cart
    session['checkout_key'] = str(uuid4())
    session.modified = True


def _token():
    return request.form.get('token') or request.args.get('token') or request.headers.get('X-Order-Token', '')


def _wants_json():
    return request.is_json or request.accept_mimetypes.best == 'application/json'


def _cart_stats(cart):
    return (sum(line['quantity'] for line in cart['lines'].values()),
            sum((money(line.get('unit_price', 0)) * line['quantity'] for line in cart['lines'].values()), Decimal('0.00')))


def _cart_reply(branch_id):
    count, total = _cart_stats(_cart())
    if _wants_json():
        return jsonify(cart_count=count, cart_total=float(total), message='เพิ่มอาหารในตะกร้าแล้ว')
    return redirect(url_for('user.index', branch_id=branch_id))


def _selection(item, option_ids):
    if len(option_ids) > 10 or len(option_ids) != len(set(option_ids)):
        raise UserError('ตัวเลือกอาหารไม่ถูกต้อง')
    available = {str(option['id']): option for option in (item.get('options') or [])}
    if any(option_id not in available for option_id in option_ids):
        raise UserError('ตัวเลือกอาหารเปลี่ยนไป กรุณาเลือกใหม่', 409)
    options = [available[option_id] for option_id in sorted(option_ids)]
    return options, money(item['price']) + sum((money(option.get('price', 0)) for option in options), Decimal('0.00'))


def _load_cart_lines(cart):
    if not cart['lines']:
        return [], Decimal('0.00')
    ids = list({line['menu_item_id'] for line in cart['lines'].values()})
    response = get_supabase().table('menu_items').select('*').eq('branch_id', cart['branch_id']).in_('id', ids).execute()
    items = {str(item['id']): item for item in response.data}
    result, total, changed = [], Decimal('0.00'), False
    for key, line in cart['lines'].items():
        item = items.get(line['menu_item_id'])
        if not item:
            item = {'id': line['menu_item_id'], 'name': 'เมนูที่ถูกนำออก', 'price': line['unit_price'], 'is_available': False, 'options': []}
        try:
            options, price = _selection(item, line.get('option_ids', []))
        except UserError:
            options, price = [], money(line['unit_price'])
            item = dict(item, is_available=False)
        if str(price) != line.get('unit_price'):
            line['unit_price'] = str(price)
            changed = True
        subtotal = price * line['quantity']
        total += subtotal
        result.append({'key': key, 'item': item, 'qty': line['quantity'], 'subtotal': subtotal, 'options': options, 'note': line.get('note', '')})
    if changed:
        _save_cart(cart)
    return result, total


@user_bp.route('/')
def directory():
    campus = bounded_text(request.args.get('campus'), 150, 'หอหรือมหาวิทยาลัย')
    search = bounded_text(request.args.get('q'), 100, 'คำค้น')
    query = get_supabase().table('branches').select(PUBLIC_BRANCH_FIELDS).eq('is_active', True).order('name').limit(200)
    all_campuses = get_supabase().table('branches').select('campus').eq('is_active', True).order('campus').limit(1000).execute().data
    if campus:
        query = query.eq('campus', campus)
    branches = query.execute().data
    if search:
        branches = [b for b in branches if search.casefold() in (b['name'] + ' ' + (b.get('campus') or '')).casefold()]
    queue_counts = {}
    if branches:
        counts = get_supabase().rpc('branch_queue_counts', {'p_branch_ids': [branch['id'] for branch in branches]}).execute().data or []
        queue_counts = {str(row['branch_id']): row['orders_ahead'] for row in counts}
    for branch in branches:
        branch['accepting'] = branch_accepting(branch)
        branch['eta'] = estimate_wait(branch, queue_counts.get(str(branch['id']), 0))
    return render_template('directory.html', branches=branches, campus=campus, search=search, campuses=sorted({b['campus'] for b in all_campuses if b.get('campus')}))


@user_bp.route('/b/<branch_id>')
def index(branch_id):
    branch = get_branch(branch_id)
    response = get_supabase().table('menu_items').select('*').eq('branch_id', branch['id']).eq('is_available', True).order('sort_order').order('category').order('name').execute()
    categories = {}
    for item in response.data:
        categories.setdefault(item['category'], []).append(item)
    cart = _cart()
    count, total = _cart_stats(cart)
    return render_template('index.html', branch=branch, branch_id=branch['id'], categories=categories,
                           cart_count=count, cart_total=total, cart_branch_id=cart['branch_id'],
                           eta=estimate_wait(branch, active_ahead(branch['id'], branch=branch)), accepting=branch_accepting(branch),
                           opening_label=f"{str(branch['opening_time'])[:5]}–{str(branch['closing_time'])[:5]}")


@user_bp.route('/cart/add', methods=['POST'])
def cart_add():
    branch = get_branch(request.form.get('branch_id'))
    item_id = valid_uuid(request.form.get('menu_item_id'))
    cart = _cart()
    if cart['lines'] and cart['branch_id'] != branch['id']:
        raise UserError('ตะกร้ามีอาหารจากอีกร้าน กรุณาสั่งให้เสร็จหรือล้างตะกร้าก่อนเปลี่ยนร้าน', 409)
    try:
        quantity = int(request.form.get('quantity', '1'))
    except ValueError:
        raise UserError('จำนวนอาหารไม่ถูกต้อง')
    if not 1 <= quantity <= 20:
        raise UserError('เลือกอาหารได้ 1–20 จานต่อรายการ')
    response = get_supabase().table('menu_items').select('*').eq('id', item_id).eq('branch_id', branch['id']).eq('is_available', True).limit(1).execute()
    if not response.data:
        raise UserError('เมนูนี้ปิดขายหรือไม่ได้อยู่ในร้านที่เลือก', 409)
    option_ids = request.form.getlist('option_ids')
    options, price = _selection(response.data[0], option_ids)
    note = bounded_text(request.form.get('note'), 120, 'หมายเหตุต่อจาน')
    key = hashlib.sha256(json.dumps([item_id, sorted(option_ids), note], ensure_ascii=False).encode()).hexdigest()[:24]
    existing = cart['lines'].get(key, {}).get('quantity', 0)
    if existing + quantity > 20 or (key not in cart['lines'] and len(cart['lines']) >= 15):
        raise UserError('ตะกร้ารองรับสูงสุด 15 รายการและ 20 จานต่อรายการ')
    cart['branch_id'] = branch['id']
    cart['lines'][key] = {'menu_item_id': item_id, 'quantity': existing + quantity, 'option_ids': sorted(option_ids), 'note': note, 'unit_price': str(price)}
    _save_cart(cart)
    return _cart_reply(branch['id'])


@user_bp.route('/cart/update', methods=['POST'])
def cart_update():
    cart = _cart()
    if request.form.get('branch_id') != cart['branch_id']:
        raise UserError('ตะกร้าเปลี่ยนร้านแล้ว กรุณาเปิดตะกร้าใหม่', 409)
    key = request.form.get('line_key')
    if key not in cart['lines']:
        raise UserError('ไม่พบรายการในตะกร้า', 404)
    try:
        quantity = 0 if request.form.get('remove') == '1' else int(request.form.get('quantity', '0'))
    except ValueError:
        raise UserError('จำนวนอาหารไม่ถูกต้อง')
    if not 0 <= quantity <= 20:
        raise UserError('จำนวนอาหารต้องอยู่ระหว่าง 0–20')
    if quantity:
        cart['lines'][key]['quantity'] = quantity
    else:
        del cart['lines'][key]
    _save_cart(cart)
    return redirect(url_for('user.cart_view', branch_id=cart['branch_id']))


@user_bp.route('/cart/remove', methods=['POST'])
def cart_remove():
    # Old forms are no longer issued; fail closed rather than removing a different item.
    raise UserError('กรุณาเปิดหน้าตะกร้าใหม่เพื่อแก้ไขรายการ', 409)


@user_bp.route('/cart/clear', methods=['POST'])
def cart_clear():
    branch_id = request.form.get('branch_id')
    _save_cart({'branch_id': None, 'lines': {}})
    if branch_id:
        try:
            branch = get_branch(branch_id)
        except UserError:
            return redirect(url_for('user.directory'))
        return redirect(url_for('user.index', branch_id=branch['id']))
    return redirect(url_for('user.directory'))


@user_bp.route('/cart')
def cart_view():
    cart = _cart()
    branch_id = cart['branch_id'] or request.args.get('branch_id')
    if not branch_id:
        flash('เลือกร้านและอาหารก่อนเริ่มสั่ง', 'info')
        return redirect(url_for('user.directory'))
    branch = get_branch(branch_id, include_inactive=True)
    lines, total = _load_cart_lines(cart)
    if not session.get('checkout_key'):
        session['checkout_key'] = str(uuid4())
    return render_template('cart.html', branch=branch, branch_id=branch['id'], lines=lines, total=total,
                           cart_count=_cart_stats(cart)[0], idempotency_key=session['checkout_key'],
                           requested_slots=requested_slots(branch), eta=estimate_wait(branch, active_ahead(branch['id'], branch=branch)), accepting=branch_accepting(branch))


@user_bp.route('/checkout', methods=['POST'])
def checkout():
    key = valid_uuid(request.form.get('idempotency_key'))
    # A resubmission after the success response resolves to the same existing order.
    for previous in session.get('order_history', []):
        if previous.get('key') == key:
            return redirect(url_for('user.status_page', order_id=previous['id'], token=previous['token']), code=303)
    if key != session.get('checkout_key'):
        raise UserError('ตะกร้ามีการเปลี่ยนแปลง กรุณาเปิดตะกร้าใหม่ก่อนยืนยัน', 409)
    cart = _cart()
    branch_id = valid_uuid(request.form.get('branch_id'))
    if not cart['lines'] or cart['branch_id'] != branch_id:
        raise UserError('ตะกร้าว่างหรือไม่ตรงกับร้านที่เลือก', 409)
    method = request.form.get('payment_method', '')
    if method not in ('cash', 'promptpay'):
        raise UserError('กรุณาเลือกเงินสดหรือพร้อมเพย์')
    name = bounded_text(request.form.get('student_name'), 100, 'ชื่อผู้รับ', True)
    room = bounded_text(request.form.get('room_no'), 40, 'เลขห้อง')
    note = bounded_text(request.form.get('note'), 300, 'หมายเหตุ')
    requested_for = request.form.get('requested_for') or None
    if requested_for:
        try:
            parsed = datetime.fromisoformat(requested_for.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                raise ValueError
            requested_for = parsed.isoformat()
        except ValueError:
            raise UserError('เวลารับอาหารไม่ถูกต้อง')
    token = stable_access_token(key)
    items = [dict(menu_item_id=line['menu_item_id'], quantity=line['quantity'], option_ids=line['option_ids'],
                  note=line['note'], expected_unit_price=line['unit_price']) for line in cart['lines'].values()]
    order = create_order(branch_id=branch_id, items=items, student_name=name, room_no=room, note=note,
                         payment_method=method, idempotency_key=key, token_hash=token_hash(token),
                         staff_id=None, requested_for=requested_for)
    session['order_history'] = [{'id': order['id'], 'key': key, 'token': token}] + session.get('order_history', [])[:4]
    _save_cart({'branch_id': None, 'lines': {}})
    target = 'user.payment_page' if order['status'] == 'pending_payment' else 'user.status_page'
    return redirect(url_for(target, order_id=order['id'], token=token), code=303)


@user_bp.route('/order/<int:order_id>')
def status_page(order_id):
    token = _token()
    order = get_order(order_id, token)
    order = _expire_if_needed(order, token)
    branch = get_branch(order['branch_id'], include_inactive=True)
    recent = [entry for entry in session.get('order_history', []) if entry['id'] != order_id]
    session['order_history'] = [{'id': order_id, 'key': order.get('idempotency_key'), 'token': token}] + recent[:4]
    base = current_app.config.get('PUBLIC_BASE_URL', '').rstrip('/')
    status_path = url_for('user.status_page', order_id=order_id, token=token)
    tracking_url = base + status_path if base else url_for('user.status_page', order_id=order_id, token=token, _external=True)
    return render_template('status.html', qr_b64=make_qr_base64(tracking_url), order_id=order_id, order=order, token=token, branch=branch,
                           initial_status=_status_payload(order, branch),
                           status_api_url=url_for('user.api_order_status', order_id=order_id, token=token),
                           payment_url=url_for('user.payment_page', order_id=order_id, token=token),
                           push_public_key=current_app.config.get('VAPID_PUBLIC_KEY', '') if all(current_app.config.get(k) for k in ('VAPID_PRIVATE_KEY', 'VAPID_PUBLIC_KEY', 'VAPID_SUBJECT')) else '')


def _expire_if_needed(order, token):
    # Expiration is also run by the worker; enforce it when an unpaid customer returns.
    if order.get('status') == 'pending_payment' and order.get('payment_status') in ('pending', 'rejected') and order.get('expires_at') and parse_datetime(order['expires_at']) <= datetime.now(timezone.utc):
        call_rpc('expire_unpaid_orders', {'p_branch_id': order['branch_id']})
        order = get_order(order['id'], token)
    return order


def _status_payload(order, branch):
    ahead = active_ahead(branch['id'], order, branch) if order['status'] in ('waiting', 'preparing') else 0
    eta = estimate_wait(branch, ahead, order)
    return dict(order_code=order['order_code'], status=order['status'], payment_status=order['payment_status'],
                   payment_reason=order.get('payment_reason') or order.get('cancellation_reason') or '',
                   total_price=float(order['total_price']),
                   items=[{'name': item['item_name'], 'quantity': item['quantity'], 'unit_price': float(item['unit_price']),
                           'options': item.get('options') or [], 'note': item.get('note') or ''} for item in order.get('order_items', [])],
                   orders_ahead=ahead, eta_minutes=eta['max'], eta_min=eta['min'], eta_max=eta['max'],
                   branch={'name': branch['name'], 'pickup_point': branch.get('pickup_point') or branch.get('address') or ''},
                   created_at=order['created_at'], requested_for=order.get('requested_for'), promised_ready_at=order.get('promised_ready_at'),
                   arrived_at=order.get('arrived_at'), can_cancel=order['status'] in ('pending_payment', 'waiting') and order['payment_status'] != 'verifying')


@user_bp.route('/api/order_status/<int:order_id>')
def api_order_status(order_id):
    token = _token()
    order = _expire_if_needed(get_order(order_id, token), token)
    branch = get_branch(order['branch_id'], include_inactive=True)
    return jsonify(_status_payload(order, branch))


@user_bp.route('/payment/<int:order_id>')
def payment_page(order_id):
    token = _token()
    order = _expire_if_needed(get_order(order_id, token), token)
    branch = get_branch(order['branch_id'], include_inactive=True)
    if order['payment_method'] != 'promptpay' or order['status'] != 'pending_payment':
        return redirect(url_for('user.status_page', order_id=order_id, token=token))
    # New orders keep the recipient selected at checkout, even if the shop edits
    # its receiving account later. Legacy orders use the configured shop account.
    recipient = order.get('payment_promptpay_id') or branch.get('promptpay_id')
    recipient_name = order.get('payment_promptpay_name') or branch.get('promptpay_name')
    reviewing = order['payment_status'] == 'verifying'
    if not reviewing and (not branch.get('is_active') or not recipient):
        raise UserError('ร้านหยุดรับโอนชั่วคราว กรุณาติดต่อร้านก่อนชำระเงิน', 409)
    qr = '' if reviewing else generate_promptpay_qr_base64(recipient, money(order['total_price']))
    payment_branch = dict(branch, promptpay_id=recipient, promptpay_name=recipient_name)
    return render_template('payment.html', order=order, branch=payment_branch, token=token, qr_b64=qr, promptpay_id=recipient)


def _normalise_slip(file):
    payload = file.read(current_app.config['MAX_SLIP_BYTES'] + 1)
    if not payload or len(payload) > current_app.config['MAX_SLIP_BYTES']:
        raise UserError('รูปหลักฐานต้องมีขนาดไม่เกิน 5 MB', 413)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(payload)) as picture:
                if picture.format not in ('JPEG', 'PNG', 'WEBP') or picture.width * picture.height > 20_000_000:
                    raise ValueError
                picture.load()
                picture = ImageOps.exif_transpose(picture).convert('RGB')
                picture.thumbnail((2400, 2400))
                output = io.BytesIO()
                picture.save(output, format='JPEG', quality=90)
                return output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise UserError('กรุณาใช้ไฟล์ภาพ JPEG, PNG หรือ WebP ที่เปิดอ่านได้')


@user_bp.route('/payment/<int:order_id>/upload', methods=['POST'])
def upload_slip(order_id):
    token = _token()
    order = get_order(order_id, token)
    if order['payment_method'] != 'promptpay' or order['status'] != 'pending_payment' or order['payment_status'] not in ('pending', 'rejected'):
        raise UserError('สถานะออเดอร์นี้ไม่อนุญาตให้อัปโหลดหลักฐาน', 409)
    if order.get('expires_at') and parse_datetime(order['expires_at']) <= datetime.now(timezone.utc) and order['payment_status'] != 'verifying':
        raise UserError('ออเดอร์หมดเวลาชำระเงินแล้ว กรุณาสั่งใหม่', 409)
    file = request.files.get('slip')
    if not file or not file.filename:
        raise UserError('กรุณาแนบรูปหลักฐานการโอน')
    image_bytes = _normalise_slip(file)
    path = f'orders/{order_id}/{uuid4().hex}.jpg'
    storage = get_supabase().storage.from_('slips')
    storage.upload(path, image_bytes, {'content-type': 'image/jpeg', 'upsert': 'false'})
    try:
        call_rpc('attach_order_slip', {'p_order_id': order_id, 'p_token_hash': token_hash(token), 'p_slip_path': path})
    except Exception:
        # Compensate a rejected state race without ever changing the order backwards.
        try:
            storage.remove([path])
        except Exception:
            current_app.logger.warning('slip_cleanup_failed order_id=%s', order_id)
        raise
    flash('ส่งหลักฐานแล้ว รอร้านตรวจสอบก่อนเริ่มทำอาหาร', 'success')
    return redirect(url_for('user.status_page', order_id=order_id, token=token), code=303)


@user_bp.route('/order/<int:order_id>/action', methods=['POST'])
def customer_action(order_id):
    token = _token()
    get_order(order_id, token)
    action = request.form.get('action')
    if action not in ('cancel', 'arrive'):
        raise UserError('รายการไม่ถูกต้อง')
    reason = bounded_text(request.form.get('reason'), 300, 'เหตุผล', action == 'cancel')
    call_rpc('customer_order_action', {'p_order_id': order_id, 'p_token_hash': token_hash(token), 'p_action': action, 'p_reason': reason})
    flash('บันทึกรายการแล้ว', 'success')
    return redirect(url_for('user.status_page', order_id=order_id, token=token), code=303)


@user_bp.route('/history')
def history():
    orders = []
    for entry in session.get('order_history', [])[:5]:
        try:
            order = get_order(entry['id'], entry['token'])
            branch = get_branch(order['branch_id'], include_inactive=True)
        except UserError:
            continue
        orders.append({**order, 'token': entry['token'], 'branch': branch, 'branch_name': branch['name']})
    return render_template('history.html', orders=orders)


@user_bp.route('/order/<int:order_id>/reorder', methods=['POST'])
def reorder(order_id):
    order = get_order(order_id, _token())
    branch = get_branch(order['branch_id'])
    if _cart()['lines']:
        raise UserError('กรุณาสั่งหรือล้างตะกร้าปัจจุบันก่อนสั่งซ้ำ', 409)
    cart = {'branch_id': branch['id'], 'lines': {}}
    skipped = 0
    for previous in order.get('order_items', [])[:15]:
        item_id = previous.get('menu_item_id')
        if not item_id:
            skipped += 1
            continue
        response = get_supabase().table('menu_items').select('*').eq('id', item_id).eq('branch_id', branch['id']).eq('is_available', True).limit(1).execute()
        if not response.data:
            skipped += 1
            continue
        option_ids = [str(option['id']) for option in previous.get('options') or []]
        try:
            _, price = _selection(response.data[0], option_ids)
        except UserError:
            skipped += 1
            continue
        key = uuid4().hex[:24]
        cart['lines'][key] = {'menu_item_id': str(item_id), 'quantity': min(20, previous['quantity']), 'option_ids': option_ids,
                              'note': (previous.get('note') or '')[:120], 'unit_price': str(price)}
    _save_cart(cart)
    flash('เพิ่มรายการที่ยังขายอยู่ด้วยราคาปัจจุบันแล้ว' + (f' ข้าม {skipped} รายการที่ไม่พร้อมขาย' if skipped else ''), 'info')
    return redirect(url_for('user.cart_view', branch_id=branch['id']))


@user_bp.route('/order/<int:order_id>/push', methods=['POST'])
def push_subscribe(order_id):
    from app.services.notifications import validate_subscription
    data = request.get_json(silent=True) or {}
    token = data.get('token') or _token()
    order = get_order(order_id, token)
    if not all(current_app.config.get(k) for k in ('VAPID_PRIVATE_KEY', 'VAPID_PUBLIC_KEY', 'VAPID_SUBJECT')):
        raise UserError('ระบบแจ้งเตือนเบื้องหลังยังไม่เปิดใช้งาน กรุณาเปิดหน้าติดตามไว้', 503)
    if order['status'] in ('completed', 'cancelled'):
        raise UserError('ออเดอร์จบแล้ว', 409)
    subscription = validate_subscription(data.get('subscription') or data)
    get_supabase().table('push_subscriptions').upsert({'order_id': order_id, 'endpoint': subscription['endpoint'], 'keys': subscription['keys']}, on_conflict='order_id,endpoint').execute()
    return jsonify(ok=True)
