/* Pure viewport math. Plot coordinates are display-wall-time milliseconds. */
const ChartViewport = (() => {
  const date = new Intl.DateTimeFormat('ko-KR', {timeZone:'UTC', month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
  function label(time) {return Number.isFinite(time) ? date.format(new Date(time)) : '';}
  function lower(xs, x) {let lo=0,hi=xs.length;while(lo<hi){const m=(lo+hi)>>1;if(xs[m]<x)lo=m+1;else hi=m;}return lo;}
  function limit(range, bounds) {
    const span=Math.min(bounds.max-bounds.min,Math.max(bounds.step*Math.min(12,bounds.count),range[1]-range[0]));
    const xs=bounds.xs, keep=xs?Math.min(3,xs.length):0;
    // Future Ichimoku space is still available, but never at the cost of all
    // real candles. Use actual timestamps for irregular exchange sessions.
    const min=keep?Math.max(bounds.min,xs[keep-1]-span):bounds.min;
    const max=keep?Math.min(bounds.max-span,xs.at(-keep)):bounds.max-span;
    let left=Math.max(min,Math.min(max,range[0]));
    if(xs&&lower(xs,left)===lower(xs,left+span+1)){
      const center=left+span/2,i=lower(xs,center);
      const at=i>0&&(i===xs.length||center-xs[i-1]<xs[i]-center)?xs[i-1]:xs[i];
      left=Math.max(bounds.min,Math.min(bounds.max-span,at-span/2));
    }
    return [left,left+span];
  }
  function initialRange(bounds,width) {
    const {xs,step}=bounds;
    const count=Math.min(xs.length,Math.max(24,Math.min(72,Math.floor(width/11))));
    return [xs.at(-count)-step*.7,xs.at(-1)+step*1.5];
  }
  function priceLimit(range, prices) {
    if(!prices)return range;
    const span=range[1]-range[0],overlap=Math.min(span,prices[1]-prices[0])*.2;
    const left=Math.max(prices[0]+overlap-span,Math.min(prices[1]-overlap,range[0]));
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
    return {range:[min-pad,max+pad],prices:[min,max],begin,end};
  }
  return {label,lower,limit,initialRange,priceLimit,pinch,extent};
})();
