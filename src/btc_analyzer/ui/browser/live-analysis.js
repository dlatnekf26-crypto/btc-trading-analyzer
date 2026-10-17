function makeLiveAnalysis(root) {
  let doc;
  try {doc=root.document;} catch(_) {return {accept(){},paint(){},stop(){},dispose(){}};}
  let host=null,payload=null,cfg=null,books={},symbol=null,dirty=true,lastPaint=0,disposed=false,timer=null,latestQuote=null;
  const plots=new WeakMap(),held=new WeakSet(),invalidWatch=new WeakSet(),formatters=new Map();
  const array=PlotData.values;
  const clock=new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'});
  function text(node,value) {if(node && node.textContent!==value) node.textContent=value;}
  function displayDate(time,zone='Asia/Seoul') {
    if(!formatters.has(zone)) formatters.set(zone,new Intl.DateTimeFormat('en-CA',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}));
    const p=Object.fromEntries(formatters.get(zone).formatToParts(new Date(time)).map(p=>[p.type,p.value]));
    return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}:${p.second}`;
  }
  function load() {
    const node=doc.getElementById('btc-live-analysis'),chart=doc.getElementById('btc-chart-seed');
    const selected=node?.dataset.symbol ?? chart?.dataset.symbol;
    const sources=[node,chart].filter(n=>n&&n.dataset.symbol===selected&&n.dataset.seeds);
    const raw=sources.map(n=>n.dataset.seeds).join('|');
    if(node!==host){host=node;dirty=true;}
    if(selected&&selected!==symbol){symbol=selected;books={};payload=null;latestQuote=null;}
    if(!raw||raw===payload)return;
    try{
      for(const source of sources){
        const parsed=JSON.parse(source.dataset.seeds);cfg=parsed.cfg;
        for(const [tf,seed] of Object.entries(parsed.frames)){
          const book=books[tf];
          if(seed&&(!book||seed.at>book.seed.at)){
            const candle=book?.candle;
            books[tf]={seed,candle:candle?.at===seed.end?candle:null,features:null};
            if(books[tf].candle)books[tf].features=LiveCandles.advance(seed,candle,cfg)?.features??null;
          }
        }
      }
      payload=raw;dirty=true;
    }catch(_){/* Retry incomplete DOM replacement on the next heartbeat. */}
  }
  function accept(packet) {
    load(); const k=LiveCandles.parse(packet,Date.now(),symbol);
    if(!k || !cfg) return;
    const b=books[k.tf]; if(!b || (b.candle && (k.at<b.candle.at || k.event<=b.candle.event || (b.candle.closed && k.at===b.candle.at)))) return;
    const updated=LiveCandles.advance(b.seed,k,cfg);
    if(!updated) {b.gap=true;b.features=null;dirty=true;return;}
    b.candle=k;b.features=updated.features;b.gap=false;
    if(k.closed) b.seed=updated;
    dirty=true;
  }
  function status(b,now) {
    if(!b?.candle) return '봉 수신 대기';
    if(b.gap) return '누락 봉 · 동기화 대기';
    if(now-b.candle.event>15000 || b.candle.event>now+3000) return '수신 지연 · 마지막 값';
    return b.candle.closed ? '마감 봉 · 다음 봉 대기' : '실시간 · 잠정';
  }
  function current(b,now) {return !!b?.features && !b.gap && now-b.candle.event<=15000 && b.candle.at===LiveCandles.boundary(now,b.candle.tf);}
  function metrics(f,price) {
    const trend=LiveCandles.finite(f.ema_20) ? Math.sign(price-f.ema_20) : 0;
    const macd=LiveCandles.finite(f.macd_hist) ? (f.macd_hist>=0 ? 'MACD ↑' : 'MACD ↓') : 'MACD 준비 중';
    const cloud=LiveCandles.finite(f.ichimoku_cloud_a)&&LiveCandles.finite(f.ichimoku_cloud_b) ?
      (price>Math.max(f.ichimoku_cloud_a,f.ichimoku_cloud_b) ? '구름 위' : price<Math.min(f.ichimoku_cloud_a,f.ichimoku_cloud_b) ? '구름 아래' : '구름 안') : '일목 준비 중';
    return {trend,label:trend>0 ? '20봉선 위' : trend<0 ? '20봉선 아래' : '추세 준비 중',
      detail:`RSI ${LiveCandles.finite(f.rsi) ? f.rsi.toFixed(0) : '—'} · ${macd} · ${cloud}`};
  }
  // Each plot has one in-flight Plotly update. Subsequent ticks coalesce; parent
  // fragment replacements get a new WeakMap state and the newest candle.
  function update(plot,key,work) {
    let state=plots.get(plot);
    if(!state || (!state.busy && state.data!==plot.data)) {
      state={key:null,busy:false,base:JSON.parse(JSON.stringify(plot.data)),data:plot.data};plots.set(plot,state);
    }
    if(state.busy || state.key===key) return;
    state.busy=true;
    Promise.resolve().then(()=>work(state)).then(()=>{state.key=key;}).catch(()=>{}).finally(()=>{state.busy=false;});
  }
  function market(plot,meta,b,now) {
    if(!current(b,now)) return;
    const k=b.candle, key=`${k.event}-${k.row[4]}`;
    update(plot,key,async state=>{
      // Include a closed candle observed since the server snapshot, then the
      // current candle. A missing intervening candle stops updates above.
      const extra=b.seed.rows.filter(r=>r[0]>=meta.closedEnd).concat(k.closed ? [] : [k.row]);
      const lines={x:[],y:[],'marker.color':[]},lineIndices=[];
      for(let i=0;i<state.base.length;i++) {
        const trace=state.base[i];
        if(trace.type!=='candlestick' && trace.type!=='bar') continue;
        const xs=[...array(trace.x),...extra.map(r=>displayDate(r[0],meta.timezone))].slice(-meta.bars);
        const updates={x:[xs]};
        for(const [field,column] of [['open',1],['high',2],['low',3],['close',4]])
          if(trace.type==='candlestick') updates[field]=[[...array(trace[field]),...extra.map(r=>r[column])].slice(-meta.bars)];
        if(trace.type==='bar') {
          lineIndices.push(i);lines.x.push(xs);
          lines.y.push([...array(trace.y),...extra.map(r=>r[5])].slice(-meta.bars));
          lines['marker.color'].push([...array(trace.marker.color),...extra.map(r=>r[4]>=r[1] ? '#34d399' : '#fb7185')].slice(-meta.bars));
        } else {
          if(extra.length) await root.Plotly.restyle(plot,updates,[i]);
        }
      }
      if(!extra.length) return;
      for(const [index,column] of Object.entries(meta.overlays ?? {})) {
        const trace=state.base[index];
        const ys=extra.map(r=>r[0]===k.at ? b.features[column] : r[0]===b.seed.at ? b.seed.features?.[column] ?? null : null);
        lineIndices.push(Number(index));
        lines.x.push([...array(trace.x),...extra.map(r=>displayDate(r[0],meta.timezone))].slice(-meta.bars));
        lines.y.push([...array(trace.y),...ys].slice(-meta.bars));lines['marker.color'].push(null);
      }
      await root.Plotly.restyle(plot,lines,lineIndices);
      if(doc.getElementById('btc-chart-reader')?.dataset.mode==='latest')
        chartReader.inspect(plot,Infinity,'latest');
      // Overlays from the server remain explicitly closed-candle geometry.
      // A marker adds the current price without moving axes or hiding hover.
      plot.dataset.liveEvent=String(k.event);plot.dataset.livePrice=String(k.row[4]);plot.dataset.liveTimeframe=k.tf;
      const summary=doc.querySelector('.btc-chart-summary');
      text(summary?.querySelector('strong'),`${k.row[4].toLocaleString('en-US',{minimumFractionDigits:k.row[4]<10 ? 4 : 2,maximumFractionDigits:k.row[4]<10 ? 4 : 2})} USDT`);
      text(summary?.querySelector('span'),`${meta.label} · 진행 중 봉 · ${clock.format(new Date(k.event))} KST`);
      text(summary?.querySelector('span:last-child'),`현재 봉 ${k.row[4]/k.row[1]-1>=0 ? '+' : ''}${((k.row[4]/k.row[1]-1)*100).toFixed(2)}% · EMA/밴드 잠정 · 일목 구름은 확정 봉`);
    });
  }
  function forecast(plot,meta,quote,now) {
    const card=doc.getElementById('btc-live-forecast');
    const live=quote?.fresh && LiveCandles.finite(quote.price) && quote.price>0 && quote.event>=meta.baseAt &&
      quote.event<=now+3000 && now-quote.event<=15000;
    const active=LiveCandles.analysisFrames.filter(tf=>current(books[tf],now));
    text(card?.querySelector('.btc-live-status'),live ? `현재가 출발 · ${clock.format(new Date(quote.event))} KST · 잠정 지표 ${active.length}/5` : '시세 수신 대기/지연 · 조건부 경로 갱신 보류');
    if(!live) return;
    const ratio=quote.price/meta.anchor, center=meta.center.map(y=>y*ratio), lower=meta.lower.map(y=>y*ratio), upper=meta.upper.map(y=>y*ratio);
    const money=n=>n.toLocaleString('en-US',{maximumFractionDigits:n<10 ? 4 : 2,minimumFractionDigits:n<10 ? 4 : 2});
    text(card?.querySelector('strong'),`${money(center.at(-1))} USDT`);
    text(card?.querySelector('.btc-live-forecast-range'),`현재 ${money(quote.price)} → ${meta.label} · 범위 ${money(lower.at(-1))} ~ ${money(upper.at(-1))}`);
    const directions=active.map(tf=>metrics(books[tf].features,books[tf].candle.row[4]).trend);
    const up=directions.filter(n=>n>0).length,down=directions.filter(n=>n<0).length;
    text(card?.querySelector('.btc-live-forecast-reason'),`${up}개 시간대 20봉선 위 · ${down}개 아래. 현재가로 출발점을 바꾸고 기존 지표·유사 사례의 수익률 경로/방향 비중을 유지해요. 잠정 지표는 관찰 근거이며 추가 가격 가중치로 쓰지 않아요.`);
    const xs=meta.offsets.map(t=>displayDate(quote.event+t,meta.timezone));
    update(plot,`${quote.event}-${quote.price}`,async()=>{
      const indices=[...meta.liveIndices], xValues=[xs,xs,xs], yValues=[upper,lower,center];
      if(meta.indicatorSeed){
        const projected=projectIndicators(meta.indicatorSeed,center);
        for(const [index,key] of Object.entries(meta.indicatorOverlays ?? {})){
          indices.push(Number(index));xValues.push(xs);yValues.push(projected[key]);
        }
      }
      await root.Plotly.restyle(plot,{x:xValues,y:yValues},indices);
      plot.dataset.liveEvent=String(quote.event);plot.dataset.livePrice=String(quote.price);
    });
  }
  function watchDistance(quote,now) {
    const card=doc.getElementById('btc-buy-watch');
    if(!card) return;
    const low=Number(card.dataset.low),high=Number(card.dataset.high),stop=Number(card.dataset.stop);
    const riskFloor=Number(card.dataset.riskFloor ?? card.dataset.stop);
    const base=Number(card.dataset.baseAt),expires=Number(card.dataset.expires);
    if(![low,high,stop,riskFloor,base,expires].every(LiveCandles.finite) || !(0<stop && stop<low && low<high && base<expires)) return;
    let state='waiting',label='시세 수신 대기/지연 · 가격대 도달 여부 확인 보류';
    const fresh=quote?.fresh && LiveCandles.finite(quote.price) && quote.price>0 && LiveCandles.finite(quote.event) &&
      quote.event>=base && quote.event<=now+3000 && now-quote.event<=15000;
    if(now>=expires) {state='expired';label='확정 봉 갱신 대기 · 매수 검토 가격대 재계산 중';}
    else if(fresh) {
      if(quote.price<Math.max(stop,riskFloor)) invalidWatch.add(card);
      if(invalidWatch.has(card)) {state='invalid';label='급락 또는 지지 이탈 · 신규 매수 보류 및 가격대 재평가';}
      else if(quote.price>high) {state='above';label=`현재가 기준 ${((1-high/quote.price)*100).toFixed(2)}% 아래에 매수 검토 가격대가 있습니다.`;}
      else if(quote.price>=low) {state='inside';label='현재가가 매수 검토 가격대에 도달했습니다. 하락 진정 확인 전까지 신규 매수 대기.';}
      else {state='below';label='현재가가 검토 가격대보다 낮습니다. 지지 유지 여부를 재확인해야 합니다.';}
    }
    // A rebound alone cannot reactivate a price band whose support broke.
    if(invalidWatch.has(card)) state='invalid';
    card.dataset.status=state;
    const price=card.querySelector('.btc-buy-watch-price');
    if(price) {
      if(!price.dataset.original) price.dataset.original=price.textContent;
      text(price,state==='invalid' ? '가격대 재평가 필요' : state==='expired' ? '새 확정 가격대 계산 중' : price.dataset.original);
    }
    text(card.querySelector('.btc-buy-watch-distance'),label);
  }
  function paint(quote) {
    latestQuote=quote;
    if(disposed || doc.hidden || !root.Plotly) return;
    const remaining=500-(Date.now()-lastPaint);
    if(remaining>0) {
      if(timer===null) timer=setTimeout(()=>{timer=null;paint(latestQuote);},remaining);
      return;
    }
    if(timer!==null) {clearTimeout(timer);timer=null;}
    load();if(quote?.symbol && quote.symbol!==symbol) return;
    const now=Date.now();lastPaint=now;watchDistance(quote,now);
    if(host) {
      const active=LiveCandles.analysisFrames.filter(tf=>current(books[tf],now));
      text(host.querySelector('.btc-live-status'),active.length ? `실시간 ${active.length}/5 · ${clock.format(new Date(Math.max(...active.map(tf=>books[tf].candle.event))))} KST` : '봉 수신 대기/지연');
      for(const tf of LiveCandles.frames) {
        const b=books[tf],node=host.querySelector(`[data-tf="${tf}"]`);
        if(!node) continue;
        node.dataset.status=status(b,now);node.dataset.event=String(b?.candle?.event ?? 0);
        if(current(b,now)) {
          const m=metrics(b.features,b.candle.row[4]);node.dataset.direction=String(m.trend);
          text(node.querySelector('strong'),m.label);text(node.querySelector('span'),m.detail);
          text(node.querySelector('.btc-live-volatility'),`ATR ${LiveCandles.finite(b.features.atr_pct) ? b.features.atr_pct.toFixed(1)+'%' : '준비 중'}`);
        } else {node.dataset.direction='0';text(node.querySelector('strong'),'—');text(node.querySelector('span'),status(b,now));text(node.querySelector('.btc-live-volatility'),'');}
      }
    }
    for(const plot of doc.querySelectorAll('.js-plotly-plot')) {
      if(!plot.isConnected || !plot.data?.length || !plot.getClientRects().length || held.has(plot)) continue;
      const meta=plot.layout?.meta?.btcLive;
      if(meta?.symbol && meta.symbol!==symbol) continue;
      if(meta?.kind==='market') {
        market(plot,meta,books[meta.timeframe],now);
        if(!current(books[meta.timeframe],now) && plot.dataset.liveEvent)
          text(doc.querySelector('.btc-chart-summary span'),`${meta.label} · ${status(books[meta.timeframe],now)}`);
      }
      if(meta?.kind==='forecast') forecast(plot,meta,quote,now);
    }
    dirty=false;
  }
  function stop() {if(timer!==null) clearTimeout(timer);timer=null;latestQuote=null;for(const b of Object.values(books)) if(b.candle) b.candle.event=0;dirty=true;}
  return {accept,paint,stop,hold(plot,on){if(plot) {if(on) held.add(plot);else held.delete(plot);}},
    dispose(){stop();disposed=true;books={};host=null;payload=null;},get dirty(){return dirty;}};
}
const liveAnalysis=makeLiveAnalysis(window.parent);
