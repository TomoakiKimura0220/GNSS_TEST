'use strict';
// WGS84 local tangent-plane offsets in metres; heading is clockwise from north.
const Mowing = (() => {
 const rad=Math.PI/180;
 function scales(lat){const s=Math.sin(lat*rad),d=1-0.00669437999014*s*s;return {north:6378137*(1-0.00669437999014)/d**1.5*rad,east:6378137/Math.sqrt(d)*Math.cos(lat*rad)*rad};}
 function offset(p,east,north){const s=scales(p.lat);return [p.lat+north/s.north,p.lon+east/s.east];}
 function track(points,seed=null){
  let heading=seed?.heading??0,reverse=seed?.reverse??false,anchor=seed?.anchor??null,segment=seed?.segment??null;
  return points.map(p=>{
   if(!anchor||segment!==p.segment){anchor=p;segment=p.segment;}
   else{
    const s=scales(anchor.lat),e=(p.lon-anchor.lon)*s.east,n=(p.lat-anchor.lat)*s.north;
    if(Math.hypot(e,n)>=.20){
     const travel=(Math.atan2(e,n)/rad+360)%360;
     let candidate=(travel+(reverse?180:0))%360;
     const delta=(candidate-heading+540)%360-180;
     if(Math.abs(delta)>120){reverse=!reverse;candidate=(candidate+180)%360;}
     heading=candidate;anchor=p;
    }
   }
   return {...p,heading,reverse,tracking:{heading,reverse,anchor,segment}};
  });
 }
 function blade(p,heading){const h=heading*rad,forward=[Math.sin(h),Math.cos(h)],right=[Math.cos(h),-Math.sin(h)];return {
  center:offset(p,.30*forward[0],.30*forward[1]),
  left:offset(p,.30*forward[0]-.25*right[0],.30*forward[1]-.25*right[1]),
  right:offset(p,.30*forward[0]+.25*right[0],.30*forward[1]+.25*right[1])};}
 // Sweep a radius-25 cm disk along each pair of corrected blade centres.
 // All rings have the same winding so retraced paths do not cancel their fill.
 function capsule(a,b){
  const scale=scales(a.lat),e=(b.lon-a.lon)*scale.east,n=(b.lat-a.lat)*scale.north;
  const angle=Math.atan2(n,e),ring=[];
  for(const [center,start] of [[b,angle-Math.PI/2],[a,angle+Math.PI/2]]){
   for(let i=0;i<=16;i++){
    const t=start+i*Math.PI/16;
    ring.push(offset(center,.25*Math.cos(t),.25*Math.sin(t)));
   }
  }
  return ring;
 }
 function strips(points,heading){
  return points.map((p,i)=>{
   const c=blade(p,p.heading??heading).center,b={lat:c[0],lon:c[1]};
   const previous=i&&points[i-1].segment===p.segment?blade(points[i-1],points[i-1].heading??heading).center:c;
   return {quality:p.quality,ring:capsule({lat:previous[0],lon:previous[1]},b)};
  });
 }
 return {track,blade,strips};
})();
if(typeof module!=='undefined')module.exports=Mowing;
