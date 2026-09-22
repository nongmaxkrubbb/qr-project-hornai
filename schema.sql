-- Fresh installation baseline. Includes the production foundation migration.
-- Existing deployments: apply migrations/202609210001_production_foundation.sql instead.
-- No demo organizations, menus or administrator credentials are seeded.
begin;

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

create extension if not exists pgcrypto;

alter table public.branches
  add column if not exists campus text not null default '',
  add column if not exists pickup_point text not null default '',
  add column if not exists opening_time time not null default '08:00',
  add column if not exists closing_time time not null default '20:00',
  add column if not exists is_accepting_orders boolean not null default true,
  add column if not exists promptpay_id text,
  add column if not exists promptpay_name text not null default '',
  add column if not exists prep_minutes integer not null default 10,
  add column if not exists kitchen_capacity integer not null default 1,
  add column if not exists allow_cash_before_payment boolean not null default true,
  add column if not exists slot_minutes integer not null default 15,
  add column if not exists slot_capacity integer not null default 0,
  add column if not exists preorder_days integer not null default 0;
alter table public.menu_items
  add column if not exists description text not null default '',
  add column if not exists image_url text,
  add column if not exists options jsonb not null default '[]',
  add column if not exists sort_order integer not null default 0;
alter table public.orders
  add column if not exists payment_method text default 'cash',
  add column if not exists payment_status text default 'pending',
  add column if not exists slip_url text,
  add column if not exists slip_path text,
  add column if not exists token_hash text,
  add column if not exists idempotency_key uuid,
  add column if not exists request_hash text,
  add column if not exists source text not null default 'online',
  add column if not exists order_date date,
  add column if not exists expires_at timestamptz,
  add column if not exists requested_for timestamptz,
  add column if not exists promised_ready_at timestamptz,
  add column if not exists payment_promptpay_id text,
  add column if not exists payment_promptpay_name text,
  add column if not exists payment_reference text,
  add column if not exists payment_reason text,
  add column if not exists refunded_at timestamptz,
  add column if not exists payment_verified_at timestamptz,
  add column if not exists payment_verified_by uuid references public.staff(id),
  add column if not exists cancellation_reason text,
  add column if not exists incident_note text,
  add column if not exists arrived_at timestamptz;
alter table public.order_items
  add column if not exists options jsonb not null default '[]',
  add column if not exists note text not null default '';

-- Replace legacy check constraints by name without discarding historic rows.
alter table public.orders drop constraint if exists orders_status_check;
alter table public.orders drop constraint if exists orders_payment_status_check;
update public.orders set payment_status = 'legacy_unverified' where payment_status = 'completed';
update public.orders set payment_status = 'pending' where payment_status is null;
update public.orders set payment_method = 'cash' where payment_method is null;
update public.orders o set order_date = (o.created_at at time zone b.timezone)::date
from public.branches b where b.id = o.branch_id and o.order_date is null;
alter table public.orders alter column payment_status set not null;
alter table public.orders alter column payment_method set not null;
alter table public.orders alter column order_date set not null;
alter table public.orders add constraint orders_status_check check
  (status in ('pending_payment','waiting','preparing','ready','completed','cancelled')) not valid;
alter table public.orders add constraint orders_payment_status_check check
  (payment_status in ('pending','verifying','paid','rejected','refund_due','refunded','legacy_unverified')) not valid;

do $$ begin
  if not exists (select 1 from pg_constraint where conrelid='public.branches'::regclass and conname='branches_operating_settings_check') then
    alter table public.branches add constraint branches_operating_settings_check check
      (prep_minutes between 1 and 180 and kitchen_capacity between 1 and 100
       and slot_minutes in (5,10,15,20,30,60) and slot_capacity between 0 and 500
       and preorder_days between 0 and 30) not valid;
  end if;
  if not exists (select 1 from pg_constraint where conrelid='public.menu_items'::regclass and conname='menu_items_valid_price_options') then
    alter table public.menu_items add constraint menu_items_valid_price_options check
      (price >= 0 and price::text not in ('NaN','Infinity','-Infinity') and jsonb_typeof(options)='array') not valid;
  end if;
  if not exists (select 1 from pg_constraint where conrelid='public.orders'::regclass and conname='orders_capability_check') then
    alter table public.orders add constraint orders_capability_check check
      ((token_hash is null or token_hash ~ '^[0-9a-f]{64}$') and source in ('online','walk_in')
       and payment_method in ('cash','promptpay')) not valid;
  end if;
end $$;
create unique index if not exists idx_orders_idempotency on public.orders(idempotency_key) where idempotency_key is not null;
create unique index if not exists idx_orders_payment_reference on public.orders(branch_id, payment_reference)
  where payment_reference is not null and payment_reference <> '';
-- One transfer cannot fund two branches that receive money into the same account.
-- Historic orders have no trustworthy recipient snapshot and remain null.
create unique index if not exists idx_orders_recipient_payment_reference on public.orders(payment_promptpay_id, payment_reference)
  where payment_promptpay_id is not null and payment_reference is not null and payment_reference <> '';
