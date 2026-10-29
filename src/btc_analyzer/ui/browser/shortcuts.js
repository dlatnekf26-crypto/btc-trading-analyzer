export default function(component) {
  const {parentElement,data,setTriggerValue}=component;
  const root=parentElement.querySelector('.shortcuts'),key='market-shortcuts-v1';
  const names=data.markets,current=data.current;
  let editing=false,stored=true;
  const clean=(items,limit)=>Array.isArray(items)?[...new Set(items.filter(x=>typeof x==='string'&&Object.hasOwn(names,x)))].slice(0,limit):[];
  function read(){
    let raw;
    try{
      if(window.__marketShortcutsVolatile){stored=false;raw=window.__marketShortcuts;}
      else raw=JSON.parse(localStorage.getItem(key)||'{}');
    }catch(_){stored=false;}
    raw=raw&&typeof raw==='object'?raw:window.__marketShortcuts||{};
    return {favorites:clean(raw.favorites,12),recent:clean(raw.recent,6)};
  }
  let state=read();
  function save(){
    window.__marketShortcuts=state;
    try{localStorage.setItem(key,JSON.stringify(state));stored=true;window.__marketShortcutsVolatile=false;}
    catch(_){stored=false;window.__marketShortcutsVolatile=true;}
    window.dispatchEvent(new Event('market-shortcuts-change'));
  }
  function element(tag,text,cls){const n=document.createElement(tag);n.textContent=text;if(cls)n.className=cls;return n;}
  function button(text,action,cls){const n=element('button',text,cls);n.type='button';n.onclick=action;return n;}
  function toggle(code){
    if(state.favorites.includes(code))state.favorites=state.favorites.filter(x=>x!==code);
    else if(state.favorites.length<12)state.favorites.push(code);
    else {root.querySelector('[role=status]').textContent='관심종목은 12개까지 저장할 수 있어요.';return;}
    if(!state.favorites.length)editing=false;
    save();draw();
  }
  function moveFirst(code){
    state.favorites=[code,...state.favorites.filter(x=>x!==code)];
    save();draw();
  }
  function list(codes,removable=false){
    const row=element('div','','shortcut-list');
    for(const code of codes){
      const b=button(names[code],()=>setTriggerValue('open',code));
      b.setAttribute('aria-label',names[code]+' 차트 열기');
      if(removable){
        const group=element('div','','shortcut-item');
        group.append(b);
        if(code!==codes[0]){
          const first=button('맨 앞',()=>moveFirst(code),'shortcut-action');
          first.setAttribute('aria-label',names[code]+' 맨 앞으로 이동');group.append(first);
        }
        const remove=button('×',()=>toggle(code),'shortcut-action');
        remove.setAttribute('aria-label',names[code]+' 관심종목에서 삭제');group.append(remove);
        row.append(group);
      }else row.append(b);
    }
    root.append(row);
  }
  function draw(){
    root.replaceChildren();
    if(current&&Object.hasOwn(names,current)){
      const active=state.favorites.includes(current);
      const b=button((active?'★ 관심종목 저장됨':'☆ 관심종목에 추가'),()=>toggle(current),'shortcut-favorite');
      b.setAttribute('aria-pressed',String(active));root.append(b);
    }else{
      const heading=element('div','내 관심종목','shortcut-heading');
      if(state.favorites.length)heading.append(button(editing?'완료':'편집',()=>{editing=!editing;draw();},'shortcut-edit'));
      else heading.append(element('small','이 브라우저에 저장'));
      root.append(heading);
      if(state.favorites.length)list(state.favorites,editing);
      else root.append(element('p','차트에서 ☆를 누르면 여기에 모아볼 수 있어요.','shortcut-note'));
      const recent=state.recent.filter(x=>!state.favorites.includes(x));
      if(state.recent.length){
        const heading=element('div','최근 본 종목','shortcut-heading');
        heading.append(button('기록 지우기',()=>{state.recent=[];save();draw();},'shortcut-edit'));
        root.append(heading);
        if(recent.length)list(recent);
        else root.append(element('p','최근 본 종목이 모두 관심종목에 있어요.','shortcut-note'));
      }
    }
    const status=element('p',stored?'':'저장 공간을 사용할 수 없어 현재 화면에서만 유지돼요.','shortcut-note');
    status.setAttribute('role','status');root.append(status);
  }
  if(current&&Object.hasOwn(names,current)&&state.recent[0]!==current){
    state.recent=[current,...state.recent.filter(x=>x!==current)].slice(0,6);save();
  }
  function sync(event){
    if(event.type==='storage'&&event.key!==key&&event.key!==null)return;
    const before=JSON.stringify([state,stored]);
    state=read();
    if(JSON.stringify([state,stored])!==before)draw();
  }
  window.addEventListener('storage',sync);window.addEventListener('market-shortcuts-change',sync);
  draw();
  return ()=>{window.removeEventListener('storage',sync);window.removeEventListener('market-shortcuts-change',sync);};
}
