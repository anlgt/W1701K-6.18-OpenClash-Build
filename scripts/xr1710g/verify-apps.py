#!/usr/bin/env python3
"""Check the actual requested apps and exercise FRP's unconfigured start path."""
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

def read_uci(path):
    sections, current = {}, None
    for line in path.read_text().splitlines():
        words = shlex.split(line, comments=True)
        if not words:
            continue
        if words[0] == 'config':
            name = words[2] if len(words) == 3 else words[1]
            assert name not in sections
            current = sections[name] = {'type': words[1]}
        else:
            assert current is not None and words[0] == 'option' and len(words) == 3
            assert words[1] not in current
            current[words[1]] = words[2]
    return sections

def verify_frpc(config, init, defaults):
    sections = read_uci(config)
    assert set(sections) == {'init', 'common'}, 'Unexpected FRP proxy/visitor section'
    common = sections['common']
    assert not common.get('server_addr') and not common.get('server_port')
    assert common['tls_enable'] == 'true'
    assert common['pprof_enable'] == 'false'
    assert not any(k.startswith(('token', 'admin_', 'dashboard_', 'oidc_')) and value
                   for k, value in common.items() if k != 'admin_tls_enable')
    assert set(sections['init']) == {'type', 'stdout', 'stderr', 'respawn'}
    assert not any(k in common for k in ('includes', '_', 'store_path'))
    text = defaults.read_text()
    assert 'server_addr 127.0.0.1' not in text and 'server_port 7000' not in text
    # Source the real shipped init script, but replace every external side effect.
    # Empty config must return before even mkdir/TOML generation; a configured
    # address must reach mkdir. Neither test can spawn a client or token command.
    harness = r'''
. "$1"
config_load() { :; }
config_get() {
    [ "$2:$3" = common:server_addr ] || exit 91
    eval "$1=\$FRPC_TEST_ADDRESS"
}
logger() { :; }
mkdir() { exit 97; }
procd_open_instance() { exit 98; }
_emit_common() { exit 99; }
start_service
'''
    for address, expected in [('', 0), ('unit-test.invalid', 97)]:
        env = dict(os.environ, FRPC_TEST_ADDRESS=address)
        r = subprocess.run(['sh', '-c', harness, 'frpc-test', str(init.resolve())],
                           env=env, capture_output=True, text=True)
        assert r.returncode == expected, (address, r.returncode, r.stderr)

def verify(root, source=False):
    root = Path(root)
    if source:
        frp = root/'feeds/packages/net/frp/files'
        verify_frpc(frp/'frpc.config', frp/'frpc.init', frp/'frpc.uci-defaults')
    else:
        verify_frpc(root/'etc/config/frpc', root/'etc/init.d/frpc', root/'etc/uci-defaults/frpc')
        assert os.access(root/'usr/bin/frpc', os.X_OK)
        assert not list((root/'etc/rc.d').glob('S*frpc')), 'FRP client unexpectedly enabled at boot'
        assert not (root/'usr/bin/frps').exists()
        expected = [
            'www/luci-static/resources/view/frpc.js',
            'www/luci-static/resources/view/system/filemanager.js',
            'www/luci-static/resources/view/system/filemanager/HexEditor.js',
            'www/luci-static/resources/view/system/filemanager/md.js',
            'www/luci-static/resources/view/system/filemanager/md_help.js',
            'usr/lib/lua/luci/i18n/frpc.zh-cn.lmo',
            'usr/lib/lua/luci/i18n/filemanager.zh-cn.lmo',
        ]
        for path in expected:
            assert (root/path).is_file(), path
        menu = json.loads((root/'usr/share/luci/menu.d/luci-app-filemanager.json').read_text())
        item = menu['admin/system/filemanager']
        assert item['action'] == {'type': 'view', 'path': 'system/filemanager'}
        assert item['depends']['acl'] == ['luci-app-filemanager']
        for app in ('frpc', 'filemanager'):
            acl = json.loads((root/f'usr/share/rpcd/acl.d/luci-app-{app}.json').read_text())
            assert f'luci-app-{app}' in acl
        assert '/etc/init.d/frpc disable' in (root/'etc/uci-defaults/99-xr1710g-custom-defaults').read_text()
    print('Requested FRP/File Manager app checks and fail-closed FRP startup test passed')

if __name__ == '__main__':
    verify(sys.argv[1], '--source' in sys.argv)
