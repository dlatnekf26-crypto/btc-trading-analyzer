/* Transform existing SVG data while dragging; commit exact axes on release. */
const ChartPreview = (()=>{
  function matrix(before,after,size,invert=false){
    const scale=(before[1]-before[0])/(after[1]-after[0]);
    const offset=(invert?after[1]-before[1]:before[0]-after[0])/(after[1]-after[0])*size;
    return {scale,offset};
  }
  function create(plot){
    const layers=[];
    const canvas=plot.layout?.meta?.btcLive?.canvasOnly&&plot.dataset?.canvasRendering==='ready';
    for(const [key,axes] of canvas?[]:Object.entries(plot._fullLayout?._plots??{})){
      const group=plot.querySelector(`.subplot.${key} .overplot > g.${key}`);
      if(!group)continue;
      const x=axes.xaxis,y=axes.yaxis;
      for(const node of group.children){
        if(node.classList.contains('btc-canvas-layer'))continue;
        const traces=[...node.querySelectorAll('.trace')];
        if(traces.length&&traces.every(trace=>trace.style.opacity==='0'))continue;
        if(node.childElementCount===0)continue;
        layers.push({node,x:x.range.map(n=>x.r2c(n)),y:y.range.map(Number),width:x._length,height:y._length,
          axis:y._name ?? Object.keys(plot._fullLayout).find(k=>/^yaxis\d*$/.test(k)&&plot._fullLayout[k]===y) ?? 'yaxis',transform:node.style.transform,origin:node.style.transformOrigin});
      }
    }
    return {
      show(range,updates){
        ChartCanvas.preview(plot,range,updates);
        const transforms=new Map();
        for(const layer of layers){
          if(!transforms.has(layer.axis)){
            const x=matrix(layer.x,range,layer.width),target=updates[layer.axis+'.range']??layer.y;
            const y=matrix(layer.y,target,layer.height,true);
            transforms.set(layer.axis,`matrix(${x.scale},0,0,${y.scale},${x.offset},${y.offset})`);
          }
          const transform=transforms.get(layer.axis);
          if(layer.applied===transform)continue;
          layer.node.style.transformOrigin='0 0';layer.node.style.transform=transform;layer.applied=transform;
        }
      },
      clear(){for(const layer of layers){layer.node.style.transform=layer.transform;layer.node.style.transformOrigin=layer.origin;layer.applied=null;}ChartCanvas.clear(plot);},
      supported:layers.length>0||Boolean(plot.layout?.meta?.btcLive?.canvasTraces)
    };
  }
  return {matrix,create};
})();
