#!/usr/bin/env python3
"""Regression tests for the catalog plan's explicit body/fence counting convention."""
import importlib.util
from pathlib import Path
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('catalog_measurement', ROOT / 'docs/evidence/catalog_measurement.py')
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def text(body):
    return '---\nmetadata:\n  kind: entry\n---\n\n' + body + '\n\n'


def doc(body_lines, kind='entry', extra=()):
    """Whole file: one frontmatter line per entry plus the given body lines, one trailing newline."""
    return '\n'.join(['---', 'metadata:', '  kind: %s' % kind, *extra, '---', *body_lines]) + '\n'


def body_with(line_count, h2_count, word_count):
    """Body lines whose trimmed body holds exactly line_count lines, h2_count H2 and word_count words."""
    lines = ['## H%d' % index for index in range(h2_count)]
    filler, filler_words = line_count - h2_count, word_count - 2 * h2_count
    if not filler:
        assert filler_words == 0
        return lines
    base, extra = divmod(filler_words, filler)
    assert base >= 1
    for index in range(filler):
        lines.append(' '.join(['w'] * (base + (1 if index < extra else 0))))
    return lines


def skill(line_count, h2_count=0, word_count=0, kind='entry'):
    return doc(body_with(line_count, h2_count, word_count), kind=kind)


class FakeGit:
    """Serve a synthetic tree so measure()'s selection rules are pinned without a repository."""

    def __init__(self, files, commit='f' * 40, tree='e' * 40):
        self.files, self.commit, self.tree = dict(files), commit, tree

    def __call__(self, repo, *args):
        if args[:1] == ('rev-parse',) and args[1].endswith('^{commit}'):
            return self.commit + '\n'
        if args[:1] == ('rev-parse',) and args[1].endswith('^{tree}'):
            return self.tree + '\n'
        if args[:1] == ('ls-tree',):
            return ''.join(path + '\n' for path in sorted(self.files))
        if args[:1] == ('show',):
            return self.files[args[1].split(':', 1)[1]]
        raise AssertionError('unexpected git call: %r' % (args,))


TREE = {
    'skills/alpha/SKILL.md': skill(201, h2_count=8, word_count=300),
    'skills/alpha/notes.md': '# not a skill\n',
    'skills/beta/SKILL.md': skill(200, h2_count=10, word_count=300),
    'skills/delta/SKILL.md': skill(201, word_count=2501),
    'skills/epsilon/SKILL.md': skill(5, word_count=49),
    'skills/gamma/SKILL.md': skill(201, h2_count=7, word_count=2500),
    'skills/nested/deep/SKILL.md': skill(300, h2_count=20, word_count=5000),
    'skills/zeta/SKILL.md': skill(5, word_count=50),
    'reference/kept.py': 'x\n' * 700,
    'ref/skipped.py': 'x\n' * 900,
    'scripts/big.py': 'x\n' * 601,
    'scripts/eq_a.py': 'x\n' * 700,
    'scripts/eq_b.py': 'x\n' * 700,
    'scripts/exact600.py': 'x\n' * 600,
    'scripts/notes.md': 'x\n' * 900,
    'scripts/readme.ts': 'x\n' * 601,
}


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

    def test_shorter_fence_does_not_close(self):
        row = MODULE.body_metrics(text('````\n```\n## Hidden'))
        self.assertEqual(row['h2'], 0)
        self.assertEqual(row['body_lines'], 3)

    def test_different_fence_character_does_not_close(self):
        row = MODULE.body_metrics(text('```\n~~~\n## Hidden'))
        self.assertEqual(row['h2'], 0)
        self.assertEqual(row['body_lines'], 3)

    def test_closing_fence_requires_blank_suffix(self):
        row = MODULE.body_metrics(text('```\n```not a close\n## Hidden'))
        self.assertEqual(row['h2'], 0)
        self.assertEqual(row['body_lines'], 3)

    def test_distribution_uses_nearest_rank(self):
        self.assertEqual(MODULE.distribution(list(range(1, 11)))['p90'], 9)
        self.assertEqual(MODULE.distribution([121, 200, 201])['between_121_and_200'], 2)

    def test_missing_frontmatter_is_not_silently_counted(self):
        with self.assertRaises(ValueError):
            MODULE.body_metrics('## Not a skill')


