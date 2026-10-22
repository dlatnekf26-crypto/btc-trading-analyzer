"""Count actual forecast formatting/plot work with a deterministic browser boundary.

This is a Node microbenchmark, not a browser FPS or network latency measurement.
The same public JS runs with a small DOM/Plotly boundary; no forecast math is mocked.
"""

import argparse
import json
from pathlib import Path
import subprocess

FIXTURE = r"""
const fs=require('fs'),vm=require('vm');
const directory=process.argv[1];
let now=Date.UTC(2026,9,22,12),visible=true,formats=0,restyles=0;
Date.now=()=>now;
const originalFormat=Intl.DateTimeFormat.prototype.formatToParts;
Intl.DateTimeFormat.prototype.formatToParts=function(...args){formats++;return originalFormat.apply(this,args);};
const fields=new Map(),card={querySelector(key){if(!fields.has(key))fields.set(key,{textContent:''});return fields.get(key);}};
const seed={dataset:{symbol:'BTCUSDT',seeds:JSON.stringify({cfg:{},frames:{}})}};
const meta={kind:'forecast',symbol:'BTCUSDT',baseAt:now-1000,anchor:100,label:'6개월',timezone:'Asia/Seoul',
  offsets:Array.from({length:181},(_,i)=>i*86400000),center:Array.from({length:181},(_,i)=>100+i),
  lower:Array.from({length:181},(_,i)=>90+i),upper:Array.from({length:181},(_,i)=>110+i),liveIndices:[0,1,2]};
const plot={isConnected:true,data:[{}],layout:{uirevision:'forecast-test',meta:{btcLive:meta}},dataset:{}};
let lastUpdate;
const root={document:{hidden:false,getElementById(id){return id==='btc-chart-seed'?seed:id==='btc-live-forecast'?card:null;},querySelectorAll(){return [plot];}},
  Plotly:{restyle(p,update,indices){restyles++;lastUpdate=update;return Promise.resolve();}}};
global.window={parent:root};
const prefix="const PlotData={values:x=>x,visible:()=>global.testVisible()};";
global.testVisible=()=>visible;
vm.runInThisContext(prefix+fs.readFileSync(directory+'/candles.js','utf8')+fs.readFileSync(directory+'/project-indicators.js','utf8')+fs.readFileSync(directory+'/live-analysis.js','utf8'));
const settle=()=>new Promise(resolve=>setImmediate(resolve));
async function paint(price=100){liveAnalysis.paint({symbol:'BTCUSDT',price,event:now,fresh:true});await settle();now+=500;}
(async()=>{
  const scenarios={};
  for(const [name,on] of [['unchanged',true],['offscreen',false]]){
    visible=on;const f=formats,r=restyles,start=performance.now();
    for(let i=0;i<20;i++)await paint(name==='offscreen'?101:100);
    scenarios[name]={formats:formats-f,restyles:restyles-r,ms:performance.now()-start,card:fields.get('strong').textContent};
  }
  visible=true;await paint(101);
  const resumed={formats,restyles,center:lastUpdate.y[2].at(-1)};
  // Same revision and same data array, replaced forecast metadata must invalidate.
  plot.layout.meta.btcLive={...meta,center:meta.center.map(v=>v*2)};
  await paint(101);const replacement=lastUpdate.y[2].at(-1);
  // A queued microtask from a replaced/detached chart must not write stale data.
  const before=restyles;
  liveAnalysis.paint({symbol:'BTCUSDT',price:102,event:now,fresh:true});
  plot.isConnected=false;await settle();
  const detachedWrites=restyles-before;
  liveAnalysis.dispose();
  console.log(JSON.stringify({scenarios,resumed,replacement,detachedWrites}));
})().catch(error=>{console.error(error);process.exitCode=1;});
"""


def measure(checkout):
    result = subprocess.run(
        ["node", "-e", FIXTURE, str(checkout / "src/btc_analyzer/ui/browser")],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 30:
        parser.error("repeats must be 1–30")
    print(json.dumps([measure(args.checkout) for _ in range(args.repeats)], indent=2))
