"""Keep canonical chart arrays; paint market panes without thousands of SVG nodes."""


def canvas_market(spec):
    meta = spec["layout"]["meta"]["btcLive"]
    original_count = len(spec["data"])
    indices, panes = [], {}
    for index, trace in enumerate(spec["data"]):
        if trace["type"] not in ("candlestick", "bar", "scatter"):
            continue
        if trace["type"] == "scatter" and (
            trace.get("mode", "lines") != "lines" or trace.get("line", {}).get("shape", "linear") != "linear"
        ):
            continue
        indices.append(index)
        trace["visible"] = False
        axes = trace.get("xaxis", "x"), trace.get("yaxis", "y")
        panes.setdefault(axes, trace["x"])
    # Two transparent points retain otherwise empty panes. Explicit viewport
    # ranges prevent their zeros from entering price or volume auto scaling.
    for (xaxis, yaxis), times in panes.items():
        spec["data"].append(
            {
                "type": "scatter",
                "mode": "lines",
                "x": [times[0], times[-1]],
                "y": [0, 0],
                "xaxis": xaxis,
                "yaxis": yaxis,
                "opacity": 0,
                "showlegend": False,
                "hoverinfo": "skip",
                "name": "canvas pane",
            }
        )
    meta["canvasTraces"] = indices
    meta["canvasOnly"] = len(indices) == original_count
    return spec
