"""Candle inspection stays in the browser; no requests or Python reruns."""

from html import escape
import math

from btc_analyzer.assets import ASSETS, price_text

FIELDS = {
    "open": "시가",
    "high": "고가",
    "low": "저가",
    "close": "종가",
    "ema_20": "EMA 20",
    "ema_50": "EMA 50",
    "ema_200": "EMA 200",
    "bb_upper": "볼린저 상단",
    "bb_middle": "볼린저 중심",
    "bb_lower": "볼린저 하단",
}


def reader_html(frame, timeframe, asset_code, averages, bands):
    keys = ["open", "high", "low", "close", *averages]
    if bands:
        keys.extend(("bb_upper", "bb_middle", "bb_lower"))
    row = frame.iloc[-1]

    def value(key):
        n = row.get(key)
        return price_text(n) if n is not None and math.isfinite(n) else "—"

    cells = "".join(
        f'<div class="btc-read-{key}"><span>{FIELDS[key]}</span><b data-field="{key}">{value(key)}</b></div>'
        for key in keys
    )
    at = frame.index[-1].tz_convert("Asia/Seoul").strftime("%m.%d %H:%M")
    return (
        f'<section id="btc-chart-reader" class="btc-chart-reader" data-symbol="{ASSETS[asset_code].stream_symbol}" '
        f'data-timeframe="{escape(timeframe)}" data-decimals="{ASSETS[asset_code].decimals}" data-mode="latest" '
        'aria-label="가리킨 봉의 가격과 지표">'
        f'<div class="btc-reader-heading"><span data-reader-time>{at} KST · 마지막 확정 봉</span><span>USDT</span></div>'
        f'<div class="btc-reader-values">{cells}</div>'
        '<div class="btc-chart-nav" aria-label="차트 구간 이동">'
        '<button type="button" data-chart-action="previous" aria-label="이전 차트 구간">← 이전 구간</button>'
        '<button type="button" data-chart-action="latest">최신 봉</button>'
        '<button type="button" data-chart-action="next" aria-label="다음 차트 구간">다음 구간 →</button></div>'
        "</section>"
    )


