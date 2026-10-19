/* Shared Plotly 6 array decoding and axis lookup; retain precision and cache identity. */
const PlotData = (() => {
  const decoded=new WeakMap(),dates=new WeakMap();
  const shown=new WeakMap(),watched=new Set(),root=typeof window==='undefined'?null:window.parent;
  const observer=root?.IntersectionObserver?new root.IntersectionObserver(entries=>{
    for(const entry of entries)shown.set(entry.target,entry.isIntersecting);
  }):null;
  function visible(plot){
    for(const old of watched)if(!old.isConnected){observer?.unobserve(old);watched.delete(old);}
    if(!plot.isConnected)return false;
    if(!observer)return Boolean(plot.getClientRects().length);
    if(!watched.has(plot)){watched.add(plot);shown.set(plot,true);observer.observe(plot);}
    return shown.get(plot);
  }
  function values(data){
    if(!data)return [];
    // Plotly adds typed _inputArray alongside bdata. JSON snapshots turn that
    // typed array into an ordinary object; decode the original wire data first.
    if(!data.bdata)return data._inputArray ?? data;
    if(decoded.get(data)?.encoded!==data.bdata){
      const Type={f8:Float64Array,f4:Float32Array,i4:Int32Array,i2:Int16Array,i1:Int8Array,u4:Uint32Array,u2:Uint16Array,u1:Uint8Array}[data.dtype];
      if(!Type)throw new TypeError('Unsupported chart array');
      decoded.set(data,{encoded:data.bdata,values:new Type(Uint8Array.from(atob(data.bdata),c=>c.charCodeAt(0)).buffer)});
    }
    return decoded.get(data).values;
  }
  function times(xs,axis){
    const cached=dates.get(xs);
    if(!cached || cached.axis!==axis || cached.length!==xs.length || cached.first!==xs[0] || cached.last!==xs.at(-1))
      dates.set(xs,{axis,length:xs.length,first:xs[0],last:xs.at(-1),values:Array.from(xs,x=>axis.d2c(x))});
    return dates.get(xs).values;
  }
  function nearest(xs,x){let lo=0,hi=xs.length-1;while(lo<hi){const mid=(lo+hi)>>1;if(xs[mid]<x)lo=mid+1;else hi=mid;}return lo>0&&Math.abs(xs[lo-1]-x)<Math.abs(xs[lo]-x)?lo-1:lo;}
  return {values,times,nearest,visible,dispose(){observer?.disconnect();watched.clear();}};
})();
