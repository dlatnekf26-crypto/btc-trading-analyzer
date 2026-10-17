// Pure UTC/protocol/indicator functions are also exercised against Python's
// gap-aware full-history indicators. No SDK, extra socket or Python tick event.
const LiveCandles = (()=>{
  const analysisFrames=['1h','4h','1d','1w','1M'],frames=['5m','15m',...analysisFrames];
  const finite=n=>typeof n==='number' && Number.isFinite(n);
  function boundary(time,tf) {
    const d=new Date(time);
    if(tf==='1M') return Date.UTC(d.getUTCFullYear(),d.getUTCMonth(),1);
    if(tf==='1w') return Date.UTC(d.getUTCFullYear(),d.getUTCMonth(),d.getUTCDate()-(d.getUTCDay()+6)%7);
    const span={'5m':300000,'15m':900000,'1h':3600000,'4h':14400000,'1d':86400000}[tf];
    return Math.floor(time/span)*span;
  }
  function end(time,tf) {
    const d=new Date(time);
    return tf==='1M' ? Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+1,1) :
      time+({'5m':300000,'15m':900000,'1h':3600000,'4h':14400000,'1d':86400000,'1w':604800000}[tf]);
  }
  function parse(packet,now,symbol='BTCUSDT') {
    const k=packet?.k, tf=k?.i;
    if(packet?.e!=='kline' || packet.s!==symbol || k?.s!==symbol || !frames.includes(tf) ||
       !Number.isSafeInteger(packet.E) || packet.E>now+3000 || now-packet.E>15000 ||
       !Number.isSafeInteger(k.t) || !Number.isSafeInteger(k.T) || k.t!==boundary(k.t,tf) ||
       k.T!==end(k.t,tf)-1 || packet.E<k.t || typeof k.x!=='boolean' ||
       (k.x ? packet.E<k.T : boundary(now,tf)!==k.t)) return null;
    const raw=[k.o,k.h,k.l,k.c,k.v];
    if(raw.some(v=>!(typeof v==='number' || (typeof v==='string' && /^\d+(\.\d+)?$/.test(v))))) return null;
    const values=raw.map(Number), [o,h,l,c,v]=values;
    if(!values.every(finite) || [o,h,l,c].some(n=>n<=0) || v<0 || h<Math.max(o,c) || l>Math.min(o,c) || h<l) return null;
    return {tf,at:k.t,end:k.T+1,event:packet.E,closed:k.x,row:[k.t,...values]};
  }
  function advance(seed,k,cfg) {
    if(!seed || k.at!==seed.end) return null; // Never smooth across missing candles.
    const rows=[...seed.rows,k.row].slice(-80), closes=rows.map(r=>r[4]), n=seed.count+1, price=k.row[4];
    const ema={};
    for(const [length,value] of Object.entries(seed.ema)) ema[length]=value+(price-value)*2/(Number(length)+1);
    const delta=price-seed.rows.at(-1)[4], gains=Math.max(0,delta), losses=Math.max(0,-delta), r=cfg.rsi_length;
    const smooth=(prior,value,length,samples)=>finite(prior) ? (prior*(length-1)+value)/length :
      samples.length>=length ? samples.slice(-length).reduce((a,b)=>a+b,0)/length : null;
    const differences=closes.slice(1).map((c,i)=>c-closes[i]);
    const gain=smooth(seed.gain,gains,r,differences.map(d=>Math.max(0,d)));
    const loss=smooth(seed.loss,losses,r,differences.map(d=>Math.max(0,-d)));
    const line=n>=cfg.macd_slow ? ema[cfg.macd_fast]-ema[cfg.macd_slow] : null;
    const signal=finite(line) ? (finite(seed.signal) ? seed.signal+(line-seed.signal)*2/(cfg.macd_signal+1) : line) : null;
    const tr=rows.map((row,i)=>Math.max(row[2]-row[3],i ? Math.abs(row[2]-rows[i-1][4]) : 0,i ? Math.abs(row[3]-rows[i-1][4]) : 0));
    const atr=smooth(seed.atr,tr.at(-1),cfg.atr_length,tr);
    function midpoint(length,offset=0) {
      const stop=rows.length-offset, part=rows.slice(Math.max(0,stop-length),stop);
      return stop>=length ? (Math.max(...part.map(r=>r[2]))+Math.min(...part.map(r=>r[3])))/2 : null;
    }
    const tenkan=midpoint(cfg.ichimoku_conversion), kijun=midpoint(cfg.ichimoku_base);
    const a1=midpoint(cfg.ichimoku_conversion,cfg.ichimoku_displacement),a2=midpoint(cfg.ichimoku_base,cfg.ichimoku_displacement);
    const cloudA=finite(a1)&&finite(a2) ? (a1+a2)/2 : null,cloudB=midpoint(cfg.ichimoku_span_b,cfg.ichimoku_displacement);
    const window=closes.slice(-cfg.bb_length), mean=window.reduce((a,b)=>a+b,0)/window.length;
    const deviation=Math.sqrt(window.reduce((s,c)=>s+(c-mean)**2,0)/window.length)*cfg.bb_std;
    const features={rsi:!finite(gain)||!finite(loss) ? null : loss===0 ? (gain===0 ? 50 : 100) : 100-100/(1+gain/loss),
      macd_hist:n>=cfg.macd_slow+cfg.macd_signal-1 ? line-signal : null,atr,atr_pct:finite(atr) ? atr/price*100 : null,
      bb_middle:n>=cfg.bb_length ? mean : null,bb_upper:n>=cfg.bb_length ? mean+deviation : null,bb_lower:n>=cfg.bb_length ? mean-deviation : null,
      ichimoku_tenkan:tenkan,ichimoku_kijun:kijun,ichimoku_cloud_a:cloudA,ichimoku_cloud_b:cloudB};
    for(const [length,value] of Object.entries(ema)) features['ema_'+length]=n>=Number(length) ? value : null;
    return {at:k.at,end:k.end,count:n,rows,ema,gain,loss,signal,atr,features};
  }
  return {frames,analysisFrames,finite,boundary,end,parse,advance};
})();