create unique index if not exists idx_orders_daily_number on public.orders(branch_id, order_date, order_code) where token_hash is not null;
create index if not exists idx_orders_branch_date on public.orders(branch_id, order_date);
create index if not exists idx_orders_receipts on public.orders(branch_id,payment_verified_at) where payment_verified_at is not null;
create index if not exists idx_orders_refunds on public.orders(branch_id,refunded_at) where refunded_at is not null;
create index if not exists idx_orders_unpaid_expiry on public.orders(expires_at)
  where status='pending_payment' and payment_status in ('pending','rejected');
create index if not exists idx_orders_slots on public.orders(branch_id, requested_for)
  where requested_for is not null and status <> 'cancelled';
-- Preserve the highest old number so deploying cannot restart a live day's counter.
insert into public.order_counters(branch_id,the_date,last_number)
select branch_id,order_date,max(substring(order_code from '[0-9]+$')::integer)
from public.orders where order_code ~ '^[A-Za-z]*[0-9]{1,9}$'
group by branch_id,order_date
on conflict(branch_id,the_date) do update
set last_number=greatest(order_counters.last_number,excluded.last_number);

create table if not exists public.push_subscriptions (
  id bigint generated always as identity primary key,
  order_id bigint not null references public.orders(id) on delete cascade,
  endpoint text not null check(length(endpoint) between 10 and 2048),
  keys jsonb not null,
  created_at timestamptz not null default now(),
  unique(order_id,endpoint)
);
create table if not exists public.notification_outbox (
  id bigint generated always as identity primary key,
  order_id bigint not null references public.orders(id) on delete cascade,
  event text not null,
  payload jsonb not null default '{}',
  attempts integer not null default 0,
  available_at timestamptz not null default now(),
  locked_at timestamptz,
  delivered_at timestamptz,
  last_error text,
  created_at timestamptz not null default now(),
  unique(order_id,event)
);
create index if not exists idx_notification_outbox_due on public.notification_outbox(available_at) where delivered_at is null;

-- All browser access goes through Flask. The service key must never reach a browser.
do $$ declare v_table text; v_policy record; v_sequence text; begin
  foreach v_table in array array['organizations','branches','menu_items','staff','order_counters','orders','order_items','audit_log','push_subscriptions','notification_outbox'] loop
    execute format('alter table public.%I enable row level security',v_table);
    for v_policy in select policyname from pg_policies where schemaname='public' and tablename=v_table loop
      execute format('drop policy %I on public.%I',v_policy.policyname,v_table);
    end loop;
    execute format('revoke all on public.%I from public, anon, authenticated',v_table);
    execute format('grant all on public.%I to service_role',v_table);
    if v_table in ('orders','order_items','audit_log','push_subscriptions','notification_outbox') then
      v_sequence:=pg_get_serial_sequence('public.'||v_table,'id');
      if v_sequence is not null then
        execute format('revoke all on sequence %s from public,anon,authenticated',v_sequence);
        execute format('grant usage,select on sequence %s to service_role',v_sequence);
      end if;
    end if;
  end loop;
end $$;

-- Preserve legitimate legacy branch staff, but never overwrite a conflicting organization.
update public.staff s set organization_id=b.organization_id from public.branches b
where s.branch_id=b.id and s.organization_id is null and s.role in ('branch_admin','staff');

-- Predicate shared by write/report RPCs. A missing branch never means global access.
create or replace function public.staff_can_access_branch(p_staff_id uuid,p_branch_id uuid)
returns boolean language sql stable security invoker set search_path=public,pg_temp as $$
  select exists(select 1 from staff s join branches b on b.id=p_branch_id
    where s.id=p_staff_id and s.is_active and s.auth_user_id is not null and
      (s.role='super_admin' or
       (s.role='org_admin' and s.organization_id is not null and s.organization_id=b.organization_id) or
       (s.role in ('branch_admin','staff') and s.branch_id is not null and s.branch_id=b.id and s.organization_id=b.organization_id)));
$$;
create or replace function public.branch_open_at(p_open time,p_close time,p_at time)
returns boolean language sql immutable security invoker set search_path=public,pg_temp as $$
  select case when p_open=p_close then true when p_open<p_close then p_at>=p_open and p_at<p_close
    else p_at>=p_open or p_at<p_close end;
$$;
create or replace function public.branch_queue_counts(p_branch_ids uuid[])
returns table(branch_id uuid,orders_ahead bigint)
language sql stable security invoker set search_path=public,pg_temp as $$
  select b.id,count(o.id)
  from branches b left join orders o on o.branch_id=b.id and o.status in ('waiting','preparing')
    and (o.requested_for is null or o.requested_for<=now()+make_interval(mins=>b.prep_minutes))
  where b.is_active and b.id=any(p_branch_ids)
  group by b.id;
