#!/bin/env python3

import os
import sys

from PyQt6.QtWebEngineWidgets import *
from PyQt6.QtWidgets import QApplication

os.environ["TEST"] = "True"
app = QApplication(sys.argv)

import re
import unittest
from types import SimpleNamespace
from typing import Any, Self

from src.limit import update_limits
from src.report import limit_utilization_report_data

def create_mock_limit(deck_names: list[str], young: int | None = None, load: float | None = None, soon: int | None = None, soon_days: int | None = None, minimum: int | None = None) -> dict[str, Any]:
    ret = {'deckNames': deck_names}
    if young:
        ret['youngCardLimit'] = young
    if load:
        ret['loadLimit'] = load
    if soon:
        ret['soonLimit'] = soon
    if soon_days:
        ret['soonDays'] = soon_days
    if minimum:
        ret['minimum'] = minimum
    return ret

def create_mock_deck(id: int, name: str, cards: int, young: int, load: float, soon: int, new: int, new_limit: int, max_new: int, deck_max_new: int | None = None) -> dict[str, Any]:
    return {'id': id, 'name': name, 'cards': cards, 'young': young, 'load': load, 'soon': soon, 'newToday': [0, 0] if not new else [0, new], 'newLimitToday': None if not new_limit else {'today': 0, 'limit': new_limit}, 'new': {'perDay': max_new }, 'newLimit': deck_max_new}

def create_mock_anki(limits, decks):
    class MockAnki:

        def get_config(self):
            return {'limits': limits}

        def write_config(self, config):
            pass

        def get_deck_identifiers(self):
            return [SimpleNamespace(id=x['id'], name=x['name']) for x in decks]

        def get_subdeck_ids_csv(self, deck_id):
            return str(deck_id)

        def get_deck_by_id(self, deck_id):
            return next(x for x in decks if x['id'] == deck_id)

        def save_deck(self, deck) -> None:
            pass

        def config_dict_for_deck_id(self, deck_id):
            return next(x for x in decks if x['id'] == deck_id)

        def col(self):
            def f(search):
                deck_id = int(re.sub('.*did:([0-9]*).*', '\\1', search))
                deck = [x for x in decks if x['id'] == deck_id][0]
                if 'prop:ivl<21' in search:
                    return list(range(deck['young']))
                if 'prop:due<' in search:
                    return list(range(deck['soon']))
                return list(range(deck['cards']))
            return SimpleNamespace(sched =  SimpleNamespace(today= 0), find_cards=f)

        def db(self):
            def f(search):
                did = [x for x in search.split('\n') if 'did IN' in x][0]
                return [decks[0]['load']]
            return SimpleNamespace(first = f)

        def safe_reset(self):
            pass

    return MockAnki()

