/* Pure viewport math. Plot coordinates are display-wall-time milliseconds. */
const ChartViewport = (() => {
  const date = new Intl.DateTimeFormat('ko-KR', {timeZone:'UTC', month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
  function label(time) {return Number.isFinite(time) ? date.format(new Date(time)) : '';}
  function lower(xs, x) {let lo=0,hi=xs.length;while(lo<hi){const m=(lo+hi)>>1;if(xs[m]<x)lo=m+1;else hi=m;}return lo;}
  function limit(range, bounds) {
    const span=Math.min(bounds.max-bounds.min,Math.max(bounds.step*Math.min(12,bounds.count),range[1]-range[0]));
    const left=Math.max(bounds.min,Math.min(bounds.max-span,range[0]));
    return [left,left+span];
  }
  function pinch(range,startPixel,pixel,width,scale) {
    const span=(range[1]-range[0])/Math.max(.05,Math.min(20,scale));
    const left=range[0]+startPixel/width*(range[1]-range[0])-pixel/width*span;
    return [left,left+span];
  }
  function extent(xs,low,high,range) {
    const begin=lower(xs,range[0]),end=lower(xs,range[1]+1);
    let min=Infinity,max=-Infinity;
    for(let i=begin;i<end;i++){if(Number.isFinite(low[i]))min=Math.min(min,low[i]);if(Number.isFinite(high[i]))max=Math.max(max,high[i]);}
    if(!Number.isFinite(min)||!Number.isFinite(max))return null;
    const pad=Math.max(max-min,Math.abs(max)*.001,.000001)*.12;
    return {range:[min-pad,max+pad],begin,end};
  }
  return {label,lower,limit,pinch,extent};
})();
