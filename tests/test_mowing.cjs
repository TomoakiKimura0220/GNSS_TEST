const assert=require('node:assert/strict');
const m=require('../gnss_maps/web/mowing.js');
const a={lat:35,lon:137,segment:1,quality:4};
const b={...a,lat:35.00003};
const blade=m.blade(a,0);
const northScale=110940.5745,eastScale=91288.1696;
assert.ok(Math.abs((blade.center[0]-a.lat)*northScale-.30)<.00001);
assert.ok(Math.abs((blade.right[1]-blade.left[1])*eastScale-.50)<.00001);
assert.equal(blade.center[1],a.lon);
const disconnected=m.strips([a,{...b,segment:2}],0);
assert.equal(disconnected.length,2);
for(const strip of disconnected){
 const lats=strip.ring.map(p=>p[0]);
 assert.ok((Math.max(...lats)-Math.min(...lats))*northScale<.501,'gap must contain only isolated disks');
}
const strips=m.strips([a,b,a],0);
assert.equal(strips.length,3);
const area=ring=>ring.reduce((sum,p,i)=>{const q=ring[(i+1)%ring.length],o=ring[0];return sum+(p[1]-o[1])*(q[0]-o[0])-(q[1]-o[1])*(p[0]-o[0]);},0);
assert.ok(strips.every(s=>area(s.ring)>0),'reverse travel must not cancel filled coverage');
assert.deepEqual(m.blade(a,0),blade,'returning to same antenna point preserves forward offset');
console.log('Mowing geometry: passed');

// Width perpendicular to travel must stay 50 cm even when heading is fixed north.
for(const angle of [0,Math.PI/4,Math.PI/2,Math.PI,Math.PI*1.5]){
 const e=Math.cos(angle),n=Math.sin(angle);
 const end={...a,lat:a.lat+2*n/northScale,lon:a.lon+2*e/eastScale};
 const ring=m.strips([a,end],0)[1].ring;
 const cross=ring.map(p=>-(p[1]-a.lon)*eastScale*n+(p[0]-a.lat)*northScale*e);
 assert.ok(Math.abs(Math.max(...cross)-Math.min(...cross)-.5)<.001,'constant width in every direction');
}
const disk=m.strips([a],0)[0].ring;
for(const p of disk)assert.ok(Math.abs(Math.hypot((p[0]-blade.center[0])*northScale,(p[1]-blade.center[1])*eastScale)-.25)<.00001);
console.log('Circular blade sweep: passed');

const trajectory=[[0,0],[0,1],[.5,1.866],[1.366,2.366],[2.366,2.366],[1.366,2.366],[2.366,2.366]].map(([x,y])=>({...a,lat:35+y/northScale,lon:137+x/eastScale}));
const tracked=m.track(trajectory);
assert.ok(Math.abs(tracked[4].heading-90)<.01);
assert.ok(Math.abs(tracked[5].heading-90)<.01);
assert.equal(tracked[5].reverse,true);
assert.equal(tracked[6].reverse,false);
assert.deepEqual(m.track(trajectory.slice(3),tracked[2].tracking).map(p=>p.heading),tracked.slice(3).map(p=>p.heading));
console.log('Heading tracking: passed');
