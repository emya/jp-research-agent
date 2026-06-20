"""Offline tests for the management / officer profile feature."""
from __future__ import annotations

import unittest

from src.edinet.client import EDINETClient
from src.management import build_profile, render
from src.parser.officer_parser import extract_officers

TICKER = "8035"


class TestOfficerExtraction(unittest.TestCase):
    def setUp(self):
        self.filing = EDINETClient().fetch_filing(TICKER)

    def test_officers_and_representatives(self):
        mp = extract_officers(self.filing)
        self.assertEqual(len(mp.officers), 2)
        reps = mp.representatives()
        self.assertEqual(len(reps), 1)
        ceo = reps[0]
        self.assertIn("山田", ceo.name)
        self.assertEqual(ceo.name_en, "Yamada Taro")           # romanized from member id
        self.assertIn("代表取締役", ceo.title)
        self.assertIn("Representative Director", ceo.title_en)  # English title
        self.assertIn("President", ceo.title_en)
        self.assertTrue(ceo.is_representative)
        self.assertEqual(ceo.shares_held, 50000)
        # age derived from DOB 1965-04-01
        self.assertTrue(55 <= ceo.age <= 70)
        # representatives sort first
        self.assertEqual(mp.officers[0].name, ceo.name)

    def test_non_rep_flagged_correctly(self):
        mp = extract_officers(self.filing)
        director = next(o for o in mp.officers if "鈴木" in o.name)
        self.assertFalse(director.is_representative)

    def test_render(self):
        mp = build_profile(TICKER)
        md = render(mp, show_all=False)
        self.assertIn("Management — ", md)
        self.assertIn("Yamada Taro", md)          # English heading
        self.assertIn("⭐ (Representative)", md)
        self.assertIn("Shares held", md)


if __name__ == "__main__":
    unittest.main()
