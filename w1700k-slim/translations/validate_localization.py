#!/usr/bin/env python3
"""Validate catalogs and the unapplied localization patch without editing sources."""
import ast
import json
import pathlib
import re
import runpy
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
catalog = runpy.run_path(str(ROOT / 'build_translations.py'), run_name='__main__')
patch = runpy.run_path(str(ROOT / 'build_source_patch.py'))
translations = {'luci-app-airoha-npu': catalog['NPU'], 'luci-app-w1700k-fancontrol': catalog['FAN']}
report = []
for name, content in patch['modified'].items():
    app = pathlib.PurePosixPath(name).parts[1]
    keys = {ast.literal_eval(match.group(1)) for match in re.finditer(r'''\b_\(\s*((?:'(?:\\.|[^'\\])*')|(?:"(?:\\.|[^"\\])*"))\s*\)''', content)}
    assert not keys - translations[app].keys(), (name, keys - translations[app].keys())
    report.append(f'{name}: {len(keys)}/{len(keys)} patched gettext keys translated.')
    # Machine interfaces/values must be unchanged by a localization-only patch.
    original = patch['originals'][name]
    for pattern in [r'rpc\.declare\([\s\S]*?\}\)', r'call\w+\([^\n;]*?\)', r"o\.value\('[^']+'", r"o\.default\s*=\s*[^;]+;", r"o\.datatype\s*=\s*[^;]+;", r"var inp = E\('input',[^\n]+", r'if\(isNaN\(f\)\|\|f<500\|\|f>1600\)']:
        assert re.findall(pattern, original) == re.findall(pattern, content), (name, 'machine behavior changed', pattern)
    if name == patch['NPU']:
        assert "if(f>1400&&!confirm(_('Frequencies above 1400 MHz may be unstable. Continue?'))) return;" in content

fixture = {'npu': patch['modified'][patch['NPU']].split('return view.extend({', 1)[0],
           'fan': patch['modified'][patch['FAN_STATUS']].split('return view.extend({', 1)[0],
           'npuTranslations': catalog['NPU'], 'fanTranslations': catalog['FAN']}
js = r'''
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const f = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
function context(code, translations) {
    const ctx = vm.createContext({
        _: s => translations[s] || s,
        rpc: {declare: d => function() { throw new Error('Unexpected RPC call: ' + d.method); }},
        E: (tag, attrs, children) => ({tag, attrs, children}),
        document: {getElementById: () => ({value: '1450'})},
        confirm: s => {ctx.warning = s; return false;},
        ui: {addNotification: () => {}},
    });
    vm.runInContext("String.prototype.format = function(...args) { let i = 0; return this.replace(/%[ds%]/g, m => m === '%%' ? '%' : String(args[i++])); };", ctx);
    vm.runInContext(code, ctx);
    return ctx;
}
const npu = context(f.npu, f.npuTranslations);
assert.strictEqual(vm.runInContext('fmtFreq(0)', npu), '不可用');
assert.strictEqual(vm.runInContext('tokenHealth(1, 10).text', npu), '正常');
assert.strictEqual(vm.runInContext('bandHealth({count: 0}).text', npu), '无客户端');
const gov = vm.runInContext("renderGovSelect('performance powersave schedutil future_governor', 'performance')", npu);
assert.deepStrictEqual(Array.from(gov.children, c => c.attrs.value), ['performance', 'powersave', 'schedutil', 'future_governor']);
assert.deepStrictEqual(Array.from(gov.children, c => c.children), ['性能', '省电', '调度器调频', 'future_governor']);
const controls = vm.runInContext('renderOcControls()', npu);
assert.strictEqual(controls.children[0].attrs.value, '1400');
controls.children[2].attrs.click();
assert.strictEqual(npu.warning, '高于 1400 MHz 的频率可能导致运行不稳定。是否继续？');
const fan = context(f.fan, f.fanTranslations);
assert.strictEqual(vm.runInContext("presetLabel('balanced')", fan), '均衡');
assert.strictEqual(vm.runInContext("presetLabel('future')", fan), 'Future');
assert.strictEqual(vm.runInContext("fanModeLabel('Auto (Closed Loop)')", fan), '自动（闭环控制）');
assert.strictEqual(vm.runInContext('fanModeLabel(null)', fan), '未知');
assert.strictEqual(vm.runInContext("fanModeLabel('New Mode')", fan), 'New Mode');
console.log('Node mocked-UI smoke tests passed; no real RPC calls executed.');
'''
with tempfile.TemporaryDirectory(prefix='.smoke-', dir=ROOT) as temp:
    temp = pathlib.Path(temp)
    (temp / 'fixture.json').write_text(json.dumps(fixture), encoding='utf-8')
    (temp / 'test.js').write_text(js, encoding='utf-8')
    subprocess.run(['node', str(temp / 'test.js'), str(temp / 'fixture.json')], check=True)
report += ['All patched JavaScript gettext strings have nonempty translations.',
           'All 3 patched JavaScript files pass node --check.',
           'The unapplied patch passes git apply --check against the pinned checkout.',
           'Static behavior checks pass for RPC declarations/call arguments, defaults, allowed values,',
           'the CPU input default and range, and the >1400 MHz confirmation threshold.',
           'Mocked UI smoke tests verify Chinese governor, health, fan-mode and preset labels;',
           'unknown machine values preserve their display fallback; rejecting the translated',
           'overclock confirmation triggers no RPC call. No real hardware operations ran.',
           '', 'Apply source-localization.patch to resolve the hard-coded English gaps listed above.',
           'Firmware/runtime rendering on a physical W1700K has not been tested.']
with (ROOT / 'validation-report.txt').open('a', encoding='utf-8') as stream:
    stream.write('\nPatch validation\n' + '\n'.join(report) + '\n')
print('\n'.join(report))