class FrontmatterTests(unittest.TestCase):
    def test_frontmatter_is_excluded_and_full_lines_keeps_every_line(self):
        row = MODULE.body_metrics(doc(['## H'], extra=['  extra: 1']))
        self.assertEqual(row['body_lines'], 1)
        self.assertEqual(row['h2'], 1)
        self.assertEqual(row['full_lines'], 6)

    def test_full_lines_counts_frontmatter_and_untrimmed_exterior_blanks(self):
        row = MODULE.body_metrics(doc(['', '   ', '## H', 'text', '', '  ']))
        self.assertEqual(row['body_lines'], 2)
        self.assertEqual(row['body_words'], 3)
        self.assertEqual(row['h2'], 1)
        self.assertEqual(row['full_lines'], 10)

    def test_interior_blank_lines_stay_in_the_body(self):
        row = MODULE.body_metrics(doc(['## H', '', 'text']))
        self.assertEqual(row['body_lines'], 3)
        self.assertEqual(row['body_words'], 3)

    def test_leading_exterior_blanks_are_trimmed(self):
        row = MODULE.body_metrics(doc(['', '   ', '## H']))
        self.assertEqual(row['body_lines'], 1)
        self.assertEqual(row['body_words'], 2)
        self.assertEqual(row['h2'], 1)

    def test_trailing_exterior_blanks_are_trimmed(self):
        row = MODULE.body_metrics(doc(['## H', 'text', '', '   ', '']))
        self.assertEqual(row['body_lines'], 2)
        self.assertEqual(row['body_words'], 3)
        self.assertEqual(row['h2'], 1)

    def test_word_count_uses_whitespace_split_on_the_rejoined_body(self):
        row = MODULE.body_metrics(doc(['alpha  beta', 'gamma delta']))
        self.assertEqual(row['body_lines'], 2)
        self.assertEqual(row['body_words'], 4)

    def test_kind_is_metadata_kind_verbatim(self):
        self.assertEqual(MODULE.body_metrics(doc(['## H'], kind='mechanism'))['kind'], 'mechanism')
        self.assertEqual(MODULE.body_metrics(doc(['## H'], kind='Entry'))['kind'], 'Entry')

    def test_body_metrics_returns_exactly_the_documented_keys(self):
        self.assertEqual(set(MODULE.body_metrics(doc(['## H']))),
                         {'kind', 'body_lines', 'body_words', 'h2', 'full_lines'})

    def test_frontmatter_requires_the_dash_line_at_column_zero(self):
        with self.assertRaisesRegex(ValueError, 'missing frontmatter'):
            MODULE.body_metrics(' ---\nmetadata:\n  kind: entry\n---\nbody\n')
        with self.assertRaisesRegex(ValueError, 'missing frontmatter'):
            MODULE.body_metrics('body\n---\nmetadata:\n  kind: entry\n---\n')


class HeadingTests(unittest.TestCase):
    def test_h2_requires_level_two_with_space_or_end_of_line(self):
        row = MODULE.body_metrics(doc(['# One', '## Two', '### Three', '##Four', '## Five', '#### Six', '##']))
        self.assertEqual(row['h2'], 3)

    def test_h2_allows_at_most_three_leading_spaces(self):
        row = MODULE.body_metrics(doc(['## A', ' ## B', '  ## C', '   ## D', '    ## E', '\t## F']))
        self.assertEqual(row['h2'], 4)


class FenceTests(unittest.TestCase):
    def test_fence_marker_requires_three_characters(self):
        row = MODULE.body_metrics(doc(['``', '``x', '## Visible']))
        self.assertEqual(row['body_lines'], 3)
        self.assertEqual(row['h2'], 1)

    def test_fence_marker_allows_at_most_three_leading_spaces(self):
        self.assertEqual(MODULE.body_metrics(doc(['   ```', '## Hidden']))['h2'], 0)
        self.assertEqual(MODULE.body_metrics(doc(['    ```', '## Visible']))['h2'], 1)

    def test_fence_opening_may_carry_an_info_string(self):
        row = MODULE.body_metrics(doc(['```python is fine', '## Hidden']))
        self.assertEqual(row['body_lines'], 2)
        self.assertEqual(row['h2'], 0)

    def test_equal_length_fence_closes(self):
        self.assertEqual(MODULE.body_metrics(doc(['```', '## Hidden', '```', '## Visible']))['h2'], 1)

    def test_longer_fence_closes(self):
        self.assertEqual(MODULE.body_metrics(doc(['```', '## Hidden', '`````', '## Visible']))['h2'], 1)

    def test_closing_fence_may_have_trailing_whitespace(self):
        self.assertEqual(MODULE.body_metrics(doc(['```', '## Hidden', '```   ', '## Visible']))['h2'], 1)

    def test_tilde_fences_follow_the_same_closing_rules(self):
        row = MODULE.body_metrics(doc(['~~~~', '## Hidden', '~~~', '## Still hidden', '~~~~', '## Visible']))
        self.assertEqual(row['body_lines'], 6)
        self.assertEqual(row['h2'], 1)

    def test_unclosed_fence_hides_the_rest_of_the_body(self):
        row = MODULE.body_metrics(doc(['```', '## Hidden', 'text']))
        self.assertEqual(row['body_lines'], 3)
        self.assertEqual(row['h2'], 0)

    def test_the_first_marker_sets_the_fence_not_the_longest(self):
        self.assertEqual(MODULE.body_metrics(doc(['````', '```', '## Hidden', '````', '## Visible']))['h2'], 1)


