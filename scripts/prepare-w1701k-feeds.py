#!/usr/bin/env python3
"""Exclude two unselected optional feed menus with recursive Kconfig dependencies."""
from pathlib import Path

# These unrelated applications are absent from both firmware configurations.
# Their optional menus currently produce Kconfig self-dependencies even when
# unselected. Remove only their installed feed links, never hardware sources.
excluded = ('applications/luci-app-fwknopd', 'sound/squeezelite')
for group in Path('package/feeds').iterdir():
    if not group.is_dir():
        continue
    for entry in group.iterdir():
        if entry.is_symlink() and any(entry.resolve().as_posix().endswith('/' + p) for p in excluded):
            print('Excluding unused optional feed menu:', entry)
            entry.unlink()

# Use the pinned official frpc init/UCI migration and LuCI interface unchanged.
# Its upstream sample enables an SSH proxy; ship an unconfigured, disabled
# client instead. This changes the package's factory defaults, never the live
# router's configuration or a configuration restored by sysupgrade.
frp = Path('feeds/packages/net/frp')
if 'PKG_VERSION:=0.71.0' not in (frp / 'Makefile').read_text():
    raise SystemExit('Unexpected frp package version; review UCI/init compatibility')
(frp / 'files/frpc.config').write_text('''config init
\toption stdout '1'
\toption stderr '1'
\toption respawn '1'
\toption w1701k_unconfigured '1'

config conf 'common'
\toption server_addr '127.0.0.1'
\toption server_port '7000'
\toption authentication_method 'token'
\toption login_fail_exit 'true'
\toption protocol 'tcp'
\toption wire_protocol 'v1'
\toption tcp_mux 'true'
\toption tls_enable 'true'
\toption disable_custom_tls_first_byte 'true'
\toption log_file 'console'
\toption log_level 'info'
\toption log_max_days '3'
''')
