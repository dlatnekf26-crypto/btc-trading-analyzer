"""Small, exact indicator seeds and a browser-owned provisional candle layer."""

from html import escape
import json

import numpy as np
import streamlit as st

from btc_analyzer.candles import candle_close
from btc_analyzer.config import COMPOSITE_TIMEFRAMES
from btc_analyzer.indicators.core import wilder
from btc_analyzer.ui.cache_keys import MARKET_HASH_FUNCS


@st.cache_data(ttl=3600, max_entries=12, show_spinner=False, hash_funcs=MARKET_HASH_FUNCS)
def live_seed_json(enriched, cfg):
    """Continue recursive indicators from the entire last contiguous segment.

    Only 80 rolling OHLCV samples are sent. Recursive EMA/Wilder states retain
    their full history, avoiding the bias of recalculating from a short tail.
    The caller supplies already closed, gap-aware feature frames.
    """
    frames = {}
    for tf in COMPOSITE_TIMEFRAMES:
        frame = enriched.get(tf)
        if frame is None or frame.empty:
            continue
        count = int(frame.bars_since_gap.iloc[-1])
        segment = frame.tail(count)
        close = segment.close
        delta = close.diff()
        row = frame.iloc[-1]

        def number(value):
            return float(value) if np.isfinite(value) else None

        ema = {
            str(n): number(close.ewm(span=n, adjust=False).mean().iloc[-1])
            for n in set((*cfg.ema_lengths, cfg.macd_fast, cfg.macd_slow))
        }
        line = close.ewm(span=cfg.macd_fast, adjust=False, min_periods=cfg.macd_fast).mean() - (
            close.ewm(span=cfg.macd_slow, adjust=False, min_periods=cfg.macd_slow).mean()
        )
        frames[tf] = {
            "at": int(frame.index[-1].timestamp() * 1000),
            "end": int(candle_close(frame.index[-1], tf).timestamp() * 1000),
            "count": count,
            "ema": ema,
            "gain": number(wilder(delta.clip(lower=0), cfg.rsi_length).iloc[-1]),
            "loss": number(wilder(-delta.clip(upper=0), cfg.rsi_length).iloc[-1]),
            "signal": number(line.ewm(span=cfg.macd_signal, adjust=False).mean().iloc[-1]),
            "atr": number(row.atr),
            "rows": [
                [int(t.timestamp() * 1000), *map(float, values)]
                for t, values in segment[["open", "high", "low", "close", "volume"]].tail(80).iterrows()
            ],
        }
    parameters = {
        key: getattr(cfg, key)
        for key in (
            "rsi_length",
            "atr_length",
            "bb_length",
            "bb_std",
            "macd_fast",
            "macd_slow",
            "macd_signal",
            "ichimoku_conversion",
            "ichimoku_base",
            "ichimoku_span_b",
            "ichimoku_displacement",
        )
    }
    return json.dumps({"frames": frames, "cfg": parameters}, separators=(",", ":"), allow_nan=False)


def render_live_analysis(enriched, cfg):
    seeds = {
        tf: frame[["open", "high", "low", "close", "volume", "bars_since_gap", "atr"]]
        for tf, frame in enriched.items()
        if tf in COMPOSITE_TIMEFRAMES and not frame.empty
    }
    payload = escape(live_seed_json(seeds, cfg), quote=True)
    st.markdown(
        f'<section id="btc-live-analysis" data-seeds="{payload}" aria-label="실시간 잠정 분석">'
        '<div class="btc-live-heading"><strong>지금, 다섯 시간대</strong>'
        '<span class="btc-live-status">진행 중 봉 연결 대기</span></div>'
        '<div class="btc-live-frames">'
        + "".join(
            f'<article data-tf="{tf}"><b>{label}</b><strong>—</strong><span>봉 수신 대기</span>'
            '<span class="btc-live-volatility"></span></article>'
            for tf, label in zip(COMPOSITE_TIMEFRAMES, ("1시간", "4시간", "일봉", "주봉", "월봉"))
        )
        + '</div><p class="btc-live-note">진행 중 봉의 EMA·RSI·MACD·변동성·일목을 갱신해요. '
        "봉 마감 전 값은 바뀌며, 종합 매수·매도와 과거 검증은 확정 봉 기준이에요.</p></section>",
        unsafe_allow_html=True,
    )