CHART_READER_JS = r"""
const chartReader=(()=>{
  let root,doc;try{root=window.parent;doc=root.document;}catch(_){return {inspect(){},dispose(){}};}
  const decoded=new WeakMap(), dates=new WeakMap(), readouts=new WeakMap();let pending=null,frame=null;
  const formats=Object.fromEntries([2,4].map(n=>[n,new Intl.NumberFormat('en-US',{minimumFractionDigits:n,maximumFractionDigits:n})]));
  const host=()=>doc.getElementById('btc-chart-reader');
  function values(value){
    if(!value)return [];
    if(Array.isArray(value)||ArrayBuffer.isView(value))return value;
    if(decoded.has(value))return decoded.get(value);
    if(!value.bdata)return [];
    const bytes=Uint8Array.from(atob(value.bdata),c=>c.charCodeAt(0));
    const Type={f8:Float64Array,f4:Float32Array,i4:Int32Array,i2:Int16Array,i1:Int8Array,u4:Uint32Array,u2:Uint16Array,u1:Uint8Array}[value.dtype];
    const result=Type?new Type(bytes.buffer):[];decoded.set(value,result);return result;
  }
  function times(xs,axis){
    if(!dates.has(xs))dates.set(xs,Array.from(xs,x=>axis.d2c(x)));
    return dates.get(xs);
  }
  function nearest(xs,x){
    let lo=0,hi=xs.length-1;
    while(lo<hi){const mid=(lo+hi)>>1;if(xs[mid]<x)lo=mid+1;else hi=mid;}
    return lo>0 && Math.abs(xs[lo-1]-x)<Math.abs(xs[lo]-x)?lo-1:lo;
  }
  function inspect(plot,x,mode='inspect'){
    const node=host(),meta=plot?.layout?.meta?.btcLive;
    if(!node || meta?.kind!=='market' || meta.symbol!==node.dataset.symbol || meta.timeframe!==node.dataset.timeframe)return;
    const candle=plot.data?.find(t=>t.type==='candlestick'),axis=plot._fullLayout?.xaxis;
    if(!candle || !axis || !candle.x?.length)return;
    const ts=times(candle.x,axis),i=nearest(ts,x);
    let state=readouts.get(node);if(!state){state={};readouts.set(node,state);}
    const money=n=>Number.isFinite(n)?formats[node.dataset.decimals].format(n):'—';
    const write=(el,value)=>{if(el && el.textContent!==value)el.textContent=value;};
    function price(key,n){if(Object.is(state[key],n))return;state[key]=n;write(node.querySelector(`[data-field="${key}"]`),money(n));}
    for(const key of ['open','high','low','close'])price(key,values(candle[key])[i]);
    for(const [index,key] of Object.entries(meta.overlays??{})){
      const trace=plot.data[index],tx=times(trace.x,axis),j=nearest(tx,ts[i]);
      price(key,tx[j]===ts[i]?values(trace.y)[j]:NaN);
    }
    const at=String(axis.c2r(ts[i])).slice(0,16).replace('T',' ');
    write(node.querySelector('[data-reader-time]'),`${at} KST · ${mode==='latest'?'최신 봉':'선택한 봉'}`);
    node.dataset.mode=mode;node.dataset.index=String(i);node.dataset.at=String(ts[i]);
  }
  function point(event){
    const rect=event.target.closest?.('.nsewdrag'),plot=rect?.closest('.js-plotly-plot');
    if(plot?.layout?.meta?.btcLive?.kind!=='market')return;
    const axis=plot._fullLayout?.xaxis,bounds=rect.getBoundingClientRect();
    pending={plot,x:axis.p2c(Math.max(0,Math.min(bounds.width,event.clientX-bounds.left)))};
    if(frame===null)frame=root.requestAnimationFrame(()=>{frame=null;if(pending){inspect(pending.plot,pending.x);pending=null;}});
  }
  function click(event){
    const button=event.target.closest?.('[data-chart-action]');if(!button)return;
    const node=host(),plot=Array.from(doc.querySelectorAll('.js-plotly-plot')).find(p=>p.layout?.meta?.btcLive?.kind==='market');
    const candle=plot?.data?.find(t=>t.type==='candlestick');if(!candle || !node)return;
    const axis=plot._fullLayout.xaxis,ts=times(candle.x,axis),span=plot.layout.meta.btcLive.window??60;
    const last=ts.length-1,range=axis.range.map(x=>axis.r2c(x));
    let end=nearest(ts,range[1]);
    if(button.dataset.chartAction==='latest')end=last;
    else end=Math.min(last,Math.max(Math.min(span-1,last),end+(button.dataset.chartAction==='previous'?-1:1)*Math.ceil(span*.65)));
    const start=Math.max(0,end-span+1),step=last?ts[last]-ts[last-1]:86400000;
    const bounds=[axis.c2r(ts[start]-step*.7),axis.c2r(ts[end]+step*1.5)];
    const high=values(candle.high),low=values(candle.low);
    const ys=[...high.slice(start,end+1),...low.slice(start,end+1)].filter(Number.isFinite);
    for(const index of Object.keys(plot.layout.meta.btcLive.overlays??{}))ys.push(...values(plot.data[index].y).slice(start,end+1).filter(Number.isFinite));
    const changes={'xaxis.range':bounds,'xaxis2.range':bounds};
    if(ys.length){const min=Math.min(...ys),max=Math.max(...ys),pad=(max-min||max*.005)*.09;changes['yaxis.range']=[min-pad,max+pad];}
    root.Plotly.relayout(plot,changes).then(()=>inspect(plot,ts[end],button.dataset.chartAction==='latest'?'latest':'inspect')).catch(()=>{});
  }
  doc.addEventListener('mousemove',point,{passive:true});doc.addEventListener('click',click);
  return {inspect,dispose(){doc.removeEventListener('mousemove',point);doc.removeEventListener('click',click);if(frame!==null)root.cancelAnimationFrame(frame);pending=null;}};
})();
"""
