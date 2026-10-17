/* Free price cursor, long-press inspection and horizontal chart panning. */
const chartReader = (() => {
  let root, doc;
  try { root = window.parent; doc = root.document; } catch (_) { return {inspect(){},dispose(){}}; }
  const cards = new WeakMap();
  const {values,times,nearest}=PlotData;
  const money = Object.fromEntries([2,4].map(n => [n,new Intl.NumberFormat('en-US',{minimumFractionDigits:n,maximumFractionDigits:n})]));
  let active = null, pending = null, frame = null, pressTimer = null, last = null;

  function write(el,value) { if(el && el.textContent!==value) el.textContent=value; }
  function reader(plot) {
    const meta=plot?.layout?.meta?.btcLive;
    const node=doc.getElementById(meta?.kind==='forecast' ? 'btc-forecast-reader' : 'btc-chart-reader');
    return node && meta?.symbol===node.dataset.symbol && (meta.kind!=='market' || meta.timeframe===node.dataset.timeframe) ? node : null;
  }
  function number(node,key,n) {
    let state=cards.get(node);if(!state){state={};cards.set(node,state);}
    const text=Number.isFinite(n) ? money[node.dataset.decimals || 2].format(n) : '—';
    if(state[key]!==text){state[key]=text;write(node.querySelector(`[data-field="${key}"]`),text);}
  }
  function inspect(plot,x,mode='inspect',price) {
    const node=reader(plot),meta=plot?.layout?.meta?.btcLive,axis=plot?._fullLayout?.xaxis;
    if(!node || !axis)return;
    const candle=plot.data.find(t=>t.type==='candlestick');
    if(meta.kind==='market' && candle?.x?.length){
      const ts=times(candle.x,axis),i=nearest(ts,x);
      for(const key of ['open','high','low','close'])number(node,key,values(candle[key])[i]);
      for(const [index,key] of Object.entries(meta.overlays ?? {})){
        const trace=plot.data[index],tx=times(trace.x,axis),j=nearest(tx,ts[i]);
        number(node,key,tx[j]===ts[i] ? values(trace.y)[j] : NaN);
      }
      write(node.querySelector('[data-reader-time]'),`${String(axis.c2r(ts[i])).slice(0,16)} KST · ${mode==='latest'?'최신 봉':'선택한 봉'}`);
      node.dataset.index=String(i);node.dataset.at=String(ts[i]);
      if(mode==='latest')price=values(candle.close)[i];
    } else if(meta.kind==='forecast') {
      for(const [index,key] of Object.entries(meta.indicatorOverlays ?? {})){
        const trace=plot.data[index],tx=times(trace.x,axis),i=nearest(tx,x);
        number(node,key,x<tx[0] || x>tx.at(-1) ? NaN : values(trace.y)[i]);
      }
      write(node.querySelector('[data-reader-time]'),`${String(axis.c2r(x)).slice(0,16)} KST · 경로 가정의 지표`);
    }
    if(Number.isFinite(price))number(node,'cursor',price);
    node.dataset.mode=mode;
  }
  function clearCursor() {
    if(last){last.layer.hidden=true;last=null;}
  }
  function geometry(target) {
    const rect=target.closest?.('.nsewdrag'),plot=rect?.closest('.js-plotly-plot');
    if(!plot || plot._fullLayout?.dragmode!==false || !root.Plotly)return null;
    const subplot=Object.keys(plot._fullLayout._plots || {}).find(key=>rect.parentElement.classList.contains(key));
    const axes=plot._fullLayout._plots[subplot];
    return axes ? {plot,rect,subplot,axis:axes.xaxis,yaxis:axes.yaxis} : null;
  }
  function show(point) {
    if(!point.plot.isConnected)return;
    const bounds=point.rect.getBoundingClientRect(),box=point.plot.getBoundingClientRect();
    const px=Math.max(0,Math.min(bounds.width,point.x-bounds.left));
    const py=Math.max(0,Math.min(bounds.height,point.y-bounds.top));
    const x=point.axis.p2c(px),price=point.yaxis.p2c(py);
    if(!['market','forecast'].includes(point.plot.layout?.meta?.btcLive?.kind)){
      root.Plotly.Fx.hover(point.plot,{xval:x,yval:price},[point.subplot]);return;
    }
    if(last?.plot!==point.plot)clearCursor();
    let layer=point.plot.querySelector('.btc-crosshair');
    if(!layer){
      layer=doc.createElement('div');layer.className='btc-crosshair';
      layer.innerHTML='<i class="btc-crosshair-x"></i><i class="btc-crosshair-y"></i><b class="btc-crosshair-price"></b><span class="btc-crosshair-time"></span>';
      point.plot.style.position='relative';point.plot.append(layer);
    }
    layer.hidden=false;last={plot:point.plot,layer};
    const left=bounds.left-box.left,top=bounds.top-box.top;
    Object.assign(layer.querySelector('.btc-crosshair-x').style,{left:left+px+'px',top:top+'px',height:bounds.height+'px'});
    Object.assign(layer.querySelector('.btc-crosshair-y').style,{left:left+'px',top:top+py+'px',width:bounds.width+'px'});
    const priceNode=layer.querySelector('.btc-crosshair-price');
    priceNode.style.top=top+py-11+'px';priceNode.style.left=Math.max(0,left+bounds.width-72)+'px';
    const precision=reader(point.plot)?.dataset.decimals || 2;
    write(priceNode,money[precision].format(price));
    const timeNode=layer.querySelector('.btc-crosshair-time');
    timeNode.style.top=top+bounds.height-19+'px';timeNode.style.left=Math.max(left,Math.min(left+bounds.width-128,left+px-64))+'px';
    write(timeNode,String(point.axis.c2r(x)).slice(0,16));
    point.plot.dataset.cursorPrice=String(price);point.plot.dataset.cursorX=String(x);
    inspect(point.plot,x,'inspect',price);
  }
  function queue(work) {
    pending=work;
    if(frame===null)frame=root.requestAnimationFrame(()=>{frame=null;const latest=pending;pending=null;latest?.();});
  }
  function cancel() {
    if(pressTimer!==null)root.clearTimeout(pressTimer);pressTimer=null;
    if(frame!==null)root.cancelAnimationFrame(frame);frame=null;pending=null;
    if(active)liveAnalysis.hold(active.plot,false);active=null;
  }
  function pan(point,state=active) {
    if(!state || !state.plot.isConnected)return;
    if(state.busy){state.next=point;return;}
    const bounds=state.rect.getBoundingClientRect();
    const shift=(point.x-state.x)/bounds.width*(state.range[1]-state.range[0]);
    const range=state.range.map(n=>state.axis.c2r(n-shift));
    state.busy=true;clearCursor();
    const shiftY=(point.y-state.y)/bounds.height*(state.yRange[1]-state.yRange[0]);
    root.Plotly.relayout(state.plot,{'xaxis.range':range,'xaxis2.range':range,'yaxis.range':state.yRange.map(n=>n+shiftY)}).catch(()=>{}).finally(()=>{state.busy=false;if(state.next && (!active || active===state)){const next=state.next;state.next=null;pan(next,state);}});
  }
  function start(event) {
    cancel();clearCursor();
    if(event.touches?.length!==1)return;
    const part=geometry(event.target);if(!part)return;
    event.stopPropagation();
    const p=event.touches[0];
    active={...part,x:p.clientX,y:p.clientY,mode:'pending',range:part.axis.range.map(n=>part.axis.r2c(n)),yRange:part.yaxis.range.map(Number)};
    liveAnalysis.hold(part.plot,true);show(active);
    pressTimer=root.setTimeout(()=>{pressTimer=null;if(active)active.mode='inspect';},350);
  }
  function move(event) {
    if(!active)return;
    if(event.touches.length!==1){cancel();clearCursor();return;}
    const p=event.touches[0],dx=p.clientX-active.x,dy=p.clientY-active.y;
    if(active.mode==='pending'){
      if(Math.abs(dy)>8 && Math.abs(dy)>Math.abs(dx)){cancel();clearCursor();return;}
      if(Math.abs(dx)>8){active.mode='pan';root.clearTimeout(pressTimer);pressTimer=null;}
    }
    event.stopPropagation();
    if(active.mode!=='pending' && event.cancelable)event.preventDefault();
    const point={...active,x:p.clientX,y:p.clientY};
    queue(()=>active && (active.mode==='pan'?pan(point):show(point)));
  }
  function end(event) {
    if(active){event.stopPropagation();if(pending){const work=pending;pending=null;work();}}
    cancel();
  }
  function mouse(event) {
    if(event.sourceCapabilities?.firesTouchEvents)return;
    const part=geometry(event.target);
    if(!part){if(!active)clearCursor();return;}
    if(active?.mouse){queue(()=>pan({x:event.clientX,y:event.clientY}));return;}
    queue(()=>show({...part,x:event.clientX,y:event.clientY}));
  }
  function mouseStart(event) {
    if(event.button!==0 || event.sourceCapabilities?.firesTouchEvents)return;
    const part=geometry(event.target);if(!part || !reader(part.plot))return;
    event.stopPropagation();active={...part,x:event.clientX,y:event.clientY,mouse:true,range:part.axis.range.map(n=>part.axis.r2c(n)),yRange:part.yaxis.range.map(Number)};
    liveAnalysis.hold(part.plot,true);
  }
  function navigate(event) {
    const button=event.target.closest?.('[data-chart-action]');if(!button)return;
    const plot=Array.from(doc.querySelectorAll('.js-plotly-plot')).find(p=>p.layout?.meta?.btcLive?.kind==='market');
    const candle=plot?.data.find(t=>t.type==='candlestick');if(!candle)return;
    const axis=plot._fullLayout.xaxis,ts=times(candle.x,axis),span=plot.layout.meta.btcLive.window ?? 60,last=ts.length-1;
    let end=nearest(ts,axis.r2c(axis.range[1]));
    end=button.dataset.chartAction==='latest'?last:Math.min(last,Math.max(Math.min(span-1,last),end+(button.dataset.chartAction==='previous'?-1:1)*Math.ceil(span*.65)));
    const begin=Math.max(0,end-span+1),step=last?ts[last]-ts[last-1]:86400000;
    const range=[axis.c2r(ts[begin]-step*.7),axis.c2r(ts[end]+step*1.5)];
    root.Plotly.relayout(plot,{'xaxis.range':range,'xaxis2.range':range,'yaxis.autorange':true}).then(()=>inspect(plot,ts[end],button.dataset.chartAction==='latest'?'latest':'inspect')).catch(()=>{});
    clearCursor();
  }
  function abort(){cancel();clearCursor();}
  function hidden(){if(doc.hidden){cancel();clearCursor();}}
  const listeners=[['visibilitychange',hidden,{capture:false}],['touchstart',start,{capture:true,passive:true}],['touchmove',move,{capture:true,passive:false}],['touchend',end,{capture:true,passive:true}],['touchcancel',abort,{capture:true,passive:true}],['mousemove',mouse,{capture:true,passive:true}],['mousedown',mouseStart,{capture:true,passive:true}],['mouseup',cancel,{capture:true,passive:true}],['click',navigate,{capture:false}]];
  for(const [name,handler,options] of listeners)doc.addEventListener(name,handler,options);
  return {inspect,dispose(){cancel();clearCursor();for(const [name,handler,options] of listeners)doc.removeEventListener(name,handler,options);doc.querySelectorAll('.btc-crosshair').forEach(n=>n.remove());}};
})();
