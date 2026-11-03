#!/usr/bin/env python3
"""Test actual shell temperature parser/discovery with missing and valid sensor fixtures."""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

root=Path(sys.argv[1])
source=(root/'package/luci-app-w1700k-fancontrol/root/usr/libexec/rpcd/luci.fan').read_text()
def function(name):
    return re.search(re.escape(name)+r'\(\) \{.*?\n\}',source,re.S).group()
with tempfile.TemporaryDirectory() as directory:
    fixture=Path(directory)
    def call(script):
        return subprocess.check_output(['sh','-c',script],text=True).strip()
    parser=function('read_temp')
    sensor=fixture/'temp1_input'
    assert call(parser+'\nread_temp '+str(sensor))=='null'
    for raw,expected in [('0','0'),('-5000','-5'),('47000','47'),('','null'),('broken','null')]:
        sensor.write_text(raw+'\n')
        assert call(parser+'\nread_temp '+str(sensor))==expected
    hwmon=fixture/'hwmon';hwmon.mkdir()
    phy=fixture/'mt7530-0:0e';phy.mkdir()
    node=hwmon/'hwmon4';node.mkdir();(node/'name').write_text('en8811h\n');(node/'device').symlink_to(phy)
    discovery=function('find_phy_hwmon').replace('/sys/class/hwmon',str(hwmon))
    assert call(discovery+'\nfind_phy_hwmon :0e')==str(node)
    assert call(discovery+'\nfind_phy_hwmon :0f')==''
    (node/'name').write_text('legacy:0f\n')
    assert call(discovery+'\nfind_phy_hwmon :0f')==str(node)
print('PASS: RPC reads PHY parent identity; missing/invalid stay null and real zero/negative temperatures survive')
