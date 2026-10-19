/* Four Canvas panes share canonical Plotly arrays, axes and viewport controls. */
const ChartCanvas = (()=>{
  const states=new WeakMap(),mounted=new Set(),svg='http://www.w3.org/2000/svg';
  const {values,times}=PlotData;
  const extents=new WeakMap();
  let disposed=false;
  const attr=(node,key,value)=>{value=String(value);if(node.getAttribute(key)!==value)node.setAttribute(key,value);};
  function fallback(plot,state,indices){
    if(state.restoring)return;
    state.restoring=true;state.disabled=true;attr(plot,'data-canvas-rendering','fallback-pending');
    const revision=plot.layout.uirevision;
    window.parent.Plotly.restyle(plot,{visible:true},indices).then(()=>{
      if(plot.layout.uirevision===revision){attr(plot,'data-canvas-rendering','fallback');attr(plot,'data-canvas-revision',revision);}
    }).catch(()=>{}).finally(()=>{state.restoring=false;});
  }
  function segment(ctx,xs,ys,px,py,begin=0,end=xs.length){
    let open=false;
    for(let i=begin;i<end;i++){
      if(!Number.isFinite(xs[i])||!Number.isFinite(ys[i])){open=false;continue;}
      if(open)ctx.lineTo(px(xs[i]),py(ys[i]));else{ctx.moveTo(px(xs[i]),py(ys[i]));open=true;}
    }
  }
  function draw(pane,traces,x,y,xr,yr,plot){
    const {canvas,context:ctx}=pane,width=x._length,height=y._length;
    const ratio=Math.min(window.parent.devicePixelRatio||1,2,Math.sqrt(2500000/(width*height)));
    const key=[...traces.flatMap(t=>[t.x,t.y,t.open,t.high,t.low,t.close,t.marker?.color,t.line?.color,t.line?.dash,t.fillcolor,t.opacity]),...xr,...yr,width,height,ratio,plot.dataset.liveEvent];
    if(pane.key&&key.every((n,i)=>Object.is(n,pane.key[i])))return;
    pane.key=key;attr(pane.node,'width',width);attr(pane.node,'height',height);
    const w=Math.ceil(width*ratio),h=Math.ceil(height*ratio);
    if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;canvas.style.width=width+'px';canvas.style.height=height+'px';}
    ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,width,height);ctx.save();
    const px=t=>(t-xr[0])/(xr[1]-xr[0])*width,py=v=>(yr[1]-v)/(yr[1]-yr[0])*height;
    const series=traces.map(trace=>{
      const xs=times(trace.x,x),begin=Math.max(0,ChartViewport.lower(xs,xr[0])-1),end=Math.min(xs.length,ChartViewport.lower(xs,xr[1])+1);
      let culled=false;
      if(trace.fill==='toself'){
        let bound=extents.get(xs);
        if(!bound){let low=Infinity,high=-Infinity;for(const at of xs)if(Number.isFinite(at)){low=Math.min(low,at);high=Math.max(high,at);}bound=[low,high];extents.set(xs,bound);}
        culled=bound[1]<xr[0]||bound[0]>xr[1];
      }
      return {trace,xs,ys:values(trace.y),begin,end,culled};
    });
    // Fills sit below candles and lines, as in the source chart. Closed cloud
    // polygons need their complete (forward/backward) x path, not a sorted slice.
    let previous=null;
    for(const s of series){
      const t=s.trace;if(t.type!=='scatter')continue;
      ctx.globalAlpha=t.opacity??1;ctx.fillStyle=t.fillcolor||'rgba(49,130,246,.06)';
      if(t.fill==='toself'&&!s.culled){
        ctx.beginPath();segment(ctx,s.xs,s.ys,px,py);ctx.fill();
      }else if(t.fill==='tonexty'&&previous){
        let start=s.begin;
        while(start<s.end){
          while(start<s.end&&(!Number.isFinite(s.ys[start])||!Number.isFinite(previous.ys[start])))start++;
          let end=start;while(end<s.end&&Number.isFinite(s.ys[end])&&Number.isFinite(previous.ys[end]))end++;
          if(end>start){
            ctx.beginPath();segment(ctx,s.xs,s.ys,px,py,start,end);
            for(let i=end-1;i>=start;i--)ctx.lineTo(px(previous.xs[i]),py(previous.ys[i]));
            ctx.closePath();ctx.fill();
          }
          start=end+1;
        }
      }
      previous=s;
    }
    for(const {trace:t,xs,ys,begin,end} of series){
      if(t.type==='scatter')continue;
      const gaps=[];for(let i=Math.max(1,begin);i<end;i++)if(xs[i]>xs[i-1])gaps.push(xs[i]-xs[i-1]);
      gaps.sort((a,b)=>a-b);const step=gaps.length?gaps[Math.floor(gaps.length/2)]:86400000;
      const barWidth=Math.max(.4,Math.abs(step/(xr[1]-xr[0])*width)*(t.type==='candlestick'?.5:1-(plot.layout.bargap??.2)));
      ctx.globalAlpha=t.opacity??1;ctx.lineWidth=1;
      if(t.type==='candlestick'){
        const o=values(t.open),hi=values(t.high),lo=values(t.low),c=values(t.close);
        for(let i=begin;i<end;i++){
          if(![o[i],hi[i],lo[i],c[i]].every(Number.isFinite))continue;
          const color=(c[i]>=o[i]?t.increasing:t.decreasing)?.fillcolor||(c[i]>=o[i]?'#ef3f50':'#2563eb');
          const at=px(xs[i]),top=py(Math.max(o[i],c[i])),bottom=py(Math.min(o[i],c[i]));
          ctx.fillStyle=color;ctx.strokeStyle=color;ctx.beginPath();ctx.moveTo(at,py(hi[i]));ctx.lineTo(at,py(lo[i]));ctx.stroke();
          ctx.fillRect(at-barWidth/2,top,barWidth,Math.max(1/ratio,bottom-top));
        }
      }else{
        const colors=t.marker?.color,zero=py(0);
        for(let i=begin;i<end;i++){
          if(!Number.isFinite(ys[i])||ys[i]===0)continue;
          ctx.fillStyle=typeof colors==='string'?colors:colors?.[i]||'#3182f6';const at=py(ys[i]);
          ctx.fillRect(px(xs[i])-barWidth/2,Math.min(at,zero),barWidth,Math.max(1/ratio,Math.abs(zero-at)));
        }
      }
    }
    for(const s of series){
      const t=s.trace;if(t.type!=='scatter'||t.line?.width===0||s.culled)continue;
      ctx.globalAlpha=t.opacity??1;ctx.strokeStyle=t.line?.color||'#3182f6';ctx.lineWidth=t.line?.width??1.5;
      ctx.setLineDash(t.line?.dash==='dot'?[2,3]:t.line?.dash==='dash'?[6,4]:t.line?.dash==='dashdot'?[6,3,2,3]:[]);
      ctx.beginPath();segment(ctx,s.xs,s.ys,px,py,s.begin,s.end);ctx.stroke();
    }
    ctx.restore();
  }
  function paint(plot,range=null,updates={}){
    if(disposed)return;
    const indices=plot.layout?.meta?.btcLive?.canvasTraces;
    if(!indices?.length||!plot._fullLayout?._plots)return;
    let state=states.get(plot);
    if(!state){state={panes:new Map(),preview:false,disabled:false,revision:plot.layout.uirevision,after:()=>refresh(plot)};states.set(plot,state);mounted.add(plot);plot.on?.('plotly_afterplot',state.after);}
    if(state.revision!==plot.layout.uirevision){for(const pane of state.panes.values())pane.node.remove();state.panes.clear();state.preview=false;state.disabled=false;state.revision=plot.layout.uirevision;}
    if(state.disabled){if(indices.some(i=>plot.data[i]?.visible===false))fallback(plot,state,indices);return;}
    const groups=new Map();
    for(const index of indices){const t=plot.data[index];if(!t)continue;const key=(t.xaxis||'x')+(t.yaxis||'y');if(!groups.has(key))groups.set(key,[]);groups.get(key).push(t);}
    let painted=0;
    for(const [subplot,traces] of groups){
      const axes=plot._fullLayout._plots[subplot],group=plot.querySelector(`.subplot.${subplot} .overplot>g.${subplot}`);if(!axes||!group)continue;
      let pane=state.panes.get(subplot);
      if(!pane?.node.isConnected){
        const node=group.ownerDocument.createElementNS(svg,'foreignObject');node.setAttribute('class','btc-canvas-layer');node.style.pointerEvents='none';
        const canvas=group.ownerDocument.createElementNS('http://www.w3.org/1999/xhtml','canvas');canvas.setAttribute('role','img');canvas.setAttribute('aria-label',subplot==='xy'?'가격·이평선·볼린저·일목':subplot==='x2y2'?'거래량':subplot==='x3y3'?'RSI':'MACD');
        canvas.dataset.pane=subplot;node.append(canvas);group.prepend(node);const context=canvas.getContext('2d');
        if(!context){for(const p of state.panes.values())p.node.remove();node.remove();fallback(plot,state,indices);return;}
        pane={node,canvas,context,key:null};state.panes.set(subplot,pane);
      }
      const x=axes.xaxis,y=axes.yaxis;draw(pane,traces,x,y,range||x.range.map(n=>x.r2c(n)),updates[y._name+'.range']||y.range.map(Number),plot);
      painted++;
    }
    if(painted!==groups.size)return;
    attr(plot,'data-canvas-rendering','ready');
    attr(plot,'data-canvas-revision',plot.layout.uirevision);
  }
  function refresh(plot){
    for(const old of mounted)if(!old.isConnected){old.removeListener?.('plotly_afterplot',states.get(old)?.after);mounted.delete(old);}
    if(!states.get(plot)?.preview)paint(plot);
  }
  return {refresh,preview(plot,range,updates){paint(plot,range,updates);const s=states.get(plot);if(s)s.preview=true;},
    clear(plot){const s=states.get(plot);if(s){s.preview=false;paint(plot);}},
    dispose(){disposed=true;for(const plot of mounted){plot.removeListener?.('plotly_afterplot',states.get(plot)?.after);for(const pane of states.get(plot)?.panes.values()||[])pane.node.remove();}mounted.clear();}
  };
})();
