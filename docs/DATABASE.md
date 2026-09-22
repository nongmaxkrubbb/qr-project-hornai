# ฐานข้อมูลและการนำขึ้นใช้งานจริง

แอปใช้ PostgreSQL/Supabase โดยให้ Flask เป็นผู้ตรวจสิทธิ์และเรียกฐานข้อมูลด้วย service-role เฉพาะบนเซิร์ฟเวอร์ เบราว์เซอร์ไม่สามารถอ่านตารางออเดอร์หรือเรียก RPC โดยตรงได้ ฐานข้อมูลตรวจสิทธิ์พนักงานและกติกาออเดอร์ซ้ำอีกชั้นใน RPC งานสำคัญ

## ติดตั้งและอัปเกรด

- **ฐานข้อมูลใหม่:** ใช้ `supabase/schema.sql` เพียงไฟล์เดียว ไฟล์นี้รวมโครงสร้างและ migration แล้ว ไม่มีร้าน เมนู หรือรหัสผู้ดูแลตัวอย่าง
- **ฐานข้อมูลเดิม:** สำรองข้อมูลและไฟล์ Storage ก่อน จากนั้นใช้ `supabase/migrations/202609210001_production_foundation.sql` ใน SQL Editor ของโครงการที่ต้องการอัปเกรด ทดสอบกับ staging ก่อน production
- Migration ครอบด้วย transaction และรันซ้ำได้ ใช้ row lock และสร้าง index จึงควรกำหนดช่วงบำรุงรักษาหากมีข้อมูลจำนวนมาก
- **อย่ารัน `add_payment_columns.sql` แทน migration** ไฟล์เก่านั้นเพิ่มเฉพาะช่องข้อมูล ไม่เพิ่มกติกาความปลอดภัย
- หลังติดตั้งต้องตั้งชื่อร้าน จุดรับอาหาร timezone เวลาเปิด/ปิด บัญชี PromptPay และกำลังครัวให้ตรงหน้างาน ค่า PromptPay ว่างจะปิดการโอนสำหรับร้านนั้น
- การเปิดข้อมูลสาธารณะและ Realtime เดิมถูกยกเลิกด้วย RLS/privilege ของตาราง แอปใช้ endpoint ของ Flask สำหรับติดตามสถานะ

Migration ไม่ได้ถูกรันกับฐานข้อมูลจริงโดยการแก้โค้ดใน repository ต้องนำ SQL ไปใช้กับโครงการจริงก่อนเปิดแอปรุ่นนี้

## ข้อมูลเก่าและการกระทบยอด

ระบบเก่าใช้ `payment_status='completed'` สำหรับเงินสดทันทีที่สั่ง ซึ่งไม่ได้ยืนยันว่ารับเงินจริง Migration แปลงเป็น `legacy_unverified` เพื่อแยกจากยอดที่ยืนยันแล้ว และไม่ปรับข้อมูลย้อนหลังให้กลายเป็น `paid` โดยเดา

ออเดอร์เก่าไม่มี capability token จึงไม่สามารถใช้ลิงก์ติดตามแบบใหม่ได้ ผู้ดูแลยังตรวจรายการเก่าในระบบได้ ควรปิดหรือส่งต่อคิวค้างอย่างมีบันทึกก่อนเปิดรุ่นใหม่ ออเดอร์โอนเก่าที่เข้าครัวไปแล้วไม่ถูกย้อนสถานะโดยอัตโนมัติ ยอดเก่าที่ไม่แน่ชัดต้องตรวจจากหลักฐานภายนอกและเก็บเหตุผลการปรับปรุงไว้

คอลัมน์ `slip_url` เดิมเก็บไว้เพื่อย้ายข้อมูลเท่านั้น แอปรุ่นใหม่ไม่ใช้ URL สาธารณะนั้น:

1. Migration บังคับ bucket `slips` ให้เป็น private จำกัด 5 MiB และ JPEG/PNG/WebP
2. restrictive policy ปิดสิทธิ์ anon/authenticated แม้จะมี storage policy อื่นเปิดกว้างอยู่
3. ไฟล์ใหม่อยู่ที่ `orders/<order_id>/<uuid>.<ext>` และเก็บเฉพาะ path ใน `orders.slip_path`
4. ไฟล์ที่เคยเผยแพร่ผ่าน bucket อื่น หรือ CDN/cache ภายนอก ต้องย้าย/เพิกถอนลิงก์เดิมแยกต่างหาก การตั้ง private ไม่สามารถเรียกคืนสำเนาที่ผู้รับเคยดาวน์โหลดแล้ว
5. เก็บ service-role key ไว้เฉพาะ backend ถ้าเคยส่ง key ให้ browser ต้องเปลี่ยน key ก่อนเปิดใช้งาน

