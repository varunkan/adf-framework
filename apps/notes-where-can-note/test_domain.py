"""Pure unit tests for domain.py — no HTTP, no I/O, fast and deterministic."""
import unittest

import domain


class CleanTextTest(unittest.TestCase):
    def test_strips_whitespace(self):
        self.assertEqual(domain.clean_text('  hello  '), 'hello')

    def test_empty_raises(self):
        for bad in ('', '   ', '\n\t'):
            with self.assertRaises(domain.ValidationError):
                domain.clean_text(bad)

    def test_non_string_raises(self):
        for bad in (None, 5, ['x'], {}):
            with self.assertRaises(domain.ValidationError):
                domain.clean_text(bad)

    def test_too_long_raises(self):
        with self.assertRaises(domain.ValidationError):
            domain.clean_text('a' * (domain.MAX_TEXT_LEN + 1))

    def test_at_limit_ok(self):
        self.assertEqual(len(domain.clean_text('a' * domain.MAX_TEXT_LEN)),
                         domain.MAX_TEXT_LEN)


class NormalizeTagsTest(unittest.TestCase):
    def test_none_is_empty(self):
        self.assertEqual(domain.normalize_tags(None), [])

    def test_lowercase_strip_dedupe_sort(self):
        self.assertEqual(
            domain.normalize_tags(['  Work ', 'home', 'WORK', 'home']),
            ['home', 'work'],
        )

    def test_drops_empties(self):
        self.assertEqual(domain.normalize_tags(['a', '   ', '']), ['a'])

    def test_non_list_raises(self):
        with self.assertRaises(domain.ValidationError):
            domain.normalize_tags('work')

    def test_non_string_element_raises(self):
        with self.assertRaises(domain.ValidationError):
            domain.normalize_tags(['ok', 5])

    def test_tag_too_long_raises(self):
        with self.assertRaises(domain.ValidationError):
            domain.normalize_tags(['x' * (domain.MAX_TAG_LEN + 1)])

    def test_too_many_tags_raises(self):
        with self.assertRaises(domain.ValidationError):
            domain.normalize_tags(['t%d' % i for i in range(domain.MAX_TAGS + 1)])


class MakeNoteTest(unittest.TestCase):
    def test_shape(self):
        n = domain.make_note(7, '  hi ', ['B', 'a'], 100)
        self.assertEqual(n['id'], 7)
        self.assertEqual(n['text'], 'hi')
        self.assertEqual(n['tags'], ['a', 'b'])
        self.assertFalse(n['pinned'])
        self.assertFalse(n['archived'])
        self.assertEqual(n['created_at'], 100)
        self.assertEqual(n['updated_at'], 100)


class ApplyUpdateTest(unittest.TestCase):
    def _note(self):
        return domain.make_note(1, 'orig', ['a'], 100)

    def test_update_text_bumps_timestamp(self):
        n = self._note()
        changed = domain.apply_update(n, {'text': 'new'}, 200)
        self.assertTrue(changed)
        self.assertEqual(n['text'], 'new')
        self.assertEqual(n['updated_at'], 200)

    def test_noop_when_same(self):
        n = self._note()
        changed = domain.apply_update(n, {'text': 'orig'}, 200)
        self.assertFalse(changed)
        self.assertEqual(n['updated_at'], 100)

    def test_pin_and_archive(self):
        n = self._note()
        self.assertTrue(domain.apply_update(n, {'pinned': True}, 200))
        self.assertTrue(n['pinned'])
        self.assertTrue(domain.apply_update(n, {'archived': True}, 201))
        self.assertTrue(n['archived'])

    def test_non_bool_flag_raises(self):
        n = self._note()
        with self.assertRaises(domain.ValidationError):
            domain.apply_update(n, {'pinned': 'yes'}, 200)

    def test_bad_body_raises(self):
        n = self._note()
        with self.assertRaises(domain.ValidationError):
            domain.apply_update(n, ['not', 'a', 'dict'], 200)

    def test_unknown_keys_ignored(self):
        n = self._note()
        # a key the updater knows nothing about must never count as a change
        self.assertFalse(domain.apply_update(n, {'totally_unknown': 'red'}, 200))


