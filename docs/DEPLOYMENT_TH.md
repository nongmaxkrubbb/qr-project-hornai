# เปิดใช้งานคิวอิ่ม

ตัวแอปใช้ Supabase สำหรับฐานข้อมูล, Auth และ private Storage; Redis ใช้ร่วมกันระหว่าง web processes สำหรับ session และ rate limit ส่วน worker จัดการหมดอายุออเดอร์และส่งแจ้งเตือนเมื่อเปิด Web Push

## 1. เตรียมฐานข้อมูลและค่าเชื่อมต่อ

- Supabase project ใหม่: รัน `supabase/schema.sql` ใน SQL Editor
- Project เดิม: ใช้ `supabase/migrations/202609210001_production_foundation.sql` โดยอ่าน `DATABASE.md` และสำรองข้อมูลก่อนเปลี่ยนระบบ
- หากเคยลง migration ฉบับก่อนระหว่างพัฒนา ให้ใช้ไฟล์ฉบับปัจจุบันซ้ำเพื่อเพิ่ม snapshot ผู้รับเงิน, guard สลิป และ RPC นับคิว
- สร้าง `.env` จาก `.env.example` แล้วกำหนด `SECRET_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`
- เก็บ `SECRET_KEY` เดิมข้ามการ restart/deploy ใช้ secret store ของ hosting สำหรับ production

ไม่มี sample account, รหัสผ่านเริ่มต้น หรือ migration ที่ถูกรันให้อัตโนมัติตอน web เริ่มทำงาน

## 2. เปิดร้านแรก

ใช้ Python environment ของแอป:

```bash
python scripts/create_organization.py --name 'ชื่อเจ้าของกิจการ'
python scripts/create_branch.py --organization-id ORG_UUID --name 'ร้านอาหารหอ A' --campus 'มหาวิทยาลัย / หอ A' --pickup-point 'หน้าร้านชั้น 1'
python scripts/create_admin.py --email owner@example.com --role branch_admin --branch-id BRANCH_UUID
```

แต่ละคำสั่งแสดง ID ที่ใช้ในคำสั่งถัดไป และการสร้างบัญชีจะถามรหัสผ่านโดยไม่แสดงบนหน้าจอ ร้านใหม่เริ่มพักรับออเดอร์ เจ้าของร้านเปิด `/admin/login` เพื่อเพิ่มเมนู ตั้งเวลา จุดรับ กำลังครัว ชื่อผู้รับเงินและ PromptPay แล้วเปิดรับงาน ก่อนพิมพ์ป้าย **QR ร้าน**

ถ้าใช้ Compose ให้แทน `python` ด้วย `docker compose run --rm web python` ในสามคำสั่งข้างต้น

## 3. เปิดด้วย Python

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

เปิดอีก terminal ใน directory เดียวกัน:

```bash
source .venv/bin/activate
flask --app run run-worker --loop
```

Development เปิดที่ `http://localhost:5001` ตามค่า `PORT` และไม่ต้องติดตั้ง Redis เพิ่ม สำหรับ production เปลี่ยน web command เป็น `gunicorn -c gunicorn.conf.py run:app` และตั้ง Redis/HTTPS ตาม README

## 4. เปิดด้วย Docker Compose

ติดตั้ง Docker Engine พร้อม Compose แล้วรันจาก directory โปรเจคที่มี `.env`:

```bash
docker compose up --build -d
```

เปิด `http://localhost:5001` ชุดนี้ใช้ image Python 3.12, web และ worker รันด้วยผู้ใช้ที่ไม่ใช่ root ส่วน Redis มี volume เก็บข้อมูลและไม่ publish port ใช้คำสั่ง `docker compose logs --tail=100 web worker` ดูสถานะ โดย log แอปไม่บันทึก query string ที่มี token

## 5. เปิด HTTPS ด้วย proxy ที่เตรียมไว้

ชี้ DNS ของโดเมนมาที่เครื่อง hosting และเปิดพอร์ต 80/443 ตั้ง `.env`:

```dotenv
APP_ENV=production
PUBLIC_DOMAIN=food.example.edu
PUBLIC_BASE_URL=https://food.example.edu
TRUSTED_PROXY_COUNT=1
```

`PUBLIC_DOMAIN` ต้องเป็นโดเมนจริงที่ควบคุมและตรงกับ hostname ของ `PUBLIC_BASE_URL` จากนั้น:

```bash
docker compose --profile https up --build -d
```

Compose เปิด Caddy เพื่อจัดการใบรับรอง HTTPS และส่งต่อไปยัง web พอร์ต web ฝั่งเครื่องผูกกับ localhost เท่านั้น เมื่อใช้งานผ่านโดเมนแล้วให้เปิด admin/QR ที่โดเมนนั้น

หาก hosting มี reverse proxy อยู่แล้ว ใช้ `docker compose up --build -d` และตั้ง proxy ของ hosting ให้ส่ง Host เดิมพร้อม X-Forwarded-For/Proto ที่เชื่อถือได้ ปรับ `TRUSTED_PROXY_COUNT` ให้ตรงกับ proxy ของการติดตั้งจริง

## 6. การแจ้งเตือนและดูแลระบบ

- Worker เปิดได้โดยไม่ต้องใช้ VAPID; เมื่อเพิ่ม `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` ครบแล้ว restart web/worker เพื่อเปิด push
- สร้างกุญแจด้วย `python scripts/generate_vapid.py` และเก็บเฉพาะฝั่ง server/secret store
- `/healthz` ใช้ดูว่า web process ตอบได้; `/readyz` ใช้ดูการติดต่อฐานข้อมูลและ Redis ที่ใช้เก็บ session
- สำรอง Supabase และ Redis volume ตามนโยบายของร้าน; `docker compose down` คง volume ไว้ ส่วน `down -v` จะลบ volume จึงไม่ควรใช้เมื่อต้องเก็บ session/ใบรับรองไว้
- ปรับสถานะเมนู/พักรับผ่านบอร์ดครัว และใช้ `PILOT_RUNBOOK_TH.md` สำหรับการเปิดขายและกระทบยอด

การติดตั้งนี้ไม่มีบริการตรวจสลิปธนาคารอัตโนมัติ พนักงานยังเป็นผู้ตรวจรับเงินและบันทึกการคืนเงินจริง การเพิ่มร้านใช้ organization/branch scope เดิมโดยสร้างบัญชีให้ถูกสาขา

รายละเอียด session backend อ้างอิง [Flask-Session configuration](https://flask-session.readthedocs.io/en/latest/config.html) และการหมุน session หลังเข้าสู่ระบบตาม [เอกสาร security](https://flask-session.readthedocs.io/en/latest/security.html)
