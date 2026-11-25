'use strict';
let precisionView=null,precisionNeedsFit=false;
const $ = id => document.getElementById(id);
const colors={1:'#64748b',2:'#d97706',4:'#059669',5:'#7c3aed'};
const labels={0:'測位不可',1:'単独測位',2:'差分補正',4:'RTK FIX',5:'RTK FLOAT'};
let mowingFront=.3,mowingSide=0,mowingOffsetValid=true;
let mowingHeading=0, mowingSeed=null, mowingExportBusy=false;
let referencePoint=null,matchPoint=null,referenceOutline=[],savedExperiment=null,experimentView=false,experimentBusy=false;
let rangeStart=0, rangeEnd=null;
let config, state={}, selected=null, points=[], cursor=0, generation=0, playing=null, fetchingGeneration=null;
let map=null, marker=null, lines=[], currentTitle='', activeView='map', rawGeneration=0, rawTimer=null;
const dateFmt=new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',fractionalSecondDigits:3});
function when(p){return p.measured ? dateFmt.format(new Date(p.measured)) : `UTC ${p.utc}（日付不明）`;}
function error(message){$('error').textContent=message;$('error').hidden=!message;}
async function api(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json','X-GNSS-Token':config.token},body:JSON.stringify(body)}:{});const data=await r.json();if(!r.ok)throw Error(data.error||'通信に失敗しました');return data;}
function clearMap(){for(const line of lines)line.remove();lines=[];if(marker){marker.remove();marker=null;}}
function chunks(visible){const groups=[];for(const p of visible){let last=groups.at(-1);if(!last||last.at(-1).segment!==p.segment||last.at(-1).quality!==p.quality){const previous=last?.at(-1);last=[];if(previous&&previous.segment===p.segment)last.push(previous);groups.push(last);}last.push(p);}return groups;}
function draw(){
 syncRange();
 const visible=displayPoints(points.slice(rangeStart,cursor+1)),p=visible.at(-1);
 updateAlignmentInfo();
 const mowing=$('mowingMode').checked&&mowingOffsetValid;
 $('mowingKml').disabled=mowingExportBusy||!mowing||mowingHeading===null||!visible.length;
 $('mowingStatus').textContent=!mowing?'OFF：アンテナの測位経路を表示します。':`推定帯：直径50 cm・前後 ${mowingFront*100} cm・左右 ${mowingSide*100} cm補正／北向き前進で開始。現在 ${p?.heading?.toFixed(1)??'0'}°・${p?.reverse?'後退':'前進'}（推定）。青点は刃の中心。`;

 $('count').textContent=points.length.toLocaleString();$('cursor').min=rangeStart;$('cursor').max=rangeLast();$('cursor').disabled=!points.length;$('cursor').value=cursor;
 const viewingLive=!experimentView&&selected===state.active&&state.running&&$('follow').checked;
 const fresh=viewingLive&&state.fresh;
 $('quality').textContent=viewingLive&&!fresh?'現在の位置なし':(p?`${p.quality} · ${labels[p.quality]}`:'—');
 $('sat').textContent=p?`${p.satellites}機 / ${p.hdop??'—'}`:'—';$('time').textContent=p?when(p):'—';
 $('viewTitle').textContent=selected?(viewingLive?'計測中 · ':'履歴 · ')+currentTitle:'計測を開始するか履歴を選択';
 $('pointInfo').textContent=p?`${$('alignEnabled').checked&&alignment()?'【位置合わせ後の座標】 ':''}${fresh?'現在の測位点':viewingLive?'最後の有効位置（現在位置ではありません）':'選択した履歴点'}｜${when(p)}｜緯度 ${p.lat.toFixed(8)} / 経度 ${p.lon.toFixed(8)}｜区間 ${p.segment}`:'有効な測位点を待っています。';
 $('google').hidden=!p;if(p)$('google').href=`https://www.google.com/maps/search/?api=1&query=${p.lat},${p.lon}`;
 if(activeView==='map'&&baseMap==='google'&&googleMap){drawGoogle(visible,p,viewingLive,fresh,mowing);}
 else if(activeView==='map'&&map){clearMap();drawReferenceLeaflet();
  if(mowing&&mowingHeading!==null){
   const groups={};for(const strip of Mowing.strips(visible,mowingHeading,mowingFront,mowingSide))(groups[strip.quality]??=[]).push([strip.ring]);
   for(const [quality,rings]of Object.entries(groups))lines.push(L.polygon(rings,{stroke:false,fillColor:colors[quality],fillOpacity:.55,fillRule:'nonzero',smoothFactor:0,interactive:false}).addTo(map));
  }
  for(const group of chunks(visible)){if(group.length>1)lines.push(L.polyline(group.map(p=>[p.lat,p.lon]),{color:colors[group.at(-1).quality],weight:mowing&&mowingHeading!==null?1:4,opacity:mowing&&mowingHeading!==null?.35:1}).addTo(map));}
  if(p&&(!viewingLive||fresh)){const position=mowing&&mowingHeading!==null?Mowing.blade(p,p.heading??0,mowingFront,mowingSide).center:[p.lat,p.lon];marker=L.circleMarker(position,{radius:7,color:'#005bac',fillOpacity:1}).addTo(map);marker.bindTooltip((mowing&&mowingHeading!==null?'推定した刃の中心 · ':'アンテナ · ')+when(p));if($('follow').checked)map.panTo([p.lat,p.lon]);}
 }else if(activeView==='precision'){if(!precisionView)precisionView=createPrecisionView();precisionView.render(visible,referenceGroups(),mowing?Mowing.strips(visible,mowingHeading,mowingFront,mowingSide).map(s=>s.ring):[]);if(precisionNeedsFit){precisionView.fit();precisionNeedsFit=false;}}
 else if(activeView==='scatter')drawScatter(visible);
 else if(activeView==='series')drawSeries();
 else if(activeView==='raw')scheduleRaw();
}

async function loadMap(){
 map=L.map('map',{center:[35,137],zoom:17,preferCanvas:true});
 L.control.scale({imperial:false}).addTo(map);
 let layers;try{layers=await api('/api/maps');}catch(e){$('mapNotice').textContent='地図を読み込めません：'+e.message;return;}const choices={};
 for(const layer of layers){const tile=L.tileLayer(`/tiles/${layer.id}/{z}/{x}/{y}`,{minZoom:layer.minzoom,maxNativeZoom:layer.maxzoom,maxZoom:22,attribution:layer.attribution});choices[layer.title]=tile;offlineLayers[layer.id]=tile;}
 if(layers.length){const b=layers[0].bounds?.split(',').map(Number);if(b?.length===4&&b.every(Number.isFinite))map.fitBounds([[b[1],b[0]],[b[3],b[2]]]);Object.values(choices)[0].addTo(map);baseMap=layers[0].id;radioMap(baseMap);$('mapNotice').textContent='保存済み地図を使用（オフライン）。詳細画像がない場所は保存済みの粗い画像で補います。保存範囲外は「全経路の地図を準備」で追加してください。';}
 else $('mapNotice').textContent='保存済み地図がありません。背景なしで経路を表示します。';
 map.on('dragstart',()=>{$('follow').checked=false;});
}
function fit(){const points=[...rangePoints(),...($('showOutline').checked?referenceOutline:[])];if(baseMap==='google'&&googleMap&&points.length){const bounds=new google.maps.LatLngBounds();for(const p of points)bounds.extend({lat:p.lat,lng:p.lon});googleMap.fitBounds(bounds,35);google.maps.event.addListenerOnce(googleMap,'idle',()=>{if(googleMap.getZoom()>18)googleMap.setZoom(18);});return;}if(map&&points.length){map.fitBounds(points.map(p=>[p.lat,p.lon]),{padding:[35,35],maxZoom:18});}}
function activateView(name){
 activeView=name;rawGeneration++;clearTimeout(rawTimer);
 for(const button of document.querySelectorAll('[role=tab]')){const chosen=button.dataset.view===name;button.setAttribute('aria-selected',String(chosen));button.tabIndex=chosen?0:-1;$('panel-'+button.dataset.view).hidden=!chosen;}
 if(name==='map'&&map)requestAnimationFrame(()=>{map.invalidateSize();if(googleMap)google.maps.event.trigger(googleMap,'resize');draw();});else draw();
}
const tabs=[...document.querySelectorAll('[role=tab]')];
for(const [i,button]of tabs.entries()){
 button.onclick=()=>activateView(button.dataset.view);
 button.onkeydown=e=>{let next=i;if(e.key==='ArrowRight')next=(i+1)%tabs.length;else if(e.key==='ArrowLeft')next=(i+tabs.length-1)%tabs.length;else if(e.key==='Home')next=0;else if(e.key==='End')next=tabs.length-1;else return;e.preventDefault();tabs[next].focus();activateView(tabs[next].dataset.view);};
}
function chart(id){const c=$(id),r=c.getBoundingClientRect(),dpr=devicePixelRatio||1;c.width=r.width*dpr;c.height=r.height*dpr;const ctx=c.getContext('2d');ctx.scale(dpr,dpr);ctx.fillStyle='#fff';ctx.fillRect(0,0,r.width,r.height);ctx.font='12px "IBM Plex Mono", "IBM Plex Sans JP", sans-serif';ctx.fillStyle='#53647b';return {ctx,w:r.width,h:r.height};}
function dot(ctx,x,y,color,r=3){ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fillStyle=color;ctx.fill();}
function drawScatter(data){const {ctx,w,h}=chart('scatter');if(!data.length){ctx.fillText('有効な測位点がありません',25,35);return;}const ref=data[0],cos=Math.cos(ref.lat*Math.PI/180);const xy=data.map(p=>[(p.lon-ref.lon)*111320*cos,(p.lat-ref.lat)*111320]);let extent=1;for(const [x,y]of xy)extent=Math.max(extent,Math.abs(x),Math.abs(y));extent*=1.1;const scale=Math.min(w-110,h-100)/(2*extent),cx=w/2,cy=h/2;ctx.strokeStyle='#e2e8f0';for(let i=-2;i<=2;i++){const d=i*extent/2*scale;ctx.beginPath();ctx.moveTo(cx+d,40);ctx.lineTo(cx+d,h-45);ctx.moveTo(50,cy+d);ctx.lineTo(w-30,cy+d);ctx.stroke();ctx.fillStyle='#53647b';ctx.fillText((i*extent/2).toFixed(1),cx+d-16,h-24);}ctx.fillText('北 ↑  南北・東西とも m（同じ縮尺）',20,22);for(let i=0;i<xy.length;i++)dot(ctx,cx+xy[i][0]*scale,cy-xy[i][1]*scale,colors[data[i].quality],2);const last=xy.at(-1);dot(ctx,cx+last[0]*scale,cy-last[1]*scale,'#005bac',6);ctx.fillStyle='#53647b';ctx.fillText('東 →',w-60,h-6);}
function seconds(p){const v=p.utc;return Number(v.slice(0,2))*3600+Number(v.slice(2,4))*60+Number(v.slice(4));}
function elapsed(points){let sum=0;return points.map((p,i)=>{if(i){let d=seconds(p)-seconds(points[i-1]);if(d< -82800)d+=86400;sum+=d>0?d:.001;}return sum;});}
function drawSeries(){const offset=rangeStart,data=rangePoints();const {ctx,w,h}=chart('series');if(!data.length){ctx.fillText('有効な測位点がありません',25,35);return;}const field=$('seriesField').value,times=elapsed(data),total=Math.max(times.at(-1),1);let max=field==='quality'?5:1;for(const p of data)if(Number.isFinite(p[field]))max=Math.max(max,p[field]);const x=t=>60+t/total*(w-90),y=v=>h-50-v/max*(h-90);ctx.fillStyle='#53647b';for(let i=0;i<=5;i++){const v=max*i/5;ctx.strokeStyle='#e2e8f0';ctx.beginPath();ctx.moveTo(60,y(v));ctx.lineTo(w-30,y(v));ctx.stroke();ctx.fillText(v.toFixed(field==='hdop'?1:0),18,y(v)+4);ctx.fillText((total*i/5).toFixed(1),x(total*i/5)-10,h-24);}ctx.fillText('経過時間（秒）',w-150,h-5);if(field==='quality')ctx.fillText('1 単独 / 2 補正 / 4 FIX / 5 FLOAT',60,20);for(let i=0;i<data.length;i++){const value=data[i][field];if(value==null||!Number.isFinite(value))continue;dot(ctx,x(times[i]),y(value),i+offset<=cursor?(colors[data[i].quality]||'#005bac'):'#cbd5e1',2);}const p=data[cursor-offset];if(p&&p[field]!=null)dot(ctx,x(times[cursor-offset]),y(p[field]),'#005bac',6);$('series').onclick=e=>{const rect=e.currentTarget.getBoundingClientRect(),wanted=(e.clientX-rect.left-60)/(w-90)*total;let best=0;for(let i=1;i<times.length;i++)if(Math.abs(times[i]-wanted)<Math.abs(times[best]-wanted))best=i;stopPlay();$('follow').checked=false;cursor=best+offset;draw();};}
function scheduleRaw(){clearTimeout(rawTimer);if($('rawPause').checked)return;const generation=++rawGeneration;rawTimer=setTimeout(()=>loadRaw(generation),120);}
async function loadRaw(version){if(!selected){$('rawText').textContent='計測を開始するか履歴を選択してください。';return;}const sid=selected,p=points[cursor],live=sid===state.active&&state.running&&$('follow').checked;try{const rows=await api('/api/raw?'+new URLSearchParams({session:sid,...(!live&&p?{utc:p.utc}:{})}));if(version!==rawGeneration||activeView!=='raw'||$('rawPause').checked)return;const kind=$('rawFilter').value;const filtered=rows.filter(r=>kind==='all'||kind==='error'&&!r.valid||r.text.slice(3,6)===kind);$('rawText').textContent=filtered.map(r=>`${r.number.toString().padStart(6)}  ${r.text}`).join('\n');$('rawInfo').textContent=`${live?'受信ログ末尾':'選択点まで'}の最大1,000行／表示 ${filtered.length}行。左端は元ログ行番号。同じUTCが複数日ある場合は最初の一致です。`;}catch(e){if(version===rawGeneration)$('rawInfo').textContent=e.message;}}
$('mowingMode').onchange=draw;
$('seriesField').onchange=drawSeries;$('rawFilter').onchange=scheduleRaw;$('rawPause').onchange=()=>{rawGeneration++;if(!$('rawPause').checked)scheduleRaw();};
async function ports(){const entries=await api('/api/ports');const old=$('source').value;$('source').replaceChildren();for(const e of [{device:'demo',description:'デモ（架空の位置）'},...(config.replay?[{device:'replay',description:'指定したログを再生'}]:[]),...entries]){const option=document.createElement('option');option.value=e.device;option.textContent=e.device==='demo'||e.device==='replay'?e.description:`${e.device} · ${e.description}`;$('source').append(option);}if([...$('source').options].some(o=>o.value===old))$('source').value=old;}
async function history(){const sessions=await api('/api/sessions');$('sessions').replaceChildren();for(const s of sessions){const button=document.createElement('button');button.className='session'+(s.id===selected?' active':'');button.textContent=s.title+(s.source==='demo'?' [デモ]':s.source==='replay'?' [ログ再生]':s.source==='import'?' [インポート]':'');const detail=document.createElement('small');detail.textContent=`${dateFmt.format(new Date(s.started))} · ${s.point_count}点 · FIX ${s.fix_count}点 · ${s.status}`;button.append(detail);button.onclick=()=>select(s.id,s.title).catch(e=>error(e.message));$('sessions').append(button);}}
async function select(sid,title){experimentView=false;savedExperiment=null;matchPoint=null;$('alignEnabled').checked=false;generation++;selected=sid;currentTitle=title;for(const url of mowingUrls)URL.revokeObjectURL(url);mowingUrls=[];$('mowingDownloads').replaceChildren();mowingHeading=0;mowingSeed=null;mowingFront=.3;mowingSide=0;mowingOffsetValid=true;$('mowingFront').value=30;$('mowingSide').value=0;$('mowingOffsetError').textContent='';points=[];cursor=0;rangeStart=0;rangeEnd=null;stopPlay();$('follow').checked=sid===state.active&&state.running;for(const kind of ['csv','kml','log']){$(kind).href=`/api/export?session=${sid}&kind=${kind}`;$(kind).download=`${sid}.${kind}`;}draw();await fetchPoints();cursor=Math.max(0,points.length-1);draw();fit();await history();}
async function fetchPoints(){
 if(!selected||experimentView||fetchingGeneration===generation)return;
 const gen=generation,sid=selected;fetchingGeneration=gen;
 try{
  let more=true,after=Math.max(0,(points.at(-1)?.id||0)-20);
  while(more){
   const data=await api(`/api/points?session=${sid}&after=${after}`);if(gen!==generation)return;
   const merged=new Map(points.map(p=>[p.id,p]));for(const p of data)merged.set(p.id,p);
   const wasEmpty=points.length===0;points=[...merged.values()].sort((a,b)=>a.id-b.id);
   points=Mowing.track(points,mowingSeed);
   more=data.length===5000;after=data.at(-1)?.id||after;

   if($('follow').checked||wasEmpty)cursor=Math.max(0,points.length-1);
  }
  draw();
 }finally{if(fetchingGeneration===gen)fetchingGeneration=null;}
}
function stopPlay(){clearInterval(playing);playing=null;$('play').textContent='履歴を再生';}
$('start').onclick=async()=>{try{error('');$('start').disabled=true;const r=await api('/api/start',{source:$('source').value,baud:Number($('baud').value),title:$('title').value});state=await api('/api/state');await select(r.session,$('title').value||($('source').value==='demo'?'デモ':'計測'));}catch(e){error(e.message);}finally{$('start').disabled=!!state.running;}};
$('stop').onclick=async()=>{try{await api('/api/stop',{});state=await api('/api/state');await fetchPoints();await history();}catch(e){error(e.message);}};
$('ports').onclick=()=>ports().catch(e=>error(e.message));$('historyRefresh').onclick=()=>history().catch(e=>error(e.message));
$('cursor').oninput=()=>{stopPlay();$('follow').checked=false;cursor=Number($('cursor').value);draw();};$('latest').onclick=()=>{rangeStart=0;rangeEnd=null;stopPlay();$('follow').checked=true;cursor=Math.max(0,points.length-1);draw();fit();};$('follow').onchange=()=>{if($('follow').checked){rangeStart=0;rangeEnd=null;cursor=Math.max(0,points.length-1);}draw();};
$('play').onclick=()=>{if(playing){stopPlay();return;}if(!points.length)return;$('follow').checked=false;cursor=rangeStart;$('play').textContent='再生停止';playing=setInterval(()=>{draw();if(cursor>=rangeLast())stopPlay();else cursor++;},200);};window.addEventListener('resize',draw);document.fonts.ready.then(draw);
async function tick(){try{state=await api('/api/state');$('start').disabled=state.running;$('stop').disabled=!state.running;$('source').disabled=state.running;$('baud').disabled=state.running;
 $('status').textContent=!state.running?'計測停止 · 履歴を確認できます':state.fresh?`受信中 · ${labels[state.quality]}`:state.rx_age===null||state.rx_age>3?'受信待ち／受信停止':'受信中 · 有効な現在位置なし';if(state.error)error(state.error);await fetchPoints();}catch(e){$('status').textContent='サーバーへの接続が切れました';error(e.message);state.running=false;state.fresh=false;draw();}finally{setTimeout(tick,1000);}}
(async()=>{try{config=await api('/api/config');await ports();await history();await refreshExperiments();await loadMap();draw();tick();}catch(e){error(e.message);}})();

$('importLog').onclick=async()=>{
 const file=$('importFile').files[0];
 if(!file){$('importStatus').textContent='ログファイルを選んでください。';return;}
 if(!file.size||file.size>50*1024*1024){$('importStatus').textContent='1バイト以上、50 MiB以下のログを選んでください。';return;}
 $('importLog').disabled=true;$('importFile').disabled=true;
 $('importStatus').textContent='読み込み中です。受信・記録は継続しています。';
 try{
  const response=await fetch('/api/import?'+new URLSearchParams({name:file.name}),{method:'POST',headers:{'X-GNSS-Token':config.token,'Content-Type':'application/octet-stream'},body:file});
  const result=await response.json();if(!response.ok)throw Error(result.error||'読み込みに失敗しました');
  await select(result.session,file.name);
  $('importStatus').textContent=`読み込み完了：${result.count.toLocaleString()}点。履歴から再表示できます。`;
 }catch(e){$('importStatus').textContent=e.message;}
 finally{$('importLog').disabled=false;$('importFile').disabled=false;}
};

$('prepareMap').onclick=async()=>{
 if(!selected){error('先に履歴を選んでください。');return;}
 $('prepareMap').disabled=true;$('mapNotice').textContent='経路全体と周囲の地図を国土地理院から取得中です。';
 try{await api('/api/maps/prepare',{session:selected});map.eachLayer(layer=>{if(layer instanceof L.TileLayer)layer.redraw();});$('mapNotice').textContent='地図の準備が完了しました。保存した範囲はオフラインでも表示できます。';error('');}
 catch(e){error(e.message);$('mapNotice').textContent='地図の取得に失敗しました。保存済み画像で表示を続けます。';}
 finally{$('prepareMap').disabled=false;}
};

let mowingUrls=[];
$('mowingKml').onclick=async()=>{
 if(mowingExportBusy||!mowingOffsetValid)return;if($('alignEnabled').checked&&alignment()&&!savedExperiment){error('位置合わせした草刈り幅を出力するには、先に区間を保存して開いてください。');return;}
 mowingExportBusy=true;
 const sid=selected,gen=generation;
 const visible=points.slice(rangeStart,cursor+1);
 $('mowingKml').disabled=true;
 $('mowingDownloads').textContent='帯の重なりを統合しています…';
 try{
  const result=await api('/api/mowing/export',{session:sid,first:visible[0].id,last:visible.at(-1).id,experiment:$('alignEnabled').checked?savedExperiment?.id:null,heading:mowingHeading,front:mowingFront,side:mowingSide,title:currentTitle});
  if(gen!==generation)return;
  for(const url of mowingUrls)URL.revokeObjectURL(url);mowingUrls=[];
  $('mowingDownloads').replaceChildren();
  const note=document.createElement('span');note.textContent=`${result.points}点 → ${result.polygons}個の面に統合しました（緑色）。`;
  const url=URL.createObjectURL(new Blob([result.kml],{type:'application/vnd.google-earth.kml+xml'}));mowingUrls.push(url);
  const a=document.createElement('a');a.href=url;a.download=`${sid}-mowing.kml`;a.textContent='統合した草刈り幅KMLを保存';
  $('mowingDownloads').append(note,a);
 }catch(e){if(gen===generation){$('mowingDownloads').textContent='作成できませんでした。';error(e.message);}}
 finally{mowingExportBusy=false;draw();}
};

// Google is loaded only on explicit selection; offline tiles never contact Google.
let baseMap='std',offlineLayers={},googleMap=null,googleOverlays=[],googleLoading=null,mapSwitch=0,googleAuthFailed=false;
function mapNotice(text){$('mapNotice').textContent=text;}
function radioMap(value){for(const input of document.querySelectorAll('[name=basemap]'))input.checked=input.value===value;}
function loadGoogle(){
 if(googleAuthFailed)return Promise.reject(Error('Googleの認証に失敗しました。APIキー・請求先・許可URLを確認して再読み込みしてください。'));
 if(window.google?.maps?.Map)return Promise.resolve();
 if(googleLoading)return googleLoading;
 googleLoading=new Promise((resolve,reject)=>{
  const script=document.createElement('script');let timer,finished=false;
  const finish=err=>{if(finished)return;finished=true;clearTimeout(timer);if(err){script.remove();reject(err);}else resolve();};
  window.gnssGoogleReady=()=>finish();
  window.gm_authFailure=()=>{googleAuthFailed=true;const message='Googleの認証に失敗しました。APIキー・請求先・許可URLを確認してください。';finish(Error(message));if(baseMap==='google'){switchMap('std');mapNotice(message+' 国土地理院の地図へ戻しました。');}};
  script.src='https://maps.googleapis.com/maps/api/js?'+new URLSearchParams({key:config.maps_key,callback:'gnssGoogleReady',loading:'async',v:'quarterly',language:'ja'});
  script.onerror=()=>finish(Error('Google航空写真を読み込めません。インターネット接続を確認してください。'));
  timer=setTimeout(()=>finish(Error('Google航空写真の読み込みがタイムアウトしました。接続を確認して再度選択してください。')),15000);
  document.head.append(script);
 }).catch(e=>{googleLoading=null;throw e;});
 return googleLoading;
}
async function switchMap(next){
 const request=++mapSwitch,previous=baseMap;radioMap(previous);
 if(next==='google'){
  if(!config.maps_key){mapNotice('Google航空写真にはAPIキーの設定が必要です。GOOGLE_MAPS_API_KEYを設定してアプリを再起動してください。');return;}
  if(!navigator.onLine){mapNotice('Google航空写真にはインターネット接続が必要です。保存済み地図を使用してください。');return;}
  mapNotice('Google航空写真を読み込んでいます…');
  try{await loadGoogle();if(request!==mapSwitch)return;if(!navigator.onLine)throw Error('Google航空写真にはインターネット接続が必要です。');if(googleAuthFailed)throw Error('Googleの認証に失敗しました。設定を確認して再読み込みしてください。');
   const c=map.getCenter(),zoom=map.getZoom();
   $('googleMap').hidden=false;$('map').hidden=true;
   if(!googleMap){googleMap=new google.maps.Map($('googleMap'),{center:{lat:c.lat,lng:c.lng},zoom,mapTypeId:'satellite',mapTypeControl:false,streetViewControl:false,fullscreenControl:false,tilt:0,scaleControl:true,zoomControlOptions:{position:google.maps.ControlPosition.LEFT_TOP}});googleMap.addListener('dragstart',()=>{$('follow').checked=false;});}
   else if(previous!=='google'){google.maps.event.trigger(googleMap,'resize');googleMap.setCenter({lat:c.lat,lng:c.lng});googleMap.setZoom(zoom);}
   baseMap=next;radioMap(next);mapNotice('Google航空写真（オンライン）。画像は保存されません。経路と生データは従来どおり保存できます。');draw();
  }catch(e){if(request===mapSwitch){$('googleMap').hidden=previous!=='google';$('map').hidden=previous==='google';radioMap(previous);mapNotice(e.message);}}
  return;
 }
 const c=previous==='google'?googleMap?.getCenter():null,z=previous==='google'?googleMap?.getZoom():null;
 baseMap=next;$('googleMap').hidden=true;$('map').hidden=false;map.invalidateSize();
 for(const tile of Object.values(offlineLayers))if(map.hasLayer(tile))map.removeLayer(tile);
 if(offlineLayers[next])offlineLayers[next].addTo(map);
 if(c)map.setView([c.lat(),c.lng()],z,{animate:false});
 radioMap(next);mapNotice(offlineLayers[next]?'保存済み地図を使用（オフライン）。保存範囲外は「全経路の地図を準備」で追加できます。':'この背景地図は未取得です。背景なしで経路を表示します。「全経路の地図を準備」で取得してください。');draw();
}
function drawGoogle(visible,p,viewingLive,fresh,mowing){
 for(const item of googleOverlays)item.setMap(null);googleOverlays=[];drawReferenceGoogle();
 const position=pair=>({lat:pair[0],lng:pair[1]});
 if(mowing&&mowingHeading!==null)for(const strip of Mowing.strips(visible,mowingHeading,mowingFront,mowingSide))googleOverlays.push(new google.maps.Polygon({map:googleMap,paths:strip.ring.map(position),strokeWeight:0,fillColor:colors[strip.quality],fillOpacity:.55,clickable:false}));
 for(const group of chunks(visible))if(group.length>1)googleOverlays.push(new google.maps.Polyline({map:googleMap,path:group.map(p=>({lat:p.lat,lng:p.lon})),strokeColor:colors[group.at(-1).quality],strokeWeight:mowing?1:4,strokeOpacity:mowing?.35:1,clickable:false}));
 if(p&&(!viewingLive||fresh)){const center=position(mowing&&mowingHeading!==null?Mowing.blade(p,p.heading??0,mowingFront,mowingSide).center:[p.lat,p.lon]);googleOverlays.push(new google.maps.Marker({map:googleMap,position:center,title:when(p),icon:{path:google.maps.SymbolPath.CIRCLE,scale:7,fillColor:'#005bac',fillOpacity:1,strokeWeight:1,strokeColor:'#fff'}}));if($('follow').checked)googleMap.panTo({lat:p.lat,lng:p.lon});}
}
for(const input of document.querySelectorAll('[name=basemap]'))input.addEventListener('change',()=>switchMap(input.value));
window.addEventListener('offline',()=>{if(baseMap==='google'){switchMap('std');mapNotice('インターネット接続が切れたため、国土地理院の地図へ戻しました。受信・記録は継続します。');}});

function rangeLast(){return Math.min(rangeEnd??Math.max(0,points.length-1),Math.max(0,points.length-1));}
function rangePoints(){return displayPoints(points.slice(rangeStart,rangeLast()+1));}
function syncRange(){
 const last=rangeLast();rangeStart=Math.min(rangeStart,last);cursor=Math.max(rangeStart,Math.min(cursor,last));
 for(const [id,value] of [['rangeStart',rangeStart],['rangeEnd',last]]){const el=$(id);el.max=Math.max(0,points.length-1);el.value=value;el.disabled=!points.length;}
 for(const id of ['rangeStartHere','rangeEndHere','rangeReset'])$(id).disabled=!points.length;
 $('rangeStartTime').textContent=points.length?`${rangeStart+1}点目 · ${when(points[rangeStart])}`:'—';
 $('rangeEndTime').textContent=points.length?`${last+1}点目 · ${when(points[last])}`:'—';
 $('rangeInfo').textContent=points.length?`選択区間：${(last-rangeStart+1).toLocaleString()}点／全${points.length.toLocaleString()}点（開始・終了を含む）`:'有効な測位点がありません。';
}
function changeRange(which,value){
 if(!points.length)return;
 stopPlay();$('follow').checked=false;
 value=Math.max(0,Math.min(Math.trunc(Number(value))||0,points.length-1));
 const last=rangeLast();
 if(which==='start'){rangeStart=value;rangeEnd=Math.max(value,last);}else{rangeEnd=value;rangeStart=Math.min(rangeStart,value);}
 cursor=rangeLast();draw();
}
$('rangeStart').oninput=e=>changeRange('start',e.target.value);
$('rangeEnd').oninput=e=>changeRange('end',e.target.value);
$('rangeStartHere').onclick=()=>changeRange('start',cursor);
$('rangeEndHere').onclick=()=>changeRange('end',cursor);
$('rangeReset').onclick=()=>{stopPlay();rangeStart=0;rangeEnd=null;cursor=rangeLast();draw();fit();};

function updateMowingOffset(){
 const front=$('mowingFront'),side=$('mowingSide');
 mowingOffsetValid=front.value!==''&&side.value!==''&&front.checkValidity()&&side.checkValidity();
 $('mowingOffsetError').textContent=mowingOffsetValid?'':'前後・左右とも−1000〜1000 cmの数値を入力してください。補正表示と草刈り幅KMLを停止しています。';
 if(mowingOffsetValid){mowingFront=Number(front.value)/100;mowingSide=Number(side.value)/100;}
 for(const url of mowingUrls)URL.revokeObjectURL(url);mowingUrls=[];$('mowingDownloads').replaceChildren();
 draw();
}
$('mowingFront').oninput=updateMowingOffset;$('mowingSide').oninput=updateMowingOffset;

function alignment(){
 if(!referencePoint||!matchPoint||matchPoint.session!==selected)return null;
 const first=points[rangeStart],last=points[rangeLast()];
 if(!first||matchPoint.id<first.id||matchPoint.id>last.id)return null;
 const dlat=referencePoint.lat-matchPoint.lat,dlon=referencePoint.lon-matchPoint.lon;
 const rad=Math.PI/180,d=1-.00669437999014*Math.sin(referencePoint.lat*rad)**2;
 const n=6378137*(1-.00669437999014)/d**1.5*rad,e=6378137/Math.sqrt(d)*Math.cos(referencePoint.lat*rad)*rad;
 return {dlat,dlon,north:dlat*n,east:dlon*e};
}
function displayPoints(data){const delta=$('alignEnabled').checked?alignment():null;return delta?data.map(p=>({...p,lat:p.lat+delta.dlat,lon:p.lon+delta.dlon})):data;}
function updateAlignmentInfo(){
 const a=alignment(),describe=p=>p?`${when(p)}／品質${p.quality}／点ID ${p.id}／${p.lat.toFixed(8)}, ${p.lon.toFixed(8)}`:'未指定';
 $('alignmentInfo').textContent=`FIX基準：${describe(referencePoint)} ｜位置合わせ点：${describe(matchPoint)} ｜${a?`東 ${a.east.toFixed(3)} m・北 ${a.north.toFixed(3)} m（負は西・南）`:'区間内の品質2の対応点を指定してください'}`;
 $('alignEnabled').disabled=!a;
 $('pointNumber').max=points.length;$('pointNumber').value=points.length?cursor+1:1;
 $('previousPoint').disabled=!points.length||cursor<=rangeStart;$('nextPoint').disabled=!points.length||cursor>=rangeLast();
}
function referenceGroups(){
 if(!$('showOutline').checked)return [];
 const groups=[];let current=null,previous=null;
 for(const p of referenceOutline){if(p.quality!==4){current=null;previous=null;continue;}if(!current||p.segment!==previous.segment){current=[];groups.push(current);}current.push(p);previous=p;}
 return groups.filter(g=>g.length>1);
}
function drawReferenceLeaflet(){for(const g of referenceGroups())lines.push(L.polyline(g.map(p=>[p.lat,p.lon]),{color:'#059669',weight:3,opacity:.6,dashArray:'6 5'}).addTo(map));if(referencePoint&&$('showOutline').checked)lines.push(L.circleMarker([referencePoint.lat,referencePoint.lon],{radius:9,color:'#059669',fillOpacity:0}).addTo(map));}
function drawReferenceGoogle(){for(const g of referenceGroups())googleOverlays.push(new google.maps.Polyline({map:googleMap,path:g.map(p=>({lat:p.lat,lng:p.lon})),strokeColor:'#059669',strokeWeight:3,strokeOpacity:.6,clickable:false}));if(referencePoint&&$('showOutline').checked)googleOverlays.push(new google.maps.Marker({map:googleMap,position:{lat:referencePoint.lat,lng:referencePoint.lon},title:'FIX基準点',icon:{path:google.maps.SymbolPath.CIRCLE,scale:9,fillOpacity:0,strokeColor:'#059669',strokeWeight:2}}));}
function movePoint(value){stopPlay();$('follow').checked=false;cursor=Math.max(rangeStart,Math.min(rangeLast(),Math.trunc(Number(value))||0));draw();}
$('previousPoint').onclick=()=>movePoint(cursor-1);$('nextPoint').onclick=()=>movePoint(cursor+1);$('jumpPoint').onclick=()=>movePoint(Number($('pointNumber').value)-1);
function invalidateExperiment(){savedExperiment=null;for(const u of mowingUrls)URL.revokeObjectURL(u);mowingUrls=[];$('mowingDownloads').replaceChildren();}
$('setReference').onclick=()=>{const p=points[cursor];if(!p||p.quality!==4){error('品質4（FIX）の地点を選んでください。');return;}referencePoint={...p,session:selected};referenceOutline=points.map(p=>({...p}));invalidateExperiment();error('');draw();};
$('setMatch').onclick=()=>{const p=points[cursor];if(!p||p.quality!==2){error('品質2（差分補正）の地点を選んでください。');return;}matchPoint={...p,session:selected};invalidateExperiment();error('');draw();};
$('clearAlignment').onclick=()=>{referencePoint=null;matchPoint=null;referenceOutline=[];$('alignEnabled').checked=false;invalidateExperiment();draw();};
$('alignEnabled').onchange=()=>{for(const u of mowingUrls)URL.revokeObjectURL(u);mowingUrls=[];$('mowingDownloads').replaceChildren();draw();};$('showOutline').onchange=draw;
async function refreshExperiments(){const rows=await api('/api/experiments');for(const id of ['experiments','comparisonBoundary','comparisonRun']){const previous=$(id).value;$(id).replaceChildren();for(const row of rows){const option=document.createElement('option');option.value=row.id;option.textContent=`${row.title} ｜ ${when(row.start)} → ${when(row.end)}`;$(id).append(option);}if(rows.some(r=>r.id===previous))$(id).value=previous;}}
$('saveExperiment').onclick=async()=>{
 if(experimentBusy||!points.length)return;
 if(!mowingOffsetValid){error('取り付け補正の数値を確認してください。');return;}
 if(matchPoint&&!alignment()){error('位置合わせ点が区間外です。点を選び直すか、位置合わせを解除してください。');return;}
 const gen=generation;experimentBusy=true;$('saveExperiment').disabled=true;
 try{const payload={session:selected,title:$('experimentTitle').value,first:points[rangeStart].id,last:points[rangeLast()].id,front:mowingFront,side:mowingSide,reference:matchPoint?referencePoint:null,match:matchPoint};const row=await api('/api/experiments',payload);if(gen!==generation)return;await refreshExperiments();$('experiments').value=row.id;error('');$('alignmentInfo').textContent+=' ｜区間を保存しました。「選択した区間を開く」で再表示できます。';}
 catch(e){error(e.message);}finally{experimentBusy=false;$('saveExperiment').disabled=false;}
};
$('openExperiment').onclick=async()=>{
 const id=$('experiments').value;if(!id||experimentBusy)return;
 const gen=generation;experimentBusy=true;$('openExperiment').disabled=true;
 try{const data=await api('/api/experiment?'+new URLSearchParams({id}));if(gen!==generation)return;
 generation++;stopPlay();experimentView=true;savedExperiment=data.experiment;selected=savedExperiment.session;currentTitle=savedExperiment.title;
 points=data.points;rangeStart=0;rangeEnd=points.length-1;cursor=rangeLast();referencePoint=savedExperiment.reference;matchPoint=savedExperiment.match;referenceOutline=data.outline;
 mowingFront=savedExperiment.front;mowingSide=savedExperiment.side;mowingOffsetValid=true;$('mowingFront').value=mowingFront*100;$('mowingSide').value=mowingSide*100;$('mowingOffsetError').textContent='';
 $('experimentTitle').value=savedExperiment.title;$('follow').checked=false;$('alignEnabled').checked=!!referencePoint;
 for(const u of mowingUrls)URL.revokeObjectURL(u);mowingUrls=[];$('mowingDownloads').replaceChildren();
 for(const kind of ['csv','kml','log']){$(kind).href=`/api/export?session=${selected}&kind=${kind}`;$(kind).download=`${selected}.${kind}`;}
 error('');draw();fit();
 }catch(e){error(e.message);}finally{experimentBusy=false;$('openExperiment').disabled=false;}
};

$('precisionFit').onclick=()=>precisionView?.fit();$('precisionCm').onclick=()=>precisionView?.centimetres();
$('compareExperiments').onclick=async()=>{
 const boundaryId=$('comparisonBoundary').value,runId=$('comparisonRun').value;
 if(!boundaryId||!runId){error('外周と実験の保存区間を選んでください。');return;}
 if(boundaryId===runId){error('外周と実験には別々の区間を選んでください。');return;}
 if(experimentBusy)return;
 const gen=generation;$('compareExperiments').disabled=true;
 try{
  const boundary=await api('/api/experiment?'+new URLSearchParams({id:boundaryId}));if(gen!==generation)return;
  if(!boundary.points.some(p=>p.quality===4))throw Error('外周の区間にFIX点がありません。');
  $('experiments').value=runId;await $('openExperiment').onclick();
  if(savedExperiment?.id!==runId)return;
  referenceOutline=boundary.points;$('showOutline').checked=true;$('mowingMode').checked=true;
  $('comparisonStatus').textContent=`外周：${boundary.experiment.title}（FIXのみ・未補正）／実験：${savedExperiment.title}（前後 ${mowingFront*100} cm、左右 ${mowingSide*100} cm）。航空写真は地図右上で選択、平面図は専用タブで表示します。`;
  if(!referencePoint)$('alignEnabled').checked=false;
  precisionNeedsFit=true;draw();fit();error('');
 }catch(e){error(e.message);}finally{$('compareExperiments').disabled=false;}
};
