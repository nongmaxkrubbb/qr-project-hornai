-- Run ONLY on a disposable development/staging database after the migration.
-- Fixtures and helper functions roll back, including intentional state changes.
begin;
create or replace function pg_temp.assert_ok(p_condition boolean,p_message text)
returns void language plpgsql as $$ begin
  if p_condition is distinct from true then raise exception 'ASSERTION FAILED: %',p_message; end if;
end $$;
create or replace function pg_temp.expect_error(p_sql text,p_error text)
returns void language plpgsql as $$
declare v_failed boolean:=false;
begin
  begin execute p_sql;
  exception when others then
    if position(p_error in sqlerrm)=0 then raise exception 'Expected %, got %',p_error,sqlerrm; end if;
    v_failed:=true;
  end;
  if not v_failed then raise exception 'Expected error % but statement succeeded',p_error; end if;
end $$;
insert into organizations(id,name) values
  ('f1000000-0000-0000-0000-000000000001','Test campus'),
  ('f1000000-0000-0000-0000-000000000002','Other campus');
insert into branches(id,organization_id,name,opening_time,closing_time,promptpay_id,slot_capacity,preorder_days)
values
  ('f2000000-0000-0000-0000-000000000001','f1000000-0000-0000-0000-000000000001','Test shop','00:00','00:00','0812345678',1,7),
  ('f2000000-0000-0000-0000-000000000002','f1000000-0000-0000-0000-000000000001','Sibling shop','00:00','00:00','0812345678',1,7),
  ('f2000000-0000-0000-0000-000000000003','f1000000-0000-0000-0000-000000000002','Other shop','00:00','00:00','0812345678',1,7);
insert into staff(id,branch_id,organization_id,username,role) values
  ('f3000000-0000-0000-0000-000000000001','f2000000-0000-0000-0000-000000000001','f1000000-0000-0000-0000-000000000001','sql_test_branch','branch_admin'),
  ('f3000000-0000-0000-0000-000000000002',null,'f1000000-0000-0000-0000-000000000001','sql_test_org','org_admin'),
  ('f3000000-0000-0000-0000-000000000003',null,null,'sql_test_unscoped','staff');
insert into menu_items(id,branch_id,name,price,options) values
  ('f4000000-0000-0000-0000-000000000001','f2000000-0000-0000-0000-000000000001','Rice',40,'[{"id":"egg","name":"Egg","price":10}]'),
  ('f4000000-0000-0000-0000-000000000002','f2000000-0000-0000-0000-000000000002','Other Rice',50,'[]');
create or replace function pg_temp.order_fixture(p_key uuid,p_method text default 'cash',p_requested timestamptz default null)
returns jsonb language sql as $$
 select create_order('f2000000-0000-0000-0000-000000000001',
  '[{"menu_item_id":"f4000000-0000-0000-0000-000000000001","quantity":2,"option_ids":["egg"],"note":"less spicy"}]',
  'Student','A101','',p_method,p_key,repeat('a',64),null,p_requested);
$$;

do $$
declare v_cash jsonb; v_transfer jsonb; v_second jsonb; v_expired jsonb; v_slot jsonb;
  v_id bigint; v_count integer; v_before integer; v_next_slot timestamptz; v_metrics jsonb;
