"""Browser-owned public quotes: no keys, Python polling, or chart dependencies."""

import streamlit.components.v1 as components

LIVE_PRICES_HTML = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box}body{margin:0;line-height:1.3;color:#191f28;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.dashboard{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.market{min-width:0;border:1px solid #e7ecf3;border-radius:18px;padding:12px 15px;background:linear-gradient(135deg,#fff,#f9fbff)}
.name{font-size:11px;color:#66758b}.name b{color:#191f28;margin-right:7px;font-size:14px}
.price{font-size:27px;font-weight:750;letter-spacing:-.8px;font-variant-numeric:tabular-nums;line-height:1.15;margin:6px 0 4px;white-space:nowrap}.price small{font-size:10px;letter-spacing:0;color:#66758b;font-weight:500;margin-left:4px}
.change{font-size:11px;min-height:14px;color:#66758b}.status{font-size:10px;margin-top:5px;color:#66758b;min-height:13px}.dot{display:inline-block;width:6px;height:6px;background:#98a5b5;border-radius:50%;margin-right:5px}.fresh .dot{background:#10a878}.reference .dot{background:#3182f6}.stale .price{color:#8793a4}
.plot{min-width:0;position:relative;margin-top:5px}canvas{width:100%;height:42px;display:block;touch-action:pan-y}.range{display:flex;justify-content:space-between;gap:3px;font-size:9px;color:#66758b;margin-top:2px}.empty{position:absolute;inset:12px 0 auto;text-align:center;font-size:10px;color:#8793a4}
.aux{min-height:114px}.aux .change{font-size:10px;min-height:26px}.note{margin:7px 2px 0;color:#7b8797;font-size:10px;line-height:1.45}
@media(max-width:450px){.market{padding:11px 10px;border-radius:16px}.name b{font-size:12px}.name{font-size:10px}.price{font-size:clamp(17px,5.2vw,23px)}.status{font-size:9px}.aux .change{font-size:9px}.range{font-size:8px}}
</style></head><body><div class="dashboard">
<section class="market crypto stale" id="binance" aria-label="비트코인 실시간 가격">
<div class="name"><b>BTC</b>Binance</div><div class="price"><span>—</span><small>USDT</small></div><div class="change">24시간 변동 대기</div><div class="status"><i class="dot"></i><span>연결 중…</span></div>
<div class="plot"><canvas role="img" aria-label="비트코인 최근 1시간 가격 그래프"></canvas><div class="empty">가격을 기다리고 있어요</div><div class="range"><span>최근 1시간</span><span>지금</span></div></div>
</section>
<section class="market crypto stale" id="ethereum" aria-label="이더리움 실시간 가격">
<div class="name"><b>ETH</b>Binance</div><div class="price"><span>—</span><small>USDT</small></div><div class="change">24시간 변동 대기</div><div class="status"><i class="dot"></i><span>연결 중…</span></div>
<div class="plot"><canvas role="img" aria-label="이더리움 최근 1시간 가격 그래프"></canvas><div class="empty">가격을 기다리고 있어요</div><div class="range"><span>최근 1시간</span><span>지금</span></div></div>
</section>
<section class="market aux stale" id="forex" aria-label="미국 달러 원화 환율">
<div class="name"><b>원·달러 환율</b>USD/KRW</div><div class="price"><span>—</span><small>원</small></div><div class="change">1 USD당 원화 · 시장 시세 대기</div><div class="status"><i class="dot"></i><span>환율 연결 중…</span></div>
</section>
<section class="market aux stale" id="premium" aria-label="비트코인 김치프리미엄">
<div class="name"><b>김치프리미엄</b>BTC</div><div class="price"><span>—</span><small>%</small></div><div class="change">Upbit / Binance · 환산 반영</div><div class="status"><i class="dot"></i><span>계산 자료 대기</span></div>
</section>
</div><p class="note">환율은 시장 시세 우선 · 고시/일별 대체값은 구분해요. 김프는 USDT/USD 환산 포함.</p>
<script>
(() => {
  'use strict';
  // Delegate touch inspection to the existing parent charts. No extra iframe,
  // data requests or Streamlit events; passive listeners preserve page scrolling.
  const disposeChartTouch=(()=>{
    let doc, root;
    try {root=window.parent; doc=root.document;} catch (_) {return ()=>{};}
    let active=null, lastChart=null, pending=null, frame=null, painted=0;
    function clear() {
      if (frame!==null) root.cancelAnimationFrame(frame);
      frame=null; pending=null; active=null;
      if (lastChart?.isConnected) root.Plotly?.Fx?.unhover(lastChart);
      lastChart=null;
    }
    function show(point) {
      if (!point.chart.isConnected || !root.Plotly?.Fx) return;
      const bounds=point.rect.getBoundingClientRect();
      const pixel=Math.max(0,Math.min(bounds.width,point.x-bounds.left));
      const vertical=Math.max(0,Math.min(bounds.height,point.y-bounds.top));
      // Use the same Plotly tooltip as the mouse, with a real axis coordinate.
      root.Plotly.Fx.hover(point.chart,{xval:point.axis.p2c(pixel),yval:point.yaxis.p2c(vertical)},[point.subplot]);
      lastChart=point.chart;
    }
    function paint(now) {
      if (now-painted<33) {frame=root.requestAnimationFrame(paint); return;}
      frame=null; painted=now;
      if (pending) {const point=pending; pending=null; show(point);}
    }
    function start(event) {
      clear();
      const rect=event.target.closest?.('.nsewdrag'), chart=rect?.closest('.js-plotly-plot');
      if (!chart || chart._fullLayout?.dragmode!==false || !root.Plotly?.Fx) return;
      const subplot=Object.keys(chart._fullLayout._plots || {}).find(key=>rect.parentElement.classList.contains(key));
      const axis=chart._fullLayout._plots[subplot]?.xaxis;
      const yaxis=chart._fullLayout._plots[subplot]?.yaxis;
      if (!axis || !yaxis || !event.touches.length) return;
      // Stop Plotly's native touch-drag handler from setting _dragging, which
      // suppresses hover until release. Do not prevent the browser's pan gesture.
      event.stopPropagation();
      if (event.touches.length!==1) return;
      const touch=event.touches[0];
      active={chart,rect,axis,yaxis,subplot,x:touch.clientX,y:touch.clientY};
      show(active);
    }
    function move(event) {
      if (!active) return;
      event.stopPropagation();
      if (event.touches.length!==1) {clear(); return;}
      const touch=event.touches[0], dx=touch.clientX-active.x, dy=touch.clientY-active.y;
      if (Math.abs(dy)>8 && Math.abs(dy)>Math.abs(dx)) {clear(); return;}
      pending={...active,x:touch.clientX,y:touch.clientY};
      if (frame===null) frame=root.requestAnimationFrame(paint);
    }
    function end(event) {
      if (!active) return;
      event.stopPropagation();
      if (pending) show(pending);
      if (frame!==null) root.cancelAnimationFrame(frame);
      frame=null; pending=null; active=null;
    }
    const options={capture:true,passive:true};
    doc.addEventListener('touchstart',start,options);
    doc.addEventListener('touchmove',move,options);
    doc.addEventListener('touchend',end,options);
    doc.addEventListener('touchcancel',clear,options);
    return ()=>{
      clear();
      doc.removeEventListener('touchstart',start,true);
      doc.removeEventListener('touchmove',move,true);
      doc.removeEventListener('touchend',end,true);
      doc.removeEventListener('touchcancel',clear,true);
    };
  })();
  const MAX_POINTS = 61, STALE_MS = 15000, DRAW_MS = 50;
  const configs = [
    {id:'binance', market:'binance', symbol:'BTCUSDT', decimals:2, changeLabel:'24시간', restGap:1000,
     socket:'wss://data-stream.binance.vision/stream?streams=btcusdt@aggTrade/ethusdt@aggTrade/btcusdt@ticker/ethusdt@ticker',
     history:'https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1m&limit=60'},
    {id:'ethereum', market:'binance', symbol:'ETHUSDT', decimals:2, changeLabel:'24시간', restGap:1000,
     history:'https://data-api.binance.vision/api/v3/klines?symbol=ETHUSDT&interval=1m&limit=60'},
    {id:'upbit', market:'upbit', symbol:'KRW-BTC', decimals:0, changeLabel:'전일 대비', restGap:11000,
     socket:'wss://api.upbit.com/websocket/v1',
     ticker:'https://api.upbit.com/v1/ticker?markets=KRW-BTC', history:null}
  ];
  let disposed = false, paintTimer = null;
  const states = configs.map(config => ({...config, el:document.getElementById(config.id), points:[],
    socketRef:null, retryTimer:null, retries:0, connectedAt:0, lastRx:0, lastEvent:0,
    lastPoll:0, lastWs:0, historyAt:0, transport:'', price:null, change:null, pending:false,
    loadingHistory:false, historyReady:false, historyRetryAt:0, historyFailures:0, nextRestAt:0, storageAt:0, controllers:new Set(), dirty:true}));
  const binanceRequest={pending:false,lastPoll:0,restGap:1000,nextRestAt:0,controllers:new Set()};
  const validNumber = n => typeof n === 'number' && Number.isFinite(n);
  const timeFormat = new Intl.DateTimeFormat('en-GB', {hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23',timeZone:'Asia/Seoul'});
  const clock = t => timeFormat.format(new Date(t));
  const storageKey = s => 'btc-live-history-v2-'+s.id;
  function restore(s) {
    if (!s.history) return;
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
        if (!s.el) continue;
        const live = fresh(s);
        s.el.className = 'market crypto ' + (live ? 'fresh' : 'stale');
        s.el.dataset.transport = s.transport;
        s.el.querySelector('.status span').textContent = s.price === null
          ? (s.retries ? '연결 지연 · 재시도 중' : '연결 중…')
          : (s.transport === 'history' ? '최근 분봉' : live ? (s.transport === 'ws' ? '실시간' : (Math.max(5,s.restGap/1000)+'초 조회')) : '수신 지연 · 마지막 가격') + ' · ' + clock(s.lastEvent);
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
      paintAux();
      paintMacro();
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
    const binance = s.market === 'binance';
    if ((binance ? item.s || item.symbol : item.code || item.market) !== s.symbol) return;
    const price = binance ? Number(item.e==='aggTrade' ? item.p : item.c ?? item.lastPrice) : item.trade_price;
    const change = binance ? Number(item.P ?? item.priceChangePercent) : item.signed_change_rate*100;
    const time = binance ? item.E ?? item.closeTime : item.timestamp;
    if (!validNumber(price) || price <= 0 || !validNumber(time) || time <= 0 ||
        time < s.lastEvent || time > Date.now()+60000) return;
    s.price=price;
    if (validNumber(change)) s.change=change;
    s.lastEvent=time; s.lastRx=Date.now(); s.transport=transport;
    if (transport === 'ws') { s.lastWs=Date.now(); if (fresh(s)) s.retries=0; }
    if (s.history) addPoint(s,time,price);
    schedulePaint();
  }
  function draw(s) {
    const canvas=s.el.querySelector('canvas'), width=canvas.clientWidth, height=42;
    const scale=Math.min(window.devicePixelRatio || 1,2);
    if (canvas.width!==Math.round(width*scale) || canvas.height!==Math.round(height*scale)) {
      canvas.width=Math.round(width*scale); canvas.height=Math.round(height*scale);
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
    if (!s.history || s.loadingHistory || disposed || document.hidden || Date.now()<s.historyRetryAt ||
        (s.historyReady && Date.now()-s.historyAt<60000) || !reserveRest(s)) return;
    s.loadingHistory=true;
    try {
      const rows=await json(s,s.history);
      if (!Array.isArray(rows) || disposed || document.hidden) return;
      const points=rows.map(row=>s.market==='binance' ? [Number(row[0]),Number(row[4])] :
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
    if (s.market==='binance') { pollBinance(); return; }
    if (s.pending || disposed || document.hidden || (s.transport==='ws' && fresh(s)) ||
        Date.now()-s.lastPoll<Math.max(10000,s.restGap) || !reserveRest(s)) return;
    s.pending=true; s.lastPoll=Date.now();
    try { const raw=await json(s,s.ticker); if (!disposed && !document.hidden) accept(s,raw,'rest'); }
    catch (_) { s.retries=Math.max(1,s.retries); schedulePaint(); }
    finally { s.pending=false; }
  }
  async function pollBinance() {
    const s=binanceRequest, group=states.slice(0,2);
    if (s.pending || disposed || document.hidden || group.every(x=>x.transport==='ws' && fresh(x)) ||
        Date.now()-s.lastPoll<5000 || !reserveRest(s)) return;
    s.pending=true; s.lastPoll=Date.now();
    try {
      const rows=await json(s,'https://data-api.binance.vision/api/v3/ticker/24hr?symbols='+encodeURIComponent('["BTCUSDT","ETHUSDT"]'));
      if (!Array.isArray(rows) || disposed || document.hidden) return;
      // A slow REST response cannot displace a healthy, more recent WebSocket.
      for (const item of rows) for (const market of group) {
        if (!(market.transport==='ws' && fresh(market))) accept(market,item,'rest');
      }
    } catch (_) { group.forEach(x=>x.retries=Math.max(1,x.retries)); schedulePaint(); }
    finally {s.pending=false;}
  }
  function reconnect(s) {
    if (disposed || document.hidden || s.retryTimer) return;
    const delay=Math.min(30000,(s.id==='upbit' ? 11000 : 1000)*2**Math.min(s.retries++,5));
    s.retryTimer=setTimeout(()=>{s.retryTimer=null; connect(s);},delay);
    schedulePaint();
  }
  function connect(s) {
    if (s.id==='ethereum' || disposed || document.hidden || s.socketRef) return;
    const group=s.market==='binance' ? states.slice(0,2) : [s];
    let ws;
    try { ws=new WebSocket(s.socket); }
    catch (_) { reconnect(s); return; }
    for (const market of group) {market.socketRef=ws; market.connectedAt=Date.now();}
    ws.binaryType='arraybuffer';
    ws.onopen=()=>{
      if (s.id==='upbit') ws.send(JSON.stringify([
        {ticket:'btc-signal-lab-'+Math.random().toString(36).slice(2)},
        {type:'ticker',codes:[s.symbol],is_only_realtime:true}
      ]));
    };
    ws.onmessage=event=>{
      if (disposed || s.socketRef!==ws || document.hidden) return;
      try {
        const packet=JSON.parse(typeof event.data==='string' ? event.data : new TextDecoder().decode(event.data));
        for (const market of group) accept(market,packet.data ?? packet,'ws');
      }
      catch (_) { /* Ignore malformed messages; never convert them to a price. */ }
    };
    ws.onerror=()=>ws.close();
    ws.onclose=()=>{
      if (s.socketRef!==ws) return;
      for (const market of group) {
        market.socketRef=null;
        if (market.transport==='ws') market.lastRx=0;
      }
      reconnect(s); poll(s); schedulePaint();
    };
  }
  function stop(s) {
    clearTimeout(s.retryTimer); s.retryTimer=null;
    const ws=s.socketRef; s.socketRef=null; if (ws) ws.close();
    for (const controller of s.controllers) controller.abort();
    s.lastRx=0;
  }
  const rateState=id=>({id,rate:null,asOf:0,fetched:0,source:'',daily:false,market:false,pending:false,nextPoll:0,
    restGap:60000,nextRestAt:0,controllers:new Set()});
  const fx=rateState('fx'), peg=rateState('peg'), rates=[fx,peg];
  const fxEl=document.getElementById('forex'), premiumEl=document.getElementById('premium');
  let lastPremium=null;
  const dayFormat=new Intl.DateTimeFormat('ko-KR',{month:'2-digit',day:'2-digit',timeZone:'Asia/Seoul'});
  const validRate=s=>validNumber(s.rate) && s.rate>0 && validNumber(s.asOf) && validNumber(s.fetched) && s.asOf>0 && s.asOf<=Date.now()+60000 &&
    Date.now()-s.asOf<=(s.id==='fx' ? (s.market ? 180000 : 96*3600000) : 300000) && Date.now()-s.fetched<=180000;
  function restoreRates() {
    for (const s of rates) {
      try {
        const saved=JSON.parse(sessionStorage.getItem('btc-reference-v1-'+s.id));
        if (!saved || !validNumber(saved.fetched) || saved.fetched>Date.now() || Date.now()-saved.fetched>60000) continue;
        const value={...s,rate:saved.rate,asOf:saved.asOf,fetched:saved.fetched,source:saved.source,daily:saved.daily,market:saved.market===true};
        if (!validRate(value) || !['은행 고시','ECB 일별','Coinbase','Yahoo 시장'].includes(value.source)) continue;
        Object.assign(s,{rate:value.rate,asOf:value.asOf,fetched:value.fetched,source:value.source,daily:value.daily===true,market:value.market});
        s.nextPoll=s.fetched+60000;
      } catch (_) { /* Optional session cache. */ }
    }
  }
  function saveRate(s, candidate) {
    const value={...s,...candidate,fetched:Date.now()};
    if (!validRate(value)) throw new Error('Invalid or expired reference');
    // A delayed response must not replace a more recent observation.
    if (s.asOf>value.asOf && validRate(s)) return;
    Object.assign(s,{rate:value.rate,asOf:value.asOf,fetched:value.fetched,source:value.source,daily:value.daily,market:value.market===true});
    try {sessionStorage.setItem('btc-reference-v1-'+s.id,JSON.stringify({rate:s.rate,asOf:s.asOf,fetched:s.fetched,source:s.source,daily:s.daily,market:s.market}));} catch (_) {}
  }
  async function pollRate(s) {
    if (s===fx && s.market && validRate(s) && Date.now()-s.asOf<15000) return;
    if (s.pending || disposed || document.hidden || Date.now()<Math.max(s.nextPoll,s.nextRestAt)) return;
    s.pending=true; s.nextPoll=Date.now()+60000;
    try {
      if (s===fx) {
        try {
          const rows=await json(s,'https://quotation-api-cdn.dunamu.com/v1/forex/recent?codes=FRX.KRWUSD');
          const row=Array.isArray(rows) ? rows.find(r=>r.code==='FRX.KRWUSD' && r.currencyCode==='USD') : null;
          if (!row || !validNumber(row.basePrice) || (row.currencyUnit!==undefined && row.currencyUnit!==1)) throw new Error('Invalid USD/KRW');
          if (disposed || document.hidden) return;
          saveRate(s,{rate:row.basePrice,asOf:Date.parse(row.date+'T'+row.time+'+09:00'),source:'은행 고시',daily:false,market:false});
        } catch (error) {
          if (disposed || document.hidden) return;
          const row=await json(s,'https://api.frankfurter.dev/v1/latest?base=USD&symbols=KRW');
          if (row.base!=='USD' || row.amount!==1) throw new Error('Wrong FX base');
          if (disposed || document.hidden) return;
          saveRate(s,{rate:row.rates?.KRW,asOf:Date.parse(row.date+'T00:00:00Z'),source:'ECB 일별',daily:true,market:false});
        }
      } else {
        const row=await json(s,'https://api.exchange.coinbase.com/products/USDT-USD/ticker');
        if (disposed || document.hidden) return;
        saveRate(s,{rate:Number(row.price),asOf:Date.parse(row.time),source:'Coinbase',daily:false});
      }
    } catch (_) { /* Keep the last reference labeled stale; do not invent a replacement. */ }
    finally {s.pending=false; schedulePaint();}
  }
  function pollRates() {for (const s of rates) pollRate(s);}
  function paintAux() {
    const fxReady=validRate(fx), pegReady=validRate(peg);
    fxEl.className='market aux '+(fxReady ? (fx.market && Date.now()-fx.asOf<15000 ? 'fresh' : 'reference') : 'stale');
    fxEl.dataset.market=String(fx.market);
    if (fx.rate!==null) fxEl.querySelector('.price span').textContent=fx.rate.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
    fxEl.querySelector('.change').textContent='1 USD당 원화 · '+(fx.source || '고시 환율');
    fxEl.querySelector('.status span').textContent=fx.rate===null ? '환율 연결 대기' :
      (fxReady ? '' : '갱신 지연 · ')+dayFormat.format(new Date(fx.asOf))+(fx.daily ? ' 기준' : ' '+clock(fx.asOf)+(fx.market ? ' 시장 시세' : ' 고시'));
    const btc=states[0], domestic=states[2];
    const quotesReady=fresh(btc) && fresh(domestic) && Math.abs(btc.lastEvent-domestic.lastEvent)<=15000;
    const ready=quotesReady && fxReady && pegReady;
    premiumEl.className='market aux '+(ready ? 'reference' : 'stale');
    premiumEl.dataset.ready=String(Boolean(ready));
    if (ready) {
      const value=(domestic.price/(btc.price*peg.rate*fx.rate)-1)*100;
      if (validNumber(value)) {
        lastPremium=value;
        premiumEl.querySelector('.price span').textContent=(value>=0 ? '+' : '')+value.toFixed(2);
        premiumEl.querySelector('.price span').style.color=value>=0 ? '#d97716' : '#216bdd';
        premiumEl.querySelector('.change').textContent=(value>=0 ? '국내 가격이 더 높아요' : '해외 가격이 더 높아요')+' · BTC';
        premiumEl.dataset.value=String(value);
      }
    } else premiumEl.querySelector('.price span').style.color='#8793a4';
    premiumEl.querySelector('.status span').textContent=ready ?
      (fx.market ? '시장환율 기반 · ' : fx.daily ? '일별 환율 기반 · ' : '고시환율 기반 · ')+clock(Math.min(btc.lastEvent,domestic.lastEvent)) :
      (lastPremium===null ? '' : '마지막 값 · ')+(!fxReady ? '환율 대기' : !pegReady ? 'USDT 환산 대기' : '시세 지연');
    premiumEl.title='(Upbit BTC/KRW ÷ (Binance BTC/USDT × USDT/USD × USD/KRW) − 1) × 100. 수수료 제외.';
  }

  // Yahoo's public PricingData wire format (yfinance/pricing.proto). Decode
  // only bounded strings, price, time and change; no remote JS/protobuf library.
  function decodeMacro(raw) {
    if (typeof raw!=='string' || raw.length>16384) throw new Error('Quote size');
    const encoded=raw.startsWith('{') ? JSON.parse(raw).message : raw;
    if (typeof encoded!=='string' || encoded.length>8192) throw new Error('Quote message');
    const bytes=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0)), view=new DataView(bytes.buffer);
    let at=0;
    const read=()=>{
      let value=0, scale=1;
      for (let i=0;i<10;i++) {
        if (at>=bytes.length) throw new Error('Truncated quote');
        const byte=bytes[at++]; value+=(byte&127)*scale;
        if (!Number.isSafeInteger(value)) throw new Error('Quote integer');
        if (!(byte&128)) return value;
        scale*=128;
      }
      throw new Error('Quote varint');
    };
    const value={};
    while (at<bytes.length) {
      const tag=read(), field=Math.floor(tag/8), wire=tag%8;
      if (!field) throw new Error('Quote field');
      if (wire===0) {
        const number=read();
        if (field===3) value.time=number%2 ? -(number+1)/2 : number/2;
      } else if (wire===2) {
        const size=read();
        if (at+size>bytes.length) throw new Error('Quote string');
        if ([1,4,5].includes(field)) value[{1:'symbol',4:'currency',5:'exchange'}[field]]=new TextDecoder('utf-8',{fatal:true}).decode(bytes.subarray(at,at+size));
        at+=size;
      } else if (wire===5) {
        if (at+4>bytes.length) throw new Error('Quote float');
        const number=view.getFloat32(at,true); at+=4;
        if (field===2) value.price=number;
        if (field===8) value.change=number;
      } else if (wire===1) {
        if (at+8>bytes.length) throw new Error('Quote double');
        at+=8;
      } else throw new Error('Quote wire type');
    }
    return value;
  }
  const macroSymbols=['NQ=F','^TNX','KRW=X'];
  const macros=Object.fromEntries(['nq','tnx'].map((id,i)=>[macroSymbols[i],{
    id,price:null,asOf:0,received:0,stream:false,change:null,points:[],bucket:0,delay:-1,dirty:false
  }]));
  let macroSocket=null, macroRetry=null, macroRetries=0, macroOpened=0, macroRx=0, macroSubscribed=0;
  let parentDoc=null;
  try {parentDoc=window.parent.document;} catch (_) {}
  function acceptMacro(value) {
    if (!macroSymbols.includes(value.symbol) || !validNumber(value.price) || value.price<=0 ||
        !Number.isSafeInteger(value.time) || value.time<=0 || value.time>Date.now()+5000 || Date.now()-value.time>7*86400000 ||
        (value.symbol==='^TNX' && value.price>30) ||
        (value.symbol==='KRW=X' && value.currency!=='KRW') ||
        (value.symbol==='NQ=F' && value.currency && value.currency!=='USD')) return;
    if (value.symbol==='KRW=X') {
      if (value.time<fx.asOf || Date.now()-value.time>180000) return;
      saveRate(fx,{rate:value.price,asOf:value.time,source:'Yahoo 시장',market:true,daily:false});
    } else {
      const s=macros[value.symbol];
      if (value.time<s.asOf) return;
      const bucket=Math.floor(value.time/60000);
      if (bucket===s.bucket && s.points.length) s.points[s.points.length-1]=value.price;
      else s.points.push(value.price);
      Object.assign(s,{price:value.price,asOf:value.time,received:Date.now(),stream:true,
        change:validNumber(value.change) ? value.change : null,bucket,dirty:true});
      s.points=s.points.slice(-60);
    }
    macroRx=Date.now(); macroRetries=0; schedulePaint();
  }
  function paintMacro() {
    if (!parentDoc) return;
    for (const [symbol,s] of Object.entries(macros)) {
      const el=parentDoc.getElementById('macro-'+s.id);
      if (!el) continue;
      const asOf=Number(el.dataset.asof), price=Number(el.dataset.price);
      s.delay=Number(el.dataset.delay ?? -1);
      // REST is a seed/fallback. An older response never displaces a stream.
      if (el.dataset.symbol===symbol && validNumber(price) && price>0 && asOf>0 && asOf>s.asOf) {
        Object.assign(s,{price,asOf,received:Number(el.dataset.fetched),stream:false});
      }
      if (s.points.length<2 && el.dataset.points) s.points=[...el.dataset.points.split(',').map(Number).filter(p=>validNumber(p)&&p>0),...s.points].slice(-60);
      if (!s.stream || s.price===null) continue;
      el.dataset.transport='ws';
      el.querySelector('.btc-macro-value').textContent=s.price.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
      const age=Math.max(0,Math.floor((Date.now()-s.asOf)/1000));
      const status=Date.now()-s.received<15000 && macroSocket?.readyState===1 ? '스트림 수신' : '수신 지연 · 마지막 값';
      el.querySelector('.btc-macro-status').textContent=status+' · 원자료 '+(age<60 ? age+'초' : Math.floor(age/60)+'분')+' 전 · '+clock(s.asOf)+' KST · '+(s.delay>=0 ? '제공 지연 '+s.delay+'분' : '제공 지연 미확인');
      el.querySelector('.btc-macro-change').textContent=(s.id==='nq' ? 'pt · NQ 선물' : '% · 수익률 지표')+' · '+(s.change===null ? '변동률 자료 대기' : '24시간 '+(s.change>=0 ? '+' : '')+s.change.toFixed(2)+'%');
      const graph=el.querySelector('.btc-macro-graph');
      if (s.dirty || graph.dataset.asof!==String(s.asOf)) {
        if (s.points.length>1) {
          const low=Math.min(...s.points), high=Math.max(...s.points), span=high-low || Math.max(low*.001,.001);
          const points=s.points.map((p,i)=>(i*240/(s.points.length-1)).toFixed(1)+','+(38-(p-low)/span*32).toFixed(1)).join(' ');
          graph.innerHTML='<svg viewBox="0 0 240 42" role="img" aria-label="최근 표시 시세 그래프"><polyline points="'+points+'" fill="none" stroke="#3182f6" stroke-width="2" stroke-linejoin="round"/></svg>';
        }
        graph.dataset.asof=String(s.asOf); s.dirty=false;
      }
    }
    const reference=parentDoc.getElementById('macro-fx-reference');
    if (reference?.dataset.symbol==='KRW=X') {
      const asOf=Number(reference.dataset.asof), fetched=Number(reference.dataset.fetched), rate=Number(reference.dataset.price);
      if (asOf>fx.asOf && fetched<=Date.now()+5000 && Date.now()-fetched<15000 &&
          validRate({...fx,rate,asOf,fetched,market:true})) {
        saveRate(fx,{rate,asOf,source:'Yahoo 시장',market:true,daily:false});
        paintAux();
      }
    }
  }
  function subscribeMacro() {
    if (macroSocket?.readyState!==1) return;
    try {macroSocket.send(JSON.stringify({subscribe:macroSymbols})); macroSubscribed=Date.now();}
    catch (_) {macroSocket.close();}
  }
  function connectMacro() {
    if (disposed || document.hidden || macroSocket) return;
    let ws;
    try {ws=new WebSocket('wss://streamer.finance.yahoo.com/?version=2');}
    catch (_) {retryMacro(); return;}
    macroSocket=ws; macroOpened=Date.now();
    ws.onopen=subscribeMacro;
    ws.onmessage=event=>{
      if (disposed || document.hidden || macroSocket!==ws) return;
      try {acceptMacro(decodeMacro(event.data));} catch (_) {}
    };
    ws.onerror=()=>ws.close();
    ws.onclose=()=>{if (macroSocket!==ws) return; macroSocket=null; retryMacro(); schedulePaint();};
  }
  function retryMacro() {
    if (disposed || document.hidden || macroRetry) return;
    macroRetry=setTimeout(()=>{macroRetry=null;connectMacro();},Math.min(30000,1000*2**Math.min(macroRetries++,5)));
  }
  function stopMacro() {
    clearTimeout(macroRetry); macroRetry=null;
    const ws=macroSocket; macroSocket=null; if (ws) ws.close();
  }
  // Restore stream values promptly if a native quote fragment replaces its DOM.
  const macroObserver=parentDoc ? new MutationObserver(records=>{
    if (records.some(r=>[...r.addedNodes].some(n=>n.nodeType===1 && (n.matches?.('.btc-macro-grid,#macro-nq,#macro-tnx,#macro-fx-reference') || n.querySelector?.('.btc-macro-grid,#macro-nq,#macro-tnx,#macro-fx-reference'))))) schedulePaint();
  }) : null;
  if (parentDoc?.body) macroObserver?.observe(parentDoc.body,{childList:true,subtree:true});

  const heartbeat=setInterval(()=>{
    if (disposed || document.hidden) return;
    for (const s of states) {
      if (s.socketRef && Date.now()-Math.max(s.connectedAt,s.lastWs)>(s.market==='binance' ? 12000 : 20000)) s.socketRef.close();
      if (s.history && !s.historyReady) history(s);
      poll(s);
    }
    if (macroSocket && Date.now()-Math.max(macroOpened,macroRx)>120000) macroSocket.close();
    if (Date.now()-macroSubscribed>15000) subscribeMacro();
    pollRates(); schedulePaint();
  },1000);
  document.addEventListener('visibilitychange',()=>{
    for (const s of states) {
      if (document.hidden) stop(s);
      else { history(s); connect(s); poll(s); }
    }
    if (document.hidden) {
      stopMacro();
      rates.forEach(s=>s.controllers.forEach(c=>c.abort()));
      binanceRequest.controllers.forEach(c=>c.abort());
    } else {connectMacro();pollRates();}
    schedulePaint();
  });
  const observer=new ResizeObserver(()=>{ for (const s of states) s.dirty=true; schedulePaint(); });
  observer.observe(document.body);
  window.addEventListener('pagehide',()=>{
    disposeChartTouch();
    disposed=true; stopMacro(); macroObserver?.disconnect(); clearInterval(heartbeat); clearTimeout(paintTimer); observer.disconnect(); states.forEach(stop); rates.forEach(s=>s.controllers.forEach(c=>c.abort()));
    binanceRequest.controllers.forEach(c=>c.abort());
  });
  for (const s of states) { restore(s); history(s); connect(s); poll(s); }
  restoreRates(); connectMacro(); pollRates(); schedulePaint();
})();
</script></body></html>"""


def render_live_prices() -> None:
    """Keep a stable iframe outside analysis fragments so tab clicks keep sockets."""
    components.html(LIVE_PRICES_HTML, height=362, scrolling=False)
