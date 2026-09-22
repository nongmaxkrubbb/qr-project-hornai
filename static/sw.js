'use strict';
self.addEventListener('push',event => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (_) { data = {}; }
  let target = '/history';
  try { const url = new URL(data.url || data.data?.url || target,self.location.origin); if (url.origin === self.location.origin && ['http:','https:'].includes(url.protocol)) target=url.href; } catch (_) { /* Safe same-origin fallback. */ }
  event.waitUntil(self.registration.showNotification(data.title || 'อาหารพร้อมรับแล้ว',{
    body:data.body || 'เปิดดูออเดอร์เพื่อเช็กสถานะและจุดรับอาหาร',icon:'/static/icon.svg',badge:'/static/icon.svg',tag:data.tag || 'queue-order',data:{url:target}
  }));
});
self.addEventListener('notificationclick',event => {
  event.notification.close();
  let target = new URL('/history',self.location.origin).href;
  try { const url=new URL(event.notification.data?.url || target,self.location.origin); if (url.origin===self.location.origin && ['http:','https:'].includes(url.protocol)) target=url.href; } catch (_) { /* Keep fallback. */ }
  event.waitUntil(self.clients.matchAll({type:'window',includeUncontrolled:true}).then(async clients => {
    for (const client of clients) { if (client.url === target && 'focus' in client) return client.focus(); }
    if (self.clients.openWindow) return self.clients.openWindow(target);
  }));
});
// No fetch handler: order pages, tokens, receipts and APIs are never cached here.
