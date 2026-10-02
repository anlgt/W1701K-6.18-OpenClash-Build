import contextlib
import importlib.util
import io
import json
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location('verify_fit', HERE / 'verify-fit.py')
v = importlib.util.module_from_spec(spec); spec.loader.exec_module(v)

def fdt_bytes(props):
    strings = bytearray(); offsets = {}
    body = bytearray()
    def u(n): body.extend(struct.pack('>I', n))
    def pad(): body.extend(b'\0' * (-len(body) % 4))
    def node(name, values):
        u(1); body.extend(name.encode() + b'\0'); pad()
        for key, value in values.items():
            if isinstance(value, dict): continue
            if key not in offsets:
                offsets[key] = len(strings); strings.extend(key.encode() + b'\0')
            u(3); u(len(value)); u(offsets[key]); body.extend(value); pad()
        for key, value in values.items():
            if isinstance(value, dict): node(key, value)
        u(2)
    node('', props); u(9)
    total = 56 + len(body) + len(strings)
    return struct.pack('>10I', 0xd00dfeed, total, 56, 56+len(body), 40, 17, 16, 0, len(strings), len(body)) + b'\0'*16 + body + strings

class GateTests(unittest.TestCase):
    def test_fdt_round_trip(self):
        b = fdt_bytes({'compatible': b'gemtek,xr1710g-ubi\0', 'chosen': {'bootargs': b'root=/dev/fit0\0'}})
        total, nodes = v.fdt(b)
        self.assertEqual(total, len(b)); self.assertEqual(nodes['/chosen']['bootargs'], b'root=/dev/fit0\0')
    def test_fdt_bad_magic(self):
        b = bytearray(fdt_bytes({})); b[0] = 0
        with self.assertRaises(AssertionError): v.fdt(b)
    def test_fdt_truncated(self):
        for b in (b'', b'\0'*20, fdt_bytes({})[:-1]):
            with self.assertRaises(AssertionError): v.fdt(b)
    def test_fdt_property_bounds(self):
        b = bytearray(fdt_bytes({'x': b'y'}))
        struct.pack_into('>I', b, 68, 0xffffffff)
        with self.assertRaises(AssertionError): v.fdt(b)
    def test_download_failure_not_masked(self):
        # Same recipe form as the patched toplevel.mk, including SUBMAKE's prefix.
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'Makefile'
            p.write_text('DIRS=first second\nSUBMAKE=umask 022; $(MAKE) -f $(lastword $(MAKEFILE_LIST))\nall:\n\t@$(foreach dir,$(DIRS),$(SUBMAKE) $(dir) || exit 1;)\nfirst:\n\t@false\nsecond:\n\t@touch reached-second\n')
            result = subprocess.run(['make', '-f', str(p)], cwd=td, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((Path(td)/'reached-second').exists())
    def test_seed_package_guard(self):
        result = subprocess.run(['python3', str(HERE/'verify-config.py'), str(HERE.parent.parent/'xr1710g-candidate.config')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
    def test_missing_required_package_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'bad.config'; p.write_text('CONFIG_TARGET_airoha=y\n')
            result = subprocess.run(['python3', str(HERE/'verify-config.py'), str(p)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)

if __name__ == '__main__': unittest.main()
