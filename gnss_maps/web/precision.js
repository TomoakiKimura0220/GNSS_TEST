'use strict';
// Local WGS84 coordinates in metres, east/right and north/up.
const PrecisionGeometry=(()=>{
 function project(p,origin){const rad=Math.PI/180,d=1-.00669437999014*Math.sin(origin.lat*rad)**2;const n=6378137*(1-.00669437999014)/d**1.5*rad,e=6378137/Math.sqrt(d)*Math.cos(origin.lat*rad)*rad;return [(p.lat-origin.lat)*n,(p.lon-origin.lon)*e];}
 function step(zoom){const wanted=55/2**zoom,power=10**Math.floor(Math.log10(wanted));return Math.max(.01,[1,2,5,10].find(n=>n*power>=wanted)*power);}
 return {project,step};
})();
function createPrecisionView(){
 const chart=L.map('precision',{crs:L.CRS.Simple,center:[0,0],zoom:3,minZoom:-8,maxZoom:16,preferCanvas:true});
 const grid=L.layerGroup().addTo(chart),shapes=L.layerGroup().addTo(chart);let origin=null,extent=null;
 function redrawGrid(){
  grid.clearLayers();const b=chart.getBounds(),step=PrecisionGeometry.step(chart.getZoom());
  const decimals=step<1?2:0;
  for(let x=Math.ceil(b.getWest()/step)*step;x<=b.getEast();x+=step){L.polyline([[b.getSouth(),x],[b.getNorth(),x]],{color:'#cad5df',weight:1,interactive:false}).addTo(grid);L.marker([b.getSouth()+(b.getNorth()-b.getSouth())*.04,x],{interactive:false,icon:L.divIcon({className:'precision-label',html:x.toFixed(decimals),iconSize:[60,16],iconAnchor:[30,8]})}).addTo(grid);}
  for(let y=Math.ceil(b.getSouth()/step)*step;y<=b.getNorth();y+=step){L.polyline([[y,b.getWest()],[y,b.getEast()]],{color:'#cad5df',weight:1,interactive:false}).addTo(grid);L.marker([y,b.getWest()+(b.getEast()-b.getWest())*.05],{interactive:false,icon:L.divIcon({className:'precision-label',html:y.toFixed(decimals),iconSize:[60,16],iconAnchor:[30,8]})}).addTo(grid);}
  document.getElementById('precisionInfo').textContent=`東 → / 北 ↑　単位m　1目盛り ${step<1?(step*100).toFixed(0)+' cm':step+' m'}。${origin?'原点 '+origin.lat.toFixed(8)+', '+origin.lon.toFixed(8):''}　目盛りは測位精度を保証しません。`;
 }
 chart.on('moveend zoomend resize',redrawGrid);
 return {
  render(data,outlines,rings){
   chart.invalidateSize();shapes.clearLayers();
   const next=outlines[0]?.[0]||data[0];if(!next){origin=null;extent=null;redrawGrid();return;}
   const changed=!origin||origin.lat!==next.lat||origin.lon!==next.lon;origin={lat:next.lat,lon:next.lon};
   const project=p=>PrecisionGeometry.project(p,origin);let bounds=L.latLngBounds([]);
   for(const ring of rings){const xy=ring.map(p=>project({lat:p[0],lon:p[1]}));L.polygon(xy,{stroke:false,fillColor:'#2563eb',fillOpacity:.35,interactive:false}).addTo(shapes);for(const p of xy)bounds.extend(p);}
   for(const group of outlines){const xy=group.map(project);L.polyline(xy,{color:'#059669',weight:3,dashArray:'6 5'}).addTo(shapes);for(const p of xy)bounds.extend(p);}
   const paths=[];let previous=null;for(const p of data){const xy=project(p);bounds.extend(xy);if(!previous||previous.segment!==p.segment)paths.push([]);paths.at(-1).push(xy);previous=p;}for(const path of paths)if(path.length>1)L.polyline(path,{color:'#526178',weight:1,interactive:false}).addTo(shapes);
   if(data.length)L.circleMarker(project(data.at(-1)),{radius:4,color:'#005bac'}).addTo(shapes);
   extent=bounds.isValid()?bounds:null;if(changed&&extent)chart.fitBounds(extent,{padding:[40,40],maxZoom:12});redrawGrid();
  },
  fit(){if(extent)chart.fitBounds(extent,{padding:[40,40],maxZoom:12});},
  centimetres(){chart.setZoom(13);},
 };
}
if(typeof module!=='undefined')module.exports=PrecisionGeometry;