class SearchAndFilterTest(unittest.TestCase):
    def _notes(self):
        return [
            domain.make_note(1, 'buy milk', ['shopping'], 100),
            domain.make_note(2, 'call dentist', ['health'], 100),
            {'id': 3, 'text': 'old note'},  # legacy note, no newer keys
        ]

    def test_search_text(self):
        notes = self._notes()
        out = domain.filter_notes(notes, query='milk')
        self.assertEqual([n['id'] for n in out], [1])

    def test_search_matches_tags(self):
        notes = self._notes()
        out = domain.filter_notes(notes, query='health')
        self.assertEqual([n['id'] for n in out], [2])

    def test_search_case_insensitive(self):
        out = domain.filter_notes(self._notes(), query='MILK')
        self.assertEqual([n['id'] for n in out], [1])

    def test_filter_by_tag(self):
        out = domain.filter_notes(self._notes(), tag='shopping')
        self.assertEqual([n['id'] for n in out], [1])

    def test_legacy_note_survives(self):
        out = domain.filter_notes(self._notes())
        self.assertIn(3, [n['id'] for n in out])

    def test_archived_modes(self):
        notes = [
            domain.make_note(1, 'active one', None, 100),
            domain.make_note(2, 'archived one', None, 100),
        ]
        notes[1]['archived'] = True
        active = domain.filter_notes(notes, archived='active')
        only = domain.filter_notes(notes, archived='only')
        every = domain.filter_notes(notes, archived='all')
        self.assertEqual([n['id'] for n in active], [1])
        self.assertEqual([n['id'] for n in only], [2])
        self.assertEqual(sorted(n['id'] for n in every), [1, 2])


class SortTest(unittest.TestCase):
    def test_pinned_first_then_recency(self):
        notes = [
            domain.make_note(1, 'a', None, 100),
            domain.make_note(2, 'b', None, 200),
            domain.make_note(3, 'c', None, 150),
        ]
        notes[0]['pinned'] = True  # id 1 pinned
        ordered = [n['id'] for n in domain.sort_notes(notes)]
        # pinned id 1 first, then most-recently-updated (200=id2, 150=id3)
        self.assertEqual(ordered, [1, 2, 3])

    def test_does_not_mutate_input(self):
        notes = [domain.make_note(1, 'a', None, 100),
                 domain.make_note(2, 'b', None, 200)]
        original = list(notes)
        domain.sort_notes(notes)
        self.assertEqual(notes, original)


class TagsAndStatsTest(unittest.TestCase):
    def _notes(self):
        ns = [
            domain.make_note(1, 'one two three', ['work', 'urgent'], 100),
            domain.make_note(2, 'four five', ['work'], 100),
        ]
        ns[1]['pinned'] = True
        return ns

    def test_collect_tags_counts(self):
        tags = domain.collect_tags(self._notes())
        self.assertEqual(tags, [{'tag': 'urgent', 'count': 1},
                                {'tag': 'work', 'count': 2}])

    def test_stats(self):
        s = domain.compute_stats(self._notes())
        self.assertEqual(s['total'], 2)
        self.assertEqual(s['active'], 2)
        self.assertEqual(s['archived'], 0)
        self.assertEqual(s['pinned'], 1)
        self.assertEqual(s['tags'], 2)
        self.assertEqual(s['words'], 5)  # 3 + 2

    def test_count_words(self):
        self.assertEqual(domain.count_words('  hello   world '), 2)
        self.assertEqual(domain.count_words(''), 0)
        self.assertEqual(domain.count_words(None), 0)


class CleanColorTest(unittest.TestCase):
    def test_none_and_empty_default(self):
        self.assertEqual(domain.clean_color(None), 'default')
        self.assertEqual(domain.clean_color('   '), 'default')

    def test_normalizes_case_and_space(self):
        self.assertEqual(domain.clean_color('  RED '), 'red')

    def test_unknown_raises(self):
        with self.assertRaises(domain.ValidationError):
            domain.clean_color('chartreuse')

    def test_non_string_raises(self):
        with self.assertRaises(domain.ValidationError):
            domain.clean_color(5)

    def test_all_palette_colors_valid(self):
        for c in domain.NOTE_COLORS:
            self.assertEqual(domain.clean_color(c), c)


class ColorOnNoteTest(unittest.TestCase):
    def test_make_note_default_color(self):
        n = domain.make_note(1, 'x', None, 100)
        self.assertEqual(n['color'], 'default')

    def test_make_note_with_color(self):
        n = domain.make_note(1, 'x', None, 100, color='Green')
        self.assertEqual(n['color'], 'green')

    def test_make_note_bad_color_raises(self):
        with self.assertRaises(domain.ValidationError):
            domain.make_note(1, 'x', None, 100, color='neon')

    def test_apply_update_changes_color(self):
        n = domain.make_note(1, 'x', None, 100)
        self.assertTrue(domain.apply_update(n, {'color': 'blue'}, 200))
        self.assertEqual(n['color'], 'blue')
        self.assertEqual(n['updated_at'], 200)

    def test_apply_update_color_noop(self):
        n = domain.make_note(1, 'x', None, 100, color='blue')
        self.assertFalse(domain.apply_update(n, {'color': 'blue'}, 200))

    def test_note_color_tolerates_legacy(self):
        self.assertEqual(domain.note_color({'id': 1, 'text': 'old'}), 'default')
        self.assertEqual(domain.note_color({'color': 'bogus'}), 'default')


