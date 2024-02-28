from aqt import mw, gui_hooks
from aqt.utils import qconnect
import aqt.qt as qt

import re
import sys
import threading
import time

# copy the burden calculation from https://github.com/open-spaced-repetition/fsrs4anki-helper/blob/6d6de3af7e8f3e0801cef1f562a48dbf80d69769/stats.py#L25
def deckBurden(did: int) -> int:
    '''Takes in a number deck id, returns the estimated burden in reviews per day'''
    return int(mw.col.db.first(
        f"""
    SELECT SUM(1.0 / max(1, ivl))
    FROM cards c1
    WHERE queue >= 1
    AND data != ''
    AND json_extract(data, '$.s') IS NOT NULL
    AND did = {str(did)}
    """
    )[0] or 0)

def updateLimits(hookEnabledConfigKey=None, forceUpdate=False) -> None:
    addonConfig = mw.addonManager.getConfig(__name__)
    today = mw.col.sched.today

    if hookEnabledConfigKey and not addonConfig[hookEnabledConfigKey]:
        return

    for deckIndentifer in mw.col.decks.all_names_and_ids():
        deck = mw.col.decks.get(deckIndentifer.id)
        if deck['dyn'] == 1:
            continue # ignore 'Custom Study Session' style decks

        addonConfigLimits = None
        for limits in addonConfig["limits"]:
            if (isinstance(limits["deckNames"], str) and re.compile(limits["deckNames"]).match(deckIndentifer.name)) \
                or (isinstance(limits["deckNames"], list) and deckIndentifer.name in limits["deckNames"]):
                    addonConfigLimits = limits
                    break

        if not addonConfigLimits:
            continue # no user defined limits to apply

        limitAlreadySet = False if deck["newLimitToday"] is None else deck["newLimitToday"]["today"] == today

        if not forceUpdate and limitAlreadySet:
            continue

        deckConfig = mw.col.decks.config_dict_for_deck_id(deckIndentifer.id)
        deck_size = len(list(mw.col.find_cards(f'deck:"{deckIndentifer.name}"')))

        youngCardLimit = addonConfigLimits.get('youngCardLimit', 999999999)
        youngCount = 0 if youngCardLimit > deck_size else len(list(mw.col.find_cards(f'deck:"{deckIndentifer.name}" prop:due<21 prop:ivl<21')))

        burdenLimit = addonConfigLimits.get('burdenLimit', 999999999)
        burden = 0 if burdenLimit > deck_size else deckBurden(deckIndentifer.id)

        maxNewCardsPerDay = deckConfig['new']['perDay']

        newLimit = max(0, min(maxNewCardsPerDay, youngCardLimit - youngCount, burdenLimit - burden))

        deck["newLimitToday"] = {"limit": newLimit, "today": mw.col.sched.today}
        mw.col.decks.save(deck)
        mw.reset()

def updateLimitsOnIntervalLoop():
    time.sleep(5 * 60) #HACK wait for anki to finish loading
    while True:
        addonConfig = mw.addonManager.getConfig(__name__)
        sleepInterval = max(60, addonConfig['updateLimitsIntervalTimeInMinutes'] * 60)
        time.sleep(sleepInterval)

        mw.taskman.run_on_main(lambda: updateLimits(hookEnabledConfigKey='updateLimitsOnInterval'))

updateLimitsOnIntervalThread = threading.Thread(target=updateLimitsOnIntervalLoop, daemon=True)
updateLimitsOnIntervalThread.start()

gui_hooks.main_window_did_init.append(lambda: updateLimits(hookEnabledConfigKey='updateLimitsOnApplicationStartup'))
gui_hooks.sync_did_finish.append(lambda: updateLimits(hookEnabledConfigKey='updateLimitsAfterSync'))

action = qt.QAction("Recalculate today's new card limit for all decks", mw)
qconnect(action.triggered, lambda: updateLimits(forceUpdate=True))
mw.form.menuTools.addAction(action)