begin
  perform pg_temp.assert_ok(staff_can_access_branch('f3000000-0000-0000-0000-000000000002','f2000000-0000-0000-0000-000000000002'),'org admin same organization');
  perform pg_temp.assert_ok(not staff_can_access_branch('f3000000-0000-0000-0000-000000000002','f2000000-0000-0000-0000-000000000003'),'org admin blocked from other organization');
  perform pg_temp.assert_ok(not staff_can_access_branch('f3000000-0000-0000-0000-000000000003','f2000000-0000-0000-0000-000000000001'),'unscoped staff denied');
  v_cash:=pg_temp.order_fixture('f5000000-0000-0000-0000-000000000001'); v_id:=(v_cash->>'id')::bigint;
  perform pg_temp.assert_ok(v_cash->>'payment_status'='pending' and v_cash->>'status'='waiting','cash is unpaid until collected');
  perform pg_temp.assert_ok((v_cash->>'total_price')::numeric=100,'server prices include selected options');
  perform pg_temp.assert_ok((v_cash->>'promised_ready_at')::timestamptz>now(),'first order includes own cooking time');
  perform pg_temp.assert_ok((select count(*)=1 from order_items where order_id=v_id),'items inserted in same transaction');
  v_second:=pg_temp.order_fixture('f5000000-0000-0000-0000-000000000001');
  perform pg_temp.assert_ok(v_second->>'id'=v_cash->>'id','retry returns original order');
  perform pg_temp.assert_ok((select last_number=1 from order_counters where branch_id='f2000000-0000-0000-0000-000000000001' and the_date=(now() at time zone 'Asia/Bangkok')::date),'retry does not consume number');
  perform pg_temp.expect_error($q$select create_order('f2000000-0000-0000-0000-000000000001','[{"menu_item_id":"f4000000-0000-0000-0000-000000000001","quantity":1}]','Other','','','cash','f5000000-0000-0000-0000-000000000001',repeat('a',64))$q$,'idempotency_conflict');
  perform pg_temp.expect_error(format($q$select order_action(%s,'f3000000-0000-0000-0000-000000000003','start')$q$,v_id),'forbidden');
  perform order_action(v_id,'f3000000-0000-0000-0000-000000000001','start');
  perform order_action(v_id,'f3000000-0000-0000-0000-000000000001','ready');
  perform pg_temp.expect_error(format($q$select order_action(%s,'f3000000-0000-0000-0000-000000000001','complete')$q$,v_id),'payment_required');
  perform order_action(v_id,'f3000000-0000-0000-0000-000000000001','cash');
  perform order_action(v_id,'f3000000-0000-0000-0000-000000000001','complete');
  perform pg_temp.assert_ok((select status='completed' and payment_status='paid' from orders where id=v_id),'complete only after cash collection');

  select count(*) into v_before from orders where branch_id='f2000000-0000-0000-0000-000000000001';
  perform pg_temp.expect_error($q$select create_order('f2000000-0000-0000-0000-000000000001','[{"menu_item_id":"f4000000-0000-0000-0000-000000000001","quantity":1},{"menu_item_id":"f4000000-0000-0000-0000-000000000002","quantity":1}]','Student','','','cash','f5000000-0000-0000-0000-000000000002',repeat('a',64))$q$,'menu_unavailable');
  perform pg_temp.assert_ok((select count(*)=v_before from orders where branch_id='f2000000-0000-0000-0000-000000000001'),'mixed branch fails without orphan header');
  perform pg_temp.expect_error($q$select create_order('f2000000-0000-0000-0000-000000000001','[{"menu_item_id":"f4000000-0000-0000-0000-000000000001","quantity":21}]','Student','','','cash','f5000000-0000-0000-0000-000000000002',repeat('a',64))$q$,'invalid_quantity');
  perform pg_temp.expect_error($q$select create_order('f2000000-0000-0000-0000-000000000001','[{"menu_item_id":"f4000000-0000-0000-0000-000000000001","quantity":1,"option_ids":["egg","egg"]}]','Student','','','cash','f5000000-0000-0000-0000-000000000002',repeat('a',64))$q$,'duplicate_option');

  perform pg_temp.expect_error($q$select create_order('f2000000-0000-0000-0000-000000000001','[{"menu_item_id":"f4000000-0000-0000-0000-000000000001","quantity":1,"expected_unit_price":"1.00"}]','Student','','','cash','f5000000-0000-0000-0000-000000000002',repeat('a',64))$q$,'price_changed');
  v_transfer:=pg_temp.order_fixture('f5000000-0000-0000-0000-000000000003','promptpay'); v_id:=(v_transfer->>'id')::bigint;
  perform pg_temp.assert_ok(v_transfer->>'status'='pending_payment','unpaid transfers excluded from kitchen');
  perform pg_temp.expect_error(format($q$select attach_order_slip(%s,repeat('b',64),'orders/%s/test.jpg')$q$,v_id,v_id),'order_not_found');
  perform attach_order_slip(v_id,repeat('a',64),'orders/'||v_id||'/test.jpg');
  perform pg_temp.expect_error(format($q$select customer_order_action(%s,repeat('a',64),'cancel')$q$,v_id),'payment_review_required');
  perform pg_temp.expect_error(format($q$select order_action(%s,'f3000000-0000-0000-0000-000000000001','cancel','customer request')$q$,v_id),'payment_review_required');
  update orders set expires_at=now()-interval '1 hour' where id=v_id;
  perform expire_unpaid_orders('f2000000-0000-0000-0000-000000000001');
  perform pg_temp.assert_ok((select status='pending_payment' and payment_status='verifying' from orders where id=v_id),'submitted slips do not expire while under review');
  perform pg_temp.expect_error(format($q$select order_action(%s,'f3000000-0000-0000-0000-000000000001','verify')$q$,v_id),'reference_required');
  perform order_action(v_id,'f3000000-0000-0000-0000-000000000001','verify','','bank-ref-123');
  perform pg_temp.expect_error(format($q$select attach_order_slip(%s,repeat('a',64),'orders/%s/reupload.jpg')$q$,v_id,v_id),'invalid_transition');
  perform customer_order_action(v_id,repeat('a',64),'arrive');
  perform customer_order_action(v_id,repeat('a',64),'cancel','Changed plans');
  perform pg_temp.assert_ok((select payment_status='refund_due' from orders where id=v_id),'paid cancellation requires refund');
  perform pg_temp.expect_error(format($q$select order_action(%s,'f3000000-0000-0000-0000-000000000001','refund')$q$,v_id),'reason_required');
  perform order_action(v_id,'f3000000-0000-0000-0000-000000000001','refund','Refund receipt checked');
  v_second:=pg_temp.order_fixture('f5000000-0000-0000-0000-000000000004','promptpay'); v_id:=(v_second->>'id')::bigint;
  perform attach_order_slip(v_id,repeat('a',64),'orders/'||v_id||'/test.jpg');
  perform pg_temp.expect_error(format($q$select order_action(%s,'f3000000-0000-0000-0000-000000000001','verify','','bank-ref-123')$q$,v_id),'duplicate_payment_reference');
  perform order_action(v_id,'f3000000-0000-0000-0000-000000000001','reject','Wrong amount');
  perform pg_temp.assert_ok((select payment_reason='Wrong amount' from orders where id=v_id),'rejection reason available to customer');
  perform attach_order_slip(v_id,repeat('a',64),'orders/'||v_id||'/retry.jpg');
  perform pg_temp.assert_ok((select payment_reason is null from orders where id=v_id),'new slip clears stale rejection reason');
  perform order_action(v_id,'f3000000-0000-0000-0000-000000000001','reject','Wrong amount');
  update orders set expires_at=now()-interval '1 minute' where id=v_id;
  perform pg_temp.expect_error(format($q$select attach_order_slip(%s,repeat('a',64),'orders/%s/new.jpg')$q$,v_id,v_id),'order_expired');
  perform expire_unpaid_orders('f2000000-0000-0000-0000-000000000001');
  perform pg_temp.assert_ok((select status='cancelled' from orders where id=v_id),'rejected/unsubmitted transfer expires');

  v_next_slot:=(((now() at time zone 'Asia/Bangkok')::date+1)::timestamp+interval '12 hours') at time zone 'Asia/Bangkok';
  v_slot:=pg_temp.order_fixture('f5000000-0000-0000-0000-000000000005','cash',v_next_slot);
  perform pg_temp.expect_error(format($q$select pg_temp.order_fixture('f5000000-0000-0000-0000-000000000006','cash',%L::timestamptz)$q$,v_next_slot),'pickup_slot_full');
  perform customer_order_action((v_slot->>'id')::bigint,repeat('a',64),'cancel');
  perform pg_temp.order_fixture('f5000000-0000-0000-0000-000000000006','cash',v_next_slot);
  update branches set is_accepting_orders=false where id='f2000000-0000-0000-0000-000000000001';
  update menu_items set is_available=false where id='f4000000-0000-0000-0000-000000000001';
  v_second:=pg_temp.order_fixture('f5000000-0000-0000-0000-000000000001');
  perform pg_temp.assert_ok(v_second->>'id'=v_cash->>'id','retry still works after shop paused/menu sold out');
  perform pg_temp.expect_error($q$select pg_temp.order_fixture('f5000000-0000-0000-0000-000000000007')$q$,'branch_paused');
  v_metrics:=branch_dashboard('f2000000-0000-0000-0000-000000000001','f3000000-0000-0000-0000-000000000001');
  perform pg_temp.assert_ok((v_metrics->>'paid_total')::numeric=100,'daily paid total excludes refunded order');
  perform pg_temp.assert_ok((v_metrics->>'receipts_today')::numeric=200 and (v_metrics->>'refunds_today')::numeric=100,'actual daily receipts and refunds use event dates');
  perform pg_temp.expect_error($q$select branch_dashboard('f2000000-0000-0000-0000-000000000003','f3000000-0000-0000-0000-000000000002')$q$,'forbidden');
  perform pg_temp.assert_ok((select count(*)>0 from audit_log where branch_id='f2000000-0000-0000-0000-000000000001'),'audit events recorded');
  perform pg_temp.assert_ok((select count(*)>0 from notification_outbox where order_id=(v_cash->>'id')::bigint),'notifications enqueue transactionally');
  perform pg_temp.assert_ok(not has_table_privilege('anon','public.orders','SELECT'),'anon cannot read orders');
  perform pg_temp.assert_ok(not has_function_privilege('anon','public.create_order(uuid,jsonb,text,text,text,text,uuid,text,uuid,timestamptz)','EXECUTE'),'anon cannot call order RPC');
end $$;
rollback;
