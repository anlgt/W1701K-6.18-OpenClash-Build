#!/usr/bin/env python3
"""Build and strictly validate the W1700K Simplified Chinese catalogs, offline."""
import ast
import collections
import json
import pathlib
import os
import re

ROOT = pathlib.Path(__file__).resolve().parent
SOURCE = pathlib.Path(os.environ.get('W1700K_SOURCE_ROOT', str(ROOT.parent.parent / 'openwrt-source'))) / 'package'
NPU = {
'Active': '已启用',
'Airoha SoC Status': 'Airoha SoC 状态',
'Apply': '应用',
'Applying...': '正在应用…',
'Bound:': '已绑定：',
'Bytes': '字节数',
'CPU Cores': 'CPU 核心数',
'CPU Frequency': 'CPU 频率',
'CPU set to': 'CPU 频率已设为',
'Current Frequency': '当前频率',
'Direct PLL programming. Governor locked to performance. Stock max: 1200 MHz. Tested stable up to 1500 MHz.': '直接设置 PLL，调频策略锁定为 performance（性能模式）。原厂最高频率为 1200 MHz。上游报告测试中最高可稳定运行至 1500 MHz，但这不保证本机安全或稳定；超频可能导致过热或运行不稳定。',
'Ethernet': '以太网',
'Failed to set governor:': '设置调频策略失败：',
'Failed to set max frequency:': '设置最高频率失败：',
'Frequency must be 500-1600 MHz': '频率必须在 500–1600 MHz 范围内',
'Governor': '调频策略',
'Grant access to Airoha SoC status (NPU + CPU + Overclock)': '允许访问 Airoha SoC 状态（NPU、CPU 及超频设置）',
'Index': '索引',
'Max Frequency': '最高频率',
'NPU Clock / Cores': 'NPU 时钟频率 / 核心数',
'NPU Firmware Version': 'NPU 固件版本',
'NPU Information': 'NPU 信息',
'NPU Status': 'NPU 状态',
'New Flow': '转换后的流',
'Not Active': '未启用',
'Not available': '不可用',
'Offload Statistics': '硬件加速统计',
'Original Flow': '原始流',
'Overclock': '超频',
'Overclock failed:': '超频失败：',
'PPE Flow Offload Entries': 'PPE 流量硬件加速条目',
'Packets': '数据包数',
'Reserved Memory': '预留内存',
'SoC Status': 'SoC 状态',
'State': '状态',
'Total:': '总计：',
'Type': '类型',
'Unbound:': '未绑定：',
# Current source strings that are missing from the upstream template.
'Error: ': '错误：',
'Must be 500-1600 MHz': '频率必须在 500–1600 MHz 范围内',
'Failed: ': '操作失败：',
'CPU set to ': 'CPU 频率已设为 ',
'Direct PLL. Stock max 1200 MHz. Stable up to 1500 MHz.': '直接设置 PLL。原厂最高频率为 1200 MHz。上游声称最高可稳定运行至 1500 MHz，但这不保证本机安全或稳定；超频可能导致过热或运行不稳定。',
'NPU & Offload Engine': 'NPU 与硬件加速引擎',
'Firmware / Clock / Cores': '固件 / 时钟频率 / 核心数',
'Frame Engine': '帧处理引擎',
# Keys for source-localization wrapping; technical identifiers stay intact.
'N/A': '不可用',
'Healthy': '正常',
'Warning': '警告',
'Critical': '严重',
'No clients': '无客户端',
'Idle': '空闲',
'Poor': '较差',
'Fair': '一般',
'Good': '良好',
'Band %d': '频段 %d',
'%d clients': '%d 个客户端',
'devmem not available on this build': '此固件未提供 devmem',
'TX Drop': '发送丢包',
'RX Drop': '接收丢包',
'HW Offload: ': '硬件加速：',
'Drop ': '丢包 ',
'ACTIVE': '已启用',
'OFF': '已关闭',
'8x RISC-V via PCIe RAM': '8 个 RISC-V 核心，通过 PCIe RAM 通信',
'Manages: ': '负责：',
'PPE init, WDMA rings, flow stats': 'PPE 初始化、WDMA 环形队列及流量统计',
'PPE Engines': 'PPE 引擎',
'Bound ': '已绑定 ',
'Total ': '总计 ',
'PSE Shared Buffer': 'PSE 共享缓冲区',
'%d used / %d free (%s%%)': '已用 %d / 空闲 %d（%s%%）',
'Internal Switch (1G LAN3/4)': '内置交换机（1G LAN3/4）',
'PSE Port Queue Status': 'PSE 端口队列状态',
'%s MHz (OC)': '%s MHz（超频）',
'Frequencies above 1400 MHz may be unstable. Continue?': '高于 1400 MHz 的频率可能导致运行不稳定。是否继续？',
'Direct PLL programming. Stock max: 1200 MHz. Overclocking may cause instability, overheating, or data loss; no overclock frequency is guaranteed safe.': '直接设置 PLL。原厂最高频率为 1200 MHz。超频可能导致运行不稳定、过热或数据丢失；任何超频频率均不保证安全。',
'%d cores': '%d 个核心',
'%d regions': '%d 个内存区域',
'Performance': '性能',
'Powersave': '省电',
'Ondemand': '按需调频',
'Conservative': '保守调频',
'Schedutil': '调度器调频',
'Userspace': '用户空间',
}
FAN = {
'10G PHY': '10G PHY',
'2.4 GHz Radio': '2.4 GHz 无线模块',
'5 GHz Radio': '5 GHz 无线模块',
'6 GHz Radio': '6 GHz 无线模块',
'Active Preset': '当前预设',
'Automatic (Follow Curve)': '自动（按曲线调速）',
'Balanced - Good mix of noise and cooling': '均衡：兼顾噪声与散热',
'Board (Fan Curve)': '主板（风扇曲线依据）',
'CPU': 'CPU',
'Configure fan control mode and speed curves.': '设置风扇控制模式与转速曲线。',
'Control Mode': '控制模式',
'Curve Points': '曲线控制点',
'Curve Preview': '曲线预览',
'Custom - Define your own curve': '自定义：设置自己的调速曲线',
'Custom Curve Editor': '自定义曲线编辑器',
'Define temperature thresholds and corresponding fan speeds.': '设置各温度阈值及其对应的风扇转速。',
'Fan Control': '风扇控制',
'Fan Control - Settings': '风扇控制 - 设置',
'Fan Control - Status': '风扇控制 - 状态',
'Fan Curve Preset': '风扇曲线预设',
'Fan Speed': '风扇转速',
'Fan Status': '风扇状态',
'Grant access to W1700K fan control': '允许访问 W1700K 风扇控制',
'Manual (Fixed Speed)': '手动（固定转速）',
'Manual Fan Speed (PWM)': '手动风扇调速（PWM）',
'Manual Override': '手动控制',
'Mode': '模式',
'Performance - Higher speeds, lower temps': '性能：提高转速，降低温度',
'Point %d PWM (0-255)': '控制点 %d 的 PWM 值（0–255）',
'Point %d Temperature (°C)': '控制点 %d 的温度（°C）',
'Quiet - Lower speeds, higher temps': '静音：降低转速，温度较高',
'Set a fixed PWM value (0-255). 0 = Off, 255 = Full Speed': '设置固定的 PWM 值（0–255）。0 表示停转，255 表示全速。',
'Settings': '设置',
'Status': '状态',
'Switch PHY': '交换机 PHY',
'System': '系统',
'Temperatures': '温度',
'WiFi': '无线网络',
# Current source strings missing from the upstream template.
'LAN2 10G PHY': 'LAN2 10G PHY',
'WAN 10G PHY': 'WAN 10G PHY',
# Keys for source-localization wrapping of status and graph strings.
'Unknown': '未知',
'Quiet': '静音',
'Balanced': '均衡',
'Performance': '性能',
'Custom': '自定义',
'Full Speed': '全速',
'Manual': '手动',
'Automatic': '自动',
'Auto (Closed Loop)': '自动（闭环控制）',
'Temperature (°C)': '温度（°C）',
'PWM (0-255)': 'PWM（0–255）',
}

