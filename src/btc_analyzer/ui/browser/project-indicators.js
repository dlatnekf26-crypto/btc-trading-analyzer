/* Same seeded equations as analysis/projected_indicators.py. */
function projectIndicators(seed,path) {
  let count=seed.count,tail=seed.tail.slice();const ema={...seed.ema};
  const out=Object.fromEntries(['ema_20','ema_50','ema_200','bb_upper','bb_middle','bb_lower'].map(k=>[k,[]]));
  for(let i=0;i<path.length;i++){
    if(i){count++;tail=[...tail.slice(-19),path[i]];for(const n of Object.keys(ema))ema[n]+=2/(Number(n)+1)*(path[i]-ema[n]);}
    for(const [n,value] of Object.entries(ema))out['ema_'+n].push(count>=Number(n)?value:null);
    const middle=tail.length===20?tail.reduce((a,b)=>a+b,0)/20:null;
    const width=middle===null?null:2*Math.sqrt(tail.reduce((s,n)=>s+(n-middle)**2,0)/20);
    out.bb_middle.push(middle);out.bb_upper.push(middle===null?null:middle+width);out.bb_lower.push(middle===null?null:middle-width);
  }
  return out;
}
