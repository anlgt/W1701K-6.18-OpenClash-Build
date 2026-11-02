#!/usr/bin/env python3
"""Exercise first-boot UCI writes on the Linux Actions runner without hardware."""
import json
import os
import subprocess
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = (root / 'w1701k-refresh-files/usr/libexec/w1701k-network-defaults').read_text()
with tempfile.TemporaryDirectory() as directory:
    tmp = Path(directory)
    state_file = tmp / 'state.json'
    (tmp / 'key').write_text('test-key-123##\n')
    uci = tmp / 'uci'
    uci.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
p = Path(os.environ['UCI_TEST_STATE'])
state = json.loads(p.read_text())
args = [a for a in sys.argv[1:] if a != '-q']
if args[0] == 'set':
    key, value = args[1].split('=', 1)
    if key == os.environ.get('UCI_TEST_FAIL_KEY'):
        sys.exit(37)
    state[key] = value
elif args[0] == 'get':
    if args[1] not in state: sys.exit(1)
    print(state[args[1]])
elif args[0] == 'commit':
    state.setdefault('_commits', []).append(args[1])
else:
    sys.exit(2)
p.write_text(json.dumps(state))
''')
    uci.chmod(0o755)
    functions = '''
board_name() { echo "${TEST_BOARD:-gemtek,w1701k}"; }
config_load() { :; }
config_get() {
    local output="$1" section="$2" option="$3" value
    value=$(uci -q get "wireless.$section.$option")
    eval "$output=\\\"\\$value\\\""
}
config_foreach() {
    [ "${TEST_NO_RADIOS:-0}" = 0 ] || return 0
    case "$2" in
        wifi-device) for section in radio0 radio1 radio2; do "$1" "$section"; done ;;
        wifi-iface) for section in default_radio0 default_radio1 default_radio2; do "$1" "$section"; done ;;
    esac
}
'''
    script = source.replace('. /lib/functions.sh', functions).replace('. /lib/functions/system.sh', ':')
    script = script.replace('key_file=/etc/w1701k-wifi-key', f'key_file={tmp / "key"}')
    script = script.replace('/sbin/wifi config', 'true')
    shell = tmp / 'defaults.sh'
    shell.write_text(script)
    env = {**os.environ, 'PATH': str(tmp) + os.pathsep + os.environ['PATH'], 'UCI_TEST_STATE': str(state_file)}
    initial = {}
    for i, band in enumerate(('2g', '5g', '6g')):
        initial.update({f'wireless.radio{i}.band': band,
                        f'wireless.radio{i}.disabled': '1',
                        f'wireless.default_radio{i}.mode': 'ap',
                        f'wireless.default_radio{i}.device': f'radio{i}'})
    state_file.write_text(json.dumps(initial))
    subprocess.run(['sh', '-n', str(shell)], check=True)
    subprocess.run(['sh', str(shell)], env=env, check=True)
    state = json.loads(state_file.read_text())
    assert state['network.lan.ipaddr'] == '10.98.0.1'
    assert state['network.lan.netmask'] == '255.255.255.0'
    for i in (0, 1):
        assert state[f'wireless.radio{i}.disabled'] == '0'
        assert state[f'wireless.radio{i}.country'] == 'CN'
        assert state[f'wireless.default_radio{i}.ssid'] == 'GT'
        assert state[f'wireless.default_radio{i}.key'] == 'test-key-123##'
        assert state[f'wireless.default_radio{i}.encryption'] == 'sae-mixed'
        assert state[f'wireless.default_radio{i}.disabled'] == '0'
    assert state['wireless.radio2.disabled'] == '1'
    assert state['wireless.default_radio2.disabled'] == '1'
    assert state['_commits'] == ['network', 'wireless']
    state_file.write_text(json.dumps(initial))
    subprocess.run(['sh', str(shell)], env={**env, 'TEST_BOARD': 'gemtek,w1700k-ubi'}, check=True)
    assert json.loads(state_file.read_text()) == initial
    result = subprocess.run(['sh', str(shell)], env={**env, 'TEST_NO_RADIOS': '1'})
    assert result.returncode == 1
    assert 'wireless' not in json.loads(state_file.read_text()).get('_commits', [])
    state_file.write_text(json.dumps(initial))
    result = subprocess.run(['sh', str(shell)], env={**env, 'UCI_TEST_FAIL_KEY': 'wireless.radio2.country'})
    assert result.returncode == 1
    assert 'wireless' not in json.loads(state_file.read_text()).get('_commits', [])
print('PASS: GT/CN/LAN defaults, literal hash characters, 6 GHz disabled, board guard, late PHY retry')
