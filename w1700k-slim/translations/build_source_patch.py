#!/usr/bin/env python3
"""Generate an unapplied gettext-only patch from the pinned upstream source."""
import difflib
import hashlib
import pathlib
import os
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
SOURCE = pathlib.Path(os.environ.get('W1700K_SOURCE_ROOT', str(ROOT.parent.parent / 'openwrt-source')))
NPU = 'package/luci-app-airoha-npu/htdocs/luci-static/resources/view/airoha_npu/status.js'
FAN_STATUS = 'package/luci-app-w1700k-fancontrol/htdocs/luci-static/resources/view/fan/status.js'
FAN_SETTINGS = 'package/luci-app-w1700k-fancontrol/htdocs/luci-static/resources/view/fan/settings.js'
originals = {name: (SOURCE / name).read_text(encoding='utf-8') for name in [NPU, FAN_STATUS, FAN_SETTINGS]}
modified = dict(originals)

def replace(name, old, new, expected=1):
    count = modified[name].count(old)
    assert count == expected, (name, old, count, expected)
    modified[name] = modified[name].replace(old, new)

# Only display labels are translated. Technical names and machine values stay unchanged.
replace(NPU, "'N/A'", "_('N/A')", 7)
for old in ['Healthy', 'Warning', 'Critical', 'No clients', 'Idle', 'Poor', 'Fair', 'Good']:
    replace(NPU, "text:'" + old + "'", "text: _('" + old + "')")
replace(NPU, "name: 'Band '+band", "name: _('Band %d').format(band)")
replace(NPU, "stats.count + ' sta'", "_('%d clients').format(stats.count)")
replace(NPU, "stats.count+'sta'", "_('%d clients').format(stats.count)")
for label in [
    'devmem not available on this build', 'TX Drop', 'RX Drop', 'HW Offload: ',
    'Drop ', '8x RISC-V via PCIe RAM', 'Manages: ', 'PPE init, WDMA rings, flow stats',
    'PPE Engines', 'Bound ', 'Total ', 'PSE Shared Buffer',
    'Internal Switch (1G LAN3/4)', 'PSE Port Queue Status',
    'Frequencies above 1400 MHz may be unstable. Continue?',
]:
    replace(NPU, "'" + label + "'", "_('" + label + "')")
replace(NPU, "npuActive ? 'ACTIVE' : 'OFF'", "npuActive ? _('ACTIVE') : _('OFF')")
replace(NPU, "(fe.pse_used||0)+' used / '+(fe.pse_free||0)+' free ('+pseP+'%)'", "_('%d used / %d free (%s%%)').format(fe.pse_used||0, fe.pse_free||0, pseP)")
replace(NPU, "pll+' MHz (OC)'", "_('%s MHz (OC)').format(pll)", 2)
replace(NPU, "(st.npu_cores||0)+' cores'", "_('%d cores').format(st.npu_cores||0)")
replace(NPU, "memR.length+' regions)'", "_('%d regions').format(memR.length)+')'")
replace(NPU,
    "\treturn E('select', { 'id':'cpu-governor-select'",
    "\tvar governorLabels = {\n"
    "\t\tperformance: _('Performance'), powersave: _('Powersave'),\n"
    "\t\tondemand: _('Ondemand'), conservative: _('Conservative'),\n"
    "\t\tschedutil: _('Schedutil'), userspace: _('Userspace')\n"
    "\t};\n"
    "\treturn E('select', { 'id':'cpu-governor-select'")
replace(NPU, "'selected':g===active?'':null},g);", "'selected':g===active?'':null},governorLabels[g] || g);")

