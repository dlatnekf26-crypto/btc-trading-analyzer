"""Unchanged preferences preserve focused DOM and avoid synchronous storage writes."""

from pathlib import Path
import subprocess


def test_unchanged_shortcuts_do_not_rewrite_storage_or_replace_nodes():
    source = (Path(__file__).resolve().parents[1] / "src/btc_analyzer/ui/browser/shortcuts.js").read_text()
    script = (
        r"""
const assert=require('node:assert/strict');
let writes=0,draws=0;
class Node {
  constructor(){this.children=[];this.attrs={};}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(){draws++;this.children=[];}
  setAttribute(k,v){this.attrs[k]=v;}
}
const root=new Node(),listeners=new Map();
global.document={createElement:()=>new Node()};
global.window={addEventListener:(k,f)=>listeners.set(k,f),removeEventListener:k=>listeners.delete(k),
  dispatchEvent:e=>listeners.get(e.type)?.(e)};
let saved=JSON.stringify({favorites:[],recent:['BTC']});
global.localStorage={getItem:()=>saved,setItem:(k,v)=>{writes++;saved=v;}};
const component={parentElement:{querySelector:()=>root},data:{markets:{BTC:'비트코인',ETH:'이더리움'},current:'BTC'},setTriggerValue(){}};
"""
        + source.replace("export default function(component)", "function mount(component)")
        + r"""
const cleanup=mount(component);
assert.equal(writes,0);assert.equal(draws,1);
const first=root.children[0];
window.dispatchEvent({type:'storage',key:'market-shortcuts-v1'});
window.dispatchEvent({type:'market-shortcuts-change'});
assert.equal(root.children[0],first);assert.equal(draws,1);
first.onclick();
assert.equal(writes,1);assert.equal(root.children[0].attrs['aria-pressed'],'true');
saved=JSON.stringify({favorites:[],recent:['ETH','BTC']});
window.dispatchEvent({type:'storage',key:'market-shortcuts-v1'});
assert.equal(root.children[0].attrs['aria-pressed'],'false');
cleanup();assert.equal(listeners.size,0);
// Home editing preserves chart navigation and saves the selected order.
component.data.current=null;
saved=JSON.stringify({favorites:['BTC','ETH'],recent:['BTC','ETH']});
let opened=null;component.setTriggerValue=(key,code)=>{opened=code;};
const stop=mount(component);
const all=node=>[node,...node.children.flatMap(all)];
const byText=text=>all(root).find(n=>n.textContent===text);
const byLabel=label=>all(root).find(n=>n.attrs['aria-label']===label);
byText('편집').onclick();
byLabel('이더리움 맨 앞으로 이동').onclick();
assert.deepEqual(JSON.parse(saved).favorites,['ETH','BTC']);
byLabel('이더리움 차트 열기').onclick();assert.equal(opened,'ETH');
byText('기록 지우기').onclick();
assert.deepEqual(JSON.parse(saved),{favorites:['ETH','BTC'],recent:[]});
byLabel('이더리움 관심종목에서 삭제').onclick();
byLabel('비트코인 관심종목에서 삭제').onclick();
assert.deepEqual(JSON.parse(saved).favorites,[]);
stop();assert.equal(listeners.size,0);
"""
    )
    subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True, timeout=10)


def test_quote_card_skips_self_copy_but_keeps_live_direction():
    source = (Path(__file__).resolve().parents[1] / "src/btc_analyzer/ui/browser/board-quotes.js").read_text()
    script = (
        r"""
const assert=require('node:assert/strict');
const change={isConnected:true,dataset:{quoteField:'change'},textContent:'+2%'};
const node={dataset:{quoteSymbol:'AAPL'},querySelectorAll:()=>[change],querySelector(){throw Error('redundant query')}};
const parentDoc={querySelectorAll:()=>[node],getElementById:()=>node,querySelector:()=>null};
const states=[],macros={AAPL:{id:'aapl',change:2}};
const write=(node,key,value)=>{node[key]=value};
"""
        + source
        + r"""
paintBoard();assert.equal(change.dataset.direction,'up');
macros.AAPL.change=-1;paintBoard();assert.equal(change.dataset.direction,'down');
"""
    )
    subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True, timeout=10)
