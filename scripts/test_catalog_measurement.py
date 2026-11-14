#!/usr/bin/env python3
"""Regression tests for the catalog plan's explicit body/fence counting convention."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('catalog_measurement', ROOT / 'docs/evidence/catalog_measurement.py')
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def text(body):
    return '---\nmetadata:\n  kind: entry\n---\n\n' + body + '\n\n'


class MeasurementTests(unittest.TestCase):
    def test_frontmatter_and_exterior_blanks_are_not_body(self):
        row = MODULE.body_metrics(text('## Heading\n\ntext'))
        self.assertEqual(row['body_lines'], 3)
        self.assertEqual(row['body_words'], 3)
        self.assertEqual(row['h2'], 1)
        self.assertEqual(row['kind'], 'entry')
        self.assertEqual(row['full_lines'], 9)

    def test_backtick_and_tilde_fences_hide_pseudo_headings(self):
        row = MODULE.body_metrics(text('## Real\n```text\n## Hidden\n```\n~~~\n## Hidden too\n~~~\n   ## Real too'))
        self.assertEqual(row['h2'], 2)

    def test_short_or_different_fence_does_not_close(self):
        row = MODULE.body_metrics(text('````\n```\n## Hidden\n~~~\n## Also hidden\n````\n## Real'))
        self.assertEqual(row['h2'], 1)

    def test_closing_fence_requires_blank_suffix(self):
        row = MODULE.body_metrics(text('```\n```not a close\n## Hidden\n```\n## Real'))
        self.assertEqual(row['h2'], 1)

    def test_distribution_uses_nearest_rank(self):
        self.assertEqual(MODULE.distribution(list(range(1, 11)))['p90'], 9)
        self.assertEqual(MODULE.distribution([121, 200, 201])['between_121_and_200'], 2)

    def test_missing_frontmatter_is_not_silently_counted(self):
        with self.assertRaises(ValueError):
            MODULE.body_metrics('## Not a skill')


if __name__ == '__main__':
    unittest.main(verbosity=2)
