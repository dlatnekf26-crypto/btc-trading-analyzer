/* Only install artwork and the disconnected page. Never cache live market data. */
'use strict';
const CACHE = 'crypto-signal-shell-v2';
const OFFLINE = '/app-assets/offline.html';
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll([
    OFFLINE, '/app-assets/icon-192.png', '/app-assets/icon-512.png'
  ])).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(
    keys.filter(key => key.startsWith('crypto-signal-shell-') && key !== CACHE).map(key => caches.delete(key))
  )).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  if(event.request.mode !== 'navigate' || new URL(event.request.url).origin !== self.location.origin) return;
  event.respondWith((async()=>{
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),12000);
    const fallback=async()=>await caches.match(OFFLINE)||new Response('연결을 확인한 뒤 다시 열어 주세요.',{status:503,headers:{'Content-Type':'text/plain; charset=utf-8'}});
    try{
      const response=await fetch(event.request,{signal:controller.signal});
      return [502,503,504].includes(response.status)?await fallback():response;
    }catch(_){return await fallback();}
    finally{clearTimeout(timer);}
  })());
});
