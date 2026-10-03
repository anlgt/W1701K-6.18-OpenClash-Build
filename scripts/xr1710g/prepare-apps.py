#!/usr/bin/env python3
"""Harden only the requested FRP client defaults in the pinned package feed."""
import hashlib
import sys
from pathlib import Path

EXPECTED = {
    'frpc.config': '61c6b82f30561b9f2e82018fda9e8855d699764a58a20ad355b749245c4c1b7c',
    'frpc.init': 'dc7e295980e096ad1bf36f5c5c889f19071f7cb4e04f6e44f82e4c9a610b5ca2',
    'frpc.uci-defaults': '787898df6874c8188b95da0e005f4f5109b7f3832762bda33e6cc176148fda48',
}

def prepare(root):
    folder = Path(root) / 'feeds/packages/net/frp/files'
    for name, digest in EXPECTED.items():
        assert hashlib.sha256((folder/name).read_bytes()).hexdigest() == digest, name
    makefile = folder.parent/'Makefile'
    assert hashlib.sha256(makefile.read_bytes()).hexdigest() == 'be90eea02b82875b06d26139117cbc5ac3a07e16002f510ff507cc82ca700bda'
    text = makefile.read_text()
    marker = 'define Build/Compile\n\t( '
    assert text.count(marker) == 1
    makefile.write_text(text.replace(marker, 'define Build/Compile\n\t(set -e; '))
    # No sample SSH proxy, server, token, external include or admin listener.
    (folder/'frpc.config').write_text("""config init
	option stdout '1'
	option stderr '1'
	option respawn '1'

config conf 'common'
	option server_addr ''
	option server_port ''
	option authentication_method 'token'
	option login_fail_exit 'true'
	option protocol 'tcp'
	option wire_protocol 'v1'
	option tcp_mux 'true'
	option tls_enable 'true'
	option disable_custom_tls_first_byte 'true'
	option admin_tls_enable 'false'
	option pprof_enable 'false'
	option log_file 'console'
	option log_level 'info'
	option log_max_days '3'
""")
    p = folder/'frpc.uci-defaults'
    text = p.read_text()
    for line in ('\tset_if_empty "$section" server_addr 127.0.0.1\n',
                 '\tset_if_empty "$section" server_port 7000\n'):
        assert text.count(line) == 1
        text = text.replace(line, '')
    p.write_text(text)
    p = folder/'frpc.init'
    text = p.read_text()
    old = '\tmkdir -p /var/etc\n\t_TOML_ERR=0\n\t_ALLOW_UNSAFE_TOKEN_SOURCE_EXEC=0\n\n\tconfig_load "$NAME"\n'
    new = '''\t# Fail closed before TOML generation, token-source handling or procd.
\t# A LuCI install must not create a connection or an enabled sample tunnel.
\tlocal server_addr
\tconfig_load "$NAME"
\tconfig_get server_addr common server_addr
\t[ -n "$server_addr" ] || {
\t\t_err "FRP client is unconfigured; no server connection started"
\t\treturn 0
\t}
\tmkdir -p /var/etc
\t_TOML_ERR=0
\t_ALLOW_UNSAFE_TOKEN_SOURCE_EXEC=0
'''
    assert text.count(old) == 1
    p.write_text(text.replace(old, new))
    print('FRP client defaults hardened: no server, sample tunnel or automatic connection')

if __name__ == '__main__':
    prepare(sys.argv[1])