LIVE_ANALYSIS_CSS = """<style>
#btc-live-analysis,.btc-live-forecast{border:1px solid #e7ecf3;background:linear-gradient(120deg,#fff,#f5f9ff);border-radius:18px;padding:14px 16px;margin:10px 0}
.btc-live-heading{display:flex;gap:12px;justify-content:space-between;align-items:center;flex-wrap:wrap}.btc-live-heading strong{font-size:15px;color:#192434}
.btc-live-status,.btc-live-note,.btc-live-forecast p{font-size:12px;color:#66758b;line-height:1.55;margin:6px 0 0}
.btc-live-frames{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;margin-top:12px}.btc-live-frames article{display:flex;flex-direction:column;gap:5px;min-width:0}
.btc-live-frames b{font-size:11px;color:#66758b}.btc-live-frames strong{font-size:15px;color:#192434}.btc-live-frames span{font-size:11px;color:#66758b}.btc-live-frames article[data-direction="1"] strong{color:#09845c}.btc-live-frames article[data-direction="-1"] strong{color:#d63851}
.btc-live-forecast strong{font-size:20px;color:#09845c;font-variant-numeric:tabular-nums}.btc-live-forecast .btc-live-status{display:block}
@media(max-width:600px){.btc-live-frames{grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.btc-live-status{font-size:11px}#btc-live-analysis,.btc-live-forecast{padding:12px}}
</style>"""


