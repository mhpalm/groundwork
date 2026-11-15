# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Micah Palmquist, micah.palmquist@gmail.com
"""Sandbox run finding 15: claude.ai rewrites an uploaded skill's SKILL.md frontmatter (it quotes the
version), so the release digest of a SKILL.md covers the frontmatter's values, not its bytes."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skills", "groundwork-core", "scripts"))
import check_compat  # noqa: E402

MD = b"---\nname: groundwork-x\nmetadata:\n  version: 1.0.0\n---\n\n# Body\n\nText.\n"


class FrontmatterDigest(unittest.TestCase):
    def test_a_requoted_frontmatter_has_the_same_digest(self):
        quoted = MD.replace(b"version: 1.0.0", b"version: '1.0.0'")
        self.assertEqual(check_compat.file_digest("x/SKILL.md", MD), check_compat.file_digest("x/SKILL.md", quoted))

    def test_a_changed_value_or_body_changes_it(self):
        base = check_compat.file_digest("x/SKILL.md", MD)
        for other in (MD.replace(b"1.0.0", b"1.0.1"), MD.replace(b"Text.", b"Other text.")):
            with self.subTest(other=other):
                self.assertNotEqual(base, check_compat.file_digest("x/SKILL.md", other))

    def test_other_files_are_hashed_byte_for_byte(self):
        quoted = MD.replace(b"version: 1.0.0", b"version: '1.0.0'")
        self.assertNotEqual(check_compat.file_digest("x/write.md", MD), check_compat.file_digest("x/write.md", quoted))


if __name__ == "__main__":
    unittest.main()
