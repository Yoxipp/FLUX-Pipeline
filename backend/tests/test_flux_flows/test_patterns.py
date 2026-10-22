# P3 (2026-10-23): Houdini style patterns (01_ARCHITECTURE §11, 00_LOGIQUE n°12).

from __future__ import annotations

import unittest

from flux_flows.patterns import PatternError, check_pattern, compile_pattern, filter_names, matches


class SpecExamples(unittest.TestCase):
    """Every row of the 01 §11 table."""

    def test_include_then_exclude(self) -> None:
        names = ["char_cache_v001.abc", "char_cache_tmp.abc", "scene.hip"]
        self.assertEqual(filter_names("*cache* ^*_tmp*", names), ["char_cache_v001.abc"])

    def test_several_inclusions(self) -> None:
        names = ["a.abc", "b.usd", "b_proxy.usd", "c.hip"]
        self.assertEqual(filter_names("*.abc *.usd ^*_proxy*", names), ["a.abc", "b.usd"])

    def test_inclusion_after_exclusion_adds_back(self) -> None:
        self.assertEqual(filter_names("*cache* ^*_tmp* *_final*", ["x_cache_tmp_final", "x_cache_tmp"]),
                         ["x_cache_tmp_final"])
        self.assertEqual(filter_names("x* ^*_tmp* *_final*", ["x_tmp_final", "x_tmp"]), ["x_tmp_final"])

    def test_path_word_and_basename_exclusion(self) -> None:
        names = ["/obj/geo1/cache_a", "/obj/geo1/cache_old", "/obj/a/b/cache_c", "/out/cache_d"]
        self.assertEqual(filter_names("/obj/*/cache_* ^*_old", names), ["/obj/geo1/cache_a"])

    def test_question_mark_and_sets(self) -> None:
        pat = "shot_??_v[0-9][0-9][0-9]*"
        self.assertTrue(matches(pat, "shot_01_v002.abc"))
        self.assertFalse(matches(pat, "shot_1_v2.abc"))


class Grammar(unittest.TestCase):
    def test_star_stays_in_segment_double_star_crosses(self) -> None:
        names = ["a/x.abc", "a/b/x.abc"]
        self.assertEqual(filter_names("a/*.abc", names), ["a/x.abc"])
        self.assertEqual(filter_names("a/**.abc", names), names)

    def test_word_without_slash_uses_basename(self) -> None:
        self.assertTrue(matches("*.abc", "D:/proj/cache/a.abc"))
        self.assertTrue(matches("*.abc", "D:\\proj\\cache\\a.abc"))
        self.assertFalse(matches("proj*", "D:/proj/cache/a.abc"))

    def test_first_word_exclusive_starts_from_all(self) -> None:
        self.assertEqual(filter_names("^*.hip", ["a.hip", "b.abc", "c.usd"]), ["b.abc", "c.usd"])
        self.assertEqual(filter_names("!*.hip", ["a.hip", "b.abc"]), ["b.abc"])

    def test_negated_set(self) -> None:
        self.assertEqual(filter_names("v[!0]*", ["v001", "v100"]), ["v100"])

    def test_case(self) -> None:
        self.assertTrue(matches("*.ABC", "a.abc"))
        self.assertFalse(matches("*.ABC", "a.abc", case_sensitive=True))

    def test_regex_chars_are_literal(self) -> None:
        self.assertTrue(matches("a+b.(1)", "a+b.(1)"))
        self.assertFalse(matches("a.b", "axb"))

    def test_order_and_duplicates_kept(self) -> None:
        self.assertEqual(filter_names("*", ["b", "a", "b"]), ["b", "a", "b"])

    def test_empty_keeps_nothing(self) -> None:
        self.assertEqual(filter_names("", ["a"]), [])
        self.assertEqual(filter_names("   ", ["a"]), [])


class Errors(unittest.TestCase):
    def test_invalid_syntax(self) -> None:
        for bad in ("[abc", "^", "!", "a ^ b", "[]", "[!]", "a]", "^^a", "[z-a]", "[a/b]"):
            with self.assertRaises(PatternError, msg=bad) as ctx:
                compile_pattern(bad)
            self.assertEqual(ctx.exception.code, "E_PARAM_INVALID")
            self.assertIsNotNone(check_pattern(bad))

    def test_valid_syntax(self) -> None:
        for good in ("*", "**", "a?b", "[abc]", "[a-z]*", "[-a]", "^*_tmp*", "/obj/*/x"):
            self.assertIsNone(check_pattern(good), good)


if __name__ == "__main__":
    unittest.main()