$$;
create or replace function public.next_order_number(p_branch_id uuid,p_date date)
returns integer language plpgsql security invoker set search_path=public,pg_temp as $$
declare v_number integer; begin
  insert into order_counters(branch_id,the_date,last_number) values(p_branch_id,p_date,1)
  on conflict(branch_id,the_date) do update set last_number=order_counters.last_number+1 returning last_number into v_number;
  return v_number;
end $$;

create or replace function public.create_order(
  p_branch_id uuid,p_items jsonb,p_student_name text,p_room_no text,p_note text,
  p_payment_method text,p_idempotency_key uuid,p_token_hash text,
  p_staff_id uuid default null,p_requested_for timestamptz default null)
returns jsonb language plpgsql security invoker set search_path=public,extensions,pg_temp as $$
declare
  v_branch branches%rowtype; v_menu menu_items%rowtype; v_order orders%rowtype;
  v_item jsonb; v_option jsonb; v_options jsonb; v_option_id text;
  v_lines jsonb := '[]'; v_quantity integer; v_unit numeric; v_total numeric := 0;
  v_hash text; v_number integer; v_date date; v_now timestamptz := now();
  v_local timestamp; v_requested_local timestamp; v_queue integer; v_reserved integer;
  v_promise timestamptz; v_source text; v_note text;
