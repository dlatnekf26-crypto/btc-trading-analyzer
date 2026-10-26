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
        if (field===7) value.marketHours=number;
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
  const macros=Object.fromEntries([
    ...SESSION_ASSETS.map(([code,symbol,id,unit,currency,decimals])=>[symbol,id,unit,false,currency,decimals,['USD','KRW'].includes(unit)]),
    ['CL=F','oil','USD/배럴 · WTI 선물',false,'USD',2,false],
    ['^TNX','tnx','% · 10년물 금리',true,'USD',2,false],['^TYX','tyx','% · 30년물 금리',true,'USD',2,false]
  ].map(([symbol,id,label,yieldIndex,currency,decimals,equity])=>[symbol,{
    id,label,yieldIndex,currency,decimals,equity,price:null,asOf:0,received:0,stream:false,change:null,points:[],bucket:0,delay:-1,
    dirty:false,graphDirty:false,node:null,nodes:null,statusKey:null,session:'regular',error:false,cached:false,marketState:'unknown',stateUntil:0
  }]));
  const macroSymbols=[...Object.keys(macros),'KRW=X'];
  let macroSocket=null, macroRetry=null, macroRetries=0;
  let parentDoc=null;
  try {parentDoc=window.parent.document;} catch (_) {}
  let snapshotRaw=null,lastMacroSave=0;
  const macroCacheKey='market-last-quotes-v1';
  const quoteTime=t=>Number.isSafeInteger(t)&&t>0&&t<=Date.now()+5000&&Date.now()-t<=7*86400000;
  const referenceDates=Object.fromEntries(['USD','KRW','JPY'].map(c=>[c,new Intl.DateTimeFormat('en-CA',{timeZone:{USD:'America/New_York',KRW:'Asia/Seoul',JPY:'Asia/Tokyo'}[c]})]));
  function referenceChange(s,price,session,at=s.asOf) {
    const extended=s.equity&&['pre','post','extended'].includes(session);
    if(!extended&&(!validNumber(s.regularAsOf)||referenceDates[s.currency]?.format(at)!==referenceDates[s.currency]?.format(s.regularAsOf)))return null;
    const base=extended?s.regularPrice:validNumber(s.regularPrice)&&validNumber(s.regularChange)&&s.regularChange>-100?s.regularPrice/(1+s.regularChange/100):null;
    return validNumber(base)&&base>0?(price/base-1)*100:null;
  }
  function readMacroRows(rows,cached=false){
    if(!Array.isArray(rows)||rows.length>macroSymbols.length)return;
    for(const row of rows){
      if(!row||typeof row!=='object')continue;
      const s=macros[row.symbol];if(!s)continue;
      if(!cached)s.error=Boolean(row.error)&&!(s.stream&&Date.now()-s.received<15000);
      if(!validNumber(row.price)||row.price<=0||!quoteTime(row.asOf))continue;
      if(cached&&row.currency!==s.currency)continue;
      if(['regular','pre','post','closed'].includes(row.marketState)&&Number.isSafeInteger(row.stateUntil)&&row.stateUntil>Date.now()){
        s.marketState=row.marketState;s.stateUntil=row.stateUntil;
      }
      // Regular-session metadata has its own timestamp. It may arrive behind
      // a newer after-hours tick and must still update that tick's reference.
      if(validNumber(row.regularPrice)&&row.regularPrice>0&&quoteTime(row.regularAsOf)&&row.regularAsOf>=(s.regularAsOf||0)){
        s.regularPrice=row.regularPrice;s.regularAsOf=row.regularAsOf;
        for(const key of ['regularChange','high','low','volume'])s[key]=validNumber(row[key])?row[key]:null;
        if(s.price!==null){
          const change=referenceChange(s,s.price,s.session);
          if(change!==null){s.dirty ||= change!==s.change;s.change=change;}
        }
      }
      if(Number.isInteger(row.delay)&&row.delay>=-1&&row.delay<=1440)s.delay=row.delay;
      if(row.asOf<s.asOf)continue;
      // Equal-time REST metadata must not undo a stream tick's price.
      if(!s.stream||row.asOf>s.asOf){
        const change=validNumber(row.change)&&row.change>-100?row.change:null;
        const session=s.equity&&['pre','post','extended','stream'].includes(row.session)?row.session:'regular';
        s.dirty ||= s.price!==row.price||s.change!==change||s.session!==session;
        Object.assign(s,{price:row.price,asOf:row.asOf,change,
          received:!cached&&quoteTime(row.fetched)?row.fetched:0,stream:false,cached,
          session});
        if(Array.isArray(row.points)){
          const points=row.points.filter(p=>validNumber(p)&&p>0).slice(-60);
          if(points.length!==s.points.length||points.some((p,i)=>p!==s.points[i])){s.points=points;s.graphDirty=true;}
        }
      }
    }
  }
  try{readMacroRows(JSON.parse(localStorage.getItem(macroCacheKey)||'[]'),true);}catch(_){}
  function readMacroSnapshot(){
    const raw=parentDoc?.getElementById('btc-quote-snapshot')?.dataset.quotes;
    if(!raw||raw===snapshotRaw||raw.length>100000)return;
    try{readMacroRows(JSON.parse(raw));snapshotRaw=raw;}catch(_){}
  }
  function saveMacroCache(){
    if(Date.now()-lastMacroSave<30000)return;
    const rows=Object.entries(macros).filter(([,s])=>s.price!==null&&quoteTime(s.asOf)).map(([symbol,s])=>({
      symbol,currency:s.currency,price:s.price,asOf:s.asOf,change:s.change,session:s.session,regularPrice:s.regularPrice,
      regularAsOf:s.regularAsOf,regularChange:s.regularChange,high:s.high,low:s.low,volume:s.volume,delay:s.delay,points:s.points,
      marketState:s.marketState,stateUntil:s.stateUntil
    }));
    if(rows.length){lastMacroSave=Date.now();try{localStorage.setItem(macroCacheKey,JSON.stringify(rows));}catch(_){}}
  }
  function acceptMacro(value) {
    if (!macroSymbols.includes(value.symbol) || !validNumber(value.price) || value.price<=0 ||
        !Number.isSafeInteger(value.time) || value.time<=0 || value.time>Date.now()+5000 || Date.now()-value.time>7*86400000 ||
        (macros[value.symbol]?.yieldIndex && value.price>30) ||
        (value.symbol==='KRW=X' && (value.currency ? value.currency!=='KRW' : value.exchange!=='CCY')) ||
        ((macros[value.symbol]?.currency==='KRW'||macros[value.symbol]?.equity) && value.currency!==macros[value.symbol]?.currency) ||
        (value.symbol!=='KRW=X' && macros[value.symbol]?.currency!=='KRW' && value.currency && value.currency!==macros[value.symbol]?.currency)) return;
    if (value.symbol==='KRW=X') {
      if (value.time<fx.asOf || Date.now()-value.time>180000) return;
      saveRate(fx,{rate:value.price,asOf:value.time,source:'Yahoo 시장',market:true,daily:false});
    } else {
      const s=macros[value.symbol];
      if (value.time<s.asOf) return;
      const bucket=Math.floor(value.time/60000);
      const session={0:'pre',1:'regular',2:'post',3:'extended'}[value.marketHours]??'stream';
      const calculated=referenceChange(s,value.price,session,value.time);
      const change=s.equity&&['pre','post','extended'].includes(session)&&calculated!==null?calculated:validNumber(value.change)&&value.change>-100?value.change:calculated;
      s.dirty ||= s.price!==value.price || s.change!==change || !s.stream;
      s.graphDirty ||= s.price!==value.price || bucket!==s.bucket;
      if (bucket===s.bucket && s.points.length) s.points[s.points.length-1]=value.price;
      else s.points.push(value.price);
      Object.assign(s,{price:value.price,asOf:value.time,received:Date.now(),stream:true,
        change,bucket,error:false,cached:false});
      if(s.equity)s.session=session;
      s.points=s.points.slice(-60);
    }
    macroRetries=0; schedulePaint();
  }
  function paintMacro() {
    if (!parentDoc) return;
    readMacroSnapshot();
    const now=Date.now();
    const write=(node,text)=>{if (node && node.textContent!==text) node.textContent=text;};
    for (const [symbol,s] of Object.entries(macros)) {
      const el=parentDoc.getElementById('macro-'+s.id);
      if (!el) continue;
      const asOf=Number(el.dataset.asof), price=Number(el.dataset.price);
      if(s.delay===-1&&el.dataset.delay!==undefined)s.delay=Number(el.dataset.delay);
      // REST is a seed/fallback. An older response never displaces a stream.
      if (el.dataset.symbol===symbol && validNumber(price) && price>0 && asOf>0 && asOf>s.asOf) {
        Object.assign(s,{price,asOf,received:Number(el.dataset.fetched),stream:false,cached:false});s.dirty=true;
      }
      if (s.points.length<2 && el.dataset.points) {
        s.points=[...el.dataset.points.split(',').map(Number).filter(p=>validNumber(p)&&p>0),...s.points].slice(-60);
        s.graphDirty=true;
      }
      if (s.price===null) {
        const message=s.error?'자료원 연결 지연 · 자동 재시도 중':'시세를 불러오는 중…';
        write(el.querySelector('.btc-macro-status'),message);
        if(symbol===ACTIVE_SYMBOL&&SESSION_SYMBOLS.includes(symbol))chartReader.currentQuote(symbol,NaN,message);
        continue;
      }
      const rebound=s.node!==el || Object.values(s.nodes || {}).some(node=>node && !node.isConnected);
      if (rebound) {
        s.node=el;
        s.nodes=Object.fromEntries(['value','change','status','badge','graph'].map(name=>[name,el.querySelector('.btc-macro-'+name)]));
        s.dirty=true; s.graphDirty=true; s.statusKey=null;
      }
      if (el.dataset.transport!=='ws') el.dataset.transport='ws';
      if (s.dirty) {
        s.priceText=(s.equity?(s.currency==='KRW'?'₩':'$'):'')+s.price.toLocaleString('en-US',{minimumFractionDigits:s.decimals,maximumFractionDigits:s.decimals});
        const movement=s.change===null ? '변동률 자료 대기' : s.yieldIndex
          ? ((s.price-s.price/(1+s.change/100))>=0 ? '+' : '')+(s.price-s.price/(1+s.change/100)).toFixed(3)+'%p'
          : (s.change>=0 ? '+' : '')+s.change.toFixed(2)+'%';
        s.changeText=s.equity ? (s.change===null?movement:movement+(s.session==='regular'?' · 전일 종가 대비':' · 정규장 종가 대비')) : s.label+' · '+(s.change===null ? movement : '기준 종가 대비 '+movement);
        s.dirty=false;
      }
      // Streamlit may replace children while keeping the article itself.
      // Compare cached text, without formatting or rewriting unchanged values.
      write(s.nodes.value,s.priceText); write(s.nodes.change,s.changeText);
      // Closed/unchanged quotes keep their formatted status and sparkline.
      // Reformat only when an actual source/session/age boundary changes.
      const connected=s.stream&&now-s.received<15000&&macroSocket?.readyState===1;
      const age=Math.max(0,Math.floor((now-s.asOf)/1000));
      const closed=s.marketState==='closed'&&now<s.stateUntil;
      const statusKey=[closed,connected,s.cached,s.error,age>7200,age<=15,s.asOf,s.delay,s.session].join('|');
      if (s.statusKey!==statusKey) {
        const tone=s.cached||s.error||age>7200?'stale':connected&&age<=15&&s.delay===0?'stream':'delayed';
        s.tone=tone;
        s.phase=closed?'장 마감':s.equity?({regular:'정규장',pre:'장전',post:'장후',extended:'장외',stream:'스트림'}[s.session]||'정규장'):'';
        s.badgeText=s.phase||(connected?'스트림':tone==='stale'?'마지막 시세':'공개 조회');
        const last=closed?(s.session==='post'?'장후 마지막 거래가':s.session==='pre'?'장전 마지막 거래가':'마지막 거래가'):null;
        const source=s.cached?'최근 수신 · '+(last||'마지막 값'):s.error?'갱신 지연 · '+(last||'마지막 값'):last||(connected?'스트림 수신':age>7200?'마지막 거래':'공개 조회');
        s.statusText=(s.phase?s.phase+' · ':'')+source+' · '+dayFormat.format(new Date(s.asOf))+' '+clock(s.asOf)+' KST · '+(s.delay>=0?'지연 '+s.delay+'분':'지연 미확인');
        s.statusKey=statusKey;
      }
      if (el.dataset.status!==s.tone) el.dataset.status=s.tone;
      write(s.nodes.status,s.statusText);write(s.nodes.badge,s.badgeText);
      const fields=fieldsFor(el),fmt=n=>validNumber(n)?n.toLocaleString('en-US',{minimumFractionDigits:s.decimals,maximumFractionDigits:s.decimals}):'—';
      if(s.equity){
        const key=[s.regularPrice,s.regularChange,s.high,s.low,s.volume].join('|');
        if(s.metricsKey!==key){
          s.metricsKey=key;
          const previous=validNumber(s.regularPrice)&&validNumber(s.regularChange)&&s.regularChange>-100?s.regularPrice/(1+s.regularChange/100):NaN;
          s.metricsText={regular:fmt(s.regularPrice),previous:fmt(previous),high:fmt(s.high),low:fmt(s.low),
            volume:validNumber(s.volume)?s.volume.toLocaleString('en-US',{maximumFractionDigits:0})+'주':'—'};
        }
        for(const [key,text] of Object.entries(s.metricsText))setField(fields,key,text);
      }
      if(symbol===ACTIVE_SYMBOL&&SESSION_SYMBOLS.includes(symbol))chartReader.currentQuote(symbol,s.price,s.statusText);
      const graph=s.nodes.graph;
      if (graph && (s.graphDirty || graph.firstElementChild!==s.svgNode)) {
        if (s.points.length>1) {
          const low=Math.min(...s.points), high=Math.max(...s.points), span=high-low || Math.max(low*.001,.001);
          const points=s.points.map((p,i)=>(i*240/(s.points.length-1)).toFixed(1)+','+(38-(p-low)/span*32).toFixed(1)).join(' ');
          graph.innerHTML='<svg viewBox="0 0 240 42" preserveAspectRatio="none" role="img" aria-label="최근 표시 시세 그래프"><polyline points="'+points+'" fill="none" stroke="#3182f6" stroke-width="2" stroke-linejoin="round"/></svg>';
        } else if (s.points.length===1) {
          graph.innerHTML='<svg viewBox="0 0 240 42" preserveAspectRatio="none" role="img" aria-label="현재 수신 시세, 이력 대기"><circle cx="236" cy="21" r="3" fill="#3182f6"/></svg>';
        }
        graph.dataset.asof=String(s.asOf); s.svgNode=graph.firstElementChild; s.graphDirty=false;
      }
    }
    saveMacroCache();
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
    try {macroSocket.send(JSON.stringify({subscribe:macroSymbols}));}
    catch (_) {macroSocket.close();}
  }
  function connectMacro() {
    if (disposed || document.hidden || macroSocket) return;
    let ws;
    try {ws=new WebSocket('wss://streamer.finance.yahoo.com/?version=2');}
    catch (_) {retryMacro(); return;}
    macroSocket=ws;
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
    const fields='.btc-macro-value,.btc-macro-change,.btc-macro-status,.btc-macro-badge,.btc-macro-graph';
    const selector='.btc-macro-grid,.btc-macro-card,#btc-quote-snapshot,#macro-fx-reference,#btc-news-bridge,#btc-move-alerts,#btc-live-selection,[data-quote-symbol],[data-reference],'+fields;
    const overwritten=records.some(r=>r.target.matches?.(fields) && Object.values(macros).some(s=>s.price!==null &&
      [[s.nodes?.value,s.priceText],[s.nodes?.change,s.changeText],[s.nodes?.status,s.statusText],[s.nodes?.badge,s.badgeText]]
        .some(([node,text])=>node===r.target && node.textContent!==text)));
    const selection=records.some(r=>r.type==='attributes' && ['btc-live-selection','btc-quote-snapshot'].includes(r.target.id));
    if (selection || overwritten || records.some(r=>[...r.addedNodes].some(n=>n.nodeType===1 && (n.matches?.(selector) || n.querySelector?.(selector))))) schedulePaint();
  }) : null;
  if (parentDoc?.body) macroObserver?.observe(parentDoc.body,{childList:true,subtree:true,attributes:true,attributeFilter:['data-symbol','data-quotes']});