## สัญญา RPC

ทุก RPC ด้านล่างอนุญาต `service_role` เท่านั้น ใช้ `SECURITY INVOKER` และกำหนด `search_path` ตายตัว

### สร้างออเดอร์

`create_order(p_branch_id uuid, p_items jsonb, p_student_name text, p_room_no text, p_note text, p_payment_method text, p_idempotency_key uuid, p_token_hash text, p_staff_id uuid default null, p_requested_for timestamptz default null) -> jsonb`

ตัวอย่าง `p_items`:

```json
[{"menu_item_id":"UUID","quantity":2,"option_ids":["egg"],"note":"ไม่เผ็ด","expected_unit_price":"50.00"}]
```

- `cash` สร้างเป็น `waiting/pending`; `promptpay` สร้างเป็น `pending_payment/pending` ครัวยังไม่รับงานโอนที่ไม่ยืนยัน
- Token ต้องเป็น SHA-256 รูป hexadecimal ยาว 64 ตัวเท่านั้น ไม่มี raw token ในฐานข้อมูล
- `idempotency_key` เป็น UUID ที่สร้างต่อความพยายามสั่งหนึ่งครั้ง ส่งซ้ำ key/payload/token เดิมคืนออเดอร์เดิม แม้ร้านหยุดรับแล้ว การใช้ key เดิมกับข้อมูลต่างกันได้ `idempotency_conflict`
- Header, items, counter, audit อยู่ใน transaction เดียว และล็อก branch/menu ขณะตรวจราคา/ความพร้อม
- ราคามาจากเมนูในฐานข้อมูล รวมตัวเลือกที่มีอยู่จริง `expected_unit_price` เป็นราคาที่ลูกค้ายอมรับล่าสุด ถ้าราคาเปลี่ยน RPC ตอบ `price_changed`
- ออเดอร์ PromptPay บันทึก `payment_promptpay_id` และ `payment_promptpay_name` ณ ตอนสั่ง การเปลี่ยนบัญชีรับเงินของร้านภายหลังจึงไม่เปลี่ยน QR ของออเดอร์ที่สั่งไปแล้ว ต้องตั้งชื่อผู้รับพร้อมหมายเลขก่อนเปิดรับโอน ค่า snapshot ของข้อมูลเก่าคงเป็น null เพราะไม่สามารถยืนยันบัญชีในอดีตได้
- สูงสุด 30 รายการ รายการละ 20 ชิ้น ชื่อ 100 ตัว หมายเหตุออเดอร์ 1,000 ตัว หมายเหตุต่อรายการ 500 ตัว ตัวเลือกสูงสุด 20 รายการและห้ามซ้ำ
- Walk-in ต้องระบุ staff ที่ active และเข้าถึงร้านได้ อนุญาตให้พนักงานสร้างระหว่างร้านพัก/ปิดเพื่อบันทึกงานหน้าร้าน
- วันสำหรับเลขคิวใช้ timezone ของสาขา และ counter ไม่ย้อนกลับเมื่อนำข้อมูลเดิมมาใช้

### สถานะและเงิน

`order_action(p_order_id bigint, p_staff_id uuid, p_action text, p_reason text default '', p_reference text default '', p_expected_slip_path text default null) -> jsonb`

