(() => {
  'use strict';
  let ACTIVE_SYMBOL = 'BTCUSDT';
  /* LIVE_ANALYSIS_BRIDGE */
  /* CHART_READER_BRIDGE */
  /* AI_FORECAST_BRIDGE */
  /* PWA_BRIDGE */
  const MAX_POINTS = 61, STALE_MS = 15000, DRAW_MS = 50;
  const MARKET_ASSETS = [['BTC','binance','비트코인',2],['ETH','ethereum','이더리움',2],['SOL','solana','솔라나',2],['XRP','ripple','리플',4]];
  try {
    const initial=window.parent.document.getElementById('btc-live-selection')?.dataset.symbol;
    if(['NQ=F','^KS11'].includes(initial) || MARKET_ASSETS.some(([code])=>code+'USDT'===initial)) ACTIVE_SYMBOL=initial;
  } catch(_) {}
  for (const [code,id,name] of MARKET_ASSETS) {
    let card=document.getElementById(id);
    if(!card) {card=document.getElementById('binance').cloneNode(true);card.id=id;document.getElementById('forex').before(card);}
    card.setAttribute('aria-label',name+' 실시간 가격');
    card.querySelector('.name b').textContent=code;
    card.querySelector('canvas').setAttribute('aria-label',name+' 최근 1시간 가격 그래프');
    card.dataset.selected=String(code+'USDT'===ACTIVE_SYMBOL);
  }
  const deck=document.querySelector('.dashboard'),extra=document.createElement('details');
  extra.className='quote-extra';extra.innerHTML='<summary>다른 코인 · 환율 · 김치프리미엄</summary><div class="quote-extra-grid"></div>';
  deck.append(extra);
  const extraGrid=extra.querySelector('.quote-extra-grid');
  function arrangeQuotes(){
    for(const [code,id] of MARKET_ASSETS){const card=document.getElementById(id),target=code+'USDT'===ACTIVE_SYMBOL?deck:extraGrid;if(card.parentElement!==target)target.prepend(card);}
    for(const id of ['forex','premium']){const card=document.getElementById(id);if(card.parentElement!==extraGrid)extraGrid.append(card);}
  }
  arrangeQuotes();
  const configs=MARKET_ASSETS.map(([code,id,name,decimals])=>({id,market:'binance',name,symbol:code+'USDT',decimals,changeLabel:'24시간',restGap:1000,
    history:'https://data-api.binance.vision/api/v3/klines?symbol='+code+'USDT&interval=1m&limit=60'}));
  configs.push({id:'upbit',market:'upbit',symbol:'KRW-BTC',decimals:0,changeLabel:'전일 대비',restGap:11000,
    socket:'wss://api.upbit.com/websocket/v1',ticker:'https://api.upbit.com/v1/ticker?markets=KRW-BTC',history:null});
  const streams=configs.filter(c=>c.market==='binance').flatMap(c=>[c.symbol.toLowerCase()+'@aggTrade',c.symbol.toLowerCase()+'@ticker']);
  const klineStreams=symbol=>['NQ=F','^KS11'].includes(symbol)?[]:LiveCandles.frames.map(tf=>symbol.toLowerCase()+'@kline_'+tf);
  let subscribedSymbol=null,subscriptionId=0,lastSubscriptionAt=0,selectionTimer=null;
  let disposed = false, paintTimer = null;
  const states = configs.map(config => ({...config, el:document.getElementById(config.id), points:[],
    socketRef:null, retryTimer:null, retries:0, connectedAt:0, lastRx:0, lastEvent:0,
    lastPoll:0, lastWs:0, historyAt:0, transport:'', price:null, change:null, pending:false,
    loadingHistory:false, historyReady:false, historyRetryAt:0, historyFailures:0, nextRestAt:0, storageAt:0, controllers:new Set(), dirty:true,
    moveSamples:[], move:null,plotDirty:true}));
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
  function write(target,key,value) {
    if (target[key] !== value) target[key]=value;
  }
  function textAt(root,selector,value) { write(root.querySelector(selector),'textContent',value); }
  function fresh(s) {
    const now=Date.now();
    return s.lastRx && now-s.lastRx < STALE_MS && now-s.lastEvent < STALE_MS && s.lastEvent<=now+3000;
  }
  function syncSelection() {
    let selected;
    try {selected=window.parent.document.getElementById('btc-live-selection')?.dataset.symbol;} catch(_) {}
    if(!['NQ=F','^KS11'].includes(selected) && !states.some(s=>s.market==='binance' && s.symbol===selected)) selected=ACTIVE_SYMBOL;
    if(selected!==ACTIVE_SYMBOL) {
      ACTIVE_SYMBOL=selected;liveAnalysis.stop();
      const next=states.find(s=>s.symbol===selected);if(next){next.dirty=true;next.plotDirty=true;}
    }
    for(const s of states) if(s.el) write(s.el.dataset,'selected',String(s.symbol===ACTIVE_SYMBOL));
    arrangeQuotes();disposePwa.sync?.();
    write(document.body.dataset,'asset',ACTIVE_SYMBOL);
    const socket=states[0].socketRef;
    if(socket?.readyState===1 && subscribedSymbol!==ACTIVE_SYMBOL) {
      // Two control frames per switch; keep below Binance's five messages/sec
      // limit, leaving room for protocol pong. Rapid choices use the latest.
      const delay=lastSubscriptionAt+650-Date.now();
      if(delay>0) {
        if(selectionTimer===null) selectionTimer=setTimeout(()=>{selectionTimer=null;schedulePaint();},delay);
        return;
      }
      if(subscribedSymbol && klineStreams(subscribedSymbol).length) socket.send(JSON.stringify({method:'UNSUBSCRIBE',params:klineStreams(subscribedSymbol),id:++subscriptionId}));
      if(klineStreams(ACTIVE_SYMBOL).length) socket.send(JSON.stringify({method:'SUBSCRIBE',params:klineStreams(ACTIVE_SYMBOL),id:++subscriptionId}));
      subscribedSymbol=ACTIVE_SYMBOL;lastSubscriptionAt=Date.now();
    }
  }
  function schedulePaint() {
    if (!paintTimer && !disposed && !document.hidden) paintTimer = setTimeout(() => {
      paintTimer = null;
      syncSelection();
      for (const s of states) {
        if (!s.el) continue;
        const live = fresh(s);
        write(s.el,'className','market crypto ' + (live ? 'fresh' : 'stale'));
        write(s.el.dataset,'transport',s.transport);
        textAt(s.el,'.status span',s.price === null
          ? (s.retries ? '연결 지연 · 재시도 중' : '연결 중…')
          : (s.transport === 'history' ? '최근 분봉' : live ? (s.transport === 'ws' ? '실시간' : (Math.max(5,s.restGap/1000)+'초 조회')) : '수신 지연 · 마지막 가격') + ' · ' + clock(s.lastEvent));
        if (s.dirty) {
          if (s.price !== null) {
            textAt(s.el,'.price span',s.price.toLocaleString('en-US', {
              minimumFractionDigits:s.decimals, maximumFractionDigits:s.decimals}));
            const delta=s.el.querySelector('.change');
            write(delta,'textContent',s.change === null ? s.changeLabel+' 변동 정보 없음' :
              `${s.changeLabel} ${s.change >= 0 ? '+' : ''}${s.change.toFixed(2)}%`);
            write(delta.style,'color',s.change === null ? 'rgb(102, 117, 139)' : s.change >= 0 ? 'rgb(9, 132, 92)' : 'rgb(214, 56, 81)');
          }
          if(s.plotDirty && s.symbol===ACTIVE_SYMBOL) {draw(s);s.plotDirty=false;}
          persist(s); s.dirty=false;
        }
      }
      paintAux();
      paintMacro();
      paintMoves();
      const selected=states.find(s=>s.symbol===ACTIVE_SYMBOL);
      if(selected){
        const current=selected.transport!=='history'&&selected.price!==null;
        chartReader.currentQuote(ACTIVE_SYMBOL,current?selected.price:NaN,current?
          `${fresh(selected)?(selected.transport==='ws'?'실시간':'조회 시세'):'수신 지연 · 마지막 가격'} · ${clock(selected.lastEvent)} KST`:'현재가 연결 중');
      }
      if(selected) liveAnalysis.paint({symbol:ACTIVE_SYMBOL,price:selected.price,event:selected.lastEvent,fresh:fresh(selected)});
      try{for(const plot of window.parent.document.querySelectorAll('.js-plotly-plot'))if(plot.isConnected&&plot.getClientRects().length){chartReader.refresh(plot);if(!chartReader.isInteracting(plot))aiForecast.paint(plot);}}catch(_){}
    }, DRAW_MS);
  }
  function addPoint(s, time, price) {
    const minute = Math.floor(time/60000)*60000;
    const last = s.points[s.points.length-1];
    if(last && last[0]===minute && last[1]===price) {s.dirty=true;return;}
    if (last && last[0] === minute) last[1]=price;
    else if (!last || minute > last[0]) s.points.push([minute,price]);
    s.points=s.points.filter(p => p[0] >= minute-3600000).slice(-MAX_POINTS);
    s.dirty=true;s.plotDirty=true;
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
        time < s.lastEvent || time > Date.now()+3000) return;
    s.price=price;
    if (validNumber(change)) s.change=change;
    s.lastEvent=time; s.lastRx=Date.now(); s.transport=transport;
    if (transport === 'ws') { s.lastWs=Date.now(); if (fresh(s)) s.retries=0; }
    if (s.history) addPoint(s,time,price);
    detectMove(s,time,price);
    schedulePaint();
  }
  function draw(s) {
    const canvas=s.el.querySelector('canvas'), width=canvas.clientWidth, height=42;
    const scale=Math.min(window.devicePixelRatio || 1,2);
    if (canvas.width!==Math.round(width*scale) || canvas.height!==Math.round(height*scale)) {
      canvas.width=Math.round(width*scale); canvas.height=Math.round(height*scale);
    }
    const ctx=canvas.getContext('2d'); ctx.setTransform(scale,0,0,scale,0,0); ctx.clearRect(0,0,width,height);
    write(canvas.dataset,'samples',String(s.points.length));
    write(canvas.dataset,'span',String(s.points.length>1 ? s.points[s.points.length-1][0]-s.points[0][0] : 0));
    write(s.el.dataset,'history',s.historyReady ? 'ready' : s.historyFailures ? 'retry' : 'loading');
    textAt(s.el,'.range span:last-child',s.historyReady ? '지금' : s.historyFailures ? '이력 재시도' : '이력 조회 중');
    if (s.points.length) textAt(s.el,'.range span',clock(s.points[0][0]).slice(0,5)+' KST');
    write(s.el.querySelector('.empty'),'hidden',s.points.length>0);
    if (!s.points.length || !width) return;
    const values=s.points.map(p=>p[1]), low=Math.min(...values), high=Math.max(...values);
    const span=high-low || Math.max(0.00001,low*0.0001), pad=6;
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
    write(canvas,'ariaLabel',`${s.name} 최근 1시간 가격, ${values[values.length-1].toLocaleString('en-US')}`);
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
      const seed=rows.filter(row=>validNumber(Number(row[0])) && Number(row[0])%60000===0 &&
        Number(row[6] ?? Number(row[0])+59999)===Number(row[0])+59999)
        .map(row=>[Number(row[6] ?? Number(row[0])+59999),Number(row[4])]).filter(([t,p])=>
        validNumber(t) && validNumber(p) && p>0 && t<=Date.now() && t>=Date.now()-660000);
      s.moveSamples=[...new Map([...seed,...s.moveSamples].map(p=>[p[0],p])).values()].sort((a,b)=>a[0]-b[0]).slice(-90);
      const merged=new Map([...points,...s.points].map(p=>[p[0],p[1]]));
      s.points=[...merged].sort((a,b)=>a[0]-b[0]).filter(p=>p[0]>=Date.now()-3660000).slice(-MAX_POINTS);
      if (!points.length) throw new Error('Empty candle history');
      s.historyReady=true; s.historyAt=Date.now(); s.historyFailures=0;
      if (s.price===null && s.points.length) {
        const last=s.points[s.points.length-1];
        s.price=last[1]; s.lastEvent=last[0]; s.transport='history';
      }
      s.dirty=true;s.plotDirty=true; persist(s); schedulePaint();
    } catch (_) {
      s.historyFailures++; s.historyRetryAt=Date.now()+Math.min(60000,11000*2**Math.min(s.historyFailures,3));
      s.dirty=true;s.plotDirty=true; schedulePaint();
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
    const s=binanceRequest, group=states.filter(s=>s.market==='binance');
    if (s.pending || disposed || document.hidden || group.every(x=>x.transport==='ws' && fresh(x)) ||
        Date.now()-s.lastPoll<5000 || !reserveRest(s)) return;
    s.pending=true; s.lastPoll=Date.now();
    try {
      const rows=await json(s,'https://data-api.binance.vision/api/v3/ticker/24hr?symbols='+encodeURIComponent(JSON.stringify(group.map(m=>m.symbol))));
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
    if ((s.market==='binance' && s.id!=='binance') || disposed || document.hidden || s.socketRef) return;
    const group=s.market==='binance' ? states.filter(s=>s.market==='binance') : [s];
    let ws;
    if(s.market==='binance') {
      s.socket='wss://data-stream.binance.vision/stream?streams='+[...streams,...klineStreams(ACTIVE_SYMBOL)].join('/');
      subscribedSymbol=ACTIVE_SYMBOL;
    }
    try { ws=new WebSocket(s.socket); }
    catch (_) { reconnect(s); return; }
    for (const market of group) {market.socketRef=ws; market.connectedAt=Date.now();}
    ws.binaryType='arraybuffer';
    ws.onopen=()=>{
      if(s.market==='binance') syncSelection();
      if (s.id==='upbit') ws.send(JSON.stringify([
        {ticket:'btc-signal-lab-'+Math.random().toString(36).slice(2)},
        {type:'ticker',codes:[s.symbol],is_only_realtime:true}
      ]));
    };
    ws.onmessage=event=>{
      if (disposed || s.socketRef!==ws || document.hidden) return;
      try {
        const packet=JSON.parse(typeof event.data==='string' ? event.data : new TextDecoder().decode(event.data));
        if (packet.data?.e==='kline' || packet.e==='kline') {
          liveAnalysis.accept(packet.data ?? packet); schedulePaint(); return;
        }
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
      if (s.market==='binance') liveAnalysis.stop();
      reconnect(s); poll(s); schedulePaint();
    };
  }
  function stop(s) {
    if(s.id==='binance') {clearTimeout(selectionTimer);selectionTimer=null;}
    clearTimeout(s.retryTimer); s.retryTimer=null;
    const ws=s.socketRef; s.socketRef=null; if (ws) ws.close();
    for (const controller of s.controllers) controller.abort();
    s.lastRx=0;
  }
  /* RATES_BRIDGE */
  /* MACRO_BRIDGE */
  /* ALERTS_BRIDGE */
  const heartbeat=setInterval(()=>{
    if (disposed || document.hidden) return;
    for (const s of states) {
      if(s.socketRef && (s.market!=='binance' || s.id==='binance')) {
        const peers=s.market==='binance' ? states.filter(m=>m.market==='binance') : [s];
        const latest=Math.max(...peers.map(m=>Math.max(m.connectedAt,m.lastWs)));
        if(Date.now()-latest>(s.market==='binance' ? 12000 : 20000)) s.socketRef.close();
      }
      if (s.history && !s.historyReady) history(s);
      poll(s);
    }
    if (macroSocket && Date.now()-Math.max(macroOpened,macroRx)>120000) macroSocket.close();
    if (Date.now()-macroSubscribed>15000) subscribeMacro();
    pollRates(); schedulePaint();
  },1000);
  document.addEventListener('visibilitychange',()=>{
    for (const s of states) {
      if (document.hidden) {stop(s);s.move=null;s.moveSamples=[];}
      else { history(s); connect(s); poll(s); }
    }
    if (document.hidden) {
      liveAnalysis.stop();
      const host=parentDoc?.getElementById('btc-move-alerts'); if(host) {host.hidden=true;host.dataset.signature='';host.replaceChildren();}
      stopMacro();
      rates.forEach(s=>s.controllers.forEach(c=>c.abort()));
      binanceRequest.controllers.forEach(c=>c.abort());
    } else {connectMacro();pollRates();}
    schedulePaint();
  });
  const observer=new ResizeObserver(()=>{
    try {
      const frame=window.frameElement,height=Math.ceil(document.body.scrollHeight)+'px';
      if(frame) {
        frame.style.height=height;
      }
    } catch(_) {}
    for (const s of states) {s.dirty=true;s.plotDirty=true;} schedulePaint();
  });
  observer.observe(document.body);
  window.addEventListener('pagehide',()=>{
    chartReader.dispose();
    disposePwa();
    liveAnalysis.dispose();
    disposed=true; stopMacro(); macroObserver?.disconnect(); clearInterval(heartbeat); clearTimeout(paintTimer); observer.disconnect(); states.forEach(stop); rates.forEach(s=>s.controllers.forEach(c=>c.abort()));
    binanceRequest.controllers.forEach(c=>c.abort());
    const host=parentDoc?.getElementById('btc-move-alerts'); if(host) {host.hidden=true;host.dataset.signature='';host.replaceChildren();}
  });
  for (const s of states) { restore(s); history(s); connect(s); poll(s); }
  restoreRates(); connectMacro(); pollRates(); schedulePaint();
})();
