'use strict';
const $ = id => document.getElementById(id);
const colors={1:'#64748b',2:'#d97706',4:'#059669',5:'#7c3aed'};
const labels={0:'測位不可',1:'単独測位',2:'差分補正',4:'RTK FIX',5:'RTK FLOAT'};
let config, state={}, selected=null, points=[], cursor=0, generation=0, playing=null, fetchingGeneration=null;
let map=null, marker=null, lines=[], currentTitle='', activeView='map', rawGeneration=0, rawTimer=null;
const dateFmt=new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',fractionalSecondDigits:3});
function when(p){return p.measured ? dateFmt.format(new Date(p.measured)) : `UTC ${p.utc}（日付不明）`;}
function error(message){$('error').textContent=message;$('error').hidden=!message;}
async function api(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json','X-GNSS-Token':config.token},body:JSON.stringify(body)}:{});const data=await r.json();if(!r.ok)throw Error(data.error||'通信に失敗しました');return data;}
function clearMap(){for(const line of lines)line.remove();lines=[];if(marker){marker.remove();marker=null;}}
function chunks(visible){const groups=[];for(const p of visible){let last=groups.at(-1);if(!last||last.at(-1).segment!==p.segment||last.at(-1).quality!==p.quality){const previous=last?.at(-1);last=[];if(previous&&previous.segment===p.segment)last.push(previous);groups.push(last);}last.push(p);}return groups;}
function draw(){
 const visible=points.slice(0,cursor+1),p=visible.at(-1);
 $('count').textContent=points.length.toLocaleString();$('cursor').max=Math.max(0,points.length-1);$('cursor').disabled=!points.length;$('cursor').value=cursor;
 const viewingLive=selected===state.active&&state.running&&$('follow').checked;
 const fresh=viewingLive&&state.fresh;
 $('quality').textContent=viewingLive&&!fresh?'現在の位置なし':(p?`${p.quality} · ${labels[p.quality]}`:'—');
 $('sat').textContent=p?`${p.satellites}機 / ${p.hdop??'—'}`:'—';$('time').textContent=p?when(p):'—';
 $('viewTitle').textContent=selected?(viewingLive?'計測中 · ':'履歴 · ')+currentTitle:'計測を開始するか履歴を選択';
 $('pointInfo').textContent=p?`${fresh?'現在の測位点':viewingLive?'最後の有効位置（現在位置ではありません）':'選択した履歴点'}｜${when(p)}｜緯度 ${p.lat.toFixed(8)} / 経度 ${p.lon.toFixed(8)}｜区間 ${p.segment}`:'有効な測位点を待っています。';
 $('google').hidden=!p;if(p)$('google').href=`https://www.google.com/maps/search/?api=1&query=${p.lat},${p.lon}`;
 if(activeView==='map'&&map){clearMap();for(const group of chunks(visible)){if(group.length>1)lines.push(L.polyline(group.map(p=>[p.lat,p.lon]),{color:colors[group.at(-1).quality],weight:4}).addTo(map));}
  if(p&&(!viewingLive||fresh)){marker=L.circleMarker([p.lat,p.lon],{radius:7,color:'#005bac',fillOpacity:1}).addTo(map);marker.bindTooltip(when(p));if($('follow').checked)map.panTo([p.lat,p.lon]);}
 }else if(activeView==='scatter')drawScatter(visible);
 else if(activeView==='series')drawSeries();
 else if(activeView==='raw')scheduleRaw();
}

async function loadMap(){
 map=L.map('map',{center:[35,137],zoom:17,preferCanvas:true});
 L.control.scale({imperial:false}).addTo(map);
 let layers;try{layers=await api('/api/maps');}catch(e){$('mapNotice').textContent='地図を読み込めません：'+e.message;return;}const choices={};
 for(const layer of layers){const tile=L.tileLayer(`/tiles/${layer.id}/{z}/{x}/{y}`,{minZoom:layer.minzoom,maxNativeZoom:layer.maxzoom,maxZoom:22,attribution:layer.attribution});choices[layer.title]=tile;}
 if(layers.length){const b=layers[0].bounds?.split(',').map(Number);if(b?.length===4&&b.every(Number.isFinite))map.fitBounds([[b[1],b[0]],[b[3],b[2]]]);Object.values(choices)[0].addTo(map);L.control.layers(choices,{}, {collapsed:false}).addTo(map);$('mapNotice').textContent='保存済み地図を使用（オフライン）。保存範囲外は背景が表示されません。高倍率は画像の拡大表示です。';}
 else $('mapNotice').textContent='保存済み地図がありません。背景なしで経路を表示します。';
 map.on('dragstart',()=>{$('follow').checked=false;});
}
function fit(){if(map&&points.length){map.fitBounds(points.map(p=>[p.lat,p.lon]),{padding:[35,35],maxZoom:18});}}
function activateView(name){
 activeView=name;rawGeneration++;clearTimeout(rawTimer);
 for(const button of document.querySelectorAll('[role=tab]')){const chosen=button.dataset.view===name;button.setAttribute('aria-selected',String(chosen));button.tabIndex=chosen?0:-1;$('panel-'+button.dataset.view).hidden=!chosen;}
 if(name==='map'&&map)requestAnimationFrame(()=>{map.invalidateSize();draw();});else draw();
}
const tabs=[...document.querySelectorAll('[role=tab]')];
for(const [i,button]of tabs.entries()){
 button.onclick=()=>activateView(button.dataset.view);
 button.onkeydown=e=>{let next=i;if(e.key==='ArrowRight')next=(i+1)%tabs.length;else if(e.key==='ArrowLeft')next=(i+tabs.length-1)%tabs.length;else if(e.key==='Home')next=0;else if(e.key==='End')next=tabs.length-1;else return;e.preventDefault();tabs[next].focus();activateView(tabs[next].dataset.view);};
}
function chart(id){const c=$(id),r=c.getBoundingClientRect(),dpr=devicePixelRatio||1;c.width=r.width*dpr;c.height=r.height*dpr;const ctx=c.getContext('2d');ctx.scale(dpr,dpr);ctx.fillStyle='#fff';ctx.fillRect(0,0,r.width,r.height);ctx.font='12px "IBM Plex Mono", "IBM Plex Sans JP", sans-serif';ctx.fillStyle='#53647b';return {ctx,w:r.width,h:r.height};}
function dot(ctx,x,y,color,r=3){ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fillStyle=color;ctx.fill();}
function drawScatter(data){const {ctx,w,h}=chart('scatter');if(!data.length){ctx.fillText('有効な測位点がありません',25,35);return;}const ref=points[0],cos=Math.cos(ref.lat*Math.PI/180);const xy=data.map(p=>[(p.lon-ref.lon)*111320*cos,(p.lat-ref.lat)*111320]);let extent=1;for(const [x,y]of xy)extent=Math.max(extent,Math.abs(x),Math.abs(y));extent*=1.1;const scale=Math.min(w-110,h-100)/(2*extent),cx=w/2,cy=h/2;ctx.strokeStyle='#e2e8f0';for(let i=-2;i<=2;i++){const d=i*extent/2*scale;ctx.beginPath();ctx.moveTo(cx+d,40);ctx.lineTo(cx+d,h-45);ctx.moveTo(50,cy+d);ctx.lineTo(w-30,cy+d);ctx.stroke();ctx.fillStyle='#53647b';ctx.fillText((i*extent/2).toFixed(1),cx+d-16,h-24);}ctx.fillText('北 ↑  南北・東西とも m（同じ縮尺）',20,22);for(let i=0;i<xy.length;i++)dot(ctx,cx+xy[i][0]*scale,cy-xy[i][1]*scale,colors[data[i].quality],2);const last=xy.at(-1);dot(ctx,cx+last[0]*scale,cy-last[1]*scale,'#005bac',6);ctx.fillStyle='#53647b';ctx.fillText('東 →',w-60,h-6);}
function seconds(p){const v=p.utc;return Number(v.slice(0,2))*3600+Number(v.slice(2,4))*60+Number(v.slice(4));}
function elapsed(){let sum=0;return points.map((p,i)=>{if(i){let d=seconds(p)-seconds(points[i-1]);if(d< -82800)d+=86400;sum+=d>0?d:.001;}return sum;});}
function drawSeries(){const {ctx,w,h}=chart('series');if(!points.length){ctx.fillText('有効な測位点がありません',25,35);return;}const field=$('seriesField').value,times=elapsed(),total=Math.max(times.at(-1),1);let max=field==='quality'?5:1;for(const p of points)if(Number.isFinite(p[field]))max=Math.max(max,p[field]);const x=t=>60+t/total*(w-90),y=v=>h-50-v/max*(h-90);ctx.fillStyle='#53647b';for(let i=0;i<=5;i++){const v=max*i/5;ctx.strokeStyle='#e2e8f0';ctx.beginPath();ctx.moveTo(60,y(v));ctx.lineTo(w-30,y(v));ctx.stroke();ctx.fillText(v.toFixed(field==='hdop'?1:0),18,y(v)+4);ctx.fillText((total*i/5).toFixed(1),x(total*i/5)-10,h-24);}ctx.fillText('経過時間（秒）',w-150,h-5);if(field==='quality')ctx.fillText('1 単独 / 2 補正 / 4 FIX / 5 FLOAT',60,20);for(let i=0;i<points.length;i++){const value=points[i][field];if(value==null||!Number.isFinite(value))continue;dot(ctx,x(times[i]),y(value),i<=cursor?(colors[points[i].quality]||'#005bac'):'#cbd5e1',2);}const p=points[cursor];if(p&&p[field]!=null)dot(ctx,x(times[cursor]),y(p[field]),'#005bac',6);$('series').onclick=e=>{const rect=e.currentTarget.getBoundingClientRect(),wanted=(e.clientX-rect.left-60)/(w-90)*total;let best=0;for(let i=1;i<times.length;i++)if(Math.abs(times[i]-wanted)<Math.abs(times[best]-wanted))best=i;stopPlay();$('follow').checked=false;cursor=best;draw();};}
function scheduleRaw(){clearTimeout(rawTimer);if($('rawPause').checked)return;const generation=++rawGeneration;rawTimer=setTimeout(()=>loadRaw(generation),120);}
async function loadRaw(version){if(!selected){$('rawText').textContent='計測を開始するか履歴を選択してください。';return;}const sid=selected,p=points[cursor],live=sid===state.active&&state.running&&$('follow').checked;try{const rows=await api('/api/raw?'+new URLSearchParams({session:sid,...(!live&&p?{utc:p.utc}:{})}));if(version!==rawGeneration||activeView!=='raw'||$('rawPause').checked)return;const kind=$('rawFilter').value;const filtered=rows.filter(r=>kind==='all'||kind==='error'&&!r.valid||r.text.slice(3,6)===kind);$('rawText').textContent=filtered.map(r=>`${r.number.toString().padStart(6)}  ${r.text}`).join('\n');$('rawInfo').textContent=`${live?'受信ログ末尾':'選択点まで'}の最大1,000行／表示 ${filtered.length}行。左端は元ログ行番号。同じUTCが複数日ある場合は最初の一致です。`;}catch(e){if(version===rawGeneration)$('rawInfo').textContent=e.message;}}
$('seriesField').onchange=drawSeries;$('rawFilter').onchange=scheduleRaw;$('rawPause').onchange=()=>{rawGeneration++;if(!$('rawPause').checked)scheduleRaw();};
async function ports(){const entries=await api('/api/ports');const old=$('source').value;$('source').replaceChildren();for(const e of [{device:'demo',description:'デモ（架空の位置）'},...(config.replay?[{device:'replay',description:'指定したログを再生'}]:[]),...entries]){const option=document.createElement('option');option.value=e.device;option.textContent=e.device==='demo'||e.device==='replay'?e.description:`${e.device} · ${e.description}`;$('source').append(option);}if([...$('source').options].some(o=>o.value===old))$('source').value=old;}
async function history(){const sessions=await api('/api/sessions');$('sessions').replaceChildren();for(const s of sessions){const button=document.createElement('button');button.className='session'+(s.id===selected?' active':'');button.textContent=s.title+(s.source==='demo'?' [デモ]':s.source==='replay'?' [ログ再生]':'');const detail=document.createElement('small');detail.textContent=`${dateFmt.format(new Date(s.started))} · ${s.point_count}点 · FIX ${s.fix_count}点 · ${s.status}`;button.append(detail);button.onclick=()=>select(s.id,s.title).catch(e=>error(e.message));$('sessions').append(button);}}
async function select(sid,title){generation++;selected=sid;currentTitle=title;points=[];cursor=0;stopPlay();$('follow').checked=sid===state.active&&state.running;for(const kind of ['csv','kml','log']){$(kind).href=`/api/export?session=${sid}&kind=${kind}`;$(kind).download=`${sid}.${kind}`;}draw();await fetchPoints();cursor=Math.max(0,points.length-1);draw();fit();await history();}
async function fetchPoints(){
 if(!selected||fetchingGeneration===generation)return;
 const gen=generation,sid=selected;fetchingGeneration=gen;
 try{
  let more=true,after=Math.max(0,(points.at(-1)?.id||0)-20);
  while(more){
   const data=await api(`/api/points?session=${sid}&after=${after}`);if(gen!==generation)return;
   const merged=new Map(points.map(p=>[p.id,p]));for(const p of data)merged.set(p.id,p);
   const wasEmpty=points.length===0;points=[...merged.values()].sort((a,b)=>a.id-b.id);
   more=data.length===5000;after=data.at(-1)?.id||after;
   if(points.length>50000){const removed=points.length-50000;points=points.slice(-50000);cursor=Math.max(0,cursor-removed);$('mapNotice').textContent='画面では直近50,000点を表示しています。全データはCSV・KML・元ログに保存されています。';}
   if($('follow').checked||wasEmpty)cursor=Math.max(0,points.length-1);
  }
  draw();
 }finally{if(fetchingGeneration===gen)fetchingGeneration=null;}
}
function stopPlay(){clearInterval(playing);playing=null;$('play').textContent='履歴を再生';}
$('start').onclick=async()=>{try{error('');$('start').disabled=true;const r=await api('/api/start',{source:$('source').value,baud:Number($('baud').value),title:$('title').value});state=await api('/api/state');await select(r.session,$('title').value||($('source').value==='demo'?'デモ':'計測'));}catch(e){error(e.message);}finally{$('start').disabled=!!state.running;}};
$('stop').onclick=async()=>{try{await api('/api/stop',{});state=await api('/api/state');await fetchPoints();await history();}catch(e){error(e.message);}};
$('ports').onclick=()=>ports().catch(e=>error(e.message));$('historyRefresh').onclick=()=>history().catch(e=>error(e.message));
$('cursor').oninput=()=>{stopPlay();$('follow').checked=false;cursor=Number($('cursor').value);draw();};$('latest').onclick=()=>{stopPlay();$('follow').checked=true;cursor=Math.max(0,points.length-1);draw();fit();};$('follow').onchange=()=>{if($('follow').checked)cursor=Math.max(0,points.length-1);draw();};
$('play').onclick=()=>{if(playing){stopPlay();return;}if(!points.length)return;$('follow').checked=false;cursor=0;$('play').textContent='再生停止';playing=setInterval(()=>{draw();if(cursor>=points.length-1)stopPlay();else cursor++;},200);};window.addEventListener('resize',draw);document.fonts.ready.then(draw);
async function tick(){try{state=await api('/api/state');$('start').disabled=state.running;$('stop').disabled=!state.running;$('source').disabled=state.running;$('baud').disabled=state.running;
 $('status').textContent=!state.running?'計測停止 · 履歴を確認できます':state.fresh?`受信中 · ${labels[state.quality]}`:state.rx_age===null||state.rx_age>3?'受信待ち／受信停止':'受信中 · 有効な現在位置なし';if(state.error)error(state.error);await fetchPoints();}catch(e){$('status').textContent='サーバーへの接続が切れました';error(e.message);state.running=false;state.fresh=false;draw();}finally{setTimeout(tick,1000);}}
(async()=>{try{config=await api('/api/config');await ports();await history();await loadMap();draw();tick();}catch(e){error(e.message);}})();