| Action | เงื่อนไข/ผลลัพธ์ |
|---|---|
| `start` | waiting → preparing; เงินโอนต้อง paid เงินสดยังค้างได้เมื่อร้านอนุญาต |
| `ready` | preparing → ready |
| `complete` | ready → completed และต้อง paid เท่านั้น |
| `cash` | บันทึกรับเงินจริงสำหรับเงินสดที่ยังรอ/กำลังทำ/พร้อมรับ |
| `verify` | pending_payment/verifying → waiting/paid ต้องมีสลิปและเลขอ้างอิง 3–200 ตัว ห้ามเลขซ้ำในร้านหรือข้ามร้านที่ใช้บัญชี PromptPay เดียวกัน |
| `reject` | สลิปรอตรวจ → rejected ให้เวลาแก้ไข 15 นาที ต้องมีเหตุผลซึ่งส่งให้ลูกค้าอ่านผ่าน `payment_reason` |
| `cancel` | ยกเลิกงานที่ยังไม่ completed; paid → refund_due ต้องมีเหตุผล |
| `refund` | cancelled/refund_due → refunded พร้อม `refunded_at` ต้องมีเหตุผลยืนยันคืนเงินจริง |
| `incident` | เพิ่มบันทึกปัญหาหน้างานพร้อมเวลา ต้องมีเหตุผล |

ระหว่างตรวจสลิป (`verifying`) ต้องตรวจรับหรือปฏิเสธสลิปก่อนยกเลิก มิฉะนั้นตอบ `payment_review_required` เพื่อไม่ให้เงินจริงที่อาจรับแล้วหลุดจากขั้นตอนคืนเงิน

`verify` และ `reject` ต้องส่ง `p_expected_slip_path` จากแบบฟอร์มที่พนักงานเปิดตรวจ ถ้าพนักงานอีกคนปฏิเสธแล้วลูกค้าส่งไฟล์ใหม่ระหว่างที่หน้าเดิมยังเปิดอยู่ RPC ตอบ `slip_changed` และไม่เปลี่ยนสถานะจนกว่าจะเปิดหลักฐานปัจจุบัน ส่วน action อื่นไม่ต้องส่งค่านี้ migration ลบ overload 5 parameters เดิมก่อนสร้างรุ่น 6 parameters เพื่อให้ PostgREST เลือกฟังก์ชันได้แน่นอน

การยืนยันเลขอ้างอิงเดียวกันในหลายสาขาที่ใช้ผู้รับเงินเดียวกันถูกจัดลำดับด้วย advisory lock และ unique index ของผู้รับเงิน/เลขอ้างอิง หลักประกันข้ามสาขานี้ใช้กับออเดอร์ที่มี recipient snapshot เท่านั้น ข้อมูลเก่ายังคงตรวจเลขอ้างอิงซ้ำในร้านตามเดิม

ทุก action ล็อกออเดอร์ ตรวจ staff ที่ active และขอบเขตองค์กร/สาขา และบันทึก audit ใน transaction เดียวกัน `org_admin` ข้ามได้เฉพาะสาขาในองค์กรตัวเอง `staff` ที่ไม่มี branch ไม่มีสิทธิ์ทั้งระบบ พนักงานประจำสาขาต้องมี organization ตรงกับสาขา migration เติม organization ให้เฉพาะบัญชีเก่าที่ช่องนี้ว่างจากสาขาที่ผูกไว้ และไม่แก้บัญชีที่มี organization ขัดแย้งกัน การปิดร้านหยุดรับออเดอร์ใหม่แต่ไม่ปิดสิทธิ์ดูประวัติ/คืนเงินของพนักงานที่มีขอบเขตถูกต้อง

`attach_order_slip(p_order_id bigint,p_token_hash text,p_slip_path text) -> jsonb` ยอมรับเฉพาะออเดอร์ promptpay/pending_payment ที่ยังรอหรือชำระถูกปฏิเสธ สลิปต้องอยู่ใต้ `orders/<order_id>/` สลิปที่ส่งแล้วไม่หมดอายุและไม่สามารถถูกแทนที่ระหว่างรอตรวจ เพื่อให้หลักฐานที่พนักงานเปิดดูเป็นไฟล์เดียวกับที่ยืนยัน ไม่มีการย้อนงานจาก ready/completed กลับเข้าคิว

`customer_order_action(p_order_id bigint,p_token_hash text,p_action text,p_reason text default '') -> jsonb` รองรับ cancel เฉพาะก่อนเริ่มทำ และ arrive ระหว่าง waiting/preparing/ready การยกเลิกที่จ่ายแล้วสร้างภาระคืนเงิน

`get_order_by_token(p_order_id bigint,p_token_hash text) -> jsonb` อ่านออเดอร์ที่ตรง token และไม่ส่ง hash/idempotency key/legacy slip URL ออกมา Flask ยังต้องเลือกเฉพาะข้อมูลที่เหมาะสมก่อนตอบ browser

