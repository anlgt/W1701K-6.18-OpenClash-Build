import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import prepare_feeds as gate


class FeedPreparationTests(unittest.TestCase):
    def test_selected_audio_cannot_be_excluded(self):
        for name in ('PACKAGE_squeezelite-custom', 'PACKAGE_squeezelite-full',
                     'PACKAGE_squeezelite-dynamic', 'SQUEEZELITE_WMA_ALAC'):
            for value in ('y', 'm'):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    gate.check_selection(f'CONFIG_{name}={value}\n')

    def test_unselected_audio_allowed(self):
        gate.check_selection('# CONFIG_PACKAGE_squeezelite-custom is not set\nCONFIG_CCACHE=y\n')

    def make_tree(self, root):
        target = root / 'feeds/packages/sound/squeezelite'
        target.mkdir(parents=True)
        content = b'pinned test fixture\n'
        (target / 'Makefile').write_bytes(content)
        link = root / 'package/feeds/packages/squeezelite'
        link.parent.mkdir(parents=True)
        return target, link, hashlib.sha256(content).hexdigest()

    def test_changed_recipe_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_tree(root)
            with self.assertRaisesRegex(ValueError, 'differs from reviewed pin'):
                gate.inspect_entry(root, '')

    def test_real_directory_is_never_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target, link, digest = self.make_tree(root)
            link.mkdir()
            with patch.object(gate, 'SQUEEZELITE_MAKEFILE_SHA256', digest):
                with self.assertRaisesRegex(ValueError, 'real squeezelite directory'):
                    gate.inspect_entry(root, '')
            self.assertTrue(link.is_dir())
            self.assertTrue((target / 'Makefile').is_file())

    def test_only_verified_symlink_removed_and_repeat_is_safe(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target, link, digest = self.make_tree(root)
            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError as error:
                self.skipTest('Host cannot create symlinks: ' + str(error))
            with patch.object(gate, 'SQUEEZELITE_MAKEFILE_SHA256', digest), \
                 patch.object(gate.subprocess, 'check_output', return_value=gate.PACKAGES_COMMIT):
                self.assertTrue(gate.prepare(root, '', apply=False)['link_was_present'])
                self.assertTrue(link.is_symlink())
                gate.prepare(root, '', apply=True)
                self.assertFalse(link.exists())
                self.assertTrue((target / 'Makefile').is_file())
                self.assertFalse(gate.prepare(root, '', apply=True)['link_was_present'])

    def test_wrong_link_destination_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target, link, digest = self.make_tree(root)
            other = root / 'other'
            other.mkdir()
            try:
                link.symlink_to(other, target_is_directory=True)
            except OSError as error:
                self.skipTest('Host cannot create symlinks: ' + str(error))
            with patch.object(gate, 'SQUEEZELITE_MAKEFILE_SHA256', digest):
                with self.assertRaisesRegex(ValueError, 'unexpected directory'):
                    gate.inspect_entry(root, '')
            self.assertTrue(link.is_symlink())


if __name__ == '__main__':
    unittest.main()
