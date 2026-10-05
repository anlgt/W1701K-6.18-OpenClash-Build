import unittest
from pathlib import Path
from verify_config import check_config, check_packages, REQUIRED

HERE=Path(__file__).parent
class ConfigTests(unittest.TestCase):
    def setUp(self): self.seed=(HERE/'w1700k-slim.config').read_text()
    def test_seed_passes(self): check_config(self.seed)
    def test_wrong_board_rejected(self):
        with self.assertRaises(AssertionError): check_config(self.seed.replace('DEVICE_gemtek_w1700k-ubi','DEVICE_gemtek_xr1710g-ubi'))
    def test_second_board_rejected(self):
        with self.assertRaises(AssertionError): check_config(self.seed+'\nCONFIG_TARGET_airoha_an7581_DEVICE_gemtek_xr1710g-ubi=y\n')
    def test_missing_wired_module_rejected(self):
        with self.assertRaises(AssertionError): check_config(self.seed.replace('CONFIG_PACKAGE_kmod-dsa-mt7530-mmio=y',''))
    def test_frp_built_or_installed_rejected(self):
        for name in ('frp','frpc','frps','luci-app-frpc','luci-app-frps','luci-i18n-frpc-zh-cn','luci-i18n-frps-zh-cn'):
            for mode in ('y','m'):
                with self.subTest(name=name,mode=mode):
                    with self.assertRaises(AssertionError): check_config(self.seed+f'\nCONFIG_PACKAGE_{name}={mode}\n')
    def test_frp_manifest_rejected(self):
        with self.assertRaises(AssertionError): check_packages(REQUIRED|{'frpc'})
    def test_no_all_kmods(self):
        with self.assertRaises(AssertionError): check_config(self.seed+'\nCONFIG_ALL_KMODS=y\n')
    def test_signed_packages_required(self):
        with self.assertRaises(AssertionError): check_config(self.seed.replace('CONFIG_SIGNED_PACKAGES=y',''))

if __name__=='__main__': unittest.main()
