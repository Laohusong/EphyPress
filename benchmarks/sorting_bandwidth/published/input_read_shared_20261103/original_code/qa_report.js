const fs=require('fs'),vm=require('vm'),assert=require('assert');
const root='F:/EphyPress_benchmarks/shared_cache_curve_30min_20261103';const html=fs.readFileSync(root+'/report.html','utf8');
const scripts=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];assert.equal(scripts.length,1);
const elements={};const context={console,document:{getElementById(id){return elements[id]??={value:id==='metric'?'seconds':'',checked:true,innerHTML:'',textContent:'',addEventListener(){}}}}};
vm.createContext(context);vm.runInContext(scripts[0][1],context);
let checks=0;
for(const metric of ['seconds','read_GB','observed_raw_over_method'])for(const log of [true,false])for(const old of [true,false]){
  elements.metric.value=metric;elements.log.checked=log;elements.old.checked=old;
  assert.equal(vm.runInContext('render()',context),old?3:2);
  assert.equal((elements.chart.innerHTML.match(/<circle /g)||[]).length,(old?3:2)*7);
  assert(!elements.chart.innerHTML.includes('NaN'));assert(!elements.chart.innerHTML.includes('Infinity'));checks++;
}
assert.equal((elements.summary.innerHTML.match(/<tr>/g)||[]).length,7);
assert.equal((elements.outputs.innerHTML.match(/<tr>/g)||[]).length,21);
assert(Buffer.byteLength(html)<512*1024);
assert(elements.anchor.textContent.includes('5000 MB/s raw'));
fs.writeFileSync(root+'/html_qa.json',JSON.stringify({success:true,combinations:checks,formal_new_runs:8,shared_curve_points:7,new_raw_anchor:1,historical_controls:14,qa:'Node VM with minimal DOM; SVG renderer and controls checked; no native browser screenshot QA'},null,2));console.log('HTML QA PASS');