class RenameTagTest(unittest.TestCase):
    def _notes(self):
        return [
            domain.make_note(1, 'a', ['work', 'urgent'], 100),
            domain.make_note(2, 'b', ['work'], 100),
            domain.make_note(3, 'c', ['home'], 100),
        ]

    def test_rename_across_notes(self):
        notes = self._notes()
        changed = domain.rename_tag(notes, 'work', 'office', 500)
        self.assertEqual(changed, 2)
        self.assertEqual(notes[0]['tags'], ['office', 'urgent'])
        self.assertEqual(notes[1]['tags'], ['office'])
        self.assertEqual(notes[2]['tags'], ['home'])
        self.assertEqual(notes[0]['updated_at'], 500)

    def test_rename_dedupes_when_target_exists(self):
        notes = [domain.make_note(1, 'a', ['work', 'office'], 100)]
        domain.rename_tag(notes, 'work', 'office', 500)
        self.assertEqual(notes[0]['tags'], ['office'])

    def test_empty_new_removes_tag(self):
        notes = self._notes()
        changed = domain.rename_tag(notes, 'work', '', 500)
        self.assertEqual(changed, 2)
        self.assertEqual(notes[0]['tags'], ['urgent'])
        self.assertEqual(notes[1]['tags'], [])

    def test_case_insensitive_match(self):
        notes = self._notes()
        self.assertEqual(domain.rename_tag(notes, 'WORK', 'x', 500), 2)

    def test_missing_old_raises(self):
        with self.assertRaises(domain.ValidationError):
            domain.rename_tag(self._notes(), '   ', 'x', 500)

    def test_too_long_new_raises(self):
        with self.assertRaises(domain.ValidationError):
            domain.rename_tag(self._notes(), 'work',
                              'x' * (domain.MAX_TAG_LEN + 1), 500)

    def test_no_match_returns_zero(self):
        notes = self._notes()
        self.assertEqual(domain.rename_tag(notes, 'nope', 'x', 500), 0)


class ImportNotesTest(unittest.TestCase):
    def test_import_merges_and_reassigns_ids(self):
        existing = [domain.make_note(1, 'keep', None, 100)]
        bundle = domain.export_bundle(
            [domain.make_note(50, 'incoming', ['t'], 100)], 999)
        merged, next_id, count = domain.import_notes(existing, bundle, 2, 700)
        self.assertEqual(count, 1)
        self.assertEqual(next_id, 3)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[1]['id'], 2)  # reassigned, not 50
        self.assertEqual(merged[1]['text'], 'incoming')
        self.assertEqual(merged[1]['tags'], ['t'])

    def test_round_trip_preserves_flags_and_color(self):
        src = domain.make_note(1, 'flagged', ['x'], 100, color='red')
        src['pinned'] = True
        src['archived'] = True
        bundle = domain.export_bundle([src], 999)
        merged, _, _ = domain.import_notes([], bundle, 1, 700)
        self.assertTrue(merged[0]['pinned'])
        self.assertTrue(merged[0]['archived'])
        self.assertEqual(merged[0]['color'], 'red')
        self.assertEqual(merged[0]['created_at'], 100)

    def test_non_dict_bundle_raises(self):
        with self.assertRaises(domain.ValidationError):
            domain.import_notes([], ['nope'], 1, 700)

    def test_missing_notes_list_raises(self):
        with self.assertRaises(domain.ValidationError):
            domain.import_notes([], {'version': 1}, 1, 700)

    def test_invalid_note_raises(self):
        with self.assertRaises(domain.ValidationError):
            domain.import_notes([], {'notes': [{'text': '   '}]}, 1, 700)


class DuplicateAndExportTest(unittest.TestCase):
    def test_duplicate_resets_state(self):
        src = domain.make_note(1, 'original', ['a', 'b'], 100)
        src['pinned'] = True
        src['archived'] = True
        copy = domain.duplicate_note(src, 9, 500)
        self.assertEqual(copy['id'], 9)
        self.assertEqual(copy['text'], 'original')
        self.assertEqual(copy['tags'], ['a', 'b'])
        self.assertFalse(copy['pinned'])
        self.assertFalse(copy['archived'])
        self.assertEqual(copy['created_at'], 500)

    def test_duplicate_preserves_color(self):
        src = domain.make_note(1, 'original', None, 100, color='purple')
        copy = domain.duplicate_note(src, 9, 500)
        self.assertEqual(copy['color'], 'purple')

    def test_export_bundle(self):
        notes = [domain.make_note(1, 'a', None, 100)]
        bundle = domain.export_bundle(notes, 999)
        self.assertEqual(bundle['count'], 1)
        self.assertEqual(bundle['exported_at'], 999)
        self.assertEqual(bundle['version'], 1)
        self.assertEqual(bundle['notes'][0]['id'], 1)


if __name__ == '__main__':
    unittest.main()
