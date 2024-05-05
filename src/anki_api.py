from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Self, Sequence

import aqt
from anki.utils import ids2str
from aqt.utils import tooltip

if TYPE_CHECKING:
    from anki.collection import Collection
    from anki.dbproxy import DBProxy
    from anki.decks import DeckConfigDict, DeckDict, DeckId, DeckNameId
    from aqt import AnkiQt



class AnkiApi:
    def __init__(self: Self, module_name: str) -> None:
        self._module_name = module_name

    def _mw(self: Self) -> AnkiQt:
        return aqt.mw # type: ignore[return-value]

    def get_config(self: Self) -> dict[str, Any]:
        return self._mw().addonManager.getConfig(self._module_name) or dict()

    def write_config(self: Self, config: dict[str, Any]) -> None:
        self._mw().addonManager.writeConfig(self._module_name, config)

    def get_deck_identifiers(self: Self) -> Sequence[DeckNameId]:
        return self._mw().col.decks.all_names_and_ids(include_filtered=False)

    def get_subdeck_ids_csv(self: Self, deck_id: DeckId) -> str:
        return ids2str(self._mw().col.decks.deck_and_child_ids(deck_id))

    def get_deck_by_id(self: Self, deck_id: DeckId) -> DeckDict:
        return self._mw().col.decks.get(deck_id) or dict()

    def save_deck(self: Self, deck: DeckDict) -> None:
        self._mw().col.decks.save(deck)

    def config_dict_for_deck_id(self: Self, deck_id: DeckId) -> DeckConfigDict:
        return self._mw().col.decks.config_dict_for_deck_id(deck_id)

    def col(self: Self) -> Collection:
        return self._mw().col

    def db(self: Self) -> DBProxy:
        return self._mw().col.db # type: ignore[return-value]

    def run_on_main(self: Self, func: Callable) -> None:
        return self._mw().taskman.run_on_main(func)

    def is_ready(self: Self) -> bool:
        return self._mw().state != 'startup'

    def safe_reset(self: Self) -> None:
        def reset_if_needed() -> None:
            if self._mw().state in ['deckBrowser', 'overview']:
                self._mw().reset()
        self.run_on_main(reset_if_needed)

    def tooltip(self: Self, msg: str) -> None:
        self.run_on_main(lambda: tooltip(msg))
