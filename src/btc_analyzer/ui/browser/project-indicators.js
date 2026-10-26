/* Same seeded equations as analysis/projected_indicators.py. */
function projectIndicators(seed,path) {
  let count=seed.count,tail=seed.tail.slice();const ema={...seed.ema};
  const sma=seed.sma||[],keep=Math.max(20,...sma);
  const out=Object.fromEntries([...Object.keys(ema).map(n=>'ema_'+n),...sma.map(n=>'sma_'+n),'bb_upper','bb_middle','bb_lower'].map(k=>[k,[]]));
  for(let i=0;i<path.length;i++){
    if(i){count++;tail=[...tail.slice(-(keep-1)),path[i]];for(const n of Object.keys(ema))ema[n]+=2/(Number(n)+1)*(path[i]-ema[n]);}
    for(const [n,value] of Object.entries(ema))out['ema_'+n].push(count>=Number(n)?value:null);
    for(const n of sma)out['sma_'+n].push(tail.length>=n?tail.slice(-n).reduce((a,b)=>a+b,0)/n:null);
    const band=tail.slice(-20),middle=band.length===20?band.reduce((a,b)=>a+b,0)/20:null;
    const width=middle===null?null:2*Math.sqrt(band.reduce((s,n)=>s+(n-middle)**2,0)/20);
    out.bb_middle.push(middle);out.bb_upper.push(middle===null?null:middle+width);out.bb_lower.push(middle===null?null:middle-width);
  }
  return out;
}
