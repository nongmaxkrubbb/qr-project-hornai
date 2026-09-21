-- รันคำสั่งนี้ใน SQL Editor ของ Supabase
-- เพื่อเพิ่มคอลัมน์สำหรับระบบจ่ายเงินในตาราง orders

ALTER TABLE public.orders
ADD COLUMN IF NOT EXISTS payment_method text DEFAULT 'cash',
ADD COLUMN IF NOT EXISTS payment_status text DEFAULT 'pending',
ADD COLUMN IF NOT EXISTS slip_url text;