def parse_po(path):
    entries = []
    fields = {}
    active = None
    comments = []
    def finish():
        nonlocal fields, active, comments
        if fields:
            assert set(fields) == {'msgid', 'msgstr'}, (path, fields)
            entries.append((fields['msgid'], fields['msgstr'], comments))
        fields, active, comments = {}, None, []
    for no, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        line = line.strip()
        if not line:
            finish()
        elif line.startswith('#'):
            comments.append(line)
        elif line.startswith(('msgid ', 'msgstr ')):
            field, value = line.split(' ', 1)
            assert field not in fields, (path, no, 'duplicate field')
            parsed = ast.literal_eval(value)
            assert isinstance(parsed, str), (path, no, 'not string')
            fields[field] = parsed
            active = field
        elif line.startswith('"'):
            assert active, (path, no, 'unexpected continuation')
            fields[active] += ast.literal_eval(line)
        else:
            raise AssertionError((path, no, 'unsupported/invalid syntax', line))
    finish()
    ids = [key for key, _, _ in entries]
    assert len(ids) == len(set(ids)), (path, 'duplicate msgid')
    return entries

def js_keys(app):
    keys = set()
    for path in (SOURCE / app / 'htdocs').rglob('*.js'):
        content = path.read_text(encoding='utf-8')
        # Source uses simple single/double quoted gettext string arguments.
        for match in re.finditer(r'''\b_\(\s*((?:'(?:\\.|[^'\\])*')|(?:"(?:\\.|[^"\\])*"))\s*\)''', content):
            keys.add(ast.literal_eval(match.group(1)))
    return keys

