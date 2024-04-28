from __future__ import annotations

import dataclasses
import math
import re
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable, NewType

import aqt.qt as qt
from anki.utils import ids2str
from aqt import gui_hooks, mw
from aqt.operations import QueryOp
from aqt.utils import openLink, qconnect, tooltip

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
    WHERE queue != -1 -- not suspended
    AND did IN {subdeck_id}
    AND type != 0 -- not new
    """
    )[0] or 0

def young(deckName: str) -> int:
    '''Takes in a number deck name prefix, returns the number of young cards excluding suspended'''
    return len(list(mw.col.find_cards(f'deck:"{deckName}" -is:new prop:ivl<21 -is:suspended')))

def soon(deckName: str, days: int) -> int:
    '''returns the number of cards about to be due excluding suspended'''
    return len(list(mw.col.find_cards(f'deck:"{deckName}" prop:due<{days} -is:suspended')))

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

        soonDays = addonConfigLimits.get('soonDays', 7)
        soonLimit = addonConfigLimits.get('soonLimit', 999999999)
        soonCount = 0 if soonLimit > deck_size else soon(deckIndentifer.name, soonDays)

        maxNewCardsPerDay = deckConfig['new']['perDay']

        newLimit = max(0, min(maxNewCardsPerDay - new_today, youngCardLimit - youngCount, math.ceil(loadLimit - load), soonLimit - soonCount) + new_today)

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

def textDialog(message: str, title: str) -> None:
    textEdit = qt.QPlainTextEdit(message)
    textEdit.setReadOnly(True)
    textEdit.setSizePolicy(qt.QSizePolicy.Policy.Expanding, qt.QSizePolicy.Policy.Expanding)

    layout = qt.QVBoxLayout()
    layout.addWidget(textEdit)

    dialog = qt.QDialog(mw)
    dialog.setWindowTitle(title)
    dialog.setGeometry(0, 0, 800, 800)
    dialog.setLayout(layout)
    dialog.show()

def utilizationDialog() -> None:
    data = limitUtilizationReportData()
    uiConfig = mw.addonManager.getConfig(__name__).get('utilizationReport', {})

    textEdit = qt.QPlainTextEdit("")
    textEdit.setReadOnly(True)
    textEdit.setSizePolicy(qt.QSizePolicy.Policy.Expanding, qt.QSizePolicy.Policy.Expanding)

    checkboxes = {
        'empty': qt.QCheckBox("Empty"),
        'noLimit': qt.QCheckBox("No defined limit"),
        'notStarted': qt.QCheckBox("Not started"),
        'complete': qt.QCheckBox("Complete"),
        'overLimit': qt.QCheckBox("Over limit"),
        'underLimit': qt.QCheckBox("Under limit"),
        'subDeck': qt.QCheckBox("Sub deck")
    }

    detailLevel = qt.QComboBox()
    detailLevel.addItem('Summary')
    detailLevel.addItem('Verbose')

    filters = qt.QHBoxLayout()
    filters.addWidget(detailLevel)

    layout = qt.QVBoxLayout()
    layout.addLayout(filters)
    layout.addWidget(textEdit)

    dialog = qt.QDialog(mw)
    dialog.setWindowTitle('Limit Utilization Report')
    dialog.setGeometry(0, 0, 800, 800)
    dialog.setLayout(layout)

    def saveConfig():
        config = mw.addonManager.getConfig(__name__)
        if not config.get('rememberLastUiSettings', True):
            return
        config['utilizationReport'] = {
                "detailLevel": detailLevel.currentText(),
                "empty": checkboxes['empty'].isChecked(),
                "noLimit": checkboxes['noLimit'].isChecked(),
                "notStarted": checkboxes['notStarted'].isChecked(),
                "complete": checkboxes['complete'].isChecked(),
                "overLimit": checkboxes['overLimit'].isChecked(),
                "underLimit": checkboxes['underLimit'].isChecked(),
                "subDeck": checkboxes['subDeck'].isChecked()
            }
        mw.addonManager.writeConfig(__name__, config)

    def render():
        d = [x for x in data]
        d = [x for x in d if checkboxes['empty'].isChecked() or x.deckSize > 0]
        d = [x for x in d if checkboxes['noLimit'].isChecked() or x.deckHasLimits]
        d = [x for x in d if checkboxes['notStarted'].isChecked() or x.learned > 0]
        d = [x for x in d if checkboxes['complete'].isChecked() or x.learned < x.deckSize]
        d = [x for x in d if checkboxes['overLimit'].isChecked() or x.value < x.limit]
        d = [x for x in d if checkboxes['underLimit'].isChecked() or x.value >= x.limit]
        d = [x for x in d if checkboxes['subDeck'].isChecked() or '::' not in x.deckName]

        lines = []

        if detailLevel.currentText() == 'Summary':
            lines.append('=== Limit Summary ===')
            lines.append('')
            lines.extend([str(x) for x in d if x.detailLevel == 'Summary'])
        else:
            lines.append('=== Young Limit ===')
            lines.append('')
            lines.extend([str(x) for x in d if x.limitType == 'youngCardLimit' and x.detailLevel == 'Verbose'])

            lines.append('')
            lines.append('')

            lines.append('=== Daily Load Limit ===')
            lines.append('')
            lines.extend([str(x) for x in d if x.limitType == 'loadLimit' and x.detailLevel == 'Verbose'])

            lines.append('')
            lines.append('')

            lines.append('=== Soon Limit ===')
            lines.append('')
            lines.extend([str(x) for x in d if x.limitType == 'soonLimit' and x.detailLevel == 'Verbose'])

        message = '\n'.join(lines)
        textEdit.setPlainText(message)

    for configName, checkBox in checkboxes.items():
        filters.addWidget(checkBox)
        checkBox.setChecked(bool(uiConfig.get(configName, True)))
        checkBox.stateChanged.connect(render)
        checkBox.stateChanged.connect(saveConfig)
    detailLevel.setCurrentText(uiConfig.get('detailLevel', 'Verbose'))
    detailLevel.activated.connect(render)
    detailLevel.activated.connect(saveConfig)

    render()
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

@dataclass(order=True)
class UtilizationRow:
    displayOrdinal: (float, float, float)
    summaryOrdinal: (float, int, float, float)
    utilization: float
    value: int | float
    limit: int | float
    detailLevel: str
    limitType: str
    ###
    deckId: int
    deckName: str
    deckSize: int
    learned: int
    deckHasLimits: bool

    def __str__(self):
        utilization = f'{min(9999.99, self.utilization):.2f}'
        value = f'{self.value:.2f}' if isinstance(self.value, float) else self.value
        limit = '∞' if self.limit == float('inf') else self.limit
        limit = f'{limit:.2f}' if isinstance(limit, float) else limit
        limitType = '' if self.detailLevel == 'Verbose' else f'\t[{self.limitType}]'
        limitType = re.sub('[A-Z][a-zA-Z]*', '', limitType) # `young, soon, load` rather than `youngCardLimit, ...`
        return f'{utilization}% ({value} of {limit}){limitType}\t{self.deckName}'

def limitUtilizationReportData() -> [UtilizationRow]:
    limits = mw.addonManager.getConfig(__name__)['limits']
    deckNames = {x.id: x.name for x in mw.col.decks.all_names_and_ids(include_filtered=False)}
    mapping = ruleMapping()

    def utilizationForLimit(limitConfigKey, deckIndentiferLimitFunc):
        rows = []
        for did, deckName in sorted(deckNames.items(), key=lambda x: x[1]):
            deckIndentifer = {'id': did, 'name': deckName}
            rule = {} if not mapping[did] else limits[mapping[did][0]]
            limit = rule.get(limitConfigKey, float('inf'))
            value = deckIndentiferLimitFunc(deckIndentifer, rule)
            utilization = 100.0 * (value / max(limit, sys.float_info.epsilon))
            deckSize = len(list(mw.col.find_cards(f'deck:"{deckName}" -is:suspended')))
            learned = len(list(mw.col.find_cards(f'deck:"{deckName}" (is:learn OR is:review) -is:suspended')))
            deckHasLimits = not math.isinf(limit)
            reportOrdinal = (-utilization, -value, limit, deckName)
            summaryOrdinal = (-utilization, 0 if deckHasLimits else 1, -value, limit, deckName) # prefer decks with defined limit should they all have 0 utilization

            row = UtilizationRow(reportOrdinal, summaryOrdinal, utilization, value, limit, 'Verbose', limitConfigKey, did, deckName, deckSize, learned, deckHasLimits)
            rows.append(row)
        return rows

    ret = []
    ret.extend(utilizationForLimit('youngCardLimit', lambda deckIndentifer, rule: young(deckIndentifer['name'])))
    ret.extend(utilizationForLimit('loadLimit', lambda deckIndentifer, rule: dailyLoad(deckIndentifer['id'])))
    ret.extend(utilizationForLimit('soonLimit', lambda deckIndentifer, rule: soon(deckIndentifer['name'], rule.get('soonDays', 7))))
    ret.sort()

    summary = {}
    for row in sorted(ret, key=lambda x: x.summaryOrdinal):
        deck_rows = summary.get(row.deckId, [])
        row = dataclasses.replace(row)
        row.detailLevel = 'Summary'
        row.deckHasLimits = len([x for x in ret if x.deckId == row.deckId and x.deckHasLimits]) > 0
        deck_rows.append(row)
        summary[row.deckId] = deck_rows
    summary = sorted([x[0] for x in summary.values()])
    ret.extend(summary)

    return ret

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
qconnect(ruleMappingReportAction.triggered, lambda: textDialog(ruleMappingReport(), 'Rule Mapping Report'))
menu.addAction(ruleMappingReportAction)

limitUtilizationReportAction = qt.QAction("Show limit utilization report", menu)
qconnect(limitUtilizationReportAction.triggered, lambda: utilizationDialog())
menu.addAction(limitUtilizationReportAction)

documentationAction = qt.QAction("Documentation", menu)
qconnect(documentationAction.triggered, lambda: openLink('https://github.com/lune-stone/anki-addon-limit-new-by-young'))
menu.addAction(documentationAction)

reportBugAction = qt.QAction("Report a bug", menu)
qconnect(reportBugAction.triggered, lambda: openLink('https://github.com/lune-stone/anki-addon-limit-new-by-young/issues'))
menu.addAction(reportBugAction)
