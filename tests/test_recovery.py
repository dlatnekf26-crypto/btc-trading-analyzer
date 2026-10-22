"""Recovery never caches live responses or masks authentication/route failures."""

import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_navigation_recovery_statuses_network_timeout_and_static_only_cache():
    program = r"""
const fs=require('fs'),vm=require('vm');
const handlers={},timers=new Map(),cacheAdds=[];let token=0,cached=true,mode='ok',status=200,skips=0;
const context={URL,Response,AbortController,Promise,
  setTimeout(fn){timers.set(++token,fn);return token;},clearTimeout(id){timers.delete(id);},
  self:{location:{origin:'https://app.test'},addEventListener(k,fn){handlers[k]=fn;},skipWaiting(){skips++;},clients:{claim(){}}},
  caches:{async open(){return {async addAll(paths){cacheAdds.push(...paths);}};},async match(){return cached?new Response('offline fixture'):undefined;},async keys(){return [];},async delete(){}},
  fetch:async(request,{signal})=>{
    if(mode==='error')throw new TypeError('offline');
    if(mode==='hang')return new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(new Error('timeout'))));
    return new Response('upstream',{status});
  }
};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),context);
(async()=>{
  let installed;handlers.install({waitUntil(p){installed=p;}});await installed;
  async function run(code,kind='ok'){
    status=code;mode=kind;let response;
    handlers.fetch({request:{url:'https://app.test/?market=BTC&view=chart',mode:'navigate'},respondWith(p){response=p;}});
    if(kind==='hang')for(const fn of [...timers.values()])fn();
    const value=await response;return [value.status,await value.text(),timers.size];
  }
  const results=[];
  for(const status of [200,401,403,404,500,502,503,504])results.push(await run(status));
  results.push(await run(0,'error'));results.push(await run(0,'hang'));
  cached=false;results.push(await run(0,'error'));
  let intercepted=false;handlers.fetch({request:{url:'https://app.test/data/quotes',mode:'cors'},respondWith(){intercepted=true;}});
  handlers.fetch({request:{url:'https://external.test/',mode:'navigate'},respondWith(){intercepted=true;}});
  console.log(JSON.stringify({results,cacheAdds,skips,intercepted}));
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(
        ["node", "-e", program, str(ROOT / "pwa/service-worker.js")],
        text=True,
        capture_output=True,
        check=True,
    )
    data = json.loads(result.stdout)
    assert data["cacheAdds"] == [
        "/app-assets/offline.html",
        "/app-assets/icon-192.png",
        "/app-assets/icon-512.png",
    ]
    assert data["skips"] == 1 and not data["intercepted"]
    assert [row[0] for row in data["results"][:8]] == [200, 401, 403, 404, 500, 200, 200, 200]
    assert all(row[1] == "upstream" and row[2] == 0 for row in data["results"][:5])
    assert all(row == [200, "offline fixture", 0] for row in data["results"][5:10])
    assert data["results"][10][0] == 503 and data["results"][10][2] == 0


def test_recovery_polling_is_bounded_visible_only_and_cannot_reload_forever():
    program = r"""
const fs=require('fs'),vm=require('vm');
const script=fs.readFileSync(process.argv[1],'utf8').split('<script>')[1].split('</script>')[0];
async function run({hidden=false,online=true,body='not health',storage=true,last=null}){
  const win={},events={},timers=new Map(),status={textContent:''},link={};
  let serial=0,calls=0,reloads=0,maxDelay=0;
  const document={hidden,getElementById(id){return id==='status'?status:link;},addEventListener(name,fn){events[name]=fn;}};
  const navigator={onLine:online};
  const context={URL,AbortController,Number,Date,Promise,document,navigator,
    location:{href:'https://app.test/?market=ETH&view=chart',replace(){reloads++;}},
    window:{addEventListener(name,fn){win[name]=fn;}},
    sessionStorage:{getItem(){if(!storage)throw new Error('blocked');return last;},setItem(k,v){last=v;}},
    setTimeout(fn,delay){maxDelay=Math.max(maxDelay,delay);timers.set(++serial,{fn,delay});return serial;},clearTimeout(id){timers.delete(id);},
    fetch:async()=>{calls++;return {ok:true,text:async()=>body};}
  };
  const flush=()=>new Promise(resolve=>setImmediate(resolve));
  async function drain(){
    for(let i=0;i<30&&timers.size;i++){
      const [id,item]=[...timers].sort((a,b)=>a[1].delay-b[1].delay)[0];timers.delete(id);item.fn();await flush();
    }
  }
  vm.runInNewContext(script,context);
  await drain();const before=calls;
  if(hidden){document.hidden=false;events.visibilitychange();await drain();}
  if(!online){navigator.onLine=true;win.online();await drain();}
  return {before,calls,reloads,maxDelay,timers:timers.size,target:link.href,text:status.textContent};
}
(async()=>console.log(JSON.stringify({
  malformed:await run({}),hidden:await run({hidden:true}),offline:await run({online:false}),
  blockedStorage:await run({body:'ok',storage:false}),throttled:await run({body:'ok',last:String(Date.now())}),ready:await run({body:'ok'})
})))().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(
        ["node", "-e", program, str(ROOT / "pwa/offline.html")],
        text=True,
        capture_output=True,
        check=True,
    )
    data = json.loads(result.stdout)
    for name in ("malformed", "hidden", "offline"):
        assert data[name]["calls"] == 8 and data[name]["reloads"] == 0
        assert data[name]["maxDelay"] == 30000 and data[name]["timers"] == 0
    assert data["hidden"]["before"] == data["offline"]["before"] == 0
    for name in ("blockedStorage", "throttled"):
        assert data[name]["calls"] == 1 and data[name]["reloads"] == 0
    assert data["ready"]["calls"] == data["ready"]["reloads"] == 1
    assert all(row["target"] == "https://app.test/?market=ETH&view=chart" for row in data.values())
