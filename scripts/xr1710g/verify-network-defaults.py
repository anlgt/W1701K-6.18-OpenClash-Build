#!/usr/bin/env python3
"""Run actual patched config_generate in an isolated host fixture.
External UCI/JSON helpers are shell mocks. Production/source files stay untouched.
"""
import pathlib,tempfile,subprocess,os,unittest
HERE=pathlib.Path(__file__).resolve().parent
SOURCE=pathlib.Path(os.environ['XR_CONFIG_GENERATE_SOURCE'])
MARKER="\t\t\tuci set network.$1.proto='dhcp'\n"
INSERT=MARKER+'''\t\t\tif [ "$1" = wan ] && [ "$(cat /tmp/sysinfo/board_name 2>/dev/null)" = gemtek,xr1710g-ubi ]; then
\t\t\t\tuci set network.wan.sendclientid='hardware'
\t\t\tfi
'''
JSON_STUB=r'''
json_init() { :; }
json_load() { :; }
json_select() { :; }
json_is_a() { return 1; }
json_get_values() { eval "$1=''"; }
json_get_keys() {
 case "$2" in network) eval "$1=\$TEST_IFACE";; *) eval "$1=''";; esac
}
json_get_vars() {
 for name in "$@"; do
  case "$name" in device) v=wan;; protocol) v=$TEST_PROTO;; *) v=;; esac
  eval "$name=\$v"
 done
}
'''
class ConfigGenerateTests(unittest.TestCase):
 def run_case(self,board='gemtek,xr1710g-ubi',iface='wan',proto='dhcp',retained=False,system=True):
  td=tempfile.TemporaryDirectory(prefix='generate-',dir=HERE);self.addCleanup(td.cleanup);root=pathlib.Path(td.name)
  for d in ['etc/config','tmp/sysinfo','bin']:(root/d).mkdir(parents=True,exist_ok=True)
  (root/'etc/board.json').write_text('{}');(root/'tmp/sysinfo/board_name').write_text(board+'\n')
  (root/'etc/config/dhcp').write_text('# exists\n')
  if system:(root/'etc/config/system').write_text('# exists\n')
  if retained:(root/'etc/config/network').write_text("config interface wan\n option sendclientid none\n option clientid 'explicit'\n")
  (root/'json.sh').write_text(JSON_STUB);(root/'ipv4.sh').write_text('str2ip() { :; }; netmask2prefix() { :; };\n')
  uci=root/'bin/uci';uci.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$UCI_LOG"\ncase "$*" in *batch*) cat >> "$UCI_LOG";; esac\n');uci.chmod(0o755)
  text=SOURCE.read_text();self.assertEqual(text.count(INSERT),1)
  text=text.replace('/usr/share/libubox/jshn.sh',str(root/'json.sh')).replace('/lib/functions/ipv4.sh',str(root/'ipv4.sh'))
  text=text.replace('/etc/',str(root/'etc')+'/').replace('/tmp/sysinfo/',str(root/'tmp/sysinfo')+'/')
  script=root/'config_generate';script.write_text(text)
  env={**os.environ,'PATH':str(root/'bin')+':'+os.environ['PATH'],'UCI_LOG':str(root/'uci.log'),'TEST_IFACE':iface,'TEST_PROTO':proto}
  r=subprocess.run(['sh',str(script)],env=env,capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr)
  log=(root/'uci.log').read_text() if (root/'uci.log').exists() else ''
  return log,(root/'etc/config/network').read_text()
 def test_fresh_xr_wan_adds_hardware(self):
  log,_=self.run_case();self.assertIn('set network.wan.sendclientid=hardware',log)
 def test_other_board_not_changed(self):
  log,_=self.run_case(board='gemtek,w1700k-ubi');self.assertNotIn('sendclientid',log)
 def test_other_interface_not_changed(self):
  log,_=self.run_case(iface='guest');self.assertNotIn('sendclientid',log)
 def test_non_dhcp_not_changed(self):
  log,_=self.run_case(proto='pppoe');self.assertNotIn('sendclientid',log)
 def test_retained_explicit_clientid_untouched(self):
  log,text=self.run_case(retained=True);self.assertNotIn('sendclientid',log);self.assertIn('sendclientid none',text);self.assertIn("clientid 'explicit'",text)
 def test_retained_network_missing_system_untouched(self):
  log,text=self.run_case(retained=True,system=False);self.assertNotIn('set network.wan.sendclientid',log);self.assertIn('sendclientid none',text)
if __name__=='__main__':unittest.main(verbosity=2)
