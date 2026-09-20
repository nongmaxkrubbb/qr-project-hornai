# ร้านอาหารหอใน — Food Ordering + Queue Tracking (Flask + Supabase/Postgres)

แปลงจากระบบคิวโรงพยาบาลเดิม เป็นระบบสั่งอาหารสำหรับร้านในหอพัก:
นักศึกษาสั่งอาหารผ่านมือถือ รอในแอปได้เลยไม่ต้องยืนต่อคิว แล้วระบบแจ้งเตือนอัตโนมัติเมื่ออาหารเสร็จ
ฝั่งครัว/ร้านมีบอร์ดสำหรับกดเปลี่ยนสถานะออเดอร์ (รอคิว → กำลังทำ → พร้อมรับ → รับแล้ว)

## ฟีเจอร์หลัก

- **ฝั่งนักศึกษา**: เลือกเมนู → เพิ่มลงตะกร้า → กรอกชื่อ/เลขห้อง → ยืนยันสั่งอาหาร → ได้ QR Code + หน้าติดตามสถานะแบบ real-time
- **แจ้งเตือนอัตโนมัติ**: หน้าติดตามสถานะ poll ทุก 4 วินาที และใช้ Browser Notification API ยิง push notification ทันทีที่สถานะเปลี่ยนเป็น "พร้อมรับ" (ต้องกดอนุญาตแจ้งเตือนในเบราว์เซอร์ก่อน)
- **ฝั่งร้าน/ครัว**: ล็อกอินแล้วเห็นบอร์ดออเดอร์ 3 คอลัมน์ (รอคิว / กำลังทำ / พร้อมรับ) กดปุ่มเปลี่ยนสถานะได้ทันที พร้อมหน้าจัดการเมนู (เพิ่ม/ปิด-เปิดขาย)
- **Dashboard**: สรุปยอดขาย, ออเดอร์วันนี้, เวลาทำอาหารเฉลี่ย, เมนูขายดี
- ออกเลขออเดอร์แบบ atomic (กันเลขซ้ำเวลาสั่งพร้อมกันหลายคน), CSRF protection, rate limiting, audit log, RLS

## Setup

### 1. สร้างโปรเจ็กต์ Supabase
สมัคร/สร้างโปรเจ็กต์ที่ [supabase.com](https://supabase.com) แล้วเปิด **SQL Editor**
รันไฟล์ `supabase/schema.sql` ทั้งไฟล์ (จะสร้างตาราง, function, RLS policy, และ seed
ร้านตัวอย่าง 1 ร้าน พร้อมเมนูอาหารตัวอย่าง)

### 2. ตั้งค่า environment
```bash
cp .env.example .env
# กรอก DATABASE_URL จาก Supabase Dashboard -> Project Settings -> Database
#   -> Connection string -> URI -> เลือก "Connection pooling" (port 6543)
```

### 3. ติดตั้งและรัน
```bash
pip install -r requirements.txt
python scripts/create_admin.py --username admin --role super_admin
python run.py          # dev
# production: gunicorn -w 4 -b 0.0.0.0:8000 run:app
```

เข้าหน้านักศึกษาที่ `/` และหน้าเจ้าหน้าที่ที่ `/admin/login`

### สร้างพนักงานของร้านใดร้านหนึ่ง (ไม่ใช่ super_admin)
```bash
python scripts/create_admin.py --username staff_a --role branch_admin --branch-id <uuid ของร้าน>
```
หา `branch_id` ได้จากตาราง `branches` ใน Supabase Table Editor

## โครงสร้างโปรเจ็กต์
```
supabase/schema.sql          ตาราง (orders, order_items, menu_items, ...), RLS, atomic order counter, seed data
config.py                    อ่าน secrets จาก ENV ทั้งหมด
app/database.py              connection pool ไป Supabase Postgres
app/utils.py                 QR code, ETA, atomic order numbering
app/routes/user_routes.py    หน้าเมนู, ตะกร้า, checkout, API สถานะออเดอร์
app/routes/admin_routes.py   login, บอร์ดครัว, จัดการเมนู, dashboard
scripts/create_admin.py      bootstrap ผู้ใช้แรกแบบไม่ฝังรหัสผ่านในโค้ด
```

## สถานะออเดอร์ (workflow)
```
waiting (รอคิว) → preparing (กำลังทำ) → ready (พร้อมรับ — จุดที่แจ้งเตือน) → completed (รับแล้ว)
                                       ↘ cancelled (ยกเลิกได้จาก waiting/preparing)
```

## หมายเหตุ
- แจ้งเตือนที่ทำไว้เป็น Browser Notification API (ฝั่ง client) ใช้ได้ทันทีไม่ต้องมี backend push
  เพิ่มเติม — ข้อจำกัดคือต้องเปิดแท็บ/แอปค้างไว้ (หรืออย่างน้อยเปิดล่าสุด) เบราว์เซอร์ถึงจะยิง
  notification ให้ได้ ถ้าต้องการ push แม้ปิดแอปไปแล้ว ขั้นต่อไปคือทำ Web Push (Service Worker + VAPID)
- ยังไม่ได้ต่อ Supabase Realtime ฝั่ง frontend (เปิด publication ไว้ในตาราง `orders` แล้ว) —
  ตอนนี้ใช้ polling ทุก 4 วิแทน ซึ่งเพียงพอสำหรับสเกลระดับร้านในหอ