begin
  if p_idempotency_key is null or p_token_hash is null or p_token_hash !~ '^[0-9a-f]{64}$' then raise exception 'invalid_capability'; end if;
  if p_items is null or jsonb_typeof(p_items)<>'array' or jsonb_array_length(p_items) not between 1 and 30 then raise exception 'invalid_items'; end if;
  if p_student_name is null or length(btrim(p_student_name)) not between 1 and 100
     or length(coalesce(p_room_no,''))>100 or length(coalesce(p_note,''))>1000 then raise exception 'invalid_customer_details'; end if;
  if p_payment_method is null or p_payment_method not in ('cash','promptpay') then raise exception 'invalid_payment_method'; end if;
  v_hash := encode(digest(jsonb_build_object('branch_id',p_branch_id,'items',p_items,'student_name',btrim(p_student_name),
    'room_no',coalesce(p_room_no,''),'note',coalesce(p_note,''),'payment_method',p_payment_method,
    'staff_id',p_staff_id,'requested_for',p_requested_for)::text,'sha256'),'hex');
  -- Serializes even two retries arriving before the first order row exists.
  perform pg_advisory_xact_lock(hashtextextended(p_idempotency_key::text,0));
  select * into v_order from orders where idempotency_key=p_idempotency_key;
  if found then
    if v_order.request_hash is distinct from v_hash or v_order.token_hash is distinct from p_token_hash then raise exception 'idempotency_conflict'; end if;
    if p_staff_id is not null and not staff_can_access_branch(p_staff_id,v_order.branch_id) then raise exception 'forbidden'; end if;
    return to_jsonb(v_order);
  end if;
  select * into v_branch from branches where id=p_branch_id for update;
  if not found or not v_branch.is_active then raise exception 'branch_unavailable'; end if;
  if p_staff_id is not null and not staff_can_access_branch(p_staff_id,p_branch_id) then raise exception 'forbidden'; end if;
  v_source := case when p_staff_id is null then 'online' else 'walk_in' end;
  v_local := v_now at time zone v_branch.timezone;
  v_date := v_local::date;
  if p_staff_id is null and not v_branch.is_accepting_orders then raise exception 'branch_paused'; end if;
  if p_requested_for is null and p_staff_id is null and not branch_open_at(v_branch.opening_time,v_branch.closing_time,v_local::time) then raise exception 'branch_closed'; end if;
  if p_payment_method='promptpay' and
     (v_branch.promptpay_id is null or regexp_replace(v_branch.promptpay_id,'[- ]','','g') !~ '^(0[0-9]{9}|[0-9]{13}|[0-9]{15})$'
      or length(btrim(v_branch.promptpay_name))=0) then raise exception 'promptpay_unavailable'; end if;
  -- Expired unsubmitted transfers release capacity, inside this transaction.
  perform expire_unpaid_orders(p_branch_id);
  if p_requested_for is not null then
    if v_branch.slot_capacity<=0 then raise exception 'preorder_disabled'; end if;
    v_requested_local := p_requested_for at time zone v_branch.timezone;
    if p_requested_for < v_now+make_interval(mins=>v_branch.prep_minutes)
       or v_requested_local::date < v_date or v_requested_local::date > v_date+v_branch.preorder_days
       or extract(second from v_requested_local)<>0
       or (extract(hour from v_requested_local)::integer*60+extract(minute from v_requested_local)::integer)%v_branch.slot_minutes<>0
       or not branch_open_at(v_branch.opening_time,v_branch.closing_time,v_requested_local::time) then raise exception 'invalid_pickup_slot'; end if;
    select count(*) into v_reserved from orders where branch_id=p_branch_id and requested_for=p_requested_for and status<>'cancelled';
    if v_reserved>=v_branch.slot_capacity then raise exception 'pickup_slot_full'; end if;
  end if;
  -- Menu row locks serialize validation with direct admin edits of price/availability.
  for v_item in select value from jsonb_array_elements(p_items) loop
    if jsonb_typeof(v_item)<>'object' or coalesce(v_item->>'menu_item_id','') !~ '^[0-9a-fA-F-]{36}$'
       or coalesce(v_item->>'quantity','') !~ '^[0-9]{1,2}$' then raise exception 'invalid_items'; end if;
    v_quantity := (v_item->>'quantity')::integer;
    if v_quantity not between 1 and 20 then raise exception 'invalid_quantity'; end if;
    v_note:=coalesce(v_item->>'note','');
    if length(v_note)>500 then raise exception 'item_note_too_long'; end if;
    select * into v_menu from menu_items where id=(v_item->>'menu_item_id')::uuid and branch_id=p_branch_id for update;
    if not found or not v_menu.is_available then raise exception 'menu_unavailable'; end if;
    if v_menu.price is null or v_menu.price<0 or v_menu.price::text in ('NaN','Infinity','-Infinity') then raise exception 'invalid_menu_price'; end if;
    if jsonb_typeof(coalesce(v_item->'option_ids','[]'))<>'array' or jsonb_array_length(coalesce(v_item->'option_ids','[]'))>20 then raise exception 'invalid_options'; end if;
    if (select count(*)<>count(distinct value) from jsonb_array_elements(coalesce(v_item->'option_ids','[]'))) then raise exception 'duplicate_option'; end if;
    v_options:='[]'; v_unit:=v_menu.price;
    for v_option_id in select jsonb_array_elements_text(coalesce(v_item->'option_ids','[]')) loop
      if (select count(*) from jsonb_array_elements(v_menu.options) x where x->>'id'=v_option_id)<>1 then raise exception 'invalid_option'; end if;
      select value into v_option from jsonb_array_elements(v_menu.options) where value->>'id'=v_option_id;
      if jsonb_typeof(v_option->'price')<>'number' or coalesce(v_option->>'price','') !~ '^[0-9]+([.][0-9]{1,2})?$'
         or length(coalesce(v_option->>'name','')) not between 1 and 100 then raise exception 'invalid_option_price'; end if;
      if (v_option->>'price')::numeric>999999 then raise exception 'invalid_option_price'; end if;
      v_unit:=v_unit+(v_option->>'price')::numeric;
      v_options:=v_options||jsonb_build_array(jsonb_build_object('id',v_option_id,'name',v_option->>'name','price',(v_option->>'price')::numeric));
    end loop;
    if v_item ? 'expected_unit_price' then
      if jsonb_typeof(v_item->'expected_unit_price') not in ('number','string')
         or coalesce(v_item->>'expected_unit_price','') !~ '^[0-9]+([.][0-9]{1,2})?$'
         or (v_item->>'expected_unit_price')::numeric<>v_unit then raise exception 'price_changed'; end if;
    end if;
    v_total:=v_total+v_unit*v_quantity;
    v_lines:=v_lines||jsonb_build_array(jsonb_build_object('menu_item_id',v_menu.id,'item_name',v_menu.name,
      'unit_price',v_unit,'quantity',v_quantity,'options',v_options,'note',v_note));
  end loop;
  if v_total<=0 or v_total>99999999.99 then raise exception 'invalid_total'; end if;
  select count(*) into v_queue from orders where branch_id=p_branch_id and status in ('waiting','preparing')
    and (requested_for is null or requested_for <= v_now+make_interval(mins=>v_branch.prep_minutes));
  v_promise:=coalesce(p_requested_for,v_now+make_interval(mins=>ceil((v_queue+1)::numeric/v_branch.kitchen_capacity)::integer*v_branch.prep_minutes));
  v_number:=next_order_number(p_branch_id,v_date);
  insert into orders(order_code,branch_id,student_name,room_no,note,status,total_price,payment_method,payment_status,
    token_hash,idempotency_key,request_hash,source,order_date,expires_at,requested_for,promised_ready_at,
    payment_promptpay_id,payment_promptpay_name)
  values('Q'||lpad(v_number::text,greatest(3,length(v_number::text)),'0'),p_branch_id,btrim(p_student_name),coalesce(p_room_no,''),coalesce(p_note,''),
    case when p_payment_method='promptpay' then 'pending_payment' else 'waiting' end,v_total,p_payment_method,'pending',
    p_token_hash,p_idempotency_key,v_hash,v_source,v_date,case when p_payment_method='promptpay' then v_now+interval '15 minutes' end,p_requested_for,v_promise,
    case when p_payment_method='promptpay' then regexp_replace(v_branch.promptpay_id,'[- ]','','g') end,
    case when p_payment_method='promptpay' then btrim(v_branch.promptpay_name) end)
  returning * into v_order;
  insert into order_items(order_id,menu_item_id,item_name,unit_price,quantity,options,note)
    select v_order.id,(x->>'menu_item_id')::uuid,x->>'item_name',(x->>'unit_price')::numeric,(x->>'quantity')::integer,x->'options',x->>'note'
    from jsonb_array_elements(v_lines) x;
  insert into audit_log(staff_id,branch_id,action,entity,details) values(p_staff_id,p_branch_id,'create','order:'||v_order.id,
    jsonb_build_object('source',v_source,'total',v_total,'payment_method',p_payment_method));
  return to_jsonb(v_order);
