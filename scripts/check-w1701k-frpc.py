#!/usr/bin/env python3
"""Exercise the packaged frpc UCI generator; optionally verify the ARM64 binary."""
import argparse
import shlex
import subprocess
import tempfile
import tomllib
from pathlib import Path


def require(value, message):
    if not value:
        raise SystemExit('frpc check failed: ' + message)


def generate(init, directory, configured):
    common = {'server_addr': '127.0.0.1', 'server_port': '7000',
              'authentication_method': 'token', 'login_fail_exit': 'true',
              'protocol': 'tcp', 'wire_protocol': 'v1', 'tls_enable': 'true',
              'tcp_mux': 'true', 'disable_custom_tls_first_byte': 'true',
              'log_file': 'console', 'log_level': 'info', 'log_max_days': '3'}
    data = {'common': common, 'init0': {'stdout': '1', 'stderr': '1', 'respawn': '1'}}
    if configured:
        common.update(token_source_type='file', token_source_file_path='/etc/frp/client_token')
        data['ssh'] = {'name': 'ssh', 'type': 'tcp', 'local_ip': '127.0.0.1',
                       'local_port': '2020', 'remote_port': '6000', 'enabled': 'true'}
        data['web'] = {'name': 'web', 'type': 'https', 'custom_domains': 'router.example.invalid',
                       'plugin': 'https2http', 'plugin_local_addr': '127.0.0.1:8445',
                       'plugin_crt_path': '/etc/frp/tls/client.crt',
                       'plugin_key_path': '/etc/frp/tls/client.key', 'enabled': 'true'}
    cases = '\n'.join(f'{shlex.quote(section + ":" + key)}) __value={shlex.quote(value)} ;;'
                      for section, values in data.items() for key, value in values.items())
    output = directory / ('configured.toml' if configured else 'default.toml')
    procd = directory / 'procd.txt'
    script = f'''. {shlex.quote(str(init.resolve()))}
CONF_FILE={shlex.quote(str(output))}
config_load() {{ return 0; }}
config_get() {{
 local __value
 __value="$4"
 case "$2:$3" in
 {cases}
 esac
 eval "$1=\\$__value"
}}
config_get_bool() {{ config_get "$@"; }}
config_list_foreach() {{ return 0; }}
config_foreach() {{
 case "$2" in
 init) "$1" init0 ;;
 conf) {'; '.join('"$1" ' + s for s in data if s != 'init0')} ;;
 esac
}}
mkdir() {{ [ "$2" = /var/etc ] || command mkdir "$@"; }}
logger() {{ return 0; }}
procd_open_instance() {{ return 0; }}
procd_close_instance() {{ return 0; }}
procd_set_param() {{ printf '%s\\n' "$*" >> {shlex.quote(str(procd))}; }}
procd_append_param() {{ return 0; }}
start_service
'''
    result = subprocess.run(['sh'], input=script, text=True, capture_output=True, timeout=30)
    require(result.returncode == 0, 'packaged init generator failed: ' + result.stderr[-1000:])
    require(output.stat().st_mode & 0o077 == 0, 'generated TOML is not private')
    parsed = tomllib.loads(output.read_text())
    require(parsed['transport']['tls']['enable'] is True, 'TLS not retained')
    require('command /usr/bin/frpc -c ' + str(output) in procd.read_text(), 'procd command differs')
    if configured:
        require(parsed['auth']['tokenSource'] == {'type': 'file', 'file': {'path': '/etc/frp/client_token'}},
                'file token source changed')
        require(parsed['proxies'][0]['localPort'] == 2020, 'custom SSH port lost')
        plugin = parsed['proxies'][1]['plugin']
        require(plugin == {'type': 'https2http', 'localAddr': '127.0.0.1:8445',
                           'crtPath': '/etc/frp/tls/client.crt', 'keyPath': '/etc/frp/tls/client.key'},
                'TLS bridge plugin settings changed')
    else:
        require('proxies' not in parsed and 'visitors' not in parsed, 'factory default exposes a proxy')
        require('token' not in parsed['auth'], 'factory default contains a token')
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--init', type=Path, required=True)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--program', type=Path, help='native frpc for local checks; firmware uses --root')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        default = generate(args.init, directory, False)
        generate(args.init, directory, True)
        if args.root or args.program:
            command = (['qemu-aarch64', '-L', str(args.root), str(args.root / 'usr/bin/frpc')]
                       if args.root else [str(args.program)])
            version = subprocess.check_output(command + ['-v'], text=True, timeout=30).strip()
            require(version == '0.71.0', 'unexpected binary version: ' + version)
            verify = subprocess.run(command + ['verify', '-c', str(default)], text=True, capture_output=True, timeout=30)
            require(verify.returncode == 0, 'binary rejected generated default TOML: ' + verify.stderr[-1000:])
            invalid = directory / 'invalid.toml'
            invalid.write_text('serverPort = "not-a-port"\n')
            reject = subprocess.run(command + ['verify', '-c', str(invalid)], text=True, capture_output=True, timeout=30)
            require(reject.returncode != 0, 'binary accepted invalid TOML')
    print('PASS: frpc init generation, private TOML, file-token and TLS bridge compatibility' +
          ('; actual 0.71.0 version/verify/invalid-config checks' if args.root or args.program else ''))


if __name__ == '__main__':
    main()
