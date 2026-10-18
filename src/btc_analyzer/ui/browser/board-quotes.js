// Mirror the existing feed into native cards. No additional socket or polling.
  const boardNodes=new WeakMap();
  function fieldsFor(node){
    let fields=boardNodes.get(node);
    if(!fields||Object.values(fields).some(n=>!n.isConnected)){
      fields=Object.fromEntries([...node.querySelectorAll('[data-quote-field]')].map(n=>[n.dataset.quoteField,n]));
      boardNodes.set(node,fields);
    }
    return fields;
  }
  function setField(fields,key,value){const node=fields[key];if(node&&node.textContent!==value)node.textContent=value;}
  function tickerMetrics(s,item){
    if(s.market!=='binance'||item.e==='aggTrade')return;
    const number=(short,long)=>{const n=item[short]??item[long];return n===null||n===undefined||n===''?NaN:Number(n);};
    const high=number('h','highPrice'),low=number('l','lowPrice'),volume=number('v','volume'),turnover=number('q','quoteVolume');
    if(![high,low,volume,turnover].every(validNumber)||low<=0||high<low||volume<0||turnover<0)return;
    s.metrics={high,low,volume,turnover};
  }
  function paintBoard(){
    if(!parentDoc)return;
    for(const node of parentDoc.querySelectorAll('[data-quote-symbol]')){
      const symbol=node.dataset.quoteSymbol,fields=fieldsFor(node);
      const s=states.find(s=>s.symbol===symbol),macro=macros[symbol];
      if(s){
        const live=fresh(s),status=s.el?.querySelector('.status span')?.textContent||'시세 연결 중…';
        write(node.dataset,'status',live&&s.transport!=='history'?'live':'stale');
        setField(fields,'status',status+' · Binance');
        if(s.price!==null)setField(fields,'price','$'+s.price.toLocaleString('en-US',{minimumFractionDigits:s.decimals,maximumFractionDigits:s.decimals}));
        if(s.change!==null){
          setField(fields,'change',(s.change>=0?'▲ +':'▼ ')+s.change.toFixed(2)+'% · 24시간');
          if(fields.change)write(fields.change.dataset,'direction',s.change>=0?'up':'down');
        }
        if(s.metrics){
          const fmt=n=>n.toLocaleString('en-US',{maximumFractionDigits:s.decimals,minimumFractionDigits:s.decimals});
          for(const key of ['high','low'])setField(fields,key,fmt(s.metrics[key]));
          setField(fields,'volume',s.metrics.volume.toLocaleString('en-US',{maximumFractionDigits:2})+' '+s.symbol.replace('USDT',''));
          setField(fields,'turnover',Intl.NumberFormat('en-US',{notation:'compact',maximumFractionDigits:2}).format(s.metrics.turnover));
          if(fields.position){
            const span=s.metrics.high-s.metrics.low;
            const pos=span>0?Math.max(0,Math.min(100,(s.price-s.metrics.low)/span*100)):50;
            write(fields.position.style,'left','calc('+pos.toFixed(2)+'% - 1px)');fields.position.hidden=false;
          }
        }
      }else if(macro){
        const original=parentDoc.getElementById('macro-'+macro.id);
        if(!original)continue;
        // Preserve the macro bridge's text; its observer restores native reruns.
        for(const key of ['price','change','status']){
          const source=original.querySelector('[data-quote-field="'+key+'"]');
          if(source&&source!==fields[key]){
            if(key==='status'&&node.classList.contains('board-detail')&&macro.asOf){
              const old=Date.now()-macro.asOf>7200000||macro.tone==='stale';
              const stamp=dayFormat.format(new Date(macro.asOf))+' '+clock(macro.asOf).slice(0,5)+' KST';
              setField(fields,key,(old?'마지막 값 · ':'')+stamp+' · '+(macro.delay>=0?'지연 '+macro.delay+'분':'지연 미확인'));
            }else setField(fields,key,source.textContent);
          }
        }
        write(node.dataset,'status',original.dataset.status||'stale');
        if(fields.change&&macro.change!==null)write(fields.change.dataset,'direction',macro.change>=0?'up':'down');
      }
    }
    const premiumNode=parentDoc.querySelector('[data-reference="premium"]');
    if(premiumNode){
      const price=premiumNode.querySelector('[data-reference-field="price"]'),status=premiumNode.querySelector('[data-reference-field="status"]');
      if(lastPremium!==null&&price)write(price,'textContent',(lastPremium>=0?'+':'')+lastPremium.toFixed(2)+'%');
      if(status)write(status,'textContent',premiumEl.querySelector('.status span').textContent);
    }
    const fxNode=parentDoc.querySelector('[data-reference="fx"]');
    if(fxNode){
      const price=fxNode.querySelector('[data-reference-field="price"]'),status=fxNode.querySelector('[data-reference-field="status"]');
      if(fx.rate!==null&&price)write(price,'textContent','₩'+fx.rate.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}));
      if(status)write(status,'textContent',fxEl.querySelector('.status span').textContent+' · '+(fx.source||'출처 확인 중'));
    }
  }
