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

def young(anki: Anki, deck_id: DeckId) -> int:
    '''returns the number of young cards excluding suspended'''
    did = re.sub('[()]', '', anki.get_subdeck_ids_csv(deck_id))
    return len(list(anki.col().find_cards(f'-is:new prop:ivl<21 -is:suspended did:{did}')))

def soon(anki: Anki, deck_id: DeckId, days: int) -> int:
    '''returns the number of cards about to be due excluding suspended'''
    did = re.sub('[()]', '', anki.get_subdeck_ids_csv(deck_id))
    return len(list(anki.col().find_cards(f'prop:due<{days} -is:suspended did:{did}')))

def cards(anki: Anki, deck_id: DeckId) -> int:
    '''returns the number of cards in the deck or it's subdecks'''
    did = re.sub('[()]', '', anki.get_subdeck_ids_csv(deck_id))
    return len(list(anki.col().find_cards(f'-is:suspended did:{did}')))

def seen(anki: Anki, deck_id: DeckId) -> int:
    '''returns the number of seen cards in the deck or it's subdecks'''
    did = re.sub('[()]', '', anki.get_subdeck_ids_csv(deck_id))
    return len(list(anki.col().find_cards(f'(is:learn OR is:review) -is:suspended did:{did}')))


def update_limits(anki: Anki, hook_enabled_config_key: str | None = None, force_update: bool = False) -> None:
    addon_config = anki.get_config()
    today = anki.col().sched.today

    limits_changed = 0

    if hook_enabled_config_key and not addon_config.get(hook_enabled_config_key, False):
        return

    if addon_config.get('showNotifications', False):
        anki.tooltip('Updating limits...')

    mapping = rule_mapping(anki)
    all_deck_identifiers = list(anki.get_deck_identifiers())

    # Group decks by their first-matching rule index
    rule_groups: dict[int, list] = {}
    for deck_ident in all_deck_identifiers:
        rule_indices = mapping.get(deck_ident.id, [])
        if not rule_indices:
            continue
        primary_rule_idx = rule_indices[0]
        rule_groups.setdefault(primary_rule_idx, []).append(deck_ident)

    for rule_idx, group_decks in rule_groups.items():
        addon_config_limits = addon_config["limits"][rule_idx]

        # Check if any deck in the group needs updating
        should_process = force_update or addon_config.get('recalculateLimitIfAlreadySet', False)
        if not should_process:
            for deck_ident in group_decks:
                deck = anki.get_deck_by_id(deck_ident.id)
                limit_already_set = False if deck["newLimitToday"] is None else deck["newLimitToday"]["today"] == today
                if not limit_already_set:
                    should_process = True
                    break

        if not should_process:
            continue

        # Compute collective metrics across all decks in the group
        total_deck_size = sum(cards(anki, d.id) for d in group_decks)

        young_card_limit = addon_config_limits.get('youngCardLimit', 999999999)
        total_young = 0 if young_card_limit > total_deck_size else sum(young(anki, d.id) for d in group_decks)

        load_limit = addon_config_limits.get('loadLimit', 999999999)
        total_load = 0.0 if load_limit > total_deck_size else sum(daily_load(anki, d.id) for d in group_decks)

        soon_days = addon_config_limits.get('soonDays', 7)
        soon_limit = addon_config_limits.get('soonLimit', 999999999)
        total_soon = 0 if soon_limit > total_deck_size else sum(soon(anki, d.id, soon_days) for d in group_decks)

        minimum = addon_config_limits.get('minimum', 0)

        # Collective budget: how many new cards the whole group can absorb
        # Can be negative when over limit — per-deck formula handles clamping to 0
        collective_budget = min(
            young_card_limit - total_young,
            math.ceil(load_limit - total_load),
            soon_limit - total_soon
        )

        # Distribute budget across decks (sorted by name for determinism)
        sorted_group = sorted(group_decks, key=lambda d: d.name)

        remaining = collective_budget
        for deck_ident in sorted_group:
            deck = anki.get_deck_by_id(deck_ident.id)
            deck_config = anki.config_dict_for_deck_id(deck_ident.id)
            max_new_cards_per_day = deck.get('newLimit') or deck_config['new']['perDay']
            new_today = 0 if today != deck['newToday'][0] else deck['newToday'][1]

            # Use remaining collective budget as this deck's effective config limit
            effective_config_limit = remaining

            # Apply the original per-deck formula with collective budget
            new_limit = max(0, minimum - new_today, min(max_new_cards_per_day - new_today, effective_config_limit) + new_today)

            # Deduct what this deck consumed from the collective budget
            consumed = max(0, new_limit - new_today)
            remaining -= min(consumed, remaining)

            limit_already_set = False if deck["newLimitToday"] is None else deck["newLimitToday"]["today"] == today
            if not(limit_already_set and deck["newLimitToday"]["limit"] == new_limit):
                deck["newLimitToday"] = {"limit": round(new_limit), "today": today}
                anki.save_deck(deck)
                limits_changed += 1

    if limits_changed > 0:
        anki.safe_reset()
    if addon_config.get('showNotifications', False):
        anki.tooltip(f'Updated {limits_changed} limits.')
