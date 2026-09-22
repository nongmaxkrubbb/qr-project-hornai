(() => {
  'use strict';
  const toast = (message, isError = false) => {
    const el = document.getElementById('toast'); if (!el) return;
    el.textContent = message; el.classList.toggle('error', isError); el.hidden = false;
    clearTimeout(toast.timer); toast.timer = setTimeout(() => { el.hidden = true; }, isError ? 8000 : 3500);
  };
  window.showToast = toast;
  let cartQueue = Promise.resolve();
  document.querySelectorAll('[data-cart-add]').forEach(form => form.addEventListener('submit', async event => {
    if (!window.fetch) return;
    event.preventDefault(); if (form.dataset.submitting === 'true') return;
    if (form.querySelectorAll('input[name=option_ids]:checked').length>10) { toast('เลือกเพิ่มเติมได้ไม่เกิน 10 ตัวเลือกต่อเมนู',true); return; }
    const button = form.querySelector('button[type="submit"]'); const label = button.textContent;
    const body = new FormData(form);
    const previous = cartQueue; let finish;
    cartQueue = new Promise(resolve => { finish=resolve; });
    form.dataset.submitting = 'true'; button.disabled = true; button.textContent = 'กำลังรอเพิ่ม…';
    // Each response saves the session cart before the next menu request begins.
    await previous;
    const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(),15000);
    button.textContent = 'กำลังเพิ่ม…';
    try {
      const response = await fetch(form.action, {method:'POST',body,headers:{Accept:'application/json'},credentials:'same-origin',signal:controller.signal});
      const type = response.headers.get('Content-Type') || '';
      if (!type.includes('application/json')) throw new Error(response.status === 429 ? 'มีคำขอจำนวนมาก กรุณารอสักครู่แล้วลองใหม่' : 'เพิ่มอาหารไม่สำเร็จ กรุณารีเฟรชหน้าแล้วลองใหม่');
      const data = await response.json();
      if (!response.ok || data.ok === false) throw new Error(data.error || data.message || 'เพิ่มอาหารไม่สำเร็จ');
      document.querySelectorAll('[data-cart-count]').forEach(el => { el.textContent = data.cart_count ?? data.count ?? '✓'; });
      document.querySelectorAll('[data-cart-total]').forEach(el => { if (data.cart_total != null || data.total != null) el.textContent = Number(data.cart_total ?? data.total).toFixed(2); });
      toast(data.message || 'เพิ่มอาหารในตะกร้าแล้ว');
    } catch (error) { toast(error.name === 'AbortError' || error instanceof TypeError ? 'ยังยืนยันผลการเพิ่มไม่ได้ กรุณาดูตะกร้าก่อนลองเพิ่มอีกครั้ง' : error.message || 'เชื่อมต่อไม่ได้ กรุณาลองใหม่', true); }
    finally { clearTimeout(timeout); delete form.dataset.submitting; button.disabled = false; button.textContent = label; finish(); }
  }));
  document.querySelectorAll('[data-remove-line]').forEach(button => button.addEventListener('click', () => { button.form.querySelector('[name="quantity"]').value = '0'; }));
  function lockSubmit(form,event,label) {
    if (form.dataset.submitting === 'true') { event.preventDefault(); return; }
    const button = form.querySelector('button[type="submit"]'); if (!button || button.hasAttribute('data-permanent-disabled')) { event.preventDefault(); return; }
    form.dataset.submitting = 'true'; button.dataset.idleLabel = button.textContent; button.disabled = true; button.textContent = label;
  }
  document.querySelectorAll('[data-checkout]').forEach(form => form.addEventListener('submit', event => { if (form.checkValidity()) lockSubmit(form,event,'กำลังส่งออเดอร์…'); }));
  document.querySelectorAll('[data-slip-upload]').forEach(form => form.addEventListener('submit', event => {
    const input = form.querySelector('input[type=file]'); const file = input.files[0];
    if (file && (file.size > 5 * 1024 * 1024 || (file.type && !['image/jpeg','image/png','image/webp'].includes(file.type)))) {
      event.preventDefault(); toast('กรุณาเลือกภาพ JPG, PNG หรือ WebP ขนาดไม่เกิน 5 MB', true); input.focus(); return;
    }
    if (form.checkValidity()) lockSubmit(form,event,'กำลังส่งสลิป…');
  }));
  const printDetails = new Map();
  window.addEventListener('beforeprint', () => { document.querySelectorAll('details[data-print-expand]').forEach(detail => { if (!printDetails.has(detail)) printDetails.set(detail,detail.open); detail.open=true; }); });
  window.addEventListener('afterprint', () => { printDetails.forEach((open,detail) => { detail.open=open; }); printDetails.clear(); });
  document.querySelectorAll('[data-print]').forEach(button => button.addEventListener('click', () => window.print()));
  window.addEventListener('pageshow', () => {
    document.querySelectorAll('[data-checkout],[data-slip-upload]').forEach(form => {
      delete form.dataset.submitting;
      form.querySelectorAll('button[type=submit]:not([data-permanent-disabled])').forEach(button => { button.disabled=false; if (button.dataset.idleLabel) { button.textContent=button.dataset.idleLabel; delete button.dataset.idleLabel; } });
    });
  });
})();
