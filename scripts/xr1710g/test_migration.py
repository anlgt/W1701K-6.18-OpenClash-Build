#!/usr/bin/env python3
"""Execute the real POSIX/ash-compatible proposal against a strict host UCI mock."""
import os,pathlib,shlex,subprocess,tempfile,unittest,json
HERE=pathlib.Path(__file__).resolve().parent
SCRIPT=pathlib.Path(os.environ.get('XR_TEST_MIGRATION_SCRIPT',str(HERE.parent.parent/'xr1710g-files/etc/uci-defaults/22_airoha-network-migrate-v4')))
EXTERNAL_UCI=os.environ.get('XR_TEST_UCI_WRAPPER')
OLD="""# byte preservation on skips includes this comment
config globals 'globals'
 option ula_prefix 'fd12:3456::/48'
config device
 option name 'br-lan'
 option type 'bridge'
 list ports 'eth2'
 list ports 'lan2'
 list ports 'lan3'
 option macaddr '02:11:22:33:44:55'
 option vlan_filtering '1'
config interface 'lan'
 option device 'br-lan'
 option proto 'static'
 list ipaddr '192.168.8.1/24'
 option ip6assign '60'
config interface 'wan'
 option device 'eth1'
 option proto 'dhcp'
 option sendclientid 'none'
 option mtu '1492'
config interface 'wan6'
 option device '@wan'
 option proto 'dhcpv6'
config interface 'alias'
 option device 'wlan0'
 option proto 'none'
"""
def parse(text):
 lex=shlex.shlex(text,posix=True,punctuation_chars='\n');lex.whitespace=' \t\r';lex.whitespace_split=True
 rows=[];row=[]
 for token in lex:
  if token and set(token)=={'\n'}:
   if row: rows.append(row);row=[]
  else: row.append(token)
 if row:rows.append(row)
 return rows
