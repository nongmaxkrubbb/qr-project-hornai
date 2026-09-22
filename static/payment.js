(() => {
  'use strict';
  const configEl=document.getElementById('payment-config');if(!configEl)return;
  const config=JSON.parse(configEl.textContent);const expiry=Date.parse(config.expiresAt);
  if(!Number.isFinite(expiry)||['verifying','paid','refunded','refund_due'].includes(config.paymentStatus))return;
  const countdown=document.getElementById('payment-countdown');
  function expire(){
    const remaining=expiry-Date.now();
    if(remaining>0){if(countdown)countdown.textContent=`เหลือ ${Math.ceil(remaining/60000)} นาทีสำหรับส่งหลักฐาน`;return;}
    const active=document.getElementById('payment-active');
    if(active){active.hidden=true;active.querySelectorAll('input,button').forEach(input=>{input.disabled=true;});}
    document.getElementById('payment-expired').hidden=false;
  }
  expire();setInterval(expire,1000);document.addEventListener('visibilitychange',expire);
})();