LIVE_ANALYSIS_JS = r"""
// Pure UTC/protocol/indicator functions are also exercised against Python's
// gap-aware full-history indicators. No SDK, extra socket or Python tick event.
const LiveCandles = (()=>{
  const frames=['1h','4h','1d','1w','1M'];
  const finite=n=>typeof n==='number' && Number.isFinite(n);
  function boundary(time,tf) {
    const d=new Date(time);
    if(tf==='1M') return Date.UTC(d.getUTCFullYear(),d.getUTCMonth(),1);
    if(tf==='1w') return Date.UTC(d.getUTCFullYear(),d.getUTCMonth(),d.getUTCDate()-(d.getUTCDay()+6)%7);
    const span={'1h':3600000,'4h':14400000,'1d':86400000}[tf];
    return Math.floor(time/span)*span;
  }
  function end(time,tf) {
    const d=new Date(time);
    return tf==='1M' ? Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+1,1) :
      time+({'1h':3600000,'4h':14400000,'1d':86400000,'1w':604800000}[tf]);
  }
  function parse(packet,now) {
    const k=packet?.k, tf=k?.i;
    if(packet?.e!=='kline' || packet.s!=='BTCUSDT' || k?.s!=='BTCUSDT' || !frames.includes(tf) ||
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
  return {frames,finite,boundary,end,parse,advance};
})();

function makeLiveAnalysis(root) {
  let doc;
  try {doc=root.document;} catch(_) {return {accept(){},paint(){},stop(){},dispose(){}};}
  let host=null,payload=null,cfg=null,books={},dirty=true,lastPaint=0,disposed=false,timer=null,latestQuote=null;
  const plots=new WeakMap(),held=new WeakSet(),invalidWatch=new WeakSet(),formatters=new Map();
  function array(value) {
    if(value?.bdata) {
      const types={f8:Float64Array,f4:Float32Array,i4:Int32Array,i2:Int16Array,i1:Int8Array,u4:Uint32Array,u2:Uint16Array,u1:Uint8Array};
      const Type=types[value.dtype];
      if(!Type) throw new TypeError('Unsupported chart array');
      const bytes=Uint8Array.from(atob(value.bdata),c=>c.charCodeAt(0));
      return Array.from(new Type(bytes.buffer));
    }
    return Array.from(value?._inputArray ?? value ?? []);
  }
  const clock=new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'});
  function text(node,value) {if(node && node.textContent!==value) node.textContent=value;}
  function displayDate(time,zone='Asia/Seoul') {
    if(!formatters.has(zone)) formatters.set(zone,new Intl.DateTimeFormat('en-CA',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}));
    const p=Object.fromEntries(formatters.get(zone).formatToParts(new Date(time)).map(p=>[p.type,p.value]));
    return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}:${p.second}`;
  }
  function load() {
    const node=doc.getElementById('btc-live-analysis'),raw=node?.dataset.seeds;
    if(node!==host) {host=node;dirty=true;}
    if(!raw || raw===payload) return;
    try {
      const parsed=JSON.parse(raw); cfg=parsed.cfg;
      for(const tf of LiveCandles.frames) {
        const seed=parsed.frames[tf],book=books[tf];
        if(seed && (!book || seed.at>book.seed.at)) {
          const candle=book?.candle;
          books[tf]={seed,candle:candle?.at===seed.end ? candle : null,features:null};
          if(books[tf].candle) books[tf].features=LiveCandles.advance(seed,candle,cfg)?.features ?? null;
        }
      }
      payload=raw;dirty=true;
    } catch(_) { /* Incomplete DOM replacement is retried on the next heartbeat. */ }
  }
  function accept(packet) {
    load(); const k=LiveCandles.parse(packet,Date.now());
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
      // Overlays from the server remain explicitly closed-candle geometry.
      // A marker adds the current price without moving axes or hiding hover.
      plot.dataset.liveEvent=String(k.event);plot.dataset.livePrice=String(k.row[4]);plot.dataset.liveTimeframe=k.tf;
      const summary=doc.querySelector('.btc-chart-summary');
      text(summary?.querySelector('strong'),`${k.row[4].toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})} USDT`);
      text(summary?.querySelector('span'),`${meta.label} · 진행 중 봉 · ${clock.format(new Date(k.event))} KST`);
      text(summary?.querySelector('span:last-child'),`현재 봉 ${k.row[4]/k.row[1]-1>=0 ? '+' : ''}${((k.row[4]/k.row[1]-1)*100).toFixed(2)}% · EMA/밴드 잠정 · 일목 구름은 확정 봉`);
    });
  }
  function forecast(plot,meta,quote,now) {
    const card=doc.getElementById('btc-live-forecast');
    const live=quote?.fresh && LiveCandles.finite(quote.price) && quote.price>0 && quote.event>=meta.baseAt &&
      quote.event<=now+3000 && now-quote.event<=15000;
    const active=LiveCandles.frames.filter(tf=>current(books[tf],now));
    text(card?.querySelector('.btc-live-status'),live ? `현재가 출발 · ${clock.format(new Date(quote.event))} KST · 잠정 지표 ${active.length}/5` : '시세 수신 대기/지연 · 조건부 경로 갱신 보류');
    if(!live) return;
    const ratio=quote.price/meta.anchor, center=meta.center.map(y=>y*ratio), lower=meta.lower.map(y=>y*ratio), upper=meta.upper.map(y=>y*ratio);
    const money=n=>n.toLocaleString('en-US',{maximumFractionDigits:2,minimumFractionDigits:2});
    text(card?.querySelector('strong'),`${money(center.at(-1))} USDT`);
    text(card?.querySelector('.btc-live-forecast-range'),`현재 ${money(quote.price)} → ${meta.label} · 범위 ${money(lower.at(-1))} ~ ${money(upper.at(-1))}`);
    const directions=active.map(tf=>metrics(books[tf].features,books[tf].candle.row[4]).trend);
    const up=directions.filter(n=>n>0).length,down=directions.filter(n=>n<0).length;
    text(card?.querySelector('.btc-live-forecast-reason'),`${up}개 시간대 20봉선 위 · ${down}개 아래. 현재가로 출발점을 바꾸고 기존 지표·유사 사례의 수익률 경로/방향 비중을 유지해요. 잠정 지표는 관찰 근거이며 추가 가격 가중치로 쓰지 않아요.`);
    const xs=meta.offsets.map(t=>displayDate(quote.event+t,meta.timezone));
    update(plot,`${quote.event}-${quote.price}`,async()=>{
      await root.Plotly.restyle(plot,{x:[xs,xs,xs],y:[upper,lower,center]},meta.liveIndices);
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
    let state='waiting',label='시세 수신 대기/지연 · 가격대 도달 확인을 보류해요.';
    const fresh=quote?.fresh && LiveCandles.finite(quote.price) && quote.price>0 && LiveCandles.finite(quote.event) &&
      quote.event>=base && quote.event<=now+3000 && now-quote.event<=15000;
    if(now>=expires) {state='expired';label='확정 봉 갱신 대기 · 가격대를 다시 계산하고 있어요.';}
    else if(fresh) {
      if(quote.price<Math.max(stop,riskFloor)) invalidWatch.add(card);
      if(invalidWatch.has(card)) {state='invalid';label='급락 또는 지지 기준 이탈 · 새 확정 자료로 다시 확인해요.';}
      else if(quote.price>high) {state='above';label=`현재가에서 ${((1-high/quote.price)*100).toFixed(2)}% 내려오면 검토 가격대예요.`;}
      else if(quote.price>=low) {state='inside';label='현재가가 검토 가격대에 있어요 · 하락 진정을 확인해요.';}
      else {state='below';label='현재가가 가격대 아래예요 · 더 저렴하다고 매수하지 않고 지지를 다시 확인해요.';}
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
    load();const now=Date.now();lastPaint=now;watchDistance(quote,now);
    if(host) {
      const active=LiveCandles.frames.filter(tf=>current(books[tf],now));
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
"""
