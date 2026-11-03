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

# Direct PLL writes bypass CPUFreq/PM-domain serialization. Test the actual
# dispatcher and ACL so cached clients cannot call the removed method.
import json
npu_path=root/'package/luci-app-airoha-npu/root/usr/libexec/rpcd/luci.airoha_npu'
npu=npu_path.read_text().replace('. /lib/functions.sh', ':')
assert 'set_overclock()' not in npu
assert not re.search(r'^\s*devmem\s+\S+\s+32\s+', npu, re.M)
methods=json.loads(subprocess.check_output(['sh','-c',npu,'rpc','list'],text=True))
assert 'setGovernor' in methods and 'setMaxFreq' in methods
assert 'setOverclock' not in methods
reply=subprocess.check_output(['sh','-c',npu,'rpc','call','setOverclock'],input='{"freq_mhz":1400}\n',text=True)
assert json.loads(reply)=={'error':'Invalid method'}
acl=json.loads((root/'package/luci-app-airoha-npu/root/usr/share/rpcd/acl.d/luci-app-airoha-npu.json').read_text())
write=acl['luci-app-airoha-npu']['write']
assert 'setOverclock' not in write['ubus']['luci.airoha_npu']
assert '/dev/mem' not in write['file']
print('PASS: direct PLL controls, RPC and /dev/mem ACL removed; stock CPUFreq methods retained')

with tempfile.TemporaryDirectory() as directory:
    fixture=Path(directory)/'ppe-entries'
    fixture.write_text('00001 UNB IPv4 NAPT orig=192.0.2.2:1234->198.51.100.1:443 new=203.0.113.9:49152->198.51.100.1:443 eth=aa:bb:cc:dd:ee:ff->11:22:33:44:55:66\n00002 BND IPv4 NAPT orig=192.0.2.2:1234->198.51.100.1:443 new=203.0.113.9:49152->198.51.100.1:443 eth=aa:bb:cc:dd:ee:ff->11:22:33:44:55:66\n')
    script=npu.replace('/sys/kernel/debug/ppe/entries',str(fixture))
    entries=json.loads(subprocess.check_output(['sh','-c',script,'rpc','call','getPpeEntries'],text=True))['entries']
    assert len(entries)==2 and entries[0]['state']=='UNB' and entries[1]['state']=='BND'
    assert entries[0]['orig']=='192.0.2.2:1234->198.51.100.1:443'
    assert entries[0]['new_flow']=='' and entries[0]['eth']==''
    assert entries[1]['new_flow']=='203.0.113.9:49152->198.51.100.1:443'
    assert entries[1]['eth']=='aa:bb:cc:dd:ee:ff->11:22:33:44:55:66'
print('PASS: unbound PPE fields stay empty while bound translations/MACs survive')
