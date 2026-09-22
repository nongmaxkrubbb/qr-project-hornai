(() => {
  'use strict';
  const board=document.getElementById('kitchen-board'); if (!board) return;
  const connection=document.getElementById('kitchen-connection'); const refreshButton=document.getElementById('kitchen-refresh'); const soundButton=document.getElementById('kitchen-sound');
  const dialog=document.getElementById('slip-dialog'); const image=document.getElementById('slip-image');
  let timer,inFlight=false,failures=0,soundEnabled=false,audioContext=null,dirty=false,paused=false;
  let seenIds=new Set([...board.querySelectorAll('[data-order-id]')].map(card=>card.dataset.orderId));
  const boardUrl=new URL(board.dataset.boardUrl,location.origin); if (boardUrl.origin!==location.origin) return;
  function beep() { if (!soundEnabled || !audioContext) return; const oscillator=audioContext.createOscillator(); const gain=audioContext.createGain(); oscillator.connect(gain); gain.connect(audioContext.destination); oscillator.frequency.value=740; gain.gain.setValueAtTime(.08,audioContext.currentTime); gain.gain.exponentialRampToValueAtTime(.001,audioContext.currentTime+.35); oscillator.start(); oscillator.stop(audioContext.currentTime+.35); }
  function ages() {
    board.querySelectorAll('[data-created-at]').forEach(item => {
      const card=item.closest('[data-order-id]'); const status=card.dataset.orderStatus;
      const created=new Date(item.dataset.createdAt); if (Number.isNaN(created.getTime())) return;
      const requested=Date.parse(card.dataset.requestedFor); const now=Date.now();
      const started=Date.parse(card.dataset.startedAt); const ready=Date.parse(card.dataset.readyAt);
      const baseline=status==='preparing' && Number.isFinite(started) ? started : status==='ready' && Number.isFinite(ready) ? ready : created.getTime();
      const minutes=Math.max(0,Math.floor((now-baseline)/60000));
      const label=status==='preparing' ? 'ทำมา' : status==='ready' ? 'พร้อมรับมา' : 'รับมา';
      item.textContent=Number.isFinite(requested) && requested>now && ['pending_payment','waiting'].includes(status) ? 'รับออเดอร์ล่วงหน้าแล้ว' : `${label} ${minutes} นาที`;
      item.textContent+=` · รับเมื่อ ${created.toLocaleString('th-TH',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit',timeZone:board.dataset.timezone || 'Asia/Bangkok'})}`;
      item.classList.toggle('late',minutes>=30 && !(Number.isFinite(requested) && requested>now));
    });
  }
  function schedule() { clearTimeout(timer); if (!document.hidden) timer=setTimeout(()=>refresh(false),Math.min(60000,8000*2**Math.min(failures,3))); }
  function isEditing() { return dirty || dialog.open || (board.contains(document.activeElement) && document.activeElement.matches('input,textarea,select,button')) || !!board.querySelector('details[open]'); }
  async function refresh(manual) {
    if (inFlight) return;
    if (manual && isEditing()) { if (!window.confirm('มีข้อมูลที่ยังไม่ได้ส่ง ต้องการล้างข้อมูลที่กำลังแก้และโหลดคิวล่าสุดหรือไม่?')) { schedule(); return; } dirty=false; board.querySelectorAll('details[open]').forEach(detail=>{detail.open=false;}); if (dialog.open) dialog.close(); if (board.contains(document.activeElement)) document.activeElement.blur(); }
    if (isEditing()) { paused=true; connection.textContent='พักการอัปเดตระหว่างกรอกข้อมูลหรือเปิดรายละเอียด · ส่งฟอร์ม หรือกดอัปเดตตอนนี้เพื่อล้างข้อมูลและอัปเดตต่อ'; schedule(); return; }
    inFlight=true; paused=false; refreshButton.disabled=true; const controller=new AbortController(); const timeout=setTimeout(()=>controller.abort(),12000);
    try {
      const response=await fetch(boardUrl.href,{headers:{'Accept':'text/html','X-Requested-With':'XMLHttpRequest'},cache:'no-store',credentials:'same-origin',signal:controller.signal});
      if (!response.ok || response.redirected) throw new Error([401,403].includes(response.status)||response.redirected ? 'กรุณาเข้าสู่ระบบใหม่เพื่อดูคิวล่าสุด' : 'ยังเชื่อมต่อครัวไม่ได้ กำลังลองใหม่');
      const html=await response.text(); const parsed=new DOMParser().parseFromString(html,'text/html');
      if (!parsed.querySelector('.board')) throw new Error('ยังโหลดคิวล่าสุดไม่สำเร็จ กรุณารีเฟรชหน้า');
      if (manual && isEditing()) { if (!window.confirm('มีข้อมูลที่ยังไม่ได้ส่ง ต้องการล้างข้อมูลที่กำลังแก้และโหลดคิวล่าสุดหรือไม่?')) { schedule(); return; } dirty=false; board.querySelectorAll('details[open]').forEach(detail=>{detail.open=false;}); if (dialog.open) dialog.close(); if (board.contains(document.activeElement)) document.activeElement.blur(); }
    if (isEditing()) { paused=true; return; }
      const newIds=[...parsed.querySelectorAll('[data-order-id]')].map(card=>card.dataset.orderId); if (newIds.some(id=>!seenIds.has(id))) beep(); seenIds=new Set(newIds);
      const scroll={x:window.scrollX,y:window.scrollY}; board.replaceChildren(...[...parsed.body.childNodes].map(node=>document.importNode(node,true))); window.scrollTo(scroll.x,scroll.y); ages();
      failures=0; connection.classList.remove('stale'); connection.textContent=`อัปเดตล่าสุด ${new Date().toLocaleTimeString('th-TH',{hour:'2-digit',minute:'2-digit',second:'2-digit'})} · ทุกประมาณ 8 วินาที`;
    } catch(error) { failures++; connection.classList.add('stale'); connection.textContent=navigator.onLine ? (error.name==='AbortError'?'ครัวตอบกลับช้า ข้อมูลอาจไม่เป็นปัจจุบัน':error.message) : 'ออฟไลน์ · ข้อมูลอาจไม่เป็นปัจจุบัน'; }
    finally { clearTimeout(timeout);inFlight=false;refreshButton.disabled=false;schedule(); }
  }
  board.addEventListener('input',()=>{dirty=true;});
  board.addEventListener('submit',()=>{dirty=false;});
  board.addEventListener('click',event=> { const button=event.target.closest('[data-slip-url]'); if (!button) return; const url=new URL(button.dataset.slipUrl,location.origin);if(url.origin!==location.origin || typeof dialog.showModal!=='function')return;event.preventDefault();document.getElementById('slip-error').hidden=true;image.src=url.href;document.getElementById('slip-open').href=url.href;dialog.showModal(); });
  image.addEventListener('error',()=>{document.getElementById('slip-error').hidden=false;});
  document.querySelector('[data-close-slip]').addEventListener('click',()=>dialog.close()); dialog.addEventListener('close',()=>{image.removeAttribute('src');if(!dirty)refresh(false);});
  soundButton.addEventListener('click',async()=>{soundEnabled=!soundEnabled;if(soundEnabled){try{audioContext=audioContext||new (window.AudioContext||window.webkitAudioContext)();await audioContext.resume();beep();}catch(_){soundEnabled=false;window.showToast('เบราว์เซอร์นี้เปิดเสียงไม่ได้',true);}}soundButton.setAttribute('aria-pressed',String(soundEnabled));soundButton.textContent=soundEnabled?'ปิดเสียงออเดอร์ใหม่':'เปิดเสียงออเดอร์ใหม่';});
  refreshButton.addEventListener('click',()=>{clearTimeout(timer);refresh(true);});
  document.addEventListener('visibilitychange',()=>{clearTimeout(timer);if(!document.hidden)refresh(false);});window.addEventListener('online',()=>refresh(false));
  board.addEventListener('toggle',()=>{if(paused&&!isEditing())refresh(false);},true);
  ages();setInterval(ages,15000);refresh(false);
})();