end $$;

-- Remove the previous overload so PostgREST resolves the optional review guard
-- unambiguously. No database function depends on the old action entry point.
drop function if exists public.order_action(bigint,uuid,text,text,text);
create or replace function public.order_action(p_order_id bigint,p_staff_id uuid,p_action text,p_reason text default '',p_reference text default '',p_expected_slip_path text default null)
returns jsonb language plpgsql security invoker set search_path=public,pg_temp as $$
declare v_order orders%rowtype; v_branch branches%rowtype; v_before jsonb; v_queue integer;
begin
  select * into v_order from orders where id=p_order_id;
  if not found then raise exception 'order_not_found'; end if;
  if not staff_can_access_branch(p_staff_id,v_order.branch_id) then raise exception 'forbidden'; end if;
  select * into v_branch from branches where id=v_order.branch_id for update;
  select * into v_order from orders where id=p_order_id for update;
  if not staff_can_access_branch(p_staff_id,v_order.branch_id) then raise exception 'forbidden'; end if;
  if length(coalesce(p_reason,''))>1000 or length(coalesce(p_reference,''))>200 then raise exception 'invalid_details'; end if;
  v_before:=jsonb_build_object('status',v_order.status,'payment_status',v_order.payment_status);
  if p_action in ('cancel','reject','refund','incident') and length(btrim(coalesce(p_reason,'')))=0 then raise exception 'reason_required'; end if;
  -- A different employee may reject a slip and receive a replacement while an
  -- older review form remains open. Verify/reject only the evidence displayed.
  if p_action in ('verify','reject') and
     (p_expected_slip_path is null or p_expected_slip_path is distinct from v_order.slip_path) then raise exception 'slip_changed'; end if;
  case p_action
    when 'start' then
      if v_order.status<>'waiting' then raise exception 'invalid_transition'; end if;
      if v_order.payment_status<>'paid' and not (v_order.payment_method='cash' and v_branch.allow_cash_before_payment and v_order.payment_status='pending') then raise exception 'payment_required'; end if;
      update orders set status='preparing',started_at=now(),called_by=p_staff_id where id=p_order_id returning * into v_order;
    when 'ready' then
      if v_order.status<>'preparing' then raise exception 'invalid_transition'; end if;
      update orders set status='ready',ready_at=now(),called_by=p_staff_id where id=p_order_id returning * into v_order;
    when 'complete' then
      if v_order.status<>'ready' then raise exception 'invalid_transition'; end if;
      if v_order.payment_status<>'paid' then raise exception 'payment_required'; end if;
      update orders set status='completed',completed_at=now(),called_by=p_staff_id where id=p_order_id returning * into v_order;
    when 'cancel' then
      if v_order.payment_status='verifying' then raise exception 'payment_review_required'; end if;
      if v_order.status not in ('pending_payment','waiting','preparing','ready') then raise exception 'invalid_transition'; end if;
      update orders set status='cancelled',cancellation_reason=btrim(p_reason),called_by=p_staff_id,
        payment_status=case when payment_status='paid' then 'refund_due' else payment_status end
        where id=p_order_id returning * into v_order;
    when 'verify' then
      if v_order.payment_method<>'promptpay' or v_order.status<>'pending_payment' or v_order.payment_status<>'verifying' or v_order.slip_path is null then raise exception 'invalid_transition'; end if;
      if length(btrim(coalesce(p_reference,''))) not between 3 and 200 then raise exception 'reference_required'; end if;
      -- Serialize cross-branch verification of the same recipient/reference before
      -- reading its use; branch locks alone cannot protect a shared bank account.
      if v_order.payment_promptpay_id is not null then
        perform pg_advisory_xact_lock(hashtextextended('payment:'||v_order.payment_promptpay_id||':'||btrim(p_reference),0));
      end if;
      if exists(select 1 from orders where payment_reference=btrim(p_reference) and id<>p_order_id
        and (branch_id=v_order.branch_id or payment_promptpay_id=v_order.payment_promptpay_id)) then raise exception 'duplicate_payment_reference'; end if;
      select count(*) into v_queue from orders where branch_id=v_order.branch_id and status in ('waiting','preparing')
        and (requested_for is null or requested_for<=now()+make_interval(mins=>v_branch.prep_minutes));
      update orders set payment_status='paid',status='waiting',payment_reference=btrim(p_reference),payment_reason=null,payment_verified_at=now(),
        payment_verified_by=p_staff_id,called_by=p_staff_id,expires_at=null,
        promised_ready_at=greatest(coalesce(requested_for,now()),now()+make_interval(mins=>ceil((v_queue+1)::numeric/v_branch.kitchen_capacity)::integer*v_branch.prep_minutes))
        where id=p_order_id returning * into v_order;
    when 'reject' then
      if v_order.payment_method<>'promptpay' or v_order.status<>'pending_payment' or v_order.payment_status<>'verifying' then raise exception 'invalid_transition'; end if;
      update orders set payment_status='rejected',payment_reason=btrim(p_reason),expires_at=now()+interval '15 minutes',called_by=p_staff_id
        where id=p_order_id returning * into v_order;
    when 'cash' then
      if v_order.payment_method<>'cash' or v_order.status not in ('waiting','preparing','ready') or v_order.payment_status not in ('pending','legacy_unverified') then raise exception 'invalid_transition'; end if;
      update orders set payment_status='paid',payment_verified_at=now(),payment_verified_by=p_staff_id,called_by=p_staff_id
        where id=p_order_id returning * into v_order;
    when 'refund' then
      if v_order.status<>'cancelled' or v_order.payment_status<>'refund_due' then raise exception 'invalid_transition'; end if;
      update orders set payment_status='refunded',refunded_at=now(),called_by=p_staff_id where id=p_order_id returning * into v_order;
    when 'incident' then
      update orders set incident_note=concat_ws(E'\n',nullif(incident_note,''),to_char(now(),'YYYY-MM-DD HH24:MI TZ')||' '||btrim(p_reason)),called_by=p_staff_id
        where id=p_order_id returning * into v_order;
    else raise exception 'invalid_action';
  end case;
  insert into audit_log(staff_id,branch_id,action,entity,details) values(p_staff_id,v_order.branch_id,p_action,'order:'||p_order_id,
    jsonb_build_object('before',v_before,'after',jsonb_build_object('status',v_order.status,'payment_status',v_order.payment_status),'reason',coalesce(p_reason,''),'reference',coalesce(p_reference,'')));
  return to_jsonb(v_order);
