"""All expanded stocks receive delayed REST metadata without discarding live prices."""

import json
import subprocess

from btc_analyzer.ui.browser_assets import browser_asset


def test_large_snapshot_rebases_a_newer_live_tick_and_preserves_session_reference():
    source = browser_asset("macro-quotes.js")
    fragment = source[source.index("  const macros=") : source.index("  try{readMacroRows")]
    program = (
        """
const SESSION_ASSETS=Array.from({length:95},(_,i)=>['S'+i,'S'+i,'s'+i,'USD','USD',2]);
const validNumber=n=>typeof n==='number'&&Number.isFinite(n);
const window={parent:{document:null}};
"""
        + fragment
        + """
const at=Date.now()-10000,s=macros.S0;
Object.assign(s,{stream:true,price:110,asOf:at+1000,session:'regular'});
readMacroRows(SESSION_ASSETS.map((a,i)=>({symbol:'S'+i,price:100,asOf:at,
 regularPrice:100,regularAsOf:at,regularChange:0,change:0})));
const seeded=SESSION_ASSETS.every(a=>macros[a[1]].regularPrice===100);
const regular=referenceChange(s,110,'regular',at);
const nextDay=referenceChange(s,110,'regular',at+86400000);
console.log(JSON.stringify({seeded,price:s.price,change:s.change,regular,
 post:referenceChange(s,120,'post',at),nextDay}));
"""
    )
    result = subprocess.run(["node", "-e", program], capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    assert data["seeded"] and data["price"] == 110
    assert abs(data["change"] - 10) < 1e-9 and abs(data["regular"] - 10) < 1e-9
    assert abs(data["post"] - 20) < 1e-9 and data["nextDay"] is None
