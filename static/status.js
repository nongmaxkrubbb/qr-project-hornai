(() => {
  'use strict';
  const configEl = document.getElementById('status-config'); if (!configEl) return;
  const config = JSON.parse(configEl.textContent);
  const statusNames = {pending_payment:'รอชำระเงิน / ตรวจสลิป',waiting:'ร้านรับออเดอร์แล้ว · รอคิว',preparing:'ครัวกำลังทำอาหาร',ready:'อาหารพร้อมรับแล้ว',completed:'รับอาหารเรียบร้อย',cancelled:'ออเดอร์ถูกยกเลิก'};
  const statusDescriptions = {pending_payment:'โอนและส่งสลิปเพื่อให้ร้านตรวจสอบก่อนเริ่มเตรียมอาหาร',waiting:'ร้านรับออเดอร์แล้ว รอสักครู่ก่อนถึงคิวของคุณ',preparing:'กำลังเตรียมมื้อนี้ให้คุณ ดูจุดรับอาหารด้านล่างได้เลย',ready:'แสดงหมายเลขออเดอร์กับพนักงานที่จุดรับอาหาร',completed:'ขอบคุณที่สั่งอาหาร ขอให้อิ่มอร่อยกับมื้อนี้',cancelled:'หากคุณชำระเงินแล้ว กรุณาตรวจสถานะคืนเงินหรือติดต่อร้าน'};
  const paymentNames = {pending:'รอชำระ',unpaid:'รอชำระ',cash_due:'รอรับเงินสด',verifying:'รอตรวจสลิป',paid:'ชำระแล้ว',rejected:'กรุณาตรวจสลิป',refund_due:'รอคืนเงิน',refunded:'คืนเงินแล้ว',legacy_unverified:'ร้านกำลังตรวจยอดเดิม'};
  const el = id => document.getElementById(id);
  let timer, inFlight = false, failures = 0, terminal = false, lastStatus = null, foregroundEnabled = false, notified = false, lastSuccess = null;
  const connection = el('connection');
  function sameOrigin(raw) { const url = new URL(raw, location.origin); if (url.origin !== location.origin) throw new Error('ที่อยู่การเชื่อมต่อไม่ถูกต้อง'); return url.href; }
  function dateTime(value) { if (!value) return ''; const date = new Date(value); return Number.isNaN(date.getTime()) ? '' : date.toLocaleString('th-TH', {day:'numeric',month:'short',hour:'2-digit',minute:'2-digit',timeZone:config.timezone || 'Asia/Bangkok'}); }
  function text(id, value) { el(id).textContent = value; }
  function showDate(row, id, value) { el(row).hidden = !value; text(id,dateTime(value)); }
  function paymentClass(value) { return Object.prototype.hasOwnProperty.call(paymentNames,value) ? value : 'pending'; }
  function showItems(items) {
    const list = el('order-items'); const fragment = document.createDocumentFragment();
    for (const item of items || []) {
      const li = document.createElement('li'); const row = document.createElement('div'); row.className = 'flex between';
      const name = document.createElement('strong'); name.textContent = `${item.name} × ${item.quantity}`;
      const price = document.createElement('span'); price.textContent = `${(Number(item.unit_price) * Number(item.quantity)).toFixed(2)} ฿`;
      row.append(name,price); li.append(row);
      if (Array.isArray(item.options) && item.options.length) { const options = document.createElement('div'); options.className='small muted'; options.textContent = item.options.map(o => typeof o === 'string' ? o : o.name).join(', '); li.append(options); }
      if (item.note) { const note = document.createElement('div'); note.className='small muted'; note.textContent=`หมายเหตุ: ${item.note}`; li.append(note); }
      fragment.append(li);
    }
    list.replaceChildren(fragment);
  }
  async function notifyReady(code) {
    if (!foregroundEnabled || notified || !('Notification' in window) || Notification.permission !== 'granted') return;
    notified = true;
    const options = {body:`ออเดอร์ ${code} พร้อมรับที่ร้านแล้ว`,icon:'/static/icon.svg',tag:`order-${config.orderId}-ready`,data:{url:location.href}};
    try { const registration = 'serviceWorker' in navigator ? await navigator.serviceWorker.getRegistration('/') : null; if (registration) await registration.showNotification('อาหารพร้อมรับแล้ว',options); else new Notification('อาหารพร้อมรับแล้ว',options); } catch (_) { window.showToast('อาหารของคุณพร้อมรับที่ร้านแล้ว'); }
  }
  function update(data) {
    const status = data.status;
    text('order-code', data.order_code);
    const known = Object.prototype.hasOwnProperty.call(statusNames,status);
    text('status-badge', known ? statusNames[status] : 'กำลังตรวจสอบ'); el('status-badge').className = `badge status-${known ? status : 'waiting'}`;
    text('status-description', status === 'pending_payment' && data.payment_status === 'verifying' ? 'ส่งสลิปแล้ว กำลังรอร้านตรวจสอบ ไม่ต้องโอนซ้ำ' : statusDescriptions[status] || 'กรุณาติดต่อร้านหากสถานะไม่อัปเดต');
    const steps = ['waiting','preparing','ready','completed']; const index = steps.indexOf(status);
    document.querySelectorAll('[data-step]').forEach(step => { const active = index >= steps.indexOf(step.dataset.step); step.classList.toggle('active',active); if (step.dataset.step === status) step.setAttribute('aria-current','step'); else step.removeAttribute('aria-current'); });
    text('orders-ahead', data.orders_ahead ?? '—');
    text('eta', status === 'completed' ? 'รับอาหารแล้ว' : status === 'ready' ? 'พร้อมแล้ว' : status === 'cancelled' ? '—' : status === 'pending_payment' ? 'หลังร้านยืนยันรับเงิน' : `${data.eta_min ?? data.eta_minutes ?? '—'}–${data.eta_max ?? data.eta_minutes ?? '—'} นาที`);
    text('total-price',Number(data.total_price || 0).toFixed(2)); text('pickup-point', data.branch?.pickup_point || 'หน้าร้าน');
    showDate('requested-row','requested-for',data.requested_for); showDate('promised-row','promised-at',data.promised_ready_at);
    text('payment-badge',paymentNames[data.payment_status] || 'กำลังตรวจสอบยอด'); el('payment-badge').className=`badge status-${paymentClass(data.payment_status)}`;
    el('payment-reason').hidden = !data.payment_reason; text('payment-reason',data.payment_reason || '');
    el('payment-link').hidden = config.paymentMethod !== 'promptpay' || !['pending','rejected','verifying'].includes(data.payment_status) || status !== 'pending_payment';
    el('cash-notice').hidden = config.paymentMethod !== 'cash' || ['paid','refund_due','refunded'].includes(data.payment_status) || ['cancelled','completed'].includes(status);
    el('arrive-form').hidden = !['waiting','preparing','ready'].includes(status) || !!data.arrived_at;
    el('arrived-message').hidden = !data.arrived_at || ['cancelled','completed'].includes(status);
    el('cancel-details').hidden = !data.can_cancel;
    terminal = ['completed','cancelled'].includes(status); el('reorder-form').hidden = !terminal; el('notification-card').hidden = terminal;
    if (status === 'ready' && lastStatus !== 'ready') notifyReady(data.order_code);
    lastStatus = status; showItems(data.items);
  }
  function schedule(delay) { clearTimeout(timer); if (!terminal && !document.hidden) timer = setTimeout(refresh,delay); }
  async function refresh() {
    if (inFlight) return; inFlight = true; el('refresh-status').disabled = true;
    const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(),12000);
    try {
      const response = await fetch(sameOrigin(config.statusUrl),{headers:{Accept:'application/json'},credentials:'same-origin',cache:'no-store',signal:controller.signal});
      if ([401,403,404].includes(response.status)) { terminal = true; throw new Error('ลิงก์ออเดอร์นี้ใช้ไม่ได้หรือหมดอายุ กรุณาเปิดจากออเดอร์ของฉันหรือติดต่อร้าน'); }
      if (!response.ok) throw new Error(response.status === 429 ? 'มีคำขอจำนวนมาก ระบบจะลองใหม่อัตโนมัติ' : 'เชื่อมต่อร้านไม่ได้ชั่วคราว ระบบจะลองใหม่อัตโนมัติ');
      const data = await response.json(); update(data); failures = 0; lastSuccess = new Date();
      connection.classList.remove('stale'); connection.textContent = `อัปเดตล่าสุด ${lastSuccess.toLocaleTimeString('th-TH',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}${terminal ? ' · จบออเดอร์แล้ว' : ' · อัปเดตอัตโนมัติ'}`;
      el('status-error').hidden = true; schedule(8000 + Math.random()*2000);
    } catch (error) {
      failures += 1; connection.classList.add('stale');
      connection.textContent = lastSuccess ? `ข้อมูลอาจไม่เป็นปัจจุบัน · อัปเดตล่าสุด ${lastSuccess.toLocaleTimeString('th-TH')}` : 'ยังไม่ได้รับสถานะล่าสุด';
      text('status-error', navigator.onLine ? (error.name === 'AbortError' ? 'ร้านตอบกลับช้า กำลังลองเชื่อมต่อใหม่' : error.message) : 'อุปกรณ์ไม่ได้เชื่อมต่ออินเทอร์เน็ต สถานะอาจยังไม่อัปเดต'); el('status-error').hidden = false;
      schedule(Math.min(60000, 5000 * 2 ** Math.min(failures,4)));
    } finally { clearTimeout(timeout); inFlight=false; el('refresh-status').disabled=false; }
  }
  function bytes(base64) { const input = base64.replace(/-/g,'+').replace(/_/g,'/'); return Uint8Array.from(atob(input + '='.repeat((4-input.length%4)%4)),c=>c.charCodeAt(0)); }
  const notificationButton = el('enable-notifications'); const help = el('notification-help');
  if (!('Notification' in window)) { notificationButton.disabled=true; help.textContent='เบราว์เซอร์นี้ยังแจ้งเตือนไม่ได้ เปิดหน้าสถานะไว้เพื่อติดตามอาหาร'; }
  else help.textContent = config.pushPublicKey ? 'อนุญาตการแจ้งเตือนเพื่อรับข่าวเมื่ออาหารพร้อม แม้ออกจากหน้านี้ ในอุปกรณ์ที่รองรับ' : 'เปิดการแจ้งเตือนขณะที่หน้านี้เปิดอยู่ ร้านยังไม่ได้เปิดการแจ้งเตือนเมื่อปิดหน้า';
  notificationButton.addEventListener('click',async () => {
    notificationButton.disabled=true;
    try {
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') { help.textContent='ยังไม่ได้รับอนุญาต เปิดหน้าสถานะไว้ หรือเปลี่ยนสิทธิ์การแจ้งเตือนในตั้งค่าเบราว์เซอร์'; return; }
      foregroundEnabled=true;
      if (config.pushPublicKey && 'serviceWorker' in navigator && 'PushManager' in window) {
        await navigator.serviceWorker.register('/sw.js',{scope:'/'}); const registration=await navigator.serviceWorker.ready;
        const subscription = await registration.pushManager.getSubscription() || await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:bytes(config.pushPublicKey)});
        const response=await fetch(sameOrigin(config.subscribeUrl),{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','Accept':'application/json','X-CSRFToken':document.querySelector('meta[name="csrf-token"]').content},body:JSON.stringify({token:config.token,subscription:subscription.toJSON()})});
        if (!response.ok) throw new Error('บันทึกการแจ้งเตือนเมื่อปิดหน้าไม่สำเร็จ ยังแจ้งเตือนได้ขณะเปิดหน้านี้');
        help.textContent='เปิดการแจ้งเตือนแล้ว ระบบจะแจ้งเมื่ออาหารพร้อมรับในอุปกรณ์นี้';
      } else help.textContent='เปิดการแจ้งเตือนขณะใช้งานหน้านี้แล้ว กรุณาเปิดหน้าไว้จนอาหารพร้อม';
      notificationButton.textContent='เปิดการแจ้งเตือนแล้ว';
      if (lastStatus === 'ready') notifyReady(el('order-code').textContent);
    } catch (error) { help.textContent=error.message || 'เปิดการแจ้งเตือนไม่สำเร็จ กรุณาติดตามในหน้านี้'; }
    finally { notificationButton.disabled=false; }
  });
  el('refresh-status').addEventListener('click',() => { clearTimeout(timer); refresh(); });
  document.addEventListener('visibilitychange',() => { clearTimeout(timer); if (!document.hidden && !terminal) refresh(); });
  window.addEventListener('online',() => { if (!terminal) refresh(); });
  window.addEventListener('offline',() => { connection.classList.add('stale'); connection.textContent='ออฟไลน์ · สถานะอาจยังไม่อัปเดต'; });
  if (config.initialStatus) update(config.initialStatus);
  if (!terminal) refresh();
})();