`expire_unpaid_orders(p_branch_id uuid default null) -> integer` ยกเลิก promptpay pending/rejected ที่หมดเวลา ครั้งละไม่เกิน 500 ออเดอร์ ไม่ยกเลิกรายการ verifying/paid เรียกได้จาก worker หรืองานประจำ หลีกเลี่ยงใช้ raw table update แทน RPC

### เวลารอและการจอง

`branch_queue_counts(p_branch_ids uuid[]) -> table(branch_id uuid,orders_ahead bigint)` คืนจำนวนงาน waiting/preparing ของร้านที่เปิดให้บริการทั้งหมดในคำขอเดียว รวมออเดอร์จองที่ถึงเวลาเตรียมภายใน `prep_minutes` แล้ว ใช้หน้าเลือกร้านแสดง ETA จากคิวปัจจุบันโดยไม่ต้อง query ทีละร้าน ร้านที่ไม่มีงานคืนค่า 0

- `prep_minutes` 1–180; `kitchen_capacity` 1–100
- `slot_minutes`: 5, 10, 15, 20, 30 หรือ 60 นาที; `slot_capacity` 0–500 (0 ปิดจอง); `preorder_days` 0–30 (0 = วันเดียวกัน)
- เวลาเปิดเท่าปิดหมายถึง 24 ชั่วโมง เวลาเปิดมากกว่าปิดหมายถึงข้ามเที่ยงคืน
- เวลาจองต้องตรงช่องใน timezone ของร้าน อยู่ในช่วงเปิด และล่วงหน้าอย่างน้อย `prep_minutes` นาที
- Branch lock ป้องกันการจองช่องสุดท้ายซ้ำจากคำขอพร้อมกัน ออเดอร์ยกเลิก/หมดอายุคืนความจุ
- ETA รวมงานของออเดอร์ตัวเองและงานครัวก่อนหน้า จึงไม่เริ่มที่ 0 นาที ตั้งค่า prep/capacity/slot จากข้อมูลช่วงพีกจริงเพื่อให้เวลาประมาณมีความหมาย

### Dashboard

`branch_dashboard(p_branch_id uuid,p_staff_id uuid,p_date date default null) -> jsonb`

วันเริ่มต้นตาม timezone ของสาขา ประกอบด้วย `orders_total`, `orders_completed`, `orders_cancelled`, `orders_active`, `gross_sales`, `paid_total`, `pending_total`, `refund_due_total`, `refunded_total`, `legacy_unverified_total`, `payment_pending_count`, `incidents_count`, `arrivals_count`, `wait_minutes_p50/p90`, `prep_minutes_p50/p90`, `pickup_minutes_p50/p90`, `eta_error_minutes_p50/p90`, `counter_wait_minutes_p50/p90`, `receipts_today`, `refunds_today`, `top_items`, `hourly_orders`, `payment_methods` ค่า percentile ที่ยังไม่มีตัวอย่างเป็น null ไม่ใช่ศูนย์ การรอก่อนเริ่มทำของออเดอร์จองไม่รวมใน wait เพื่อไม่ให้เวลาสั่งล่วงหน้าบิดผล

`gross_sales` รวมราคาคำสั่งซื้อที่ไม่ยกเลิกและยังไม่ใช่รายได้ที่รับเงินจริง ดู `paid_total` ประกอบและแยกเงินต้องคืน/เงินคืนแล้วเสมอ `paid_total` เป็นยอด paid ของออเดอร์ที่สร้างในวันที่เลือก ส่วน `receipts_today` และ `refunds_today` นับตามเวลารับเงินจริง/คืนเงินจริงใน timezone ร้าน จึงใช้กระทบยอดประจำวันที่มีออเดอร์สั่งล่วงหน้าได้ `counter_wait_minutes_p50/p90` วัดเวลาตั้งแต่ลูกค้ากดมาถึงจนรับอาหาร เฉพาะออเดอร์ completed

### แจ้งเตือน

การเปลี่ยนสถานะเพิ่มรายการใน `notification_outbox` transaction เดียวกับออเดอร์ ไม่เรียกเครือข่ายจาก database trigger

