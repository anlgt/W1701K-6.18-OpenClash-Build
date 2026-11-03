import fs from 'node:fs';
import assert from 'node:assert/strict';
const root=process.argv[2];
const E=(tag,attrs,children)=>({tag,attrs,children});
const rpc={declare:()=>()=>{}};
const fanSource=fs.readFileSync(root+'/package/luci-app-w1700k-fancontrol/htdocs/luci-static/resources/view/fan/status.js','utf8');
const fields={};const document={getElementById:id=>fields[id]};
const fan=new Function('rpc','_','E','document',fanSource.split('return view.extend')[0]+'; return {formatTemperature,createTempGauge,updateGauge};')(rpc,x=>x,E,document);
assert.equal(fan.formatTemperature(0),'0°C');
assert.equal(fan.formatTemperature(-5),'-5°C');
assert.equal(fan.formatTemperature(null),'Unavailable');
assert.equal(fan.formatTemperature(undefined),'Unavailable');
assert.equal(fan.formatTemperature(NaN),'Unavailable');
fields['phy-bar']={style:{}};fields['phy-value']={};
fan.updateGauge('phy',null);assert.equal(fields['phy-value'].textContent,'Unavailable');assert.equal(fields['phy-bar'].style.width,'0%');
fan.updateGauge('phy',47);assert.equal(fields['phy-value'].textContent,'47°C');
const npuSource=fs.readFileSync(root+'/package/luci-app-airoha-npu/htdocs/luci-static/resources/view/airoha_npu/status.js','utf8');
assert.doesNotMatch(npuSource,/callSetOverclock|renderOcControls|oc-freq-input/);
const npu=new Function('rpc','_','E','document',npuSource.split('return view.extend')[0]+'; return {renderFreqBar,renderGovSelect,renderMaxFreqSelect,updateFreqBar,renderPpeRows};')(rpc,x=>x,E,document);
assert.match(npu.renderFreqBar(0,0,0,1200,'unknown').children,/1200 MHz.*CPUFreq unavailable/);
assert.match(npu.renderGovSelect('','unknown').children,/not initialized/);
assert.match(npu.renderMaxFreqSelect('',0).children,/not initialized/);
fields['cpu-freq-unavailable']={};npu.updateFreqBar(0,0,0,1400,'unknown');assert.match(fields['cpu-freq-unavailable'].textContent,/1400 MHz/);
assert.equal(npu.renderGovSelect('ondemand performance','ondemand').tag,'select');
console.log('PASS: missing/invalid temperatures stay unavailable, valid zero/negative survive; PLL fallback updates without invented governor or max frequency');

assert.doesNotMatch(npuSource,/LAN3\/4|LAN2 10G|Switch 1G|USXGMII 10G|_\('Active'\)/);
const flows=npu.renderPpeRows([
  {index:'1',state:'UNB',type:'IPv4 NAPT',orig:'original',new_flow:'garbage',eth:'garbage'},
  {index:'2',state:'BND',type:'IPv4 NAPT',orig:'original',new_flow:'translated',eth:'aa->bb'}
]);
assert.equal(flows[0].children[3].children,'original');
assert.equal(flows[0].children[4].children,'-');
assert.equal(flows[0].children[5].children,'-');
assert.equal(flows[1].children[4].children,'translated');
assert.equal(flows[1].children[5].children,'aa->bb');
console.log('PASS: neutral GDM port labels, driver-bound NPU state, and unbound PPE fields hidden');