class MigrationTests(unittest.TestCase):
 def run_case(self,src,flags=(),firewall=None):
  if EXTERNAL_UCI and flags:self.skipTest('mock-only fault injection; run mock suite separately')
  td=tempfile.TemporaryDirectory(prefix='case-',dir=HERE);self.addCleanup(td.cleanup)
  root=pathlib.Path(td.name);(root/'etc/config').mkdir(parents=True);(root/'tmp/sysinfo').mkdir(parents=True)
  (root/'etc/config/firewall').write_text("config zone\n option name 'lan'\n list network 'lan'\nconfig zone\n option name 'wan'\n list network 'wan'\n list network 'wan6'\n")
  (root/'tmp/sysinfo/board_name').write_text('gemtek,xr1710g-ubi\n'); f=root/'etc/config/network';f.write_text(src);f.chmod(0o640)
  if firewall is not None:(root/'etc/config/firewall').write_text(firewall)
  for flag in flags:(root/flag).touch()
  env={**os.environ,'XR_MIGRATION_ROOT':str(root),'XR_MIGRATION_UCI':EXTERNAL_UCI or str(HERE/'mock-uci.py')}
  result=subprocess.run(['sh',str(SCRIPT)],env=env,text=True,capture_output=True)
  if not EXTERNAL_UCI:self.assertNotIn('set ',(root/'uci-calls.jsonl').read_text())
  self.assertEqual(f.stat().st_mode&0o777,0o640)
  return result,f.read_text(),root,env
 def migrated(self,src=OLD):
  r,out,root,env=self.run_case(src);self.assertEqual(r.returncode,0,r.stderr);self.assertIn('MIGRATED:',r.stderr);return out,root,env
 def skipped(self,src,flags=(),error=False):
  r,out,root,env=self.run_case(src,flags);self.assertEqual(r.returncode,1 if error else 0,r.stderr);self.assertIn('ERROR:' if error else 'SKIP:',r.stderr);self.assertEqual(out,src);return r,out,root,env
 def test_standard_simultaneous(self):
  out,_,_=self.migrated();rows=parse(out)
  self.assertEqual([r[2] for r in rows if r[:2]==['list','ports']],['lan2','lan3','lan4'])
  self.assertIn(['option','device','wan'],rows);self.assertNotIn(['option','device','eth1'],rows)
 def test_idempotent(self):
  out,root,env=self.migrated();r=subprocess.run(['sh',str(SCRIPT)],env=env,capture_output=True,text=True)
  self.assertEqual(r.returncode,0,r.stderr);self.assertIn('NOCHANGE:',r.stderr);self.assertEqual(out,(root/'etc/config/network').read_text())
 def test_correct_modern_unchanged(self):
  src=OLD.replace("'eth1'","'wan'").replace("'lan3'","'lan4'").replace("'lan2'","'lan3'").replace("'eth2'","'lan2'")
  r,out,*_=self.run_case(src);self.assertEqual(r.returncode,0);self.assertIn('NOCHANGE:',r.stderr);self.assertEqual(out,src)
 def test_partial_modern_unchanged(self):
  src=OLD.replace("'eth1'","'wan'").replace("list ports 'eth2'\n",'')
  r,out,*_=self.run_case(src);self.assertIn('NOCHANGE:',r.stderr);self.assertEqual(out,src)
 def test_mixed_skip(self): self.skipped(OLD.replace("'eth1'","'wan'"))
 def test_incomplete_bridge_skip(self):self.skipped(OLD.replace(" list ports 'lan3'\n",''))
 def test_duplicate_bridge_skip(self):self.skipped(OLD.replace(" list ports 'lan3'"," list ports 'lan2'"))
 def test_cpu_conduit_skip(self):self.skipped(OLD+"\nconfig interface 'cpuuser'\n option device 'eth0'\n")
 def test_cpu_vlan_skip_without_reset(self):self.skipped(OLD.replace("'eth2'","'eth0.8'"))
 def test_legacy_alias_skip(self):self.skipped(OLD.replace("'eth1'","'ae_wan'"))
 def test_custom_collision_skip(self):self.skipped(OLD+"\nconfig device\n option name 'lan2'\n option type 'bridge'\n")
 def test_modern_destination_collision_skip(self):self.skipped(OLD+"\nconfig device\n option name 'wan'\n option type '8021q'\n option ifname 'eth2'\n")
 def test_duplicate_named_device_skip(self):self.skipped(OLD+"\nconfig device\n option name 'eth2.50'\n option type '8021q'\n option ifname 'eth2'\nconfig device\n option name 'eth2.50'\n option type '8021q'\n option ifname 'eth2'\n")
 def test_wan_vlan(self):
  out,*_=self.migrated(OLD.replace("option device 'eth1'","option device 'eth1.35'"));self.assertIn(['option','device','wan.35'],parse(out))
 def test_wan_qinq(self):
  out,*_=self.migrated(OLD.replace("option device 'eth1'","option device 'eth1.35.100'"));self.assertIn(['option','device','wan.35.100'],parse(out))
 def test_named_vlan_parent(self):
  src=OLD.replace("option device 'eth1'","option device 'uplink35'")+"\nconfig device 'uplink_config'\n option name 'uplink35'\n option type '8021q'\n option ifname 'eth1'\n option vid '35'\n"
  out,*_=self.migrated(src);rows=parse(out);self.assertIn(['option','name','uplink35'],rows);self.assertIn(['option','ifname','wan'],rows);self.assertIn(['config','device','uplink_config'],rows)
 def test_named_virtual_parent_skip(self):
  src=OLD.replace("option device 'eth1'","option device 'uplink35'")+"\nconfig device\n option name 'uplink35'\n option type 'bridge'\n option ifname 'eth1'\n"
  self.skipped(src)
 def test_bridge_vlan_flags(self):
  src=OLD+"\nconfig bridge-vlan\n option device 'br-lan'\n option vlan '20'\n list ports 'eth2:u*'\n list ports 'lan2:t'\n list ports 'lan3.100:t'\n list ports 'eth1:t'\n"
  out,*_=self.migrated(src);rows=parse(out)
  for p in ['lan2:u*','lan3:t','lan4.100:t','wan:t']:self.assertIn(['list','ports',p],rows)
  self.assertIn(['option','vlan','20'],rows)
 def test_aliases_addresses_mac_and_custom_values_preserved(self):
  src=OLD+"\nconfig interface 'lan2'\n option device '@wan'\n option note '$(touch SHOULD_NOT_EXIST); it'\\''s quoted'\n option multiline 'line1\nline2\n'\n option ipaddr '10.2.3.4'\n option gateway '10.2.3.1'\n"
  out,root,_=self.migrated(src);rows=parse(out)
  for row in parse(src):
   if row[0]=='config' or (row[0] in ('option','list') and row[1] not in ('device','ports')):self.assertIn(row,rows)
  self.assertIn(['option','device','@wan'],rows);self.assertFalse((root/'SHOULD_NOT_EXIST').exists())
 def test_pending_changes_skip(self):self.skipped(OLD,('pending',))
 def test_staged_rejection_no_partial_write(self):self.skipped(OLD,('reject-staged',),True)
 def test_concurrent_edit_preserved(self):
  r,out,*_=self.run_case(OLD,('concurrent',));self.assertIn('SKIP:',r.stderr);self.assertEqual(out,OLD+'\n# concurrent user edit\n')
 def test_unsupported_reference_field_skip(self):self.skipped(OLD+"\nconfig device\n option name 'test0'\n option type 'macvlan'\n option parent 'eth1'\n")
 def test_nondhcp_preserved(self):
  src=OLD.replace("option proto 'dhcp'","option proto 'static'")+"\nconfig route\n option interface 'wan'\n option target '0.0.0.0/0'\n option gateway '192.0.2.1'\n"
  out,*_=self.migrated(src);self.assertIn(['option','interface','wan'],parse(out));self.assertEqual(sum(r==['option','proto','static'] for r in parse(out)),2)
 def test_firewall_direct_physical_binding_skip(self):
  for field in ('device','src_device','dest_device','ifname'):
   with self.subTest(field=field):
    fw="config zone\n option name 'wan'\n list "+field+" 'eth1'\n"
    r,out,*_=self.run_case(OLD,firewall=fw);self.assertIn('SKIP:',r.stderr);self.assertEqual(out,OLD)
 def test_firewall_opaque_include_skip(self):
  r,out,*_=self.run_case(OLD,firewall="config include\n option path '/etc/firewall.user'\n")
  self.assertIn('SKIP:',r.stderr);self.assertEqual(out,OLD)
 def test_shell_metacharacters_are_inert(self):
  markers=[HERE/'INJECTION',HERE/'INJECTION2']
  value="`touch "+shlex.quote(str(markers[0]))+"` $(touch "+shlex.quote(str(markers[1]))+") \"double\" it's literal"
  src=OLD+"\nconfig interface 'extra'\n option note "+shlex.quote(value)+"\n"
  for marker in markers:self.assertFalse(marker.exists())
  out,*_=self.migrated(src)
  self.assertEqual([r for r in parse(src) if r[:2]==['option','note']],[r for r in parse(out) if r[:2]==['option','note']])
  for marker in markers:self.assertFalse(marker.exists())
 def test_option_ports_style_preserved(self):
  src=OLD.replace(" list ports 'eth2'\n list ports 'lan2'\n list ports 'lan3'", " option ports 'eth2 lan2 lan3'")
  out,*_=self.migrated(src);self.assertIn(['option','ports','lan2 lan3 lan4'],parse(out))
if __name__=='__main__': unittest.main(verbosity=2)
