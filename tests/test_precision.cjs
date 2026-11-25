const assert=require('node:assert/strict');
const geometry=require('../gnss_maps/web/precision.js');
const origin={lat:35,lon:137};
const zero=geometry.project(origin,origin);assert.equal(zero[0],0);assert.equal(zero[1],0);
const north=geometry.project({lat:35.000001,lon:137},origin);assert.ok(north[0]>.11&&north[0]<.112);assert.equal(north[1],0);
const east=geometry.project({lat:35,lon:137.000001},origin);assert.ok(east[1]>.09&&east[1]<.092);assert.equal(east[0],0);
assert.equal(geometry.step(13),.01);
assert.ok(geometry.step(3)>=1);
console.log('Local metre projection and 1 cm grid: passed');
