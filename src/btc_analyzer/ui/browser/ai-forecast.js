/* Render only verified server responses. AI endpoints are never called here. */
const aiForecast = (() => {
  let doc,root;
  try{root=window.parent;doc=root.document;}catch(_){return {paint(){}};}
  const states=new WeakMap();
  function paint(plot){
    if(plot.layout?.meta?.btcLive?.kind!=='forecast')return;
    const meta=plot.layout.meta.btcLive,node=doc.getElementById('btc-ai-forecast'),raw=node?.dataset.scenario;
    let s=states.get(plot);if(!s){s={raw:null,data:null,busy:false};states.set(plot,s);}
    if(s.busy||(s.raw===raw&&s.data===plot.data))return;
    let data;
    try{data=raw?JSON.parse(raw):null;}catch(_){return;}
    const symbol=data?.asset==='NQ'?'NQ=F':data?.asset+'USDT';
    const valid=data&&symbol===meta.symbol&&data.baseAt===meta.baseAt&&data.count===meta.center.length&&data.basis===meta.aiBasis;
    const previous=plot.data.flatMap((t,i)=>t.meta?.btcAI?[i]:[]);
    if(valid&&previous.length===3&&plot.data[previous[0]].meta.btcAI===data.created){s.raw=raw;s.data=plot.data;return;}
    if(!valid&&!previous.length){s.raw=raw;s.data=plot.data;return;}
    s.busy=true;
    Promise.resolve().then(async()=>{
      if(previous.length)await root.Plotly.deleteTraces(plot,previous);
      if(valid){
        const x=plot.data[meta.liveIndices?.[2]??3]?.x??plot.data[3].x;
        // Preserve confirmed-model dates: the AI changes endpoints, not the clock.
        const dates=plot.data.find(t=>t.name==='실시간 범위 상단')?.x??plot.data[3].x;
        const baseTrace=plot.data.find(t=>t.name==='예상 중심 경로')??plot.data.find(t=>t.meta?.direction);
        const xs=baseTrace?.x??dates??x;
        const shared={x:xs,type:'scatter',mode:'lines',meta:{btcAI:data.created},hoverinfo:'skip'};
        await root.Plotly.addTraces(plot,[
          {...shared,y:data.upper,name:'AI 범위 상단',showlegend:false,line:{width:0}},
          {...shared,y:data.lower,name:'AI 도착 가격 범위 가정',showlegend:false,line:{width:0},fill:'tonexty',fillcolor:'rgba(140,101,218,.07)'},
          {...shared,y:data.center,name:'AI 조건부 가격 경로',line:{color:'#8c65da',width:2.5,dash:'dash'}}
        ]);
      }
      s.raw=raw;s.data=plot.data;
    }).catch(()=>{}).finally(()=>{s.busy=false;});
  }
  return {paint};
})();
