"""Browser-owned public quotes: no keys, Python polling, or chart dependencies."""

import streamlit.components.v1 as components

LIVE_PRICES_HTML = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box}body{margin:0;line-height:1.3;color:#191f28;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.market{display:grid;grid-template-columns:minmax(0,1fr) minmax(125px,1fr);gap:16px;align-items:center;background:linear-gradient(135deg,#fff,#f9fbff);border:1px solid #e7ecf3;border-radius:18px;padding:13px 17px;margin:0 0 10px;min-height:124px}
.name{font-size:12px;color:#66758b}.name b{color:#191f28;margin-right:8px;font-size:14px}.price{line-height:1.15;font-size:clamp(22px,3vw,32px);font-weight:750;letter-spacing:-1px;font-variant-numeric:tabular-nums;margin:7px 0 4px;white-space:nowrap}.price small{font-size:11px;letter-spacing:0;color:#66758b;font-weight:500;margin-left:5px}
.change{font-size:12px;min-height:15px;color:#66758b}.status{font-size:11px;margin-top:7px;color:#66758b}.dot{display:inline-block;width:6px;height:6px;background:#98a5b5;border-radius:50%;margin-right:5px}.fresh .dot{background:#10a878}.stale .price{color:#8793a4}.plot{min-width:0;position:relative}canvas{width:100%;height:72px;display:block;touch-action:pan-y}.range{display:flex;justify-content:space-between;font-size:10px;color:#66758b;margin-top:4px}.empty{position:absolute;inset:20px 0 auto;text-align:center;font-size:11px;color:#8793a4}
@media(max-width:450px){.market{padding:11px 12px;gap:9px;grid-template-columns:minmax(0,1.2fr) minmax(100px,1fr)}.name b{font-size:13px}.name{font-size:10px}.price{font-size:clamp(18px,5.3vw,23px)}.price small{font-size:10px}.status{font-size:10px}}
</style></head><body>
<section class="market stale" id="binance" aria-label="바이낸스 실시간 가격">
<div><div class="name"><b>Binance</b>BTC / USDT</div><div class="price"><span>—</span><small>USDT</small></div><div class="change">변동 정보 대기</div><div class="status"><i class="dot"></i><span>연결 중…</span></div></div>
<div class="plot"><canvas role="img" aria-label="바이낸스 최근 1시간 가격 그래프"></canvas><div class="empty">가격을 기다리고 있어요</div><div class="range"><span>최근 1시간</span><span>지금</span></div></div>
</section>
<section class="market stale" id="upbit" aria-label="업비트 실시간 가격">
<div><div class="name"><b>Upbit</b>KRW-BTC</div><div class="price"><span>—</span><small>KRW</small></div><div class="change">변동 정보 대기</div><div class="status"><i class="dot"></i><span>연결 중…</span></div></div>
<div class="plot"><canvas role="img" aria-label="업비트 최근 1시간 가격 그래프"></canvas><div class="empty">가격을 기다리고 있어요</div><div class="range"><span>최근 1시간</span><span>지금</span></div></div>
</section>
<script>
(() => {
  'use strict';
  const MAX_POINTS = 61, STALE_MS = 15000, DRAW_MS = 250;
  const configs = [
    {id:'binance', symbol:'BTCUSDT', decimals:2, changeLabel:'24시간', restGap:1000,
     socket:'wss://data-stream.binance.vision/ws/btcusdt@ticker',
     ticker:'https://data-api.binance.vision/api/v3/ticker/24hr?symbol=BTCUSDT',
     history:'https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1m&limit=60'},
    {id:'upbit', symbol:'KRW-BTC', decimals:0, changeLabel:'전일 대비', restGap:11000,
     socket:'wss://api.upbit.com/websocket/v1',
     ticker:'https://api.upbit.com/v1/ticker?markets=KRW-BTC',
     history:'https://api.upbit.com/v1/candles/minutes/1?market=KRW-BTC&count=60'}
  ];
  let disposed = false, paintTimer = null;
  const states = configs.map(config => ({...config, el:document.getElementById(config.id), points:[],
    socketRef:null, retryTimer:null, retries:0, connectedAt:0, lastRx:0, lastEvent:0,
    lastPoll:0, lastWs:0, historyAt:0, transport:'', price:null, change:null, pending:false,
    loadingHistory:false, historyReady:false, historyRetryAt:0, historyFailures:0, nextRestAt:0, storageAt:0, controllers:new Set(), dirty:true}));
  const validNumber = n => typeof n === 'number' && Number.isFinite(n);
  const timeFormat = new Intl.DateTimeFormat('en-GB', {hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23',timeZone:'Asia/Seoul'});
  const clock = t => timeFormat.format(new Date(t));
  const storageKey = s => 'btc-live-history-v2-'+s.id;
  function restore(s) {
    try {
      const cached=JSON.parse(sessionStorage.getItem(storageKey(s)));
      if (!cached || Date.now()-cached.at>60000 || cached.at>Date.now()) return;
      s.points=cached.points.filter(p=>Array.isArray(p) && validNumber(p[0]) && validNumber(p[1]) &&
        p[1]>0 && p[0]<=Date.now() && p[0]>=Date.now()-3660000).slice(-MAX_POINTS);
      s.historyReady=s.points.length>=2;
      if (s.historyReady) { s.historyAt=cached.at; s.dirty=true; }
    } catch (_) { /* Storage can be disabled in an embedded or private browser. */ }
  }
  function persist(s) {
    if (!s.historyReady || Date.now()-s.storageAt<5000) return;
    try { sessionStorage.setItem(storageKey(s),JSON.stringify({at:Date.now(),points:s.points})); s.storageAt=Date.now(); }
    catch (_) { /* A full/disabled browser cache cannot stop live prices. */ }
  }
  function reserveRest(s) {
    if (Date.now()<s.nextRestAt) return false;
    s.nextRestAt=Date.now()+s.restGap;
    return true;
  }
  function fresh(s) {
    return s.lastRx && Date.now()-s.lastRx < STALE_MS && Date.now()-s.lastEvent < STALE_MS;
  }
  function schedulePaint() {
    if (!paintTimer && !disposed && !document.hidden) paintTimer = setTimeout(() => {
      paintTimer = null;
      for (const s of states) {
        const live = fresh(s);
        s.el.className = 'market ' + (live ? 'fresh' : 'stale');
        s.el.dataset.transport = s.transport;
        s.el.querySelector('.status span').textContent = s.price === null
          ? (s.retries ? '연결 지연 · 재시도 중' : '연결 중…')
          : (s.transport === 'history' ? '최근 분봉' : live ? (s.transport === 'ws' ? '실시간' : (Math.max(10,s.restGap/1000)+'초 조회')) : '수신 지연 · 마지막 가격') + ' · ' + clock(s.lastEvent);
        if (s.dirty) {
          if (s.price !== null) {
    s.el.querySelector('.price span').textContent=s.price.toLocaleString('en-US', {
      minimumFractionDigits:s.decimals, maximumFractionDigits:s.decimals});
    const delta=s.el.querySelector('.change');
    delta.textContent=s.change === null ? s.changeLabel+' 변동 정보 없음' :
      `${s.changeLabel} ${s.change >= 0 ? '+' : ''}${s.change.toFixed(2)}%`;
    delta.style.color=s.change === null ? '#66758b' : s.change >= 0 ? '#09845c' : '#d63851';
          }
          draw(s); persist(s); s.dirty=false;
        }
      }
    }, DRAW_MS);
  }
  function addPoint(s, time, price) {
    const minute = Math.floor(time/60000)*60000;
    const last = s.points[s.points.length-1];
    if (last && last[0] === minute) last[1]=price;
    else if (!last || minute > last[0]) s.points.push([minute,price]);
    s.points=s.points.filter(p => p[0] >= minute-3600000).slice(-MAX_POINTS);
    s.dirty=true;
  }
  function accept(s, raw, transport) {
    const item = Array.isArray(raw) ? raw[0] : raw;
    if (!item || typeof item !== 'object') return;
    const binance = s.id === 'binance';
    if ((binance ? item.s || item.symbol : item.code || item.market) !== s.symbol) return;
    const price = binance ? Number(item.c ?? item.lastPrice) : item.trade_price;
    const change = binance ? Number(item.P ?? item.priceChangePercent) : item.signed_change_rate*100;
    const time = binance ? item.E ?? item.closeTime : item.timestamp;
    if (!validNumber(price) || price <= 0 || !validNumber(time) || time <= 0 ||
        time < s.lastEvent || time > Date.now()+60000) return;
    s.price=price; s.change=validNumber(change) ? change : null;
    s.lastEvent=time; s.lastRx=Date.now(); s.transport=transport;
    if (transport === 'ws') { s.lastWs=Date.now(); if (fresh(s)) s.retries=0; }
    addPoint(s,time,price); schedulePaint();
  }
  function draw(s) {
    const canvas=s.el.querySelector('canvas'), width=canvas.clientWidth, height=72;
    const scale=Math.min(window.devicePixelRatio || 1,2);
    if (canvas.width!==Math.round(width*scale) || canvas.height!==height*scale) {
      canvas.width=Math.round(width*scale); canvas.height=height*scale;
    }
    const ctx=canvas.getContext('2d'); ctx.setTransform(scale,0,0,scale,0,0); ctx.clearRect(0,0,width,height);
    canvas.dataset.samples=String(s.points.length);
    canvas.dataset.span=String(s.points.length>1 ? s.points[s.points.length-1][0]-s.points[0][0] : 0);
    s.el.dataset.history=s.historyReady ? 'ready' : s.historyFailures ? 'retry' : 'loading';
    s.el.querySelector('.range span:last-child').textContent=s.historyReady ? '지금' : s.historyFailures ? '이력 재시도' : '이력 조회 중';
    if (s.points.length) s.el.querySelector('.range span').textContent=clock(s.points[0][0]).slice(0,5)+' KST';
    s.el.querySelector('.empty').hidden=s.points.length>0;
    if (!s.points.length || !width) return;
    const values=s.points.map(p=>p[1]), low=Math.min(...values), high=Math.max(...values);
    const span=high-low || Math.max(1,low*0.0001), pad=6;
    const end=s.points[s.points.length-1][0], start=end-3600000;
    const xy=s.points.map(p=>[pad+(p[0]-start)/3600000*(width-2*pad), height-pad-(p[1]-low)/span*(height-2*pad)]);
    const color=values[values.length-1] >= values[0] ? '#10a878' : '#e94b65';
    ctx.beginPath(); xy.forEach(([x,y],i)=>i ? ctx.lineTo(x,y) : ctx.moveTo(x,y));
    ctx.strokeStyle=color; ctx.lineWidth=2; ctx.lineJoin='round'; ctx.stroke();
    ctx.lineTo(xy[xy.length-1][0],height); ctx.lineTo(xy[0][0],height); ctx.closePath();
    const gradient=ctx.createLinearGradient(0,0,0,height);
    gradient.addColorStop(0,color+'25'); gradient.addColorStop(1,color+'00');
    ctx.fillStyle=gradient; ctx.fill();
    const [x,y]=xy[xy.length-1]; ctx.beginPath(); ctx.arc(x,y,3,0,Math.PI*2); ctx.fillStyle=color; ctx.fill();
    canvas.setAttribute('aria-label', `${s.id} 최근 1시간 가격, ${values[values.length-1].toLocaleString('en-US')}`);
  }
  async function json(s,url) {
    const controller=new AbortController(); s.controllers.add(controller);
    const timeout=setTimeout(()=>controller.abort(),4000);
    try {
      const response=await fetch(url,{signal:controller.signal,credentials:'omit',cache:'no-store'});
      if (!response.ok) {
        if (response.status===429 || response.status===418) {
          const seconds=Number(response.headers.get('Retry-After'));
          s.nextRestAt=Date.now()+Math.max(s.restGap,Number.isFinite(seconds) ? Math.min(60000,seconds*1000) : 11000);
        }
        throw new Error(`HTTP ${response.status}`);
      }
      return await response.json();
    } finally { clearTimeout(timeout); s.controllers.delete(controller); }
  }
  async function history(s) {
    if (s.loadingHistory || disposed || document.hidden || Date.now()<s.historyRetryAt ||
        (s.historyReady && Date.now()-s.historyAt<60000) || !reserveRest(s)) return;
    s.loadingHistory=true;
    try {
      const rows=await json(s,s.history);
      if (!Array.isArray(rows) || disposed || document.hidden) return;
      const points=rows.map(row=>s.id==='binance' ? [Number(row[0]),Number(row[4])] :
        [Date.parse(/Z$|[+-]\d{2}:\d{2}$/.test(row.candle_date_time_utc) ? row.candle_date_time_utc : row.candle_date_time_utc+'Z'),row.trade_price]).filter(([t,p])=>
        validNumber(t) && validNumber(p) && p>0 && t<=Date.now() && t>=Date.now()-3660000);
      // A slower history response must never overwrite a newer streaming price.
      const merged=new Map([...points,...s.points].map(p=>[p[0],p[1]]));
      s.points=[...merged].sort((a,b)=>a[0]-b[0]).filter(p=>p[0]>=Date.now()-3660000).slice(-MAX_POINTS);
      if (!points.length) throw new Error('Empty candle history');
      s.historyReady=true; s.historyAt=Date.now(); s.historyFailures=0;
      if (s.price===null && s.points.length) {
        const last=s.points[s.points.length-1];
        s.price=last[1]; s.lastEvent=last[0]; s.transport='history';
      }
      s.dirty=true; persist(s); schedulePaint();
    } catch (_) {
      s.historyFailures++; s.historyRetryAt=Date.now()+Math.min(60000,11000*2**Math.min(s.historyFailures,3));
      s.dirty=true; schedulePaint();
    }
    finally { s.loadingHistory=false; }
  }
  async function poll(s) {
    if (s.pending || disposed || document.hidden || (s.transport==='ws' && fresh(s)) ||
        Date.now()-s.lastPoll<Math.max(10000,s.restGap) || !reserveRest(s)) return;
    s.pending=true; s.lastPoll=Date.now();
    try { const raw=await json(s,s.ticker); if (!disposed && !document.hidden) accept(s,raw,'rest'); }
    catch (_) { s.retries=Math.max(1,s.retries); schedulePaint(); }
    finally { s.pending=false; }
  }
  function reconnect(s) {
    if (disposed || document.hidden || s.retryTimer) return;
    const delay=Math.min(30000,(s.id==='upbit' ? 11000 : 1000)*2**Math.min(s.retries++,5));
    s.retryTimer=setTimeout(()=>{s.retryTimer=null; connect(s);},delay);
    schedulePaint();
  }
  function connect(s) {
    if (disposed || document.hidden || s.socketRef) return;
    let ws;
    try { ws=new WebSocket(s.socket); }
    catch (_) { reconnect(s); return; }
    s.socketRef=ws; s.connectedAt=Date.now(); ws.binaryType='arraybuffer';
    ws.onopen=()=>{
      if (s.id==='upbit') ws.send(JSON.stringify([
        {ticket:'btc-signal-lab-'+Math.random().toString(36).slice(2)},
        {type:'ticker',codes:[s.symbol],is_only_realtime:true}
      ]));
    };
    ws.onmessage=event=>{
      if (disposed || s.socketRef!==ws || document.hidden) return;
      try { accept(s,JSON.parse(typeof event.data==='string' ? event.data : new TextDecoder().decode(event.data)),'ws'); }
      catch (_) { /* Ignore malformed messages; never convert them to a price. */ }
    };
    ws.onerror=()=>ws.close();
    ws.onclose=()=>{
      if (s.socketRef!==ws) return;
      s.socketRef=null;
      if (s.transport==='ws') s.lastRx=0;
      reconnect(s); poll(s); schedulePaint();
    };
  }
  function stop(s) {
    clearTimeout(s.retryTimer); s.retryTimer=null;
    const ws=s.socketRef; s.socketRef=null; if (ws) ws.close();
    for (const controller of s.controllers) controller.abort();
    s.lastRx=0;
  }
  const heartbeat=setInterval(()=>{
    if (disposed || document.hidden) return;
    for (const s of states) {
      if (s.socketRef && Date.now()-Math.max(s.connectedAt,s.lastWs)>20000) s.socketRef.close();
      if (!s.historyReady) history(s);
      poll(s);
    }
    schedulePaint();
  },1000);
  document.addEventListener('visibilitychange',()=>{
    for (const s of states) {
      if (document.hidden) stop(s);
      else { history(s); connect(s); poll(s); }
    }
    schedulePaint();
  });
  const observer=new ResizeObserver(()=>{ for (const s of states) s.dirty=true; schedulePaint(); });
  observer.observe(document.body);
  window.addEventListener('pagehide',()=>{
    disposed=true; clearInterval(heartbeat); clearTimeout(paintTimer); observer.disconnect(); states.forEach(stop);
  });
  for (const s of states) { restore(s); history(s); connect(s); poll(s); }
  schedulePaint();
})();
</script></body></html>"""


def render_live_prices() -> None:
    """Keep a stable iframe outside analysis fragments so tab clicks keep sockets."""
    components.html(LIVE_PRICES_HTML, height=272, scrolling=False)