class DistributionTests(unittest.TestCase):
    def test_total_median_max_and_p90_over_unsorted_input(self):
        result = MODULE.distribution([4, 1, 2])
        self.assertEqual(result['total'], 7)
        self.assertEqual(result['median'], 2)
        self.assertEqual(result['max'], 4)
        self.assertEqual(result['p90'], 4)

    def test_median_averages_the_middle_pair(self):
        self.assertEqual(MODULE.distribution([1, 2, 3, 4])['median'], 2.5)

    def test_p90_rank_is_not_integral(self):
        self.assertEqual(MODULE.distribution([1, 2, 3])['p90'], 3)
        self.assertEqual(MODULE.distribution([10, 20, 30, 40, 50, 60, 70])['p90'], 70)
        self.assertEqual(MODULE.distribution([7])['p90'], 7)

    def test_over_120_is_strict(self):
        self.assertEqual(MODULE.distribution([119, 120, 121])['over_120'], 1)

    def test_band_bounds_are_121_to_200_inclusive(self):
        result = MODULE.distribution([120, 121, 200, 201])
        self.assertEqual(result['over_120'], 3)
        self.assertEqual(result['between_121_and_200'], 2)


class MeasureTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(MODULE, 'git', FakeGit(TREE))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.result = MODULE.measure(Path('unused'), 'HEAD')

    def test_measure_reports_the_resolved_commit_and_tree(self):
        self.assertEqual(self.result['commit'], 'f' * 40)
        self.assertEqual(self.result['tree'], 'e' * 40)

    def test_measure_returns_exactly_the_documented_keys(self):
        self.assertEqual(set(self.result),
                         {'commit', 'tree', 'skills', 'body', 'full_file', 'queue_count', 'queue',
                          'stubs', 'rows', 'code_over_600'})

    def test_only_flat_skills_named_SKILL_md_become_rows(self):
        self.assertEqual(self.result['skills'], 6)
        self.assertEqual(sorted(row['skill'] for row in self.result['rows']),
                         ['alpha', 'beta', 'delta', 'epsilon', 'gamma', 'zeta'])

    def test_queue_predicate_bounds_are_strict_without_preference(self):
        rows = {row['skill']: row for row in self.result['rows']}
        self.assertEqual(rows['beta']['body_lines'], 200)
        self.assertEqual(rows['beta']['h2'], 10)
        self.assertEqual(rows['gamma']['body_words'], 2500)
        self.assertEqual(rows['gamma']['h2'], 7)
        self.assertEqual(rows['alpha']['h2'], 8)
        self.assertEqual(rows['delta']['body_words'], 2501)
        self.assertEqual([row['skill'] for row in self.result['queue']], ['alpha', 'delta'])
        self.assertEqual(self.result['queue_count'], 2)

    def test_stub_boundary_is_below_fifty_words(self):
        self.assertEqual([row['skill'] for row in self.result['stubs']], ['epsilon'])

    def test_body_and_full_file_distributions_over_the_rows(self):
        self.assertEqual(self.result['body'],
                         {'total': 813, 'median': 200.5, 'p90': 201, 'max': 201,
                          'over_120': 4, 'between_121_and_200': 1})
        self.assertEqual(self.result['full_file'],
                         {'total': 837, 'median': 204.5, 'p90': 205, 'max': 205,
                          'over_120': 4, 'between_121_and_200': 0})

    def test_code_over_600_selection_and_order(self):
        self.assertEqual(self.result['code_over_600'], [
            {'path': 'reference/kept.py', 'lines': 700},
            {'path': 'scripts/eq_a.py', 'lines': 700},
            {'path': 'scripts/eq_b.py', 'lines': 700},
            {'path': 'scripts/big.py', 'lines': 601},
            {'path': 'scripts/readme.ts', 'lines': 601},
        ])


if __name__ == '__main__':
    unittest.main(verbosity=2)
