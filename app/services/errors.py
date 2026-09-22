class UserError(Exception):
    def __init__(self, message, status=400):
        self.message = message
        self.status = status
        super().__init__(message)


MESSAGES = {
    "slip_changed": (409, "สลิปเปลี่ยนไประหว่างตรวจ กรุณาเปิดบอร์ดครัวและตรวจสลิปล่าสุดก่อนยืนยัน"),
    "payment_review_required": (409, "กรุณารอร้านตรวจสอบสลิปก่อนยกเลิก เพื่อให้ตรวจยอดและคืนเงินได้ถูกต้อง"),
    "price_changed": (409, "ราคาเมนูเปลี่ยนไป กรุณาเปิดตะกร้าเพื่อตรวจยอดใหม่ก่อนยืนยัน"),
    "forbidden": (403, "คุณไม่มีสิทธิ์ทำรายการนี้"),
    "order_not_found": (404, "ไม่พบออเดอร์หรือไม่มีสิทธิ์เข้าถึง"),
    "branch_not_found": (404, "ไม่พบร้านนี้"),
    "branch_closed": (409, "ร้านยังไม่เปิดรับออเดอร์ กรุณาตรวจเวลาเปิดร้าน"),
    "branch_paused": (409, "ร้านพักรับออเดอร์ชั่วคราว กรุณาลองอีกครั้งภายหลัง"),
    "invalid_items": (400, "รายการอาหารไม่ถูกต้อง กรุณาตรวจตะกร้าอีกครั้ง"),
    "item_unavailable": (409, "บางเมนูปิดขายหรือไม่ใช่เมนูของร้านนี้ กรุณาตรวจตะกร้า"),
    "invalid_options": (409, "ตัวเลือกอาหารเปลี่ยนไป กรุณาเลือกเมนูใหม่"),
    "invalid_payment_method": (400, "วิธีชำระเงินไม่ถูกต้อง"),
    "promptpay_not_configured": (409, "ร้านยังไม่ได้ตั้งค่ารับโอน กรุณาเลือกเงินสด"),
    "idempotency_conflict": (409, "รายการนี้เปลี่ยนไปแล้ว กรุณาเปิดตะกร้าใหม่ก่อนยืนยัน"),
    "invalid_transition": (409, "สถานะออเดอร์เปลี่ยนไปแล้ว กรุณารีเฟรชและตรวจสอบอีกครั้ง"),
    "payment_required": (409, "กรุณายืนยันการรับเงินก่อนทำรายการนี้"),
    "reason_required": (400, "กรุณาระบุเหตุผล"),
    "reference_required": (400, "กรุณาระบุเลขอ้างอิงการโอนที่ตรวจสอบแล้ว"),
    "duplicate_reference": (409, "เลขอ้างอิงนี้ถูกใช้ยืนยันการชำระเงินแล้ว"),
    "order_expired": (409, "ออเดอร์นี้หมดเวลาชำระเงินแล้ว กรุณาสั่งใหม่"),
    "invalid_slot": (409, "เวลารับที่เลือกไม่พร้อมให้บริการ กรุณาเลือกเวลาใหม่"),
    "slot_full": (409, "ช่วงเวลานี้เต็มแล้ว กรุณาเลือกเวลาอื่น"),
    "invalid_input": (400, "ข้อมูลไม่ถูกต้อง กรุณาตรวจสอบรายการอีกครั้ง"),
    "invalid_slip": (400, "ไฟล์หลักฐานไม่ถูกต้อง กรุณาใช้รูปภาพ JPEG, PNG หรือ WebP"),
}


ALIASES = {
    "branch_unavailable": "branch_not_found", "promptpay_unavailable": "promptpay_not_configured",
    "preorder_disabled": "invalid_slot", "invalid_pickup_slot": "invalid_slot", "pickup_slot_full": "slot_full",
    "invalid_quantity": "invalid_items", "invalid_customer_details": "invalid_input", "invalid_capability": "order_not_found",
    "item_note_too_long": "invalid_input", "menu_unavailable": "item_unavailable", "invalid_menu_price": "invalid_input",
    "duplicate_option": "invalid_options", "invalid_option": "invalid_options", "invalid_option_price": "invalid_options",
    "invalid_total": "invalid_input", "invalid_details": "invalid_input", "duplicate_payment_reference": "duplicate_reference",
    "invalid_action": "invalid_input", "invalid_slip_path": "invalid_slip",
}
for alias, original in ALIASES.items():
    MESSAGES[alias] = MESSAGES[original]


def database_error(exc):
    """Expose only known domain messages, never raw database details."""
    message = str(getattr(exc, "message", ""))
    for key, (status, thai) in MESSAGES.items():
        if message == key or message.startswith(key + ":"):
            return UserError(thai, status)
    return None
