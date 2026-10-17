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
    write(fxEl,'className','market aux '+(fxReady ? (fx.market && Date.now()-fx.asOf<15000 ? 'fresh' : 'reference') : 'stale'));
    write(fxEl.dataset,'market',String(fx.market));
    if (fx.rate!==null) textAt(fxEl,'.price span',fx.rate.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}));
    textAt(fxEl,'.change','1 USD당 원화 · '+(fx.source || '고시 환율'));
    textAt(fxEl,'.status span',fx.rate===null ? '환율 연결 대기' :
      (fxReady ? '' : '갱신 지연 · ')+dayFormat.format(new Date(fx.asOf))+(fx.daily ? ' 기준' : ' '+clock(fx.asOf)+(fx.market ? ' 시장 시세' : ' 고시')));
    const btc=states.find(s=>s.symbol==='BTCUSDT'), domestic=states.find(s=>s.market==='upbit');
    const quotesReady=fresh(btc) && fresh(domestic) && Math.abs(btc.lastEvent-domestic.lastEvent)<=15000;
    const ready=quotesReady && fxReady && pegReady;
    write(premiumEl,'className','market aux '+(ready ? 'reference' : 'stale'));
    write(premiumEl.dataset,'ready',String(Boolean(ready)));
    const premiumPrice=premiumEl.querySelector('.price span');
    if (ready) {
      const value=(domestic.price/(btc.price*peg.rate*fx.rate)-1)*100;
      if (validNumber(value)) {
        lastPremium=value;
        write(premiumPrice,'textContent',(value>=0 ? '+' : '')+value.toFixed(2));
        write(premiumPrice.style,'color',value>=0 ? 'rgb(217, 119, 22)' : 'rgb(33, 107, 221)');
        textAt(premiumEl,'.change',(value>=0 ? '국내 가격이 더 높아요' : '해외 가격이 더 높아요')+' · BTC');
        write(premiumEl.dataset,'value',String(value));
      }
    } else write(premiumPrice.style,'color','rgb(135, 147, 164)');
    textAt(premiumEl,'.status span',ready ?
      (fx.market ? '시장환율 기반 · ' : fx.daily ? '일별 환율 기반 · ' : '고시환율 기반 · ')+clock(Math.min(btc.lastEvent,domestic.lastEvent)) :
      (lastPremium===null ? '' : '마지막 값 · ')+(!fxReady ? '환율 대기' : !pegReady ? 'USDT 환산 대기' : '시세 지연'));
    write(premiumEl,'title','(Upbit BTC/KRW ÷ (Binance BTC/USDT × USDT/USD × USD/KRW) − 1) × 100. 수수료 제외.');
  }
