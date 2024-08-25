from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anki.decks import DeckId

    from .anki_api import AnkiApi as Anki


def rule_mapping(anki: Anki) -> dict[DeckId, list[int]]:
    """returns the indices for matching rules where the first index is the one that determines the limits for the deck"""
    ret: dict[DeckId, list[int]] = {}

    addon_config = anki.get_config()
    for deck_indentifer in anki.get_deck_identifiers():
        ret[deck_indentifer.id] = []
        for idx, limits in enumerate(addon_config["limits"]):
                if (isinstance(limits["deckNames"], str) and re.compile(limits["deckNames"]).match(deck_indentifer.name)) \
                    or (isinstance(limits["deckNames"], list) and deck_indentifer.name in limits["deckNames"]):
                        ret[deck_indentifer.id].append(idx)

    return ret

# copy the dailyLoad calculation from https://github.com/open-spaced-repetition/fsrs4anki-helper/blob/19581d42a957285a8d949aea0564f81296a62b81/stats.py#L25
def daily_load(anki: Anki, did: DeckId) -> float:
    '''Takes in a number deck id, returns the estimated load in reviews per day'''
    return (anki.db().first(
        f"""
    SELECT SUM(1.0 / max(1, ivl))
    FROM cards
    WHERE queue != -1 -- not suspended
    AND did IN {anki.get_subdeck_ids_csv(did)}
    AND type != 0 -- not new
    """
    ) or [0])[0] or 0

def young(anki: Anki, deck_name: str) -> int:
    '''Takes in a number deck name prefix, returns the number of young cards excluding suspended'''
    return len(list(anki.col().find_cards(f'deck:"{deck_name}" -is:new prop:ivl<21 -is:suspended')))

def soon(anki: Anki, deck_name: str, days: int) -> int:
    '''returns the number of cards about to be due excluding suspended'''
    return len(list(anki.col().find_cards(f'deck:"{deck_name}" prop:due<{days} -is:suspended')))

def update_limits(anki: Anki, hook_enabled_config_key: str | None = None, force_update: bool = False) -> None:
    addon_config = anki.get_config()
    today = anki.col().sched.today

    limits_changed = 0

    if hook_enabled_config_key and not addon_config[hook_enabled_config_key]:
        return

    if addon_config.get('showNotifications', False):
        anki.tooltip('Updating limits...')

    mapping = rule_mapping(anki)

    for deck_indentifer in anki.get_deck_identifiers():
        matching_rules_idxs = mapping.get(deck_indentifer.id, [])
        if not matching_rules_idxs:
            continue

        addon_config_limits = addon_config["limits"][matching_rules_idxs[0]]
        deck = anki.get_deck_by_id(deck_indentifer.id)

        limit_already_set = False if deck["newLimitToday"] is None else deck["newLimitToday"]["today"] == today

        if not force_update and limit_already_set:
            continue

        deck_config = anki.config_dict_for_deck_id(deck_indentifer.id)
        deck_size = len(list(anki.col().find_cards(f'deck:"{deck_indentifer.name}" -is:suspended')))
        new_today = 0 if today != deck['newToday'][0] else deck['newToday'][1]

        young_card_limit = addon_config_limits.get('youngCardLimit', 999999999)
        young_count = 0 if young_card_limit > deck_size else young(anki, deck_indentifer.name)

        load_limit = addon_config_limits.get('loadLimit', 999999999)
        load = 0.0 if load_limit > deck_size else daily_load(anki, deck_indentifer.id)

        soon_days = addon_config_limits.get('soonDays', 7)
        soon_limit = addon_config_limits.get('soonLimit', 999999999)
        soon_count = 0 if soon_limit > deck_size else soon(anki, deck_indentifer.name, soon_days)

        minimum = addon_config_limits.get('minimum', 0)

        max_new_cards_per_day = deck.get('newLimit') or deck_config['new']['perDay']

        effective_config_limit = min(young_card_limit - young_count, math.ceil(load_limit - load), soon_limit - soon_count)
        new_limit = max(0, minimum - new_today, min(max_new_cards_per_day - new_today, effective_config_limit) + new_today)

        if not(limit_already_set and deck["newLimitToday"]["limit"] == new_limit):
            deck["newLimitToday"] = {"limit": new_limit, "today": today}
            anki.save_deck(deck)
            limits_changed += 1

    if limits_changed > 0:
        anki.safe_reset()
    if addon_config.get('showNotifications', False):
        anki.tooltip(f'Updated {limits_changed} limits.')
