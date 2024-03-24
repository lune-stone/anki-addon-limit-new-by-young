from aqt import mw, gui_hooks
from aqt.utils import qconnect
import aqt.qt as qt
from anki.utils import ids2str
from aqt.operations import QueryOp
from aqt.utils import tooltip

import math
import re
import sys
import threading
import time
from typing import Callable, NewType

DeckId = NewType("DeckId", int)

def ruleMapping() -> dict[DeckId, list[int]]:
    """returns the indices for matching rules where the first index is the one that determines the limits for the deck"""
    ret = {}

    addonConfig = mw.addonManager.getConfig(__name__)
    for deckIndentifer in mw.col.decks.all_names_and_ids(include_filtered=False):
        ret[deckIndentifer.id] = []
        for idx, limits in enumerate(addonConfig["limits"]):
                if (isinstance(limits["deckNames"], str) and re.compile(limits["deckNames"]).match(deckIndentifer.name)) \
                    or (isinstance(limits["deckNames"], list) and deckIndentifer.name in limits["deckNames"]):
                        ret[deckIndentifer.id].append(idx)

    return ret

# copy the dailyLoad calculation from https://github.com/open-spaced-repetition/fsrs4anki-helper/blob/19581d42a957285a8d949aea0564f81296a62b81/stats.py#L25
def dailyLoad(did: int) -> float:
    '''Takes in a number deck id, returns the estimated load in reviews per day'''
    subdeck_id = ids2str(mw.col.decks.deck_and_child_ids(did))
    return mw.col.db.first(
        f"""
    SELECT SUM(1.0 / max(1, ivl))
    FROM cards
    WHERE queue != 0 AND queue != -1
    AND did IN {subdeck_id}
    """
    )[0] or 0

def young(deckName: str) -> int:
    '''Takes in a number deck name prefix, returns the number of young cards excluding suspended'''
    return len(list(mw.col.find_cards(f'deck:"{deckName}" -is:learn is:review prop:ivl<21 -is:suspended')))

def updateLimits(hookEnabledConfigKey=None, forceUpdate=False) -> None:
    addonConfig = mw.addonManager.getConfig(__name__)
    today = mw.col.sched.today

    limitsChanged = 0

    if hookEnabledConfigKey and not addonConfig[hookEnabledConfigKey]:
        return

    if addonConfig.get('showNotifications', False):
        mw.taskman.run_on_main(lambda: tooltip('Updating limits...'))

    mapping = ruleMapping()

    for deckIndentifer in mw.col.decks.all_names_and_ids():
        matchingRulesIdxs = mapping.get(deckIndentifer.id, [])
        if not matchingRulesIdxs:
            continue

        addonConfigLimits = addonConfig["limits"][matchingRulesIdxs[0]]
        deck = mw.col.decks.get(deckIndentifer.id)

        limitAlreadySet = False if deck["newLimitToday"] is None else deck["newLimitToday"]["today"] == today

        if not forceUpdate and limitAlreadySet:
            continue

        deckConfig = mw.col.decks.config_dict_for_deck_id(deckIndentifer.id)
        deck_size = len(list(mw.col.find_cards(f'deck:"{deckIndentifer.name}" -is:suspended')))
        new_today = 0 if mw.col.sched.today != deck['newToday'][0] else deck['newToday'][1]

        youngCardLimit = addonConfigLimits.get('youngCardLimit', 999999999)
        youngCount = 0 if youngCardLimit > deck_size else young(deckIndentifer.name)

        loadLimit = addonConfigLimits.get('loadLimit', 999999999)
        load = 0.0 if loadLimit > deck_size else dailyLoad(deckIndentifer.id)

        maxNewCardsPerDay = deckConfig['new']['perDay']

        newLimit = max(0, min(maxNewCardsPerDay - new_today, youngCardLimit - youngCount, math.ceil(loadLimit - load))) + new_today

        if not(limitAlreadySet and deck["newLimitToday"]["limit"] == newLimit):
            deck["newLimitToday"] = {"limit": newLimit, "today": mw.col.sched.today}
            mw.col.decks.save(deck)
            limitsChanged += 1

    if limitsChanged > 0:
        def resetIfNeeded():
            if mw.state in ['deckBrowser', 'overview']:
                mw.reset()
        mw.taskman.run_on_main(resetIfNeeded)
    if addonConfig.get('showNotifications', False):
        mw.taskman.run_on_main(lambda: tooltip(f'Updated {limitsChanged} limits.'))

def textDialog(message: str) -> None:
    textEdit = qt.QPlainTextEdit(message)
    textEdit.setReadOnly(True)
    textEdit.setSizePolicy(qt.QSizePolicy.Policy.Expanding, qt.QSizePolicy.Policy.Expanding)

    layout = qt.QVBoxLayout()
    layout.addWidget(textEdit)

    dialog = qt.QDialog(mw)
    dialog.setGeometry(0, 0, 800, 800)
    dialog.setLayout(layout)
    dialog.show()