preset_helper = """function presetLabel(preset) {
	var labels = {
		quiet: _('Quiet'), balanced: _('Balanced'),
		performance: _('Performance'), custom: _('Custom')
	};
	return labels[preset] || preset.charAt(0).toUpperCase() + preset.slice(1);
}

"""
mode_helper = """function fanModeLabel(description) {
	var labels = {
		'Full Speed': _('Full Speed'), 'Manual': _('Manual'),
		'Automatic': _('Automatic'), 'Auto (Closed Loop)': _('Auto (Closed Loop)'),
		'Unknown': _('Unknown')
	};
	return labels[description] || description || _('Unknown');
}

"""
replace(FAN_STATUS, 'function tempColor(temp) {', preset_helper + mode_helper + 'function tempColor(temp) {')
replace(FAN_STATUS, "status.fan_mode_desc || 'Unknown'", 'fanModeLabel(status.fan_mode_desc)', 2)
replace(FAN_STATUS,
    "(status.uci_preset || 'balanced').charAt(0).toUpperCase() +\n\t\t\t\t\t\t\t\t(status.uci_preset || 'balanced').slice(1)",
    "presetLabel(status.uci_preset || 'balanced')")
replace(FAN_STATUS,
    "(status.uci_preset || 'balanced').charAt(0).toUpperCase() +\n\t\t\t\t\t\t(status.uci_preset || 'balanced').slice(1)",
    "presetLabel(status.uci_preset || 'balanced')")
replace(FAN_SETTINGS, 'function drawCurveCanvas(canvasId, curves, activePreset) {', preset_helper + 'function drawCurveCanvas(canvasId, curves, activePreset) {')
replace(FAN_SETTINGS, "ctx.fillText('Temperature (\\u00B0C)',", "ctx.fillText(_('Temperature (\\u00B0C)'),")
replace(FAN_SETTINGS, "ctx.fillText('PWM (0-255)',", "ctx.fillText(_('PWM (0-255)'),")
# Restrict replacement to the graph call, not the helper fallback.
replace(FAN_SETTINGS, "ctx.fillText(preset.charAt(0).toUpperCase() + preset.slice(1),", "ctx.fillText(presetLabel(preset),")

patch = ''.join(''.join(difflib.unified_diff(originals[name].splitlines(keepends=True), modified[name].splitlines(keepends=True), fromfile='a/'+name, tofile='b/'+name)) for name in originals)
(ROOT / 'source-localization.patch').write_text(patch, encoding='utf-8')
commit = subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()
manifest = ['Pinned source assumptions for source-localization.patch', 'Source commit: ' + commit, '']
for name, content in originals.items():
    digest = hashlib.sha256(content.encode('utf-8')).hexdigest()
    manifest.append(digest + '  ' + name)
manifest += ['', 'Apply from the root of the pinned openwrt-source checkout:',
             'git apply --check ../candidate/translations/source-localization.patch',
             'git apply ../candidate/translations/source-localization.patch',
             '', 'Then copy each translations/<app>/zh_Hans directory to package/<app>/po/zh_Hans.',
             'Run Python catalog validation before copying:',
             'python3 ../candidate/translations/build_translations.py',
             '', 'Changes are restricted to JavaScript gettext wrapping and display label mapping.',
             'No RPC declarations, calls, arguments, hardware register access, settings, defaults,',
             'frequency ranges, confirmation thresholds, fan curves, or polling intervals change.',
             'The overclock confirmation still triggers only when frequency exceeds 1400 MHz.',
             'Existing upstream English stability claims are attributed and qualified in Chinese,',
             'without promising a safe frequency. The warning text itself remains semantically intact.',
             'Technical identifiers and unknown machine-provided values remain unchanged.',
             '']
(ROOT / 'source-assumptions.txt').write_text('\n'.join(manifest), encoding='utf-8')

# Validate syntax on temporary copies inside the authorized translations directory only.
with tempfile.TemporaryDirectory(prefix='.validate-', dir=ROOT) as temp:
    for i, (name, content) in enumerate(modified.items()):
        path = pathlib.Path(temp) / f'{i}.js'
        path.write_text(content, encoding='utf-8')
        subprocess.run(['node', '--check', str(path)], check=True)
subprocess.run(['git', '-C', str(SOURCE), 'apply', '--check', str(ROOT / 'source-localization.patch')], check=True)
print('Generated source-localization.patch; all three modified JavaScript files pass node --check; git apply --check passes.')
