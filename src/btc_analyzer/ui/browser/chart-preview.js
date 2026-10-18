/* Transform existing SVG data while dragging; commit exact axes on release. */
const ChartPreview = (()=>{
  function matrix(before,after,size,invert=false){
    const scale=(before[1]-before[0])/(after[1]-after[0]);
    const offset=(invert?after[1]-before[1]:before[0]-after[0])/(after[1]-after[0])*size;
    return {scale,offset};
  }
  function create(plot){
    const layers=[];
    for(const [key,axes] of Object.entries(plot._fullLayout._plots)){
      const group=plot.querySelector(`.subplot.${key} .overplot > g.${key}`);
      if(!group)continue;
      const x=axes.xaxis,y=axes.yaxis;
      for(const node of group.children){
        layers.push({node,x:x.range.map(n=>x.r2c(n)),y:y.range.map(Number),width:x._length,height:y._length,
          primary:y===plot._fullLayout.yaxis,transform:node.style.transform,origin:node.style.transformOrigin});
      }
    }
    return {
      show(range,updates){
        for(const layer of layers){
          const x=matrix(layer.x,range,layer.width),target=updates[layer.primary?'yaxis.range':'yaxis2.range']??layer.y;
          const y=matrix(layer.y,target,layer.height,true);
          layer.node.style.transformOrigin='0 0';
          layer.node.style.transform=`matrix(${x.scale},0,0,${y.scale},${x.offset},${y.offset})`;
        }
      },
      clear(){for(const {node,transform,origin} of layers){node.style.transform=transform;node.style.transformOrigin=origin;}},
      supported:layers.length>0
    };
  }
  return {matrix,create};
})();