def ruleMappingReport() -> str:
    limits = mw.addonManager.getConfig(__name__)['limits']
    deckNames = {x.id: x.name for x in mw.col.decks.all_names_and_ids(include_filtered=False)}
    mapping = ruleMapping()

    lines = []
    for idx, limit in enumerate(limits):
        lines.append(f'rule #{idx + 1}: {str(limit)}')

        applies = [k for (k,v) in mapping.items() if v[0:1] == [idx]]
        matches = [k for (k,v) in mapping.items() if idx in v and k not in applies]

        lines.append('\tApplies to:')
        for name in sorted([deckNames[x] for x in applies]):
            lines.append(f'\t\t{name}')

        if matches:
            lines.append('\tMatches, but is already covered by an earlier rule:')
            for name, rule in sorted([(deckNames[x], mapping[x][0] + 1) for x in matches]):
                lines.append(f'\t\t{name} -> rule #{rule}')

        lines.append('')

    lines.append('not covered by any rules:')
    for name in sorted([deckNames[k] for (k,v) in mapping.items() if not v]):
        lines.append(f'\t{name}')

    return '\n'.join(lines)

def limitUtilizationReport() -> str:
    limits = mw.addonManager.getConfig(__name__)['limits']
    deckNames = {x.id: x.name for x in mw.col.decks.all_names_and_ids(include_filtered=False)}
    mapping = ruleMapping()

    lines = []

    lines.append('=== Young Limit ===')
    lines.append('')
    rows = []
    for did, deckName in sorted(deckNames.items(), key=lambda x: x[1]):
        youngCount = young(deckName)
        rule = {} if not mapping[did] else limits[mapping[did][0]]
        youngLimit = rule.get('youngCardLimit', float('inf'))

        rows.append(f"{100.0 * (youngCount / max(youngLimit, sys.float_info.epsilon)):.2f}% ({youngCount} of {youngLimit})\t{deckName}")
    rows.sort(key=lambda x: -1 * float(x.split('%')[0]))
    lines.extend(rows)

    lines.append('')
    lines.append('')

    lines.append('=== Daily Load Limit ===')
    lines.append('')
    rows = []
    for did, deckName in sorted(deckNames.items(), key=lambda x: x[1]):
        load = dailyLoad(did)
        rule = {} if not mapping[did] else limits[mapping[did][0]]
        loadLimit = float(rule.get('loadLimit', float('inf')))

        rows.append(f"{100.0 * (load / max(loadLimit, sys.float_info.epsilon)):.2f}% ({load:.2f} of {loadLimit})\t{deckName}")
    rows.sort(key=lambda x: -1 * float(x.split('%')[0]))
    lines.extend(rows)

    return '\n'.join(lines)

def execInBackground(func: Callable) -> Callable:
    return lambda: QueryOp(parent=mw, op=lambda col: func(), success=lambda *a, **k: None).run_in_background()

def updateLimitsOnIntervalLoop():
    while mw.state == 'startup':
        time.sleep(60) # wait for config to be accessible
    while True:
        addonConfig = mw.addonManager.getConfig(__name__)
        sleepInterval = max(60, addonConfig['updateLimitsIntervalTimeInMinutes'] * 60)
        time.sleep(sleepInterval)

        updateLimits(hookEnabledConfigKey='updateLimitsOnInterval')

updateLimitsOnIntervalThread = threading.Thread(target=updateLimitsOnIntervalLoop, daemon=True)
updateLimitsOnIntervalThread.start()

gui_hooks.main_window_did_init.append(execInBackground(lambda: updateLimits(hookEnabledConfigKey='updateLimitsOnApplicationStartup')))
gui_hooks.sync_did_finish.append(lambda: updateLimits(hookEnabledConfigKey='updateLimitsAfterSync'))

menu = qt.QMenu("Limit New by Young", mw)
mw.form.menuTools.addMenu(menu)

recalculate = qt.QAction("Recalculate today's new card limit for all decks", menu)
qconnect(recalculate.triggered, execInBackground(lambda: updateLimits(forceUpdate=True)))
menu.addAction(recalculate)

ruleMappingReportAction = qt.QAction("Show rule mapping report", menu)
qconnect(ruleMappingReportAction.triggered, lambda: textDialog(ruleMappingReport()))
menu.addAction(ruleMappingReportAction)

limitUtilizationReportAction = qt.QAction("Show limit utilization report", menu)
qconnect(limitUtilizationReportAction.triggered, lambda: textDialog(limitUtilizationReport()))
menu.addAction(limitUtilizationReportAction)
