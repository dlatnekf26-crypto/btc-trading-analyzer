function detectMove(s,time,price) {
    if (s.market!=='binance' || Date.now()-time>15000 || time>Date.now()+3000) return;
    const samples=s.moveSamples, last=samples.at(-1);
    if (last && time<last[0]) return;
    if (last && time-last[0]>90000) s.move=null;
    // Ten-second bins bound work and memory even during a burst of trades.
    if (last && Math.floor(last[0]/10000)===Math.floor(time/10000)) samples[samples.length-1]=[time,price];
    else samples.push([time,price]);
    s.moveSamples=samples.filter(p=>p[0]>=time-660000).slice(-90);
    let best=null;
    for (const [window,threshold] of [[60000,0.005],[300000,0.01]]) {
      let baseline=-1;
      for (let i=0;i<s.moveSamples.length;i++) if (s.moveSamples[i][0]<=time-window) baseline=i;
      if (baseline<0 || time-window-s.moveSamples[baseline][0]>30000) continue;
      const path=s.moveSamples.slice(baseline);
      if (path.some((p,i)=>i && p[0]-path[i-1][0]>90000)) continue;
      const change=price/path[0][1]-1;
      if (Math.abs(change)>=threshold && (!best || Math.abs(change)/threshold>best.strength)) {
        best={direction:Math.sign(change),change,window,start:path[0][0],at:time,strength:Math.abs(change)/threshold};
      }
    }
    if (best && (!s.move || s.move.direction!==best.direction || time-s.move.at>600000)) s.move=best;
  }
  function paintMoves() {
    const host=parentDoc?.getElementById('btc-move-alerts');
    if (!host) return;
    const now=Date.now(), alerts=[];
    for (const s of states.filter(s=>s.market==='binance')) {
      const move=s.move;
      if (!move || !fresh(s) || s.lastEvent>now+3000 || now-move.at>600000 || now<move.at) continue;
      const news=[...(parentDoc.getElementById('btc-news-bridge')?.querySelectorAll('a') || [])].filter(link=>{
        const published=Number(link.dataset.published),fetched=Number(link.dataset.fetched),direction=Number(link.dataset.direction);
        let url; try {url=new URL(link.href);} catch (_) {return false;}
        return ['http:','https:'].includes(url.protocol) && link.dataset.assets?.split(' ').includes(s.symbol) &&
          validNumber(published) && validNumber(fetched) && published<=now && now-published<=1800000 &&
          fetched<=now && now-fetched<=120000 && published>=move.start-1800000 && published<=move.at+300000 &&
          (direction===0 || direction===move.direction);
      }).slice(0,2);
      alerts.push({symbol:s.symbol,move,news});
    }
    const signature=JSON.stringify(alerts.map(({symbol,move,news})=>[symbol,move.at,move.direction,...news.map(n=>[n.href,n.dataset.fetched])]));
    if (host.dataset.signature===signature) return;
    host.dataset.signature=signature; host.hidden=!alerts.length; host.replaceChildren();
    const append=(parent,tag,text,className)=>{
      const node=parentDoc.createElement(tag); node.textContent=text; if(className) node.className=className;
      parent.appendChild(node); return node;
    };
    for (const {symbol,move,news} of alerts) {
      const card=parentDoc.createElement('article'); card.className='btc-move-card '+(move.direction>0 ? 'up' : 'down');
      card.dataset.symbol=symbol;card.dataset.detected=String(move.at);
      const name=states.find(s=>s.symbol===symbol).name;
      append(card,'strong',`${name} 급${move.direction>0 ? '상승' : '하락'} · 약 ${move.window/60000}분 ${move.change>=0 ? '+' : ''}${(move.change*100).toFixed(2)}%`);
      append(card,'p',`${clock(move.at)} KST 감지 · 비교 ${Math.round((move.at-move.start)/1000)}초 · Binance`, 'btc-move-meta');
      append(card,'p',news.length ? '관련 가능 · 움직임 전후의 소식' : '원인 확인 중 · 가까운 시각의 코인 관련 속보가 아직 없어요.');
      for (const item of news) {
        const link=append(card,'a',item.textContent+' ↗'); link.href=item.href;link.target='_blank';link.rel='noopener noreferrer';
        append(card,'p',`${item.dataset.source} · 기사 ${clock(Number(item.dataset.published))} KST · 확인 ${clock(Number(item.dataset.fetched))} KST${Number(item.dataset.direction)===0 ? ' · 방향 미정' : ''}`,'btc-move-meta');
      }
      if (news.length) append(card,'p','기사 제목·시각으로 연결한 후보예요. 이 뉴스가 원인인지는 확인되지 않았어요.','btc-move-meta');
      host.appendChild(card);
    }
  }