end $$;

create or replace function public.attach_order_slip(p_order_id bigint,p_token_hash text,p_slip_path text)
returns jsonb language plpgsql security invoker set search_path=public,pg_temp as $$
declare v_order orders%rowtype;
begin
  select * into v_order from orders where id=p_order_id and token_hash=p_token_hash and token_hash is not null for update;
  if not found then raise exception 'order_not_found'; end if;
  if p_slip_path is null or length(p_slip_path)>240 or p_slip_path !~ ('^orders/'||p_order_id::text||'/[A-Za-z0-9_-]+\.(jpg|jpeg|png|webp)$') then raise exception 'invalid_slip_path'; end if;
  if v_order.payment_method<>'promptpay' or v_order.status<>'pending_payment'
     or v_order.payment_status not in ('pending','rejected') then raise exception 'invalid_transition'; end if;
  -- Keep the evidence immutable while staff review it. Replacements are allowed
  -- only after rejection; a submitted slip no longer expires during review.
  if v_order.expires_at is null or v_order.expires_at<=now() then raise exception 'order_expired'; end if;
  update orders set slip_path=p_slip_path,slip_url=null,payment_status='verifying',payment_reason=null where id=p_order_id returning * into v_order;
  insert into audit_log(branch_id,action,entity,details) values(v_order.branch_id,'slip_submitted','order:'||p_order_id,jsonb_build_object('payment_status','verifying'));
  return to_jsonb(v_order);
end $$;

create or replace function public.customer_order_action(p_order_id bigint,p_token_hash text,p_action text,p_reason text default '')
returns jsonb language plpgsql security invoker set search_path=public,pg_temp as $$
declare v_order orders%rowtype;
begin
  select * into v_order from orders where id=p_order_id and token_hash=p_token_hash and token_hash is not null;
  if not found then raise exception 'order_not_found'; end if;
  perform 1 from branches where id=v_order.branch_id for update;
  select * into v_order from orders where id=p_order_id and token_hash=p_token_hash for update;
  if length(coalesce(p_reason,''))>1000 then raise exception 'invalid_details'; end if;
  if p_action='cancel' then
    if v_order.payment_status='verifying' then raise exception 'payment_review_required'; end if;
    if v_order.status not in ('pending_payment','waiting') then raise exception 'invalid_transition'; end if;
    update orders set status='cancelled',cancellation_reason=coalesce(nullif(btrim(p_reason),''),'customer_cancelled'),
      payment_status=case when payment_status='paid' then 'refund_due' else payment_status end where id=p_order_id returning * into v_order;
  elsif p_action='arrive' then
    if v_order.status not in ('waiting','preparing','ready') then raise exception 'invalid_transition'; end if;
    update orders set arrived_at=coalesce(arrived_at,now()) where id=p_order_id returning * into v_order;
  else raise exception 'invalid_action'; end if;
  insert into audit_log(branch_id,action,entity,details) values(v_order.branch_id,'customer_'||p_action,'order:'||p_order_id,jsonb_build_object('reason',coalesce(p_reason,'')));
  return to_jsonb(v_order);
end $$;