class Test(unittest.TestCase):

    def test_young_limit(self: Self) -> None:
        deck_under_limit = create_mock_deck(id=1, name='A', cards=1000, young=0, load=None, soon=None, new=None, new_limit=None, max_new=10)
        deck_near_limit = create_mock_deck(id=2, name='B', cards=1000, young=3, load=None, soon=None, new=None, new_limit=None, max_new=10)
        deck_over_limit = create_mock_deck(id=3, name='C', cards=1000, young=20, load=None, soon=None, new=None, new_limit=None, max_new=10)
        # Each deck has its own rule for independent per-deck limiting
        limit_a = create_mock_limit(deck_names=['A'], young=5)
        limit_b = create_mock_limit(deck_names=['B'], young=5)
        limit_c = create_mock_limit(deck_names=['C'], young=5)
        anki = create_mock_anki([limit_a, limit_b, limit_c], [deck_under_limit, deck_near_limit, deck_over_limit])

        update_limits(anki, force_update=True)

        self.assertEqual(5, deck_under_limit['newLimitToday']['limit'], 'young_card_limit - young_count = 5 - 0 = 5')
        self.assertEqual(2, deck_near_limit['newLimitToday']['limit'], 'young_card_limit - young_count = 5 - 3 = 2')
        self.assertEqual(0, deck_over_limit['newLimitToday']['limit'], 'young_card_limit - young_count = 20 - 3 < 0 ')

    def test_fractional_load_limits(self: Self) -> None:
        deck = create_mock_deck(id=1, name='A', cards=1000, young=0, load=10.2, soon=0, new=0, new_limit=None, max_new=10)
        limit = create_mock_limit(deck_names=['A'], young=None, load=15.1)
        anki = create_mock_anki([limit], [deck])

        update_limits(anki, force_update=True)

        self.assertEqual(5, deck['newLimitToday']['limit'], 'load_limit - load = ceil(15.1 - 10.2) = 5')

    def test_multiple_limits(self: Self) -> None:
        deck = create_mock_deck(id=1, name='A', cards=1000, young=3, load=10.2, soon=4, new=0, new_limit=None, max_new=10)
        limit = create_mock_limit(deck_names=['A'], young=5, load=15.1, soon=5)
        anki = create_mock_anki([limit], [deck])

        update_limits(anki, force_update=True)

        self.assertEqual(1, deck['newLimitToday']['limit'], 'min(limit - value) = soon_limit - soon = 5 - 4 = 1')

    def test_deck_has_new(self: Self) -> None:
        deck = create_mock_deck(id=1, name='A', cards=1000, young=3, load=None, soon=None, new=1, new_limit=None, max_new=10)
        limit = create_mock_limit(deck_names=['A'], young=5)
        anki = create_mock_anki([limit], [deck])

        update_limits(anki, force_update=True)

        self.assertEqual(3, deck['newLimitToday']['limit'], 'young_card_limit - young_count + new = 5 - 3 + 1 = 3')

    def test_deck_has_custom_study(self: Self) -> None:
        deck = create_mock_deck(id=1, name='A', cards=1000, young=3, load=None, soon=None, new=-1, new_limit=None, max_new=10)
        limit = create_mock_limit(deck_names=['A'], young=5)
        anki = create_mock_anki([limit], [deck])

        update_limits(anki, force_update=True)

        # Anki will adjusts new to handle custom study which then is considered while applying the limits on
        # new cards, meaning that the value we pick as the day's limit before the adjustments needs to be
        # reduced to have the effective limit reach the original target.
        self.assertEqual(1, deck['newLimitToday']['limit'], 'young_card_limit - young_count + new = 5 - 3 - 1 = 1')

    def test_report_summary(self: Self) -> None:
        deck = create_mock_deck(id=1, name='A', cards=1000, young=3, load=10.2, soon=4, new=0, new_limit=None, max_new=10)
        limit = create_mock_limit(deck_names=['A'], young=5, load=15.1, soon=5)
        anki = create_mock_anki([limit], [deck])
        data = limit_utilization_report_data(anki)
        summary = [x for x in data if x.detail_level == 'Summary'][0]
        self.assertEqual('soonLimit', summary.limit_type, 'should be the most restrictive limit')

    def test_report_summary_with_zero_utilization(self: Self) -> None:
        deck = create_mock_deck(id=1, name='A', cards=1000, young=0, load=0.19, soon=2, new=0, new_limit=None, max_new=10)
        limit = create_mock_limit(deck_names=['A'], young=50)
        anki = create_mock_anki([limit], [deck])
        data = limit_utilization_report_data(anki)
        summary = [x for x in data if x.detail_level == 'Summary'][0]
        self.assertEqual('youngCardLimit', summary.limit_type, 'should not pick an undefined limit type, even if the value is higher')

    def test_minimum_limit(self: Self) -> None:
        deck = create_mock_deck(id=1, name='A', cards=1000, young=5, load=10.2, soon=0, new=0, new_limit=None, max_new=10)
        limit = create_mock_limit(deck_names=['A'], young=6, minimum=2)
        anki = create_mock_anki([limit], [deck])
        update_limits(anki, force_update=True)
        self.assertEqual(2, deck['newLimitToday']['limit'], 'max(young_card_limit - young_count, minimum) = max(6 - 5, 2) = 2')
        
        deck = create_mock_deck(id=1, name='A', cards=1000, young=0, load=10.2, soon=0, new=0, new_limit=None, max_new=10)
        anki = create_mock_anki([limit], [deck])
        update_limits(anki, force_update=True)
        self.assertEqual(6, deck['newLimitToday']['limit'], 'max(young_card_limit - young_count, minimum) = max(6 - 0, 2) = 6')
        
        deck = create_mock_deck(id=1, name='A', cards=1000, young=7, load=10.2, soon=0, new=1, new_limit=1, max_new=10)
        limit = create_mock_limit(deck_names=['A'], young=6, minimum=1)
        anki = create_mock_anki([limit], [deck])
        update_limits(anki, force_update=True)
        self.assertEqual(0, deck['newLimitToday']['limit'], 'minimum only counts before reviews')

    def test_this_deck_config(self: Self) -> None:
        deck = create_mock_deck(id=1, name='A', cards=1000, young=0, load=None, soon=None, new=None, new_limit=None, max_new=0, deck_max_new=5)
        limit = create_mock_limit(deck_names=['A'], young=10)
        anki = create_mock_anki([limit], [deck])
        update_limits(anki, force_update=True)
        self.assertEqual(5, deck['newLimitToday']['limit'], 'max new should match "this deck" over "preset" when defined')

    def test_floating_point_limits_persisted_as_integers(self: Self) -> None:
        # Each deck gets its own rule to test per-deck rounding behavior
        soon_limit = create_mock_deck(id=1, name='A', cards=1000, young=0, load=0.0, soon=100, new=None, new_limit=None, max_new=10)
        young_limit = create_mock_deck(id=2, name='B', cards=1000, young=100, load=0.0, soon=0, new=None, new_limit=None, max_new=10)
        limit_a = create_mock_limit(deck_names=['A'], young=105.2, soon=105.2)
        limit_b = create_mock_limit(deck_names=['B'], young=105.2, soon=105.2)
        anki = create_mock_anki([limit_a, limit_b], [soon_limit, young_limit])

        update_limits(anki, force_update=True)

        self.assertEqual(5, soon_limit['newLimitToday']['limit'], 'soon_limit: 105.2 - 100 == 5 (not 5.2)')
        self.assertEqual(5, young_limit['newLimitToday']['limit'], 'young_limit: 105.2 - 100 == 5 (not 5.2)')

    # === Collective limit tests ===

    def test_collective_young_limit(self: Self) -> None:
        """Multiple decks in one rule: young cards are summed collectively"""
        deck_a = create_mock_deck(id=1, name='A', cards=1000, young=20, load=None, soon=None, new=None, new_limit=None, max_new=10)
        deck_b = create_mock_deck(id=2, name='B', cards=1000, young=15, load=None, soon=None, new=None, new_limit=None, max_new=10)
        deck_c = create_mock_deck(id=3, name='C', cards=1000, young=10, load=None, soon=None, new=None, new_limit=None, max_new=10)
        limit = create_mock_limit(deck_names=['A', 'B', 'C'], young=50)
        anki = create_mock_anki([limit], [deck_a, deck_b, deck_c])

        update_limits(anki, force_update=True)

        # total young = 20+15+10 = 45, budget = 50-45 = 5
        # A gets min(5, 10) = 5, remaining = 0
        # B gets 0, C gets 0
        total_new = deck_a['newLimitToday']['limit'] + deck_b['newLimitToday']['limit'] + deck_c['newLimitToday']['limit']
        self.assertEqual(5, total_new, 'collective budget should be 50 - 45 = 5 total new cards')
        self.assertEqual(5, deck_a['newLimitToday']['limit'], 'A gets the budget first (alphabetical)')
        self.assertEqual(0, deck_b['newLimitToday']['limit'], 'B gets remaining = 0')
        self.assertEqual(0, deck_c['newLimitToday']['limit'], 'C gets remaining = 0')

    def test_collective_single_eligible_deck(self: Self) -> None:
        """Only one deck has non-zero native limit, so it gets the full collective budget"""
        deck_a = create_mock_deck(id=1, name='A', cards=1000, young=10, load=None, soon=None, new=None, new_limit=None, max_new=0)
        deck_b = create_mock_deck(id=2, name='B', cards=1000, young=10, load=None, soon=None, new=None, new_limit=None, max_new=0)
        deck_c = create_mock_deck(id=3, name='C', cards=1000, young=10, load=None, soon=None, new=None, new_limit=None, max_new=20)
        limit = create_mock_limit(deck_names=['A', 'B', 'C'], young=50)
        anki = create_mock_anki([limit], [deck_a, deck_b, deck_c])

        update_limits(anki, force_update=True)

        # total young = 30, budget = 50-30 = 20
        # A: native limit=0, gets 0; B: native limit=0, gets 0; C: native limit=20, gets min(20, 20) = 20
        self.assertEqual(0, deck_a['newLimitToday']['limit'], 'A has native limit 0')
        self.assertEqual(0, deck_b['newLimitToday']['limit'], 'B has native limit 0')
        self.assertEqual(20, deck_c['newLimitToday']['limit'], 'C gets the full collective budget')

    def test_collective_over_limit(self: Self) -> None:
        """When total young exceeds collective limit, all decks get 0"""
        deck_a = create_mock_deck(id=1, name='A', cards=1000, young=30, load=None, soon=None, new=None, new_limit=None, max_new=10)
        deck_b = create_mock_deck(id=2, name='B', cards=1000, young=25, load=None, soon=None, new=None, new_limit=None, max_new=10)
        limit = create_mock_limit(deck_names=['A', 'B'], young=50)
        anki = create_mock_anki([limit], [deck_a, deck_b])

        update_limits(anki, force_update=True)

        # total young = 55 > 50, budget = 0
        self.assertEqual(0, deck_a['newLimitToday']['limit'], 'over collective limit, no new cards')
        self.assertEqual(0, deck_b['newLimitToday']['limit'], 'over collective limit, no new cards')

    def test_collective_with_minimum(self: Self) -> None:
        """Minimum is respected per-deck as a floor, can exceed collective budget"""
        deck_a = create_mock_deck(id=1, name='A', cards=1000, young=15, load=None, soon=None, new=0, new_limit=None, max_new=10)
        deck_b = create_mock_deck(id=2, name='B', cards=1000, young=15, load=None, soon=None, new=0, new_limit=None, max_new=10)
        limit = create_mock_limit(deck_names=['A', 'B'], young=33, minimum=2)
        anki = create_mock_anki([limit], [deck_a, deck_b])

        update_limits(anki, force_update=True)

        # total young = 30, budget = 33-30 = 3
        # A: demand=10, allocation=min(3, 10)=3, min_needed=2, 3 >= 2 so no bump
        # A gets 3, remaining = 0
        # B: demand=10, allocation=min(0, 10)=0, min_needed=2, 2 > 0 and 10 >= 2 → bumped to 2
        # B gets 2 (minimum overrides exhausted budget, matching original minimum behavior)
        self.assertEqual(3, deck_a['newLimitToday']['limit'], 'A gets 3 from collective budget')
        self.assertEqual(2, deck_b['newLimitToday']['limit'], 'B gets minimum=2 even though budget exhausted')

    def test_wildcard_and_case_insensitive_matching(self: Self) -> None:
        """Test that matching supports case-insensitivity and converts intuitive wildcards"""
        deck_exact = create_mock_deck(id=1, name='German Verbs', cards=1000, young=10, load=None, soon=None, new=0, new_limit=None, max_new=10)
        deck_wildcard = create_mock_deck(id=2, name='My german deck', cards=1000, young=10, load=None, soon=None, new=0, new_limit=None, max_new=10)
        deck_nomatch = create_mock_deck(id=3, name='French Verbs', cards=1000, young=10, load=None, soon=None, new=0, new_limit=None, max_new=10)
        
        # Test 1: case-insensitive list matching
        limit_list = create_mock_limit(deck_names=['german verbs'], young=50)
        anki_list = create_mock_anki([limit_list], [deck_exact])
        # Force rule mapping generation
        from src.limit import rule_mapping
        mapping_list = rule_mapping(anki_list)
        self.assertEqual([0], mapping_list.get(deck_exact['id']), "Should match case-insensitive list")
        
        # Test 2: intuitive wildcard (*german*) converting to regex (.*german.*) and matching case-insensitively
        limit_wildcard = create_mock_limit(deck_names='*german*', young=50)
        anki_wildcard = create_mock_anki([limit_wildcard], [deck_exact, deck_wildcard, deck_nomatch])
        mapping_wildcard = rule_mapping(anki_wildcard)
        
        self.assertEqual([0], mapping_wildcard.get(deck_exact['id']), "Should match 'German Verbs' with '*german*'")
        self.assertEqual([0], mapping_wildcard.get(deck_wildcard['id']), "Should match 'My german deck' with '*german*'")
        self.assertEqual([], mapping_wildcard.get(deck_nomatch['id']), "Should not match 'French Verbs'")

if __name__ == '__main__':
    unittest.main()
