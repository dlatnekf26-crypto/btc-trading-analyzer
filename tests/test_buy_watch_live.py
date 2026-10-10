"""Live quotes change distance only, preserving closed-band/action evidence."""

import json
import shutil
import subprocess

import pytest

from btc_analyzer.ui.live_analysis import LIVE_ANALYSIS_JS


def test_distance_staleness_expiry_and_broken_support_latch():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is a development-only browser check")
    engine = LIVE_ANALYSIS_JS.replace("const liveAnalysis=makeLiveAnalysis(window.parent);", "")
    program = (
        engine
        + r"""
let now=2000000000000;
Date.now=()=>now;
const price={textContent:'89 ~ 91 USDT',dataset:{}},distance={textContent:''};
let card={dataset:{low:'89',high:'91',stop:'87',baseAt:String(now-1000),expires:String(now+300000)},
  querySelector:s=>s==='.btc-buy-watch-price' ? price : distance};
const doc={hidden:false,getElementById:id=>id==='btc-buy-watch' ? card : null,querySelectorAll:()=>[]};
const engine=makeLiveAnalysis({document:doc,Plotly:{}}),results=[];
function quote(p,delta=0,fresh=true){now+=1000;engine.paint({price:p,event:now+delta,fresh});
 results.push({state:card.dataset.status,label:distance.textContent,price:price.textContent,low:card.dataset.low,high:card.dataset.high});}
quote(100);quote(90);quote(88);quote(90,-16000);quote(90,4000);quote(90,0,false);
quote(86);quote(90);quote(90,-16000);
card={...card,dataset:{...card.dataset}};quote(90); // New confirmed snapshot, new DOM node.
card.dataset.riskFloor='95';quote(94); // Fast-drop veto before structural stop breaks.
card={...card,dataset:{...card.dataset,riskFloor:'87'}};
now+=300000;quote(90);
engine.dispose();console.log(JSON.stringify(results));
"""
    )
    result = subprocess.run([node, "-e", program], text=True, capture_output=True, check=True)
    states = json.loads(result.stdout)
    assert [s["state"] for s in states] == [
        "above",
        "inside",
        "below",
        "waiting",
        "waiting",
        "waiting",
        "invalid",
        "invalid",
        "invalid",
        "inside",
        "invalid",
        "expired",
    ]
    assert "9.00%" in states[0]["label"]
    assert "하락 진정" in states[1]["label"]
    assert "더 저렴하다고 매수하지" in states[2]["label"]
    assert states[6]["price"] == states[7]["price"] == "가격대 재평가 필요"
    assert states[-1]["price"] == "새 확정 가격대 계산 중"
    assert all((s["low"], s["high"]) == ("89", "91") for s in states)