create or replace function public.get_order_by_token(p_order_id bigint,p_token_hash text)
returns jsonb language sql stable security invoker set search_path=public,pg_temp as $$
  select to_jsonb(o)-'token_hash'-'request_hash'-'idempotency_key'-'slip_url'
    from orders o where o.id=p_order_id and o.token_hash=p_token_hash and o.token_hash is not null;
$$;

create or replace function public.expire_unpaid_orders(p_branch_id uuid default null)
returns integer language plpgsql security invoker set search_path=public,pg_temp as $$
declare v_count integer;
begin
  with candidates as (
    select id from orders where status='pending_payment' and payment_status in ('pending','rejected') and expires_at<=now()
      and (p_branch_id is null or branch_id=p_branch_id) order by expires_at limit 500 for update skip locked
  ), expired as (
    update orders o set status='cancelled',cancellation_reason='payment_timeout'
      from candidates c where o.id=c.id returning o.id,o.branch_id
  ), logged as (
    insert into audit_log(branch_id,action,entity,details)
      select branch_id,'expire','order:'||id,jsonb_build_object('reason','payment_timeout') from expired returning id
  ) select count(*) into v_count from logged;
  return v_count;
end $$;

create or replace function public.branch_dashboard(p_branch_id uuid,p_staff_id uuid,p_date date default null)
returns jsonb language plpgsql stable security invoker set search_path=public,pg_temp as $$
declare v_branch branches%rowtype; v_date date; v_result jsonb; v_top jsonb; v_hourly jsonb; v_payment jsonb; v_day_start timestamptz; v_day_end timestamptz;
begin
  if not staff_can_access_branch(p_staff_id,p_branch_id) then raise exception 'forbidden'; end if;
  select * into v_branch from branches where id=p_branch_id;
  v_date:=coalesce(p_date,(now() at time zone v_branch.timezone)::date);
  v_day_start:=v_date::timestamp at time zone v_branch.timezone;
  v_day_end:=(v_date+1)::timestamp at time zone v_branch.timezone;
  select jsonb_build_object('date',v_date,'timezone',v_branch.timezone,
    'orders_total',count(*),'orders_completed',count(*) filter(where status='completed'),
    'orders_cancelled',count(*) filter(where status='cancelled'),'orders_active',count(*) filter(where status in ('pending_payment','waiting','preparing','ready')),
    'gross_sales',coalesce(sum(total_price) filter(where status<>'cancelled'),0),
    'paid_total',coalesce(sum(total_price) filter(where payment_status='paid'),0),
    'pending_total',coalesce(sum(total_price) filter(where payment_status in ('pending','verifying','rejected') and status<>'cancelled'),0),
    'refund_due_total',coalesce(sum(total_price) filter(where payment_status='refund_due'),0),
    'refunded_total',coalesce(sum(total_price) filter(where payment_status='refunded'),0),
    'legacy_unverified_total',coalesce(sum(total_price) filter(where payment_status='legacy_unverified'),0),
    'payment_pending_count',count(*) filter(where payment_status in ('pending','verifying','rejected') and status<>'cancelled'),
    'incidents_count',count(*) filter(where nullif(incident_note,'') is not null),'arrivals_count',count(*) filter(where arrived_at is not null),
    'wait_minutes_p50',percentile_cont(0.5) within group(order by extract(epoch from (started_at-created_at))/60) filter(where started_at is not null and requested_for is null),
    'wait_minutes_p90',percentile_cont(0.9) within group(order by extract(epoch from (started_at-created_at))/60) filter(where started_at is not null and requested_for is null),
    'prep_minutes_p50',percentile_cont(0.5) within group(order by extract(epoch from (ready_at-started_at))/60) filter(where ready_at is not null and started_at is not null),
    'prep_minutes_p90',percentile_cont(0.9) within group(order by extract(epoch from (ready_at-started_at))/60) filter(where ready_at is not null and started_at is not null),
    'pickup_minutes_p50',percentile_cont(0.5) within group(order by extract(epoch from (completed_at-ready_at))/60) filter(where status='completed' and completed_at is not null and ready_at is not null),
    'pickup_minutes_p90',percentile_cont(0.9) within group(order by extract(epoch from (completed_at-ready_at))/60) filter(where status='completed' and completed_at is not null and ready_at is not null),
    'counter_wait_minutes_p50',percentile_cont(0.5) within group(order by greatest(0,extract(epoch from (completed_at-arrived_at))/60)) filter(where status='completed' and completed_at is not null and arrived_at is not null),
    'counter_wait_minutes_p90',percentile_cont(0.9) within group(order by greatest(0,extract(epoch from (completed_at-arrived_at))/60)) filter(where status='completed' and completed_at is not null and arrived_at is not null),
    'eta_error_minutes_p50',percentile_cont(0.5) within group(order by abs(extract(epoch from (ready_at-promised_ready_at))/60)) filter(where ready_at is not null and promised_ready_at is not null),
    'eta_error_minutes_p90',percentile_cont(0.9) within group(order by abs(extract(epoch from (ready_at-promised_ready_at))/60)) filter(where ready_at is not null and promised_ready_at is not null))
  into v_result from orders where branch_id=p_branch_id and order_date=v_date;
  select coalesce(jsonb_agg(to_jsonb(t)),'[]') into v_top from (
    select i.item_name,sum(i.quantity) as quantity,sum(i.quantity*i.unit_price) as revenue
    from order_items i join orders o on o.id=i.order_id
    where o.branch_id=p_branch_id and o.order_date=v_date and o.status<>'cancelled'
    group by i.item_name order by sum(i.quantity) desc limit 10) t;
  select coalesce(jsonb_agg(to_jsonb(t)),'[]') into v_hourly from (
    select extract(hour from created_at at time zone v_branch.timezone)::integer as hour,count(*) as orders
    from orders where branch_id=p_branch_id and order_date=v_date group by 1 order by 1) t;
  select coalesce(jsonb_agg(to_jsonb(t)),'[]') into v_payment from (
    select payment_method,payment_status,count(*) as orders,sum(total_price) as total
    from orders where branch_id=p_branch_id and order_date=v_date group by 1,2 order by 1,2) t;
  v_result:=v_result||jsonb_build_object(
    'receipts_today',(select coalesce(sum(total_price),0) from orders where branch_id=p_branch_id and payment_verified_at>=v_day_start and payment_verified_at<v_day_end),
    'refunds_today',(select coalesce(sum(total_price),0) from orders where branch_id=p_branch_id and refunded_at>=v_day_start and refunded_at<v_day_end));
  return v_result||jsonb_build_object('top_items',v_top,'hourly_orders',v_hourly,'payment_methods',v_payment);
