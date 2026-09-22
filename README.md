# 🍲 คิวอิ่ม (Q-Im) — ระบบสั่งอาหารล่วงหน้าและจัดการคิวผ่าน QR Code

[![Python](https://img.shields.io/badge/Python-3.12%2B%20%7C%203.14-3776AB?logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Framework-Flask%203.x-000000?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![Supabase](https://img.shields.io/badge/Database-Supabase%20%7C%20Postgres-3ECF8E?logo=supabase&logoColor=white)](https://supabase.com/)
[![Tests](https://img.shields.io/badge/Unit%20Tests-72%2F72%20Passing-brightgreen?logo=pytest&logoColor=white)]()
[![License](https://img.shields.io/badge/License-MIT-blue.svg)]()

**คิวอิ่ม** คือระบบเว็บแอปพลิเคชันสำหรับสั่งอาหารล่วงหน้า ติดตามคิว และบริหารจัดการงานครัวสำหรับศูนย์อาหาร โรงอาหาร มหาวิทยาลัย หรือหอพัก ออกแบบมาเพื่อความรวดเร็ว รองรับงานพร้อมกันจำนวนมาก มีความปลอดภัยระดับสูง (Zero-Trust Data Boundaries) และใช้งานง่ายโดยที่ลูกค้า**ไม่ต้องดาวน์โหลดแอปหรือสมัครสมาชิก**

---

## ✨ จุดเด่นและฟังก์ชันการทำงาน (Key Features)

### 📱 1. ฝั่งลูกค้า (Customer & Walk-in)
* **ไม่ต้องสมัครสมาชิก**: สั่งอาหารได้ทันที เข้าถึงและติดตามเฉพาะออเดอร์ของตนเองผ่าน **Capability Token** (ปลอดภัย ไม่สามารถเดาเลขบิลของผู้อื่นได้)
* **เลือกร้านและดูคิวเรียลไทม์**: ดูร้านอาหารแยกตามวิทยาเขต/หอพัก ทราบจุดรับอาหาร เวลาเปิด-ปิด และเวลารอโดยประมาณ
* **ปรับแต่งเมนูตามชอบ**: เลือกระดับความหวาน ท็อปปิ้ง และระบุหมายเหตุต่อจานได้
* **การชำระเงินยืดหยุ่น**:
  - สร้าง QR Code พร้อมเพย์แบบ Dynamic (`EMVCo PromptPay`) พร้อมระบุยอดเงินถูกต้องอัตโนมัติ
  - แนบภาพสลิปโอนเงิน (ตรวจสอบความถูกต้องและปรับทิศทางภาพอัตโนมัติ)
  - หรือเลือกชำระเงินสดหน้าร้าน (หากร้านเปิดรับ)
* **ติดตามสถานะและเวลาประมาณการ (Smart ETA)**: อัปเดตสถานะแบบเรียลไทม์ (รอคิว → กำลังทำ → พร้อมรับ → รับแล้ว) พร้อมคำนวณเวลารอจริงตามกำลังการผลิตของครัว
* **แจ้งเตือนอาหารเสร็จ (Notifications)**: รองรับทั้ง Browser Notification และ Web Push Service Worker บนสมาร์ทโฟน
* **ประวัติการสั่งซื้อและสั่งซ้ำ (Re-order)**: บันทึกออเดอร์ในอุปกรณ์อย่างปลอดภัย เรียกดูย้อนหลังและกดสั่งซ้ำได้ในคลิกเดียว

---

### 👨‍🍳 2. ฝั่งพนักงานหน้าร้านและในครัว (Kitchen & Staff)
* **บอร์ดครัวเรียลไทม์ (Kitchen Display Board)**: ออกแบบมาเพื่อหน้าจอ Tablet และคอมพิวเตอร์หน้าร้านโดยเฉพาะ
* **ตรวจสอบสลิปโอนเงิน (Inline Slip Verification)**: ตรวจสอบรูปสลิปขยายดูได้ทันท่วงที กดยืนยันยอดเงิน หรือปฏิเสธพร้อมระบุเหตุผล
* **ระบบสั่งอาหารหน้าร้าน (Walk-in Ordering)**: ให้พนักงานกดสั่งอาหารให้ลูกค้าหน้าร้านได้ โดยระบบจะจัดเข้าคิวรวมกับออเดอร์ออนไลน์แบบ Atomic ป้องกันคิวแซง
* **ควบคุมการรับงาน**: ปุ่มพักรับออเดอร์ชั่วคราวเมื่อครัวหนาแน่น และเปิดรับเมื่อพร้อม

---

### 🏬 3. ฝั่งผู้จัดการสาขา (Branch Admin)
* **จัดการเมนูอาหาร (Menu Management)**: เพิ่ม แก้ไข ลบ กำหนดหมวดหมู่ เปิด-ปิดการขายรายเมนู และจัดการตัวเลือกเสริม (Options/Toppings)
* **ตั้งค่าสาขา (Branch Settings)**:
  - กำหนดเวลาเปิด-ปิดร้าน และเขตเวลา (Timezone)
  - ผูกบัญชีพร้อมเพย์ประจำสาขา (เบอร์โทร, เลขบัตรประชาชน หรือ e-Wallet)
  - กำหนดกำลังการผลิตของครัว (Kitchen Capacity) และเวลาเตรียมเฉลี่ย (Prep Minutes)
  - กำหนดช่วงเวลารับอาหารล่วงหน้า (Pre-order Slots)
* **แดชบอร์ดรายงาน (Branch Analytics)**: สรุปยอดขาย ออเดอร์สำเร็จ/ยกเลิก และเวลาเฉลี่ยในการทำอาหารประจำวัน
* **พิมพ์ QR Code หน้าร้าน**: สร้างและพิมพ์ป้าย QR Code ประจำสาขาสำหรับติดโต๊ะหรือเคาน์เตอร์

---

### ⚡ 4. ฝั่งผู้ดูแลระบบสูงสุด (Super Admin & Org Admin)
* **ศูนย์ควบคุมระบบส่วนกลาง (Super Admin Dashboard)**:
  - สรุปสถิติทั่วทั้งระบบ: จำนวนองค์กร, สาขาที่เปิดให้บริการ, จำนวนผู้ใช้งานแยกตาม Role, ยอดขายรวม
* **จัดการบัญชีผู้ใช้และรหัสผ่าน (Staff & Credentials)**:
  - สร้างบัญชีใหม่ให้เจ้าหน้าที่ทุกระดับ (`super_admin`, `org_admin`, `branch_admin`, `staff`)
  - รีเซ็ตรหัสผ่านให้เจ้าหน้าที่ได้ทันทีผ่านระบบ Supabase Auth Admin
  - สลับสถานะเปิดใช้งาน / ระงับสิทธิ์บัญชี (Active/Inactive Toggle)
* **จัดการเปิดสาขาและร้านอาหาร (Branch Management)**:
  - สร้างร้านอาหารใหม่ ผูกเข้ากับองค์กร กำหนดวิทยาเขต จุดรับอาหาร และเขตเวลา
  - สลับสถานะเปิด/ปิดร้าน หรือ พัก/เปิดรับออเดอร์ได้จากส่วนกลาง
* **จัดการองค์กรและแบรนด์ (Organization Management)**:
  - สร้างเครือข่ายร้านอาหารและบริหารแบรนด์

---

## 🔐 ลำดับขั้นสิทธิ์ในระบบ (Role Hierarchy)

| บทบาท (Role) | สิทธิ์ | ขอบเขตการทำงาน (Scope) | หน้าที่หลัก |
| :--- | :---: | :--- | :--- |
| **`super_admin`** | ระดับ 3 | ทุกองค์กร และทุกสาขาทั่วทั้งระบบ | ศูนย์ควบคุมส่วนกลาง สร้างผู้ใช้ รีเซ็ตรหัสผ่าน เปิดสาขาใหม่ จัดการองค์กร |
| **`org_admin`** | ระดับ 2 | ทุกสาขาในองค์กรตนเอง | ดูแลภาพรวมของแบรนด์/เครือข่ายร้านอาหาร |
| **`branch_admin`** | ระดับ 1 | เฉพาะสาขาที่สังกัด | จัดการเมนู ตั้งค่าสาขา ผูกพร้อมเพย์ ดูแดชบอร์ด และพิมพ์ QR ร้าน |
| **`staff`** | ระดับ 0 | เฉพาะสาขาที่สังกัด | ดูบอร์ดครัว อัปเดตสถานะ ตรวจสอบสลิป/รับเงินสด คีย์ออเดอร์หน้าร้าน |
| **`customer`** | — | ออเดอร์ของตนเอง | สั่งอาหาร ติดตามคิว และแนบสลิปผ่าน Capability Token |

---

## 🛠️ สถาปัตยกรรมและความปลอดภัย (Architecture & Security)

* **Atomic Order Transactions**: ใช้ Stored Procedures (RPC) บน PostgreSQL ในการสร้างออเดอร์ ตัดสต็อก และจัดลำดับเลขคิวรายวัน (`next_order_number`) แบบ Atomic ป้องกันปัญหาเลขคิวซ้ำหรือราคาคลาดเคลื่อนจากการกดสั่งพร้อมกัน
* **Zero-Trust Token Access**: ลิงก์ออเดอร์ใช้ Token แบบสุ่มยาว (Capability Token) โดยในฐานข้อมูลจะเก็บเฉพาะค่า SHA-256 Hash ผู้ใช้ภายนอกไม่สามารถเข้าถึงฐานข้อมูล Supabase ได้โดยตรง
* **Private Storage & Signed URLs**: ภาพสลิปจัดเก็บใน Supabase Storage Private Bucket การเปิดดูสลิปของพนักงานจะต้องผ่านการยืนยันสิทธิ์และสร้าง Short-lived Signed URL อายุสั้นเท่านั้น
* **Server-Side Session Management**: ตะกร้าและประวัติลูกค้าเก็บใน Server-side Session (Redis บน Production / Filesystem บน Development) แก้ปัญหาคุกกี้ล้นขนาด
* **Durable Push Notifications**: ระบบ Web Push ทำงานผ่าน Durable Outbox บนฐานข้อมูล มี Worker ช่วย Retry เมื่อเครือข่ายขัดข้อง และลบ Subscription ที่หมดอายุอัตโนมัติ

---

## 🚀 การติดตั้งและเริ่มต้นใช้งาน (Getting Started)

### ความต้องการของระบบ (Prerequisites)
- Python 3.12 ขึ้นไป
- บัญชี [Supabase](https://supabase.com) (โปรเจกต์ใหม่)
- Docker & Docker Compose (ตัวเลือกสำหรับการ Deploy)

---

### วิธีที่ 1: ติดตั้งแบบ Local Python Development

1. **โคลนโปรเจกต์และสร้าง Virtual Environment**:
   ```bash
   git clone <repository-url>
   cd qr-project-v2
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **ตั้งค่า Environment Variables**:
   ```bash
   cp .env.example .env
   ```
   เปิดไฟล์ `.env` แล้วกรอกค่าคอนฟิกสำคัญ:
   ```env
   SECRET_KEY=สุ่มสตริงความยาวอย่างน้อย_32_ตัวอักษร
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_ANON_KEY=eyJhbGciOi...
   SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOi...
   PORT=5001
   ```

3. **ติดตั้งฐานข้อมูลบน Supabase**:
   - นำเนื้อหาในไฟล์ [`supabase/schema.sql`](supabase/schema.sql) ไปรันใน **SQL Editor** บน Supabase Dashboard (ระบบจะสร้างตาราง, ฟังก์ชัน RPC, RLS, และ Storage Bucket `slips` ให้อัตโนมัติ)

4. **สร้างบัญชีผู้ดูแลระบบสูงสุดคนแรก (Super Admin)**:
   ```bash
   python scripts/create_admin.py --email admin@example.com --role super_admin
   ```
   *(ระบบจะให้ตั้งรหัสผ่านผ่าน Terminal)*

5. **รันเซิร์ฟเวอร์**:
   ```bash
   python run.py
   ```
   เปิดเบราว์เซอร์ไปที่:
   - หน้าร้านอาหาร/ลูกค้า: `http://localhost:5001`
   - เข้าสู่ระบบผู้ดูแล: `http://localhost:5001/admin/login`
   - ศูนย์ควบคุม Super Admin: `http://localhost:5001/admin/super`

---

### วิธีที่ 2: รันด้วย Docker Compose (แนะนำสำหรับ Production / Staging)

ชุดนี้จะเปิดระบบครบทั้ง **Web Application**, **Redis** (สำหรับจัดการ Session และ Rate Limit) และ **Background Worker**:

```bash
docker compose up --build -d
```
เข้าใช้งานผ่าน `http://localhost:5001`

---

## ⚙️ ตัวแปรสภาพแวดล้อมที่สำคัญ (Environment Variables)

| ตัวแปร | จำเป็น | ค่าเริ่มต้น | คำอธิบาย |
| :--- | :---: | :---: | :--- |
| `SECRET_KEY` | ใช่ | — | คีย์ลับสำหรับเซสชันและเข้ารหัส Token (ความยาว 32+ ตัวอักษร) |
| `SUPABASE_URL` | ใช่ | — | API URL ของโปรเจกต์ Supabase |
| `SUPABASE_ANON_KEY` | ใช่ | — | Anon Public Key ของ Supabase |
| `SUPABASE_SERVICE_ROLE_KEY` | ใช่ | — | Service Role Key ของ Supabase (สิทธิ์สูงสุด สำหรับฝั่ง Backend) |
| `PORT` | ไม่ | `5001` | พอร์ตที่ต้องการเปิดบริการ (ค่าเริ่มต้นเลี่ยงพอร์ต 5000 ของ macOS) |
| `APP_ENV` | ไม่ | `development` | สภาพแวดล้อม (`development` หรือ `production`) |
| `PUBLIC_BASE_URL` | ใช่ (Prod) | `http://localhost:5001` | โดเมนหลักสำหรับสร้าง QR Code และลิงก์ออเดอร์ |
| `RATELIMIT_STORAGE_URI` | ใช่ (Prod) | `memory://` | URL ของ Redis เช่น `redis://redis:6379/0` (Production ห้ามใช้ memory) |
| `SESSION_REDIS_URL` | ไม่ | ค่าเดียวกับ ratelimit | URL ของ Redis สำหรับเก็บ Server-side Sessions |
| `VAPID_PUBLIC_KEY` | ไม่ | — | Public Key สำหรับ Web Push Notifications |
| `VAPID_PRIVATE_KEY` | ไม่ | — | Private Key สำหรับ Web Push Notifications |
| `VAPID_SUBJECT` | ไม่ | — | อีเมลผู้ดูแลสำหรับ Web Push เช่น `mailto:admin@example.com` |

> 💡 **การสร้าง VAPID Keys สำหรับ Web Push**:  
> รันคำสั่ง `python scripts/generate_vapid.py` แล้วนำค่าที่ได้ไปใส่ใน `.env`

---

## 🧪 การทดสอบระบบ (Testing)

โปรเจกต์นี้มีชุดทดสอบครอบคลุมทุกโมดูล (Isolated Unit Tests) ที่ทำงานได้ทันทีโดยไม่ต้องต่อฐานข้อมูลจริง:

```bash
# รันชุดทดสอบทั้งหมด (72 tests)
.venv/bin/python -m unittest discover tests

# หรือรันเฉพาะส่วนการจัดการสิทธิ์และ Admin
.venv/bin/python -m unittest tests/test_admin.py
```

### การทดสอบฐานข้อมูล SQL (PGlite WASM)
```bash
npm ci --prefix supabase/tests --ignore-scripts
npm test --prefix supabase/tests
```

---

## 📁 โครงสร้างโปรเจกต์ (Project Structure)

```text
qr-project-v2/
├── app/                        # แพ็กเกจหลักของแอปพลิเคชัน Flask
│   ├── __init__.py             # Application Factory, Middleware & Filters
│   ├── database.py             # Supabase Client Wrapper
│   ├── utils.py                # ฟังก์ชันคำนวณ QR Code, PromptPay Payload, CRC16
│   ├── routes/                 # เส้นทาง URL และ Controller
│   │   ├── admin_routes.py     # ระบบ Admin, บอร์ดครัว, เมนู, ตั้งค่า, Super Admin
│   │   └── user_routes.py      # หน้าร้าน, สั่งอาหาร, ตะกร้า, ชำระเงิน, ติดตามสถานะ
│   └── services/               # บิสเนสโลจิกและบริการระบบ
│       ├── auth.py             # ระบบตรวจสอบสิทธิ์ Role และ Session
│       ├── management.py       # ศูนย์บริการ Super Admin (สร้างร้าน, ผู้ใช้, องค์กร)
│       ├── notifications.py    # ระบบแจ้งเตือน Web Push & Durable Outbox
│       ├── orders.py           # บริการจัดการออเดอร์ คำนวณราคา และ Token
│       └── sessions.py         # การจัดการ Server-side Session
├── docs/                       # เอกสารคู่มือและมาตรฐานระบบ
│   ├── DATABASE.md             # รายละเอียด Schema, Migration และ RLS
│   ├── DEPLOYMENT_TH.md        # คู่มือการติดตั้งและ Deploy บน Server จริง
│   ├── PILOT_RUNBOOK_TH.md     # แผนการเปิดร้านนำร่องและการวัดผล KPI
│   └── IMPLEMENTATION_STATUS_TH.md # รายงานสถานะการพัฒนา
├── scripts/                    # สคริปต์ Command Line
│   ├── create_admin.py         # สร้างบัญชีผู้ดูแลคนแรก
│   ├── create_branch.py        # CLI สำหรับสร้างสาขา
│   ├── create_organization.py  # CLI สำหรับสร้างองค์กร
│   └── generate_vapid.py       # สคริปต์สร้างคีย์ VAPID
├── static/                     # ไฟล์ Asset (CSS, JavaScript, Web Manifest)
├── supabase/                   # สคริปต์ฐานข้อมูล
│   ├── schema.sql              # สคีมาฐานข้อมูลฉบับสมบูรณ์
│   ├── migrations/             # ประวัติการ Migration
│   └── tests/                  # ชุดทดสอบ SQL บน PGlite
├── templates/                  # Jinja2 HTML Templates
├── tests/                      # Python Regression Unit Tests
├── compose.yaml                # Docker Compose (Web + Redis + Worker)
├── Dockerfile                  # Docker Image Specification
├── gunicorn.conf.py            # การตั้งค่า Gunicorn Production Server
├── pyproject.toml              # การกำหนดค่าโปรเจกต์ Python
├── requirements.txt            # รายการ Dependencies
└── run.py                      # จุดเริ่มต้นรันโปรแกรม (Entrypoint)
```

---

## 📖 เอกสารคู่มือเพิ่มเติม (Documentation)

* **[docs/DEPLOYMENT_TH.md](docs/DEPLOYMENT_TH.md)** — คู่มือการนำขึ้นใช้งานจริงด้วย Gunicorn, Docker, Reverse Proxy (Caddy/Nginx) และ HTTPS
* **[docs/DATABASE.md](docs/DATABASE.md)** — โครงสร้างฐานข้อมูล ตาราง ฟังก์ชัน RPC และระบบ Row Level Security (RLS)
* **[docs/PILOT_RUNBOOK_TH.md](docs/PILOT_RUNBOOK_TH.md)** — แผนปฏิบัติการทดลองเปิดร้านจริง การรับมือเหตุขัดข้อง และเกณฑ์ขยายสาขา
* **[docs/IMPLEMENTATION_STATUS_TH.md](docs/IMPLEMENTATION_STATUS_TH.md)** — รายละเอียดการปรับปรุงระบบและความปลอดภัย

---

## 📄 ใบอนุญาต (License)

โปรเจกต์นี้เผยแพร่ภายใต้ใบอนุญาต **MIT License** สามารถนำไปใช้งาน พัฒนาต่อ หรือปรับใช้ในเชิงพาณิชย์ได้ตามเงื่อนไข
