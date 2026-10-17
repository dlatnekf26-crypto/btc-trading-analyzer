const disposePwa=(()=>{
  let root,doc;try{root=window.parent;doc=root.document;}catch(_){return ()=>{};}
  const control=()=>doc.getElementById('btc-pwa-install');
  let prompt=null,valid=false,disposed=false,didInstall=false;
  const standalone=()=>root.matchMedia('(display-mode: standalone)').matches || root.navigator.standalone;
  function sync(){const node=control();if(node) node.hidden=!valid || didInstall || standalone();}
  function ready(event){event.preventDefault();prompt=event;sync();}
  async function click(event){
    if(!event.target.closest?.('#btc-pwa-install button'))return;
    if(prompt){const current=prompt;prompt=null;await current.prompt();await current.userChoice;sync();}
    else {const node=control()?.querySelector('.btc-install-help');if(node) node.textContent=/iPad|iPhone|iPod/.test(root.navigator.userAgent)?'Safari 공유 버튼 → 홈 화면에 추가':'브라우저 메뉴 → 앱 설치 또는 홈 화면에 추가';}
  }
  function installed(){didInstall=true;prompt=null;sync();}
  root.addEventListener('beforeinstallprompt',ready);root.addEventListener('appinstalled',installed);
  doc.addEventListener('click',click);
  // Traditional app.py also works; only enable installation on a PWA-capable entry.
  if(root.isSecureContext && 'serviceWorker' in root.navigator)
    root.fetch('/manifest.webmanifest',{cache:'no-cache'}).then(r=>r.ok && r.headers.get('content-type')?.includes('manifest+json')?r.json():null).then(data=>{
      if(disposed || data?.id!=='/')return;valid=true;sync();
      return root.navigator.serviceWorker.register('/service-worker.js',{scope:'/'});
    }).catch(()=>{});
  function dispose(){disposed=true;root.removeEventListener('beforeinstallprompt',ready);root.removeEventListener('appinstalled',installed);doc.removeEventListener('click',click);}
  dispose.sync=sync;return dispose;
})();