end $$;

create or replace function public.enqueue_order_notification()
returns trigger language plpgsql security invoker set search_path=public,pg_temp as $$
begin
  if tg_op='UPDATE' and (old.status is distinct from new.status or old.payment_status is distinct from new.payment_status) then
    insert into notification_outbox(order_id,event,payload)
      values(new.id,case when old.status is distinct from new.status then new.status else 'payment_'||new.payment_status end,
        jsonb_build_object('order_id',new.id,'order_code',new.order_code,'status',new.status,'payment_status',new.payment_status))
      on conflict(order_id,event) do nothing;
  end if;
  return new;
end $$;
drop trigger if exists orders_notification on public.orders;
create trigger orders_notification after update of status,payment_status on public.orders
  for each row execute function public.enqueue_order_notification();

create or replace function public.claim_notification_outbox(p_limit integer default 20)
returns setof public.notification_outbox language sql security invoker set search_path=public,pg_temp as $$
  update notification_outbox n set locked_at=now(),attempts=n.attempts+1
  from (select id from notification_outbox where delivered_at is null and attempts<8 and available_at<=now()
    and (locked_at is null or locked_at<now()-interval '5 minutes') order by available_at,id
    limit greatest(1,least(p_limit,100)) for update skip locked) due
  where n.id=due.id returning n.*;
$$;
create or replace function public.finish_notification_outbox(p_id bigint,p_success boolean,p_error text default '')
returns void language sql security invoker set search_path=public,pg_temp as $$
  update notification_outbox set delivered_at=case when p_success then now() end,locked_at=null,
    last_error=case when p_success then null else left(p_error,1000) end,
    available_at=case when p_success then available_at else now()+make_interval(secs=>least(3600,30*power(2,least(attempts,7))::integer)) end
  where id=p_id and delivered_at is null and locked_at is not null;
$$;

-- PostgreSQL gives PUBLIC execute by default: explicitly close every project RPC.
do $$ declare v_function record; begin
  for v_function in select p.oid::regprocedure as signature from pg_proc p join pg_namespace n on n.oid=p.pronamespace
    where n.nspname='public' and p.proname in ('staff_can_access_branch','branch_open_at','branch_queue_counts','next_order_number','create_order','order_action',
      'attach_order_slip','customer_order_action','get_order_by_token','expire_unpaid_orders','branch_dashboard','enqueue_order_notification',
      'claim_notification_outbox','finish_notification_outbox') loop
    execute format('revoke all on function %s from public, anon, authenticated',v_function.signature);
    execute format('grant execute on function %s to service_role',v_function.signature);
  end loop;
end $$;
-- A restrictive policy blocks slips even when other generic storage policies exist.
do $$ begin
  if to_regclass('storage.buckets') is not null then
    insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
      values('slips','slips',false,5242880,array['image/jpeg','image/png','image/webp'])
      on conflict(id) do update set public=false,file_size_limit=5242880,allowed_mime_types=excluded.allowed_mime_types;
  end if;
  if to_regclass('storage.objects') is not null then
    execute 'drop policy if exists slips_server_only on storage.objects';
    execute $policy$create policy slips_server_only on storage.objects as restrictive for all to anon,authenticated
      using(bucket_id <> 'slips') with check(bucket_id <> 'slips')$policy$;
  end if;
end $$;
notify pgrst,'reload schema';
commit;
