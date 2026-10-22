"""Guard duplicate forecast work and stale asynchronous writes across chart swaps."""

from pathlib import Path

import pytest

from scripts.benchmark_live_forecast import measure


def test_forecast_reuses_unchanged_paths_and_keeps_hidden_card_current():
    result = measure(Path(__file__).resolve().parents[1])
    unchanged = result["scenarios"]["unchanged"]
    hidden = result["scenarios"]["offscreen"]
    assert (unchanged["formats"], unchanged["restyles"]) == (181, 1)
    assert unchanged["card"] == "280.00 USDT"
    assert (hidden["formats"], hidden["restyles"]) == (0, 0)
    assert hidden["card"] == "282.80 USDT"
    assert result["resumed"]["restyles"] == 2
    assert result["resumed"]["center"] == pytest.approx(282.8)
    # Same uirevision/data object cannot keep an old model's plotted path.
    assert result["replacement"] == pytest.approx(565.6)
    assert result["detachedWrites"] == 0


def test_canvas_redraws_changed_style_and_replaced_wire_values_without_redundant_paint():
    import json
    import subprocess

    browser = Path(__file__).resolve().parents[1] / "src/btc_analyzer/ui/browser"
    setup = r"""
let paints=0;const moves=[];
const context=new Proxy({clearRect(){paints++;},moveTo(x,y){moves.push([x,y]);}}, {get:(obj,key)=>obj[key]??(()=>{})});
const node=()=>({style:{},dataset:{},isConnected:true,attributes:{},getAttribute(k){return this.attributes[k];},setAttribute(k,v){this.attributes[k]=v;},append(){},remove(){},getContext(){return context;}});
const group={ownerDocument:{createElement(){return node();}},style:{},append(n){n.parentElement=this;this.child=n;}};
const axis={_length:100,range:[0,2],r2c:x=>x,d2c:x=>x,_name:'xaxis',_offset:5};
const yaxis={_length:100,range:[0,4],_name:'yaxis',_offset:10};
const wire=values=>Buffer.from(new Float64Array(values).buffer).toString('base64');
const trace={type:'scatter',x:[0,1,2],y:{dtype:'f8',bdata:wire([1,2,3])},line:{color:'red',width:1}};
const plot={...node(),data:[trace],layout:{uirevision:'same',meta:{btcLive:{canvasTraces:[0]}}},
  _fullLayout:{_plots:{xy:{xaxis:axis,yaxis:yaxis}}},querySelector(){return group;},on(){}};
global.window={parent:{devicePixelRatio:1}};
"""
    checks = r"""
ChartCanvas.refresh(plot);const first=paints;
ChartCanvas.refresh(plot);const unchanged=paints;
axis._offset=25;yaxis._offset=80;ChartCanvas.refresh(plot);
const position={left:group.child.style.left,top:group.child.style.top,overflow:group.child.style.overflow};
trace.line.width=4;ChartCanvas.refresh(plot);const style=paints;
trace.y.bdata=wire([2,3,4]);ChartCanvas.refresh(plot);const wireChanged=paints;
ChartCanvas.refresh(plot);const repeated=paints;
ChartCanvas.dispose();
console.log(JSON.stringify({first,unchanged,style,wireChanged,repeated,position,lastMove:moves.at(-1)}));
"""
    source = "".join(
        (browser / name).read_text() for name in ("plot-data.js", "chart-viewport.js", "chart-canvas.js")
    )
    result = subprocess.run(
        ["node", "-e", setup + source + checks], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout) == {
        "first": 1,
        "unchanged": 1,
        "style": 2,
        "wireChanged": 3,
        "repeated": 3,
        "lastMove": [0, 50],
        "position": {"left": "25px", "top": "80px", "overflow": "hidden"},
    }