- `claim_notification_outbox(p_limit int default 20)` คืนรายการงานและล็อก lease 5 นาทีด้วย SKIP LOCKED
- `finish_notification_outbox(p_id bigint,p_success boolean,p_error text default '')` ปิดงานหรือเลื่อน retry แบบ exponential backoff สูงสุด 1 ชั่วโมง สูงสุด 8 attempts
- `push_subscriptions` เก็บ `{order_id,endpoint,keys}` โดย order+endpoint ไม่ซ้ำ
- Worker ต้องตรวจ endpoint ที่รับจาก browser เพื่อป้องกัน SSRF และลบ subscription ที่ push provider ตอบหมดอายุ
- การส่งแบบ at-least-once อาจแจ้งซ้ำได้เมื่อ worker ล่มหลังส่งแต่ก่อนบันทึกผล event/order ใช้ deduplicate ฝั่ง client ได้
- งานที่ครบ 8 attempts ต้องมีการตรวจ failed jobs และสั่ง retry อย่างมีเหตุผล

## ทดสอบโดยไม่ใช้ข้อมูลจริง

ชุด `supabase/tests/production_foundation.sql` สร้าง fixtures ภายใน transaction แล้ว rollback ทดสอบกติกาเงิน สิทธิ์ tenant, token, การสร้างพร้อมรายการ, idempotency, ตัวเลือก, ช่องรับอาหาร, ยอดรวม และการปิดสิทธิ์ anon

หากมี PostgreSQL/Supabase สำหรับทดสอบ ใช้ `psql "$TEST_DATABASE_URL" -v ON_ERROR_STOP=1 -f supabase/tests/production_foundation.sql` หลัง migration ห้ามกำหนดตัวแปรเป็น production

สามารถรัน PostgreSQL ในหน่วยความจำด้วย PGlite ซึ่งไม่อ่าน `.env` และไม่เชื่อม Supabase:

```sh
npm ci --prefix supabase/tests
npm test --prefix supabase/tests
```

Harness ทดสอบ fresh install, upgrade จาก schema เดิมพร้อมยอดเงิน/สิทธิ์เก่า, รัน migration ซ้ำ, regression และ bucket private ใช้ stub เฉพาะตารางระบบ Supabase จึงยังต้องทดสอบ Auth/Storage/PostgREST และหลาย connection พร้อมกันใน staging ก่อนเปิดจริง


## ทดสอบ concurrent requests ใน staging

PGlite ใช้ PostgreSQL จริงแบบ connection เดียว จึงตรวจ syntax/transaction/state machine ได้ แต่ไม่พิสูจน์การแย่ง lock ระหว่าง backend หลายตัว ก่อน pilot ให้ใช้ฐานข้อมูลทดสอบแยกและ connection `psql` สองตัว:

1. สร้างสาขาทดสอบกับเมนู จากนั้น connection A เริ่ม `BEGIN` และเรียก `create_order` ค้างไว้ก่อน `COMMIT`
2. Connection B เรียกด้วย key/payload/token เดียวกัน ควรรอ A และคืน id เดียว มีหัวออเดอร์/รายการอาหารเพียงชุดเดียว และใช้เลขคิวเพียงเลขเดียว
3. ทำอีกครั้งด้วย key คนละตัวและช่องรับอาหารเดียวที่ capacity=1 ผลสำเร็จต้องมีเพียงออเดอร์เดียว อีก connection ตอบ `pickup_slot_full`
4. แข่งเปลี่ยนเมนูเป็นหมด/แก้ราคา กับคำสั่งซื้อ ผลต้องเป็น snapshot ที่ล็อกไว้ หรือปฏิเสธ `menu_unavailable`/`price_changed` ไม่มี header ว่าง
5. แข่ง verify/cancel และ complete/cancel จากสองพนักงาน ผลต้องเป็น transition เดียวที่อนุญาต พร้อม audit ตรงกับสถานะสุดท้าย และไม่มี completed ที่ unpaid
6. ใช้ anon key เรียก REST ตาราง orders/order_items และ RPC ต้องถูกปฏิเสธ ใช้ URL public ของ bucket slips เดิมต้องโหลดไม่ได้ ส่วนพนักงานที่ถูกสาขาจึงเปิดสลิปผ่าน Flask ได้

เก็บผลทดสอบกับเวลา, build, migration version และสรุปจำนวนออเดอร์หลังแข่ง เพื่อใช้เป็นเกณฑ์ก่อนขยายร้าน
