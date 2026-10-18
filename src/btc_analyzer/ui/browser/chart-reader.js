/* Local pan/pinch, visible-candle auto scale and a free price cursor. */
const chartReader = (() => {
  let root,doc;
  try {root=window.parent;doc=root.document;}catch(_){return {inspect(){},refresh(){},currentQuote(){},dispose(){}};}
  const {values,times,nearest}=PlotData, view=ChartViewport;
  const states=new WeakMap(),cards=new WeakMap();
  const money=Object.fromEntries([2,4,6,8].map(n=>[n,new Intl.NumberFormat('en-US',{minimumFractionDigits:n,maximumFractionDigits:n})]));
  let active=null,pending=null,raf=null,pressTimer=null,last=null,disposed=false;
  const write=(el,value)=>{if(el && el.textContent!==value)el.textContent=value;};
  function state(plot) {
    const revision=plot.layout?.uirevision ?? '';
    let s=states.get(plot);
    if(!s || s.revision!==revision){s={revision,auto:true,follow:true,busy:false,next:null,lastAt:null,data:null};states.set(plot,s);}
    return s;
  }
  function reader(plot) {
    const meta=plot?.layout?.meta?.btcLive;
    const node=doc.getElementById(meta?.kind==='forecast'?'btc-forecast-reader':'btc-chart-reader');
    return node && meta?.symbol===node.dataset.symbol && (meta.kind!=='market'||meta.timeframe===node.dataset.timeframe)?node:null;
  }
  function number(node,key,n) {
    let cache=cards.get(node);if(!cache){cache={};cards.set(node,cache);}
    const digits=key==='rsi'?2:key.startsWith('macd')&&Math.abs(n)>0&&Math.abs(n)<1?(Math.abs(n)<.0001?8:6):node.dataset.decimals||2;
    const text=Number.isFinite(n)?money[digits].format(n):'—';
    const field=node.querySelector(`[data-field="${key}"]`);
    if(cache[key]!==text||field?.textContent!==text){cache[key]=text;write(field,text);}
  }
  function currentQuote(symbol,price,status){
    for(const node of doc.querySelectorAll('.btc-chart-reader'))if(node.dataset.symbol===symbol){
      number(node,'current',price);write(node.querySelector('[data-current-status]'),status);
    }
  }
  function inspect(plot,x,mode='inspect') {
    const node=reader(plot),meta=plot?.layout?.meta?.btcLive,axis=plot?._fullLayout?.xaxis;
    if(!node||!axis)return;
    const candle=plot.data.find(t=>t.type==='candlestick');
    if(candle?.x?.length){
      const ts=times(candle.x,axis),i=nearest(ts,x);
      for(const key of ['open','high','low','close'])number(node,key,values(candle[key])[i]);
      for(const [index,key] of Object.entries(meta.overlays??{})){
        const trace=plot.data[index],tx=times(trace.x,axis),j=nearest(tx,ts[i]);
        number(node,key,tx[j]===ts[i]?values(trace.y)[j]:NaN);
      }
      write(node.querySelector('[data-reader-time]'),`${view.label(ts[i])} KST · ${mode==='latest'?'최근 봉':'선택한 봉'}`);
      node.dataset.index=String(i);node.dataset.at=String(ts[i]);
    }else if(meta.kind==='forecast'){
      for(const [index,key] of Object.entries(meta.indicatorOverlays??{})){
        const trace=plot.data[index],tx=times(trace.x,axis),i=nearest(tx,x);
        number(node,key,x<tx[0]||x>tx.at(-1)?NaN:values(trace.y)[i]);
      }
      write(node.querySelector('[data-reader-time]'),`${view.label(x)} KST · 경로 가정의 지표`);
    }
    node.dataset.mode=mode;
  }
  function clearCursor(){if(last){last.hidden=true;last=null;}}
  function geometry(target) {
    const rect=target.closest?.('.nsewdrag'),plot=rect?.closest('.js-plotly-plot');
    if(!plot||plot._fullLayout?.dragmode!==false||!root.Plotly)return null;
    const subplot=Object.keys(plot._fullLayout._plots??{}).find(key=>rect.parentElement.classList.contains(key));
    const axes=plot._fullLayout._plots[subplot];
    return axes?{plot,rect,subplot,axis:axes.xaxis,yaxis:axes.yaxis,primary:axes.yaxis===plot._fullLayout.yaxis}:null;
  }
  function show(point) {
    if(!point.plot.isConnected)return;
    const bounds=point.rect.getBoundingClientRect(),box=point.plot.getBoundingClientRect();
    const px=Math.max(0,Math.min(bounds.width,point.x-bounds.left)),py=Math.max(0,Math.min(bounds.height,point.y-bounds.top));
    const x=point.axis.p2c(px),price=point.yaxis.p2c(py);
    if(!['market','forecast'].includes(point.plot.layout?.meta?.btcLive?.kind)){
      root.Plotly.Fx.hover(point.plot,{xval:x,yval:price},[point.subplot]);return;
    }
    let layer=point.plot.querySelector('.btc-crosshair');
    if(last!==layer)clearCursor();
    if(!layer){
      layer=doc.createElement('div');layer.className='btc-crosshair';
      layer.innerHTML='<i class="btc-crosshair-x"></i><i class="btc-crosshair-y"></i><b class="btc-crosshair-price"></b><span class="btc-crosshair-time"></span>';
      point.plot.style.position='relative';point.plot.append(layer);
    }
    layer.hidden=false;last=layer;
    const left=bounds.left-box.left,top=bounds.top-box.top;
    const axes=Object.entries(point.plot._fullLayout).filter(([key])=>/^yaxis\d*$/.test(key)).map(([,a])=>a),offset=top-point.yaxis._offset;
    const first=Math.min(...axes.map(a=>a._offset))+offset,bottom=Math.max(...axes.map(a=>a._offset+a._length))+offset;
    Object.assign(layer.querySelector('.btc-crosshair-x').style,{left:left+px+'px',top:first+'px',height:bottom-first+'px'});
    Object.assign(layer.querySelector('.btc-crosshair-y').style,{left:left+'px',top:top+py+'px',width:bounds.width+'px'});
    const p=layer.querySelector('.btc-crosshair-price');
    Object.assign(p.style,{top:top+py-11+'px',left:Math.max(0,left+bounds.width-72)+'px'});
    const panel=(point.plot.layout.meta.btcLive.panels??[]).find(p=>p.axis===point.yaxis._name);
    const digits=panel?.label==='RSI'?2:panel&&Math.abs(price)<1?6:reader(point.plot)?.dataset.decimals||2;
    write(p,(panel?panel.label+' ':'')+money[digits].format(price));
    const t=layer.querySelector('.btc-crosshair-time');
    Object.assign(t.style,{top:bottom-19+'px',left:Math.max(left,Math.min(left+bounds.width-128,left+px-64))+'px'});
    write(t,view.label(x));
    point.plot.dataset.cursorPrice=String(price);point.plot.dataset.cursorX=String(x);
    inspect(point.plot,x,'inspect');
  }
  function bounds(plot) {
    const axis=plot._fullLayout.xaxis,candle=plot.data.find(t=>t.type==='candlestick');
    let xs;
    if(candle)xs=times(candle.x,axis);
    else xs=[...new Set(plot.data.flatMap(t=>t.x?.length?times(t.x,axis).filter(Number.isFinite):[]))].sort((a,b)=>a-b);
    const deltas=xs.slice(1).map((n,i)=>n-xs[i]).filter(n=>n>0).sort((a,b)=>a-b);
    const step=deltas.length?deltas[Math.floor(deltas.length/2)]:86400000;
    const d=plot.layout.meta?.btcLive?.displacement??2;
    return {xs,step,count:xs.length,min:xs[0]-step*2,max:xs.at(-1)+step*Math.max(2,d)};
  }
  function autoRange(plot,range,manualY) {
    const axis=plot._fullLayout.xaxis,candle=plot.data.find(t=>t.type==='candlestick');
    const updates={};
    if(candle){
      const xs=times(candle.x,axis),fit=view.extent(xs,values(candle.low),values(candle.high),range);
      if(fit)updates['yaxis.range']=manualY?view.priceLimit(manualY,fit.prices):fit.range;
      const volume=plot.data.find(t=>t.type==='bar');
      if(fit&&volume){const ys=values(volume.y);let max=1;for(let i=fit.begin;i<fit.end;i++)if(Number.isFinite(ys[i]))max=Math.max(max,ys[i]);updates['yaxis2.range']=[0,max*1.12];}
      write(reader(plot)?.querySelector('[data-visible-bars]'),fit?`${fit.end-fit.begin}봉 보기`:'');
    }else{
      const excluded=plot.layout.meta?.btcLive?.indicatorOverlays??{};
      let low=Infinity,high=-Infinity;
      for(const [i,trace] of plot.data.entries()){
        if(excluded[i]||trace.visible===false||trace.visible==='legendonly'||!trace.x?.length||!trace.y)continue;
        const xs=times(trace.x,axis),ys=values(trace.y),fit=view.extent(xs,ys,ys,range);
        if(fit){low=Math.min(low,fit.range[0]);high=Math.max(high,fit.range[1]);}
      }
      if(Number.isFinite(low)&&Number.isFinite(high))updates['yaxis.range']=manualY?view.priceLimit(manualY,[low,high]):[low,high];
    }
    for(const panel of plot.layout.meta?.btcLive?.panels??[]){
      if(panel.fixed){updates[panel.axis+'.range']=panel.fixed;continue;}
      let low=0,high=0;
      for(const [i,field] of Object.entries(plot.layout.meta.btcLive.overlays??{}))if(panel.fields.includes(field)){
        const t=plot.data[i],fit=view.extent(times(t.x,axis),values(t.y),values(t.y),range);
        if(fit){low=Math.min(low,fit.prices[0]);high=Math.max(high,fit.prices[1]);}
      }
      const pad=Math.max(high-low,Math.abs(high),Math.abs(low),1e-8)*.12;
      updates[panel.axis+'.range']=[low-pad,high+pad];
    }
    return updates;
  }
  function apply(plot,range,yRange) {
    range=view.limit(range,bounds(plot));
    const s=state(plot);s.next={range,yRange};
    if(s.busy)return s.promise;
    const next=s.next;s.next=null;s.busy=true;
    const xaxis=plot._fullLayout.xaxis;
    const updates={'xaxis.range':next.range.map(n=>xaxis.c2d(n)),'yaxis.autorange':false};
    for(const axis of Object.keys(plot._fullLayout))if(/^xaxis\d+$/.test(axis))updates[axis+'.range']=updates['xaxis.range'];
    Object.assign(updates,s.auto?autoRange(plot,next.range):next.yRange?autoRange(plot,next.range,next.yRange):{});
    plot.dataset.autoScale=String(s.auto);
    for(const key of Object.keys(updates)){
      if(key.endsWith('.range')){
        const name=key.split('.')[0],axis=plot._fullLayout[name],before=axis?.range;
        const after=updates[key],convert=n=>name.startsWith('x')?axis.r2c(n):Number(n);
        if(before&&after.every((n,i)=>Math.abs(convert(n)-convert(before[i]))<=Math.max(1e-8,Math.abs(convert(n))*1e-10)))delete updates[key];
      }else if(key==='yaxis.autorange'&&plot._fullLayout.yaxis.autorange===false)delete updates[key];
    }
    if(!Object.keys(updates).length){s.busy=false;return;}
    s.promise=root.Plotly.relayout(plot,updates).catch(()=>{}).then(()=>{
      s.busy=false;
      if(s.next&&!disposed&&plot.isConnected&&states.get(plot)===s&&plot.layout?.uirevision===s.revision){const queued=s.next;return apply(plot,queued.range,queued.yRange);}
    });
    return s.promise;
  }
  function preview(g,range,yRange){
    const s=g.state,updates=s.auto?autoRange(g.plot,range):yRange?autoRange(g.plot,range,yRange):{};
    if(!s.preview)s.preview={drawing:ChartPreview.create(g.plot)};
    s.preview.range=range;s.preview.yRange=updates['yaxis.range']??g.yRange;
    if(!s.preview.drawing.supported){apply(g.plot,range,yRange);return;}
    s.preview.drawing.show(range,updates);g.plot.dataset.gesturePreview='true';
  }
  function queue(work){pending=work;if(raf===null)raf=root.requestAnimationFrame(()=>{raf=null;const work=pending;pending=null;work?.();});}
  function cancel(keepPreview=false,commit=false){
    if(pressTimer!==null)root.clearTimeout(pressTimer);pressTimer=null;if(raf!==null)root.cancelAnimationFrame(raf);raf=null;pending=null;
    const g=active;active=null;if(!g)return;
    const view=g.state.preview;
    if(!keepPreview){view?.drawing.clear();g.state.preview=null;delete g.plot.dataset.gesturePreview;}
    const release=()=>{if(active?.plot!==g.plot)liveAnalysis.hold(g.plot,false);};
    if(commit&&view&&currentGesture(g))Promise.resolve(apply(g.plot,view.range,view.yRange)).finally(release);else release();
  }
  const point=t=>({x:t.clientX,y:t.clientY});
  function begin(part,points,mode,view) {
    const box=part.rect.getBoundingClientRect(),first=points[0],last=points.at(-1);
    const mid={x:(first.x+last.x)/2,y:(first.y+last.y)/2};
    active={...part,state:state(part.plot),data:part.plot.data,revision:part.plot.layout?.uirevision,mode,x:mid.x,y:mid.y,box,range:view?.range??part.axis.range.map(n=>part.axis.r2c(n)),yRange:view?.yRange??part.yaxis.range.map(Number),bounds:bounds(part.plot),distance:Math.max(10,Math.hypot(last.x-first.x,last.y-first.y))};
    liveAnalysis.hold(part.plot,true);
  }
  function start(event) {
    const part=geometry(event.target),view=part&&active?.plot===part.plot?active.state.preview:null;
    cancel(Boolean(view));clearCursor();if(!part)return;
    event.stopPropagation();
    if(event.touches.length===2){event.preventDefault();begin(part,Array.from(event.touches,point),'pinch',view);return;}
    if(event.touches.length!==1)return;
    if(!state(part.plot).auto)event.preventDefault();
    begin(part,[point(event.touches[0])],'pending',view);show(active);
    pressTimer=root.setTimeout(()=>{pressTimer=null;if(active)active.mode='inspect';},350);
  }
  function pan(p,g=active) {
    if(!currentGesture(g))return;
    const dx=(p.x-g.x)/g.box.width*(g.range[1]-g.range[0]),dy=(p.y-g.y)/g.box.height*(g.yRange[1]-g.yRange[0]);
    const range=view.limit(g.range.map(n=>n-dx),g.bounds);
    state(g.plot).follow=range[1]>=g.bounds.xs.at(-1);
    clearCursor();preview(g,range,g.primary?g.yRange.map(n=>n+dy):null);
  }
  function move(event) {
    if(!active)return;
    if(!currentGesture(active)){cancel();clearCursor();return;}
    if(event.touches.length===2){
      if(active.mode!=='pinch'){cancel();return;}
      event.stopPropagation();event.preventDefault();const g=active,points=Array.from(event.touches,point);
      const mid={x:(points[0].x+points[1].x)/2,y:(points[0].y+points[1].y)/2},scale=Math.hypot(points[1].x-points[0].x,points[1].y-points[0].y)/g.distance;
      queue(()=>{if(!currentGesture(g))return;const range=view.limit(view.pinch(g.range,g.x-g.box.left,mid.x-g.box.left,g.box.width,scale),g.bounds);
        const y=view.pinch(g.yRange,g.box.bottom-g.y,g.box.bottom-mid.y,g.box.height,scale);clearCursor();preview(g,range,g.primary?y:null);state(g.plot).follow=range[1]>=g.bounds.xs.at(-1);});return;
    }
    if(event.touches.length!==1||active.mode==='pinch'){cancel();return;}
    const p=point(event.touches[0]),dx=p.x-active.x,dy=p.y-active.y;
    if(active.mode==='pending'){
      if(state(active.plot).auto&&Math.abs(dy)>8&&Math.abs(dy)>Math.abs(dx)){cancel();clearCursor();return;}
      if(Math.hypot(dx,dy)>8){active.mode='pan';root.clearTimeout(pressTimer);pressTimer=null;}
    }
    event.stopPropagation();if(active.mode!=='pending'&&event.cancelable)event.preventDefault();
    const g=active;queue(()=>g.mode==='pan'?pan(p,g):show({...g,...p}));
  }
  function currentGesture(g){return g.plot.isConnected&&g.plot.data===g.data&&reader(g.plot)&&g.plot.layout?.uirevision===g.revision;}
  function end(event){
    const previous=active;
    if(previous){event.stopPropagation();if(pending){const work=pending;pending=null;work();}}
    const continuing=previous?.mode==='pinch'&&event.touches?.length===1&&currentGesture(previous);
    const view=previous?.state.preview;cancel(Boolean(continuing),!continuing);
    if(continuing){const part=geometry(event.target);if(part)begin(part,[point(event.touches[0])],'pan',view);}
  }
  function mouse(event){
    if(event.sourceCapabilities?.firesTouchEvents)return;
    if(active?.mouse){const g=active;queue(()=>pan(point(event),g));return;}
    const part=geometry(event.target);if(!part){clearCursor();return;}queue(()=>show({...part,...point(event)}));
  }
  function mouseStart(event){if(event.button!==0||event.sourceCapabilities?.firesTouchEvents)return;const part=geometry(event.target);if(!part)return;event.preventDefault();event.stopPropagation();cancel();begin(part,[point(event)],'pan');active.mouse=true;}
  function controls(event){
    const button=event.target.closest?.('[data-chart-action="auto"]');if(!button)return;
    const node=button.closest('.btc-chart-reader'),plot=Array.from(doc.querySelectorAll('.js-plotly-plot')).find(p=>reader(p)===node);
    if(!plot)return;const s=state(plot);s.auto=!s.auto;button.setAttribute('aria-pressed',String(s.auto));
    const range=plot._fullLayout.xaxis.range.map(n=>plot._fullLayout.xaxis.r2c(n));apply(plot,range);clearCursor();
  }
  function refresh(plot) {
    if(!reader(plot)||active?.plot===plot||!plot._fullLayout?.xaxis)return;
    const s=state(plot),candle=plot.data.find(t=>t.type==='candlestick'),lastAt=candle?times(candle.x,plot._fullLayout.xaxis).at(-1):null;
    const version=`${plot.dataset.liveEvent??''}-${plot.data.length}-${plot.data.at(-1)?.meta?.btcAI??''}`;
    const changed=s.data!==plot.data||s.lastAt!==lastAt||s.version!==version;
    if(!changed)return;
    const range=plot._fullLayout.xaxis.range.map(n=>plot._fullLayout.xaxis.r2c(n));
    if(s.follow&&s.lastAt!==null&&lastAt!==null&&lastAt>s.lastAt){const delta=lastAt-s.lastAt;range[0]+=delta;range[1]+=delta;}
    s.data=plot.data;s.lastAt=lastAt;s.version=version;
    const button=reader(plot).querySelector('[data-chart-action="auto"]');button?.setAttribute('aria-pressed',String(s.auto));
    plot.dataset.autoScale=String(s.auto);if(s.auto)apply(plot,range);
  }
  function abort(){cancel();clearCursor();}
  function hidden(){if(doc.hidden)abort();}
  function context(event){if(geometry(event.target))event.preventDefault();}
  const listeners=[['visibilitychange',hidden,{}],['touchstart',start,{capture:true,passive:false}],['touchmove',move,{capture:true,passive:false}],['touchend',end,{capture:true,passive:true}],['touchcancel',abort,{capture:true,passive:true}],['mousemove',mouse,{capture:true,passive:true}],['mousedown',mouseStart,{capture:true,passive:false}],['mouseup',end,{capture:true,passive:true}],['contextmenu',context,{capture:true}],['click',controls,{}]];
  for(const [name,handler,options] of listeners)doc.addEventListener(name,handler,options);
  return {inspect,refresh,currentQuote,isInteracting:plot=>active?.plot===plot,dispose(){disposed=true;abort();for(const [name,handler,options] of listeners)doc.removeEventListener(name,handler,options);doc.querySelectorAll('.btc-crosshair').forEach(n=>n.remove());}};
})();