def placeholders(value):
    return collections.Counter(re.findall(r'%(?:\d+\$)?[-+# 0]*(?:\d+|\*)?(?:\.(?:\d+|\*))?[hlLzjt]*[diuoxXfFeEgGaAcsp%]', value))

def make(app, translations):
    template = SOURCE / app / 'po' / 'templates' / (app + '.pot')
    entries = parse_po(template)
    template_keys = {key for key, _, _ in entries if key}
    current_keys = js_keys(app)
    assert not template_keys - translations.keys(), ('untranslated template', template_keys - translations.keys())
    assert not current_keys - translations.keys(), ('untranslated current source', current_keys - translations.keys())
    output = ROOT / app / 'zh_Hans' / (app + '.po')
    output.parent.mkdir(parents=True, exist_ok=True)
    quote = lambda x: json.dumps(x, ensure_ascii=False)
    header = ('Project-Id-Version: ' + app + '\n'
              'PO-Revision-Date: 2026-10-05 00:00+0000\n'
              'Language: zh_Hans\n'
              'MIME-Version: 1.0\n'
              'Content-Type: text/plain; charset=UTF-8\n'
              'Content-Transfer-Encoding: 8bit\n'
              'Plural-Forms: nplurals=1; plural=0;\n')
    lines = ['# Simplified Chinese translations for ' + app + '.', 'msgid ""', 'msgstr ""']
    lines.extend(quote(line + '\n') for line in header.splitlines())
    lines.append('')
    for key, _, comments in entries:
        if not key:
            continue
        lines.extend(comments)
        if placeholders(key):
            lines.append('#, c-format')
        lines.extend(['msgid ' + quote(key), 'msgstr ' + quote(translations[key]), ''])
    extra = sorted(translations.keys() - template_keys)
    for key in extra:
        lines.append('#. Current source or supplemental source-localization key.')
        if placeholders(key):
            lines.append('#, c-format')
        lines.extend(['msgid ' + quote(key), 'msgstr ' + quote(translations[key]), ''])
    output.write_text('\n'.join(lines), encoding='utf-8')
    parsed = parse_po(output)
    for key, value, _ in parsed:
        assert value, (output, 'empty translation', key)
        assert not key or placeholders(key) == placeholders(value), (output, 'placeholder mismatch', key, value)
    assert {key for key, _, _ in parsed if key} == translations.keys()
    print(f'{output.relative_to(ROOT)}: {len(parsed)-1} translated entries; {len(template_keys)} template keys and {len(current_keys)} current JS gettext keys covered; placeholders match; UTF-8 and strict PO syntax OK')
    return (app, len(parsed)-1, len(template_keys), len(current_keys), len(current_keys - template_keys))

if __name__ == '__main__':
    results = [make('luci-app-airoha-npu', NPU), make('luci-app-w1700k-fancontrol', FAN)]
    report = ['W1700K Simplified Chinese localization validation',
              'Date: 2026-10-05',
              '',
              'Validation uses the standalone Python parser in build_translations.py; no dependencies installed.',
              'No msgfmt, polib, or Babel parser was installed in this environment.',
              'Checked strict PO syntax, valid UTF-8, no duplicate msgids, no empty translations,',
              'all upstream template keys, all current JavaScript gettext keys, and matching printf placeholders.',
              'Supplemental entries are included for hard-coded source labels that require gettext wrapping.',
              'The overclock disclaimer attributes the upstream stability claim and explicitly disclaims',
              'safety/stability guarantees. The >1400 MHz confirmation warning is translated unchanged in meaning.',
              'No hardware settings, defaults, source files, or remote state have been changed.',
              '']
    for app, count, templates, current, missing in results:
        report.append(f'{app}: {count} entries; {templates}/{templates} template keys, {current}/{current} current JS gettext keys; {missing} current keys absent from upstream template.')
    report += ['', 'Known source-localization gaps (PO files alone cannot translate these):',
               '- NPU: health labels, device/client counts, frame-engine diagram labels, PSE buffer usage,',
               '  overclock confirmation, CPU governor display names, core/region counts, N/A fallbacks.',
               '- Fan: backend mode descriptions, generated preset names in status/poll and graph legend,',
               '  graph temperature axis label.',
               '- Diagnostic identifiers and units (CPU, NPU, VLAN, PPPoE, PPE, DMA, PHY, TX/RX, MHz, RPM)',
               '  should remain unchanged where they identify hardware/protocols.',
               '']
    (ROOT / 'validation-report.txt').write_text('\n'.join(report), encoding='utf-8')
