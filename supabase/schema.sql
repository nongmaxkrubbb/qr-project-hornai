-- ============================================================================
-- Dorm Food Ordering — Schema for Supabase (PostgreSQL)
-- แปลงจากระบบคิวโรงพยาบาลเดิม -> ระบบสั่งอาหารร้านในหอ พร้อมติดตามคิว/สถานะออเดอร์
-- Run this in: Supabase Dashboard -> SQL Editor -> New query
-- ============================================================================

create extension if not exists "pgcrypto";   -- gen_random_uuid()

-- ----------------------------------------------------------------------------
-- 1. ORGANIZATIONS  (รองรับหลายร้าน/หลายหอในอนาคต)
-- ----------------------------------------------------------------------------
create table if not exists organizations (
    id          uuid primary key default gen_random_uuid(),
    name        text not null,
    created_at  timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- 2. BRANCHES  (ร้านอาหารแต่ละสาขา/แต่ละหอ)
-- ----------------------------------------------------------------------------
create table if not exists branches (
    id              uuid primary key default gen_random_uuid(),
    organization_id uuid not null references organizations(id) on delete cascade,
    name            text not null,
    address         text,
    timezone        text not null default 'Asia/Bangkok',
    is_active       boolean not null default true,
    created_at      timestamptz not null default now()
);

create index if not exists idx_branches_org on branches(organization_id);

-- ----------------------------------------------------------------------------
-- 3. MENU_ITEMS  (เมนูอาหาร/เครื่องดื่ม ต่อร้าน)
-- ----------------------------------------------------------------------------
create table if not exists menu_items (
    id           uuid primary key default gen_random_uuid(),
    branch_id    uuid not null references branches(id) on delete cascade,
    name         text not null,
    price        numeric(10,2) not null default 0,
    category     text not null default 'อาหาร',
    is_available boolean not null default true,
    created_at   timestamptz not null default now()
);

create index if not exists idx_menu_items_branch on menu_items(branch_id);

-- ----------------------------------------------------------------------------
-- 4. STAFF  (พนักงานร้าน/แม่ครัว — ผูกกับ Supabase Auth ผ่าน auth_user_id)
-- ----------------------------------------------------------------------------
create table if not exists staff (
    id              uuid primary key default gen_random_uuid(),
    auth_user_id    uuid unique references auth.users(id) on delete set null,
    branch_id       uuid references branches(id) on delete set null,
    organization_id uuid references organizations(id) on delete set null,
    username        text unique not null,
    password_hash   text,
    role            text not null default 'staff'
                        check (role in ('super_admin','org_admin','branch_admin','staff')),
    is_active       boolean not null default true,
    created_at      timestamptz not null default now()
);

create index if not exists idx_staff_branch on staff(branch_id);

-- ----------------------------------------------------------------------------
-- 5. ORDER_COUNTERS  (ตัวนับเลขออเดอร์แบบ atomic ต่อสาขา/ต่อวัน)
-- ----------------------------------------------------------------------------
create table if not exists order_counters (
    branch_id       uuid not null references branches(id) on delete cascade,
    the_date        date not null,
    last_number     integer not null default 0,
    primary key (branch_id, the_date)
);

-- ฟังก์ชันออกเลขออเดอร์แบบ atomic ระดับ database (กันเลขซ้ำเวลามีคนกดสั่งพร้อมกัน)
create or replace function next_order_number(p_branch_id uuid, p_date date)
returns integer
language plpgsql
as $$
declare
    v_number integer;
begin
    insert into order_counters (branch_id, the_date, last_number)
    values (p_branch_id, p_date, 1)
    on conflict (branch_id, the_date)
    do update set last_number = order_counters.last_number + 1
    returning last_number into v_number;
    return v_number;
end;
$$;

-- ----------------------------------------------------------------------------
-- 6. ORDERS  (หัวใจของระบบ — ออเดอร์ของนักศึกษาแต่ละใบ)
-- ----------------------------------------------------------------------------
create table if not exists orders (
    id              bigint generated always as identity primary key,
    order_code      text not null,             -- เช่น Q001, Q002 (รันต่อวันต่อร้าน)
    branch_id       uuid not null references branches(id),
    student_name    text not null,
    room_no         text,                       -- เลขห้อง/ที่อยู่ในหอ (ไม่บังคับ)
    note            text,                       -- หมายเหตุ เช่น "ไม่เผ็ด"
    status          text not null default 'waiting'
                        check (status in ('waiting','preparing','ready','completed','cancelled')),
    total_price     numeric(10,2) not null default 0,
    called_by       uuid references staff(id), -- พนักงานที่กดเปลี่ยนสถานะล่าสุด
    created_at      timestamptz not null default now(),
    started_at      timestamptz,                -- เริ่มทำ (waiting -> preparing)
    ready_at        timestamptz,                -- ทำเสร็จ พร้อมรับ (preparing -> ready)
    completed_at    timestamptz                 -- รับอาหารแล้ว (ready -> completed)
);

create index if not exists idx_orders_branch_status on orders(branch_id, status);
create index if not exists idx_orders_created_at    on orders(created_at);
create index if not exists idx_orders_status_created on orders(status, created_at)
    where status in ('waiting','preparing');   -- partial index เร่ง query คิวที่ยังไม่เสร็จ

-- ----------------------------------------------------------------------------
-- 7. ORDER_ITEMS  (รายการอาหารในแต่ละออเดอร์ — รองรับสั่งหลายเมนูต่อ 1 ออเดอร์)
-- ----------------------------------------------------------------------------
create table if not exists order_items (
    id            bigint generated always as identity primary key,
    order_id      bigint not null references orders(id) on delete cascade,
    menu_item_id  uuid references menu_items(id) on delete set null,
    item_name     text not null,      -- เก็บชื่อ ณ ตอนสั่ง เผื่อเมนูถูกแก้ไข/ลบทีหลัง
    unit_price    numeric(10,2) not null default 0,
    quantity      integer not null default 1 check (quantity > 0)
);

create index if not exists idx_order_items_order on order_items(order_id);

-- ----------------------------------------------------------------------------
-- 8. AUDIT_LOG  (ใครทำอะไร เมื่อไหร่)
-- ----------------------------------------------------------------------------
create table if not exists audit_log (
    id          bigint generated always as identity primary key,
    staff_id    uuid references staff(id),
    branch_id   uuid references branches(id),
    action      text not null,          -- e.g. 'start', 'ready', 'complete', 'cancel', 'login'
    entity      text,                   -- e.g. 'order:123'
    details     jsonb,
    created_at  timestamptz not null default now()
);

create index if not exists idx_audit_branch_time on audit_log(branch_id, created_at);

-- ----------------------------------------------------------------------------
-- 9. ROW LEVEL SECURITY
-- แอป Flask เชื่อมต่อผ่าน service_role key (ฝั่ง server เท่านั้น) จึง bypass RLS
-- ได้ตามปกติ — RLS ที่เปิดไว้นี้คือ "เกราะชั้นสอง"
-- ----------------------------------------------------------------------------
alter table orders        enable row level security;
alter table order_items   enable row level security;
alter table menu_items    enable row level security;
alter table staff         enable row level security;
alter table branches      enable row level security;
alter table audit_log     enable row level security;

-- อ่านสถานะออเดอร์/เมนูสาธารณะได้ (หน้าติดตามสถานะของนักศึกษา) แต่แก้ไขไม่ได้ตรง ๆ
create policy "public can read orders" on orders
    for select using (true);

create policy "public can read order_items" on order_items
    for select using (true);

create policy "public can read menu_items" on menu_items
    for select using (true);

-- staff เห็น/แก้ได้เฉพาะข้อมูลร้านตัวเอง (ยกเว้น super_admin/org_admin)
create policy "staff manage own branch orders" on orders
    for all using (
        exists (
            select 1 from staff s
            where s.auth_user_id = auth.uid()
              and s.is_active
              and (s.role in ('super_admin') or s.branch_id = orders.branch_id)
        )
    );

-- ----------------------------------------------------------------------------
-- 10. REALTIME  — เปิดให้ตาราง orders ส่ง event แบบ push แทนการ polling ล้วนๆ
-- ----------------------------------------------------------------------------
alter publication supabase_realtime add table orders;

-- ----------------------------------------------------------------------------
-- 11. SEED ตัวอย่าง (ลบ/แก้ตามร้านจริง)
-- ----------------------------------------------------------------------------
insert into organizations (id, name)
values ('00000000-0000-0000-0000-000000000001', 'หอพักมหาวิทยาลัย')
on conflict (id) do nothing;

insert into branches (id, organization_id, name)
values ('00000000-0000-0000-0000-000000000011', '00000000-0000-0000-0000-000000000001', 'ร้านอาหารหอใน')
on conflict (id) do nothing;

insert into menu_items (branch_id, name, price, category)
select '00000000-0000-0000-0000-000000000011', name, price, category
from (values
    ('ข้าวผัดกะเพราหมู', 45.00, 'อาหารจานเดียว'),
    ('ข้าวผัดกะเพราไก่', 45.00, 'อาหารจานเดียว'),
    ('ข้าวผัดหมู', 40.00, 'อาหารจานเดียว'),
    ('ผัดไทย', 40.00, 'อาหารจานเดียว'),
    ('ก๋วยเตี๋ยวต้มยำ', 40.00, 'อาหารจานเดียว'),
    ('ไข่ดาว', 10.00, 'เพิ่มเติม'),
    ('น้ำเปล่า', 10.00, 'เครื่องดื่ม'),
    ('ชาเย็น', 20.00, 'เครื่องดื่ม'),
    ('กาแฟเย็น', 25.00, 'เครื่องดื่ม')
) as t(name, price, category)
where not exists (
    select 1 from menu_items m
    where m.branch_id = '00000000-0000-0000-0000-000000000011' and m.name = t.name
);
