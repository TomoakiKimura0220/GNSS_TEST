const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(process.argv[2] || path.join(__dirname, '../gnss_maps/web/app.js'), 'utf8');
new vm.Script(source);
const elements = {};
const radios = ['std', 'seamlessphoto', 'google'].map(value => ({value, addEventListener(){}}));
let leafletCenter = {lat:35.18,lng:137.11}, leafletZoom=18,draws=0,loads=0;
const listeners={};
const context = vm.createContext({
 console, URLSearchParams, setTimeout, clearTimeout,
 config:{maps_key:''}, navigator:{onLine:true},
 $:id=>elements[id]??=(id==='follow'?{checked:false}:{}),
 document:{querySelectorAll:()=>radios,createElement:()=>({remove(){}}),head:{append(){loads++;}}},
 window:{addEventListener:(name,fn)=>listeners[name]=fn},
 map:{getCenter:()=>leafletCenter,getZoom:()=>leafletZoom,invalidateSize(){},hasLayer:()=>false,removeLayer(){},setView(c,z){leafletCenter={lat:c[0],lng:c[1]};leafletZoom=z;}},
 draw(){draws++;},
 google:{maps:{Map:class{constructor(el,options){this.options=options;this.c=options.center;this.z=options.zoom;}addListener(){}getCenter(){return {lat:()=>this.c.lat,lng:()=>this.c.lng};}getZoom(){return this.z;}setCenter(c){this.c=c;}setZoom(z){this.z=z;}},ControlPosition:{LEFT_TOP:1},event:{trigger(){}}}}
});
context.window.google=context.google;
vm.runInContext(source.slice(source.indexOf('// Google is loaded only')),context);
(async()=>{
 await vm.runInContext("switchMap('google')",context);
 assert.match(elements.mapNotice.textContent,/APIキー/);assert.equal(loads,0);
 context.config.maps_key='test';context.navigator.onLine=false;
 await vm.runInContext("switchMap('google')",context);
 assert.match(elements.mapNotice.textContent,/インターネット/);
 context.navigator.onLine=true;
 await vm.runInContext("switchMap('google')",context);
 assert.equal(elements.googleMap.hidden,false);assert.equal(elements.map.hidden,true);
 assert.equal(vm.runInContext('googleMap.getZoom()',context),18);
 vm.runInContext('googleMap.setCenter({lat:36,lng:138});googleMap.setZoom(19)',context);
 await vm.runInContext("switchMap('seamlessphoto')",context);
 assert.deepEqual(leafletCenter,{lat:36,lng:138});assert.equal(leafletZoom,19);
 assert.match(elements.mapNotice.textContent,/未取得/);
 await vm.runInContext("switchMap('google')",context);listeners.offline();
 assert.equal(elements.map.hidden,false);assert.equal(vm.runInContext('baseMap',context),'std');
 assert.ok(draws>=4);
 console.log('PASS: missing key, offline, view transfer, missing tiles, offline fallback; JS syntax');
})().catch(e=>{console.error(e);process.exitCode=1;});
