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

def rule_mapping() -> dict[DeckId, list[int]]:
    """returns the indices for matching rules where the first index is the one that determines the limits for the deck"""
    ret = {}

    addon_config = mw.addonManager.getConfig(__name__)
    for deck_indentifer in mw.col.decks.all_names_and_ids(include_filtered=False):
        ret[deck_indentifer.id] = []
        for idx, limits in enumerate(addon_config["limits"]):
                if (isinstance(limits["deckNames"], str) and re.compile(limits["deckNames"]).match(deck_indentifer.name)) \
                    or (isinstance(limits["deckNames"], list) and deck_indentifer.name in limits["deckNames"]):
                        ret[deck_indentifer.id].append(idx)

    return ret

# copy the dailyLoad calculation from https://github.com/open-spaced-repetition/fsrs4anki-helper/blob/19581d42a957285a8d949aea0564f81296a62b81/stats.py#L25
def daily_load(did: int) -> float:
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

def young(deck_name: str) -> int:
    '''Takes in a number deck name prefix, returns the number of young cards excluding suspended'''
    return len(list(mw.col.find_cards(f'deck:"{deck_name}" -is:new prop:ivl<21 -is:suspended')))

def soon(deck_name: str, days: int) -> int:
    '''returns the number of cards about to be due excluding suspended'''
    return len(list(mw.col.find_cards(f'deck:"{deck_name}" prop:due<{days} -is:suspended')))

def update_limits(hook_enabled_config_key=None, force_update=False) -> None:
    addon_config = mw.addonManager.getConfig(__name__)
    today = mw.col.sched.today

    limits_changed = 0

    if hook_enabled_config_key and not addon_config[hook_enabled_config_key]:
        return

    if addon_config.get('showNotifications', False):
        mw.taskman.run_on_main(lambda: tooltip('Updating limits...'))

    mapping = rule_mapping()

    for deck_indentifer in mw.col.decks.all_names_and_ids():
        matching_rules_idxs = mapping.get(deck_indentifer.id, [])
        if not matching_rules_idxs:
            continue

        addon_config_limits = addon_config["limits"][matching_rules_idxs[0]]
        deck = mw.col.decks.get(deck_indentifer.id)

        limit_already_set = False if deck["newLimitToday"] is None else deck["newLimitToday"]["today"] == today

        if not force_update and limit_already_set:
            continue

        deck_config = mw.col.decks.config_dict_for_deck_id(deck_indentifer.id)
        deck_size = len(list(mw.col.find_cards(f'deck:"{deck_indentifer.name}" -is:suspended')))
        new_today = 0 if mw.col.sched.today != deck['newToday'][0] else deck['newToday'][1]

        young_card_limit = addon_config_limits.get('youngCardLimit', 999999999)
        young_count = 0 if young_card_limit > deck_size else young(deck_indentifer.name)

        load_limit = addon_config_limits.get('loadLimit', 999999999)
        load = 0.0 if load_limit > deck_size else daily_load(deck_indentifer.id)

        soon_days = addon_config_limits.get('soonDays', 7)
        soon_limit = addon_config_limits.get('soonLimit', 999999999)
        soon_count = 0 if soon_limit > deck_size else soon(deck_indentifer.name, soon_days)

        max_new_cards_per_day = deck_config['new']['perDay']

        new_limit = max(0, min(max_new_cards_per_day - new_today, young_card_limit - young_count, math.ceil(load_limit - load), soon_limit - soon_count) + new_today)

        if not(limit_already_set and deck["newLimitToday"]["limit"] == new_limit):
            deck["newLimitToday"] = {"limit": new_limit, "today": mw.col.sched.today}
            mw.col.decks.save(deck)
            limits_changed += 1

    if limits_changed > 0:
        def reset_if_needed():
            if mw.state in ['deckBrowser', 'overview']:
                mw.reset()
        mw.taskman.run_on_main(reset_if_needed)
    if addon_config.get('showNotifications', False):
        mw.taskman.run_on_main(lambda: tooltip(f'Updated {limits_changed} limits.'))

def text_dialog(message: str, title: str) -> None:
    text_edit = qt.QPlainTextEdit(message)
    text_edit.setReadOnly(True)
    text_edit.setSizePolicy(qt.QSizePolicy.Policy.Expanding, qt.QSizePolicy.Policy.Expanding)

    layout = qt.QVBoxLayout()
    layout.addWidget(text_edit)

    dialog = qt.QDialog(mw)
    dialog.setWindowTitle(title)
    dialog.setGeometry(0, 0, 800, 800)
    dialog.setLayout(layout)
    dialog.show()

def utilization_dialog() -> None:
    data = limit_utilization_report_data()
    ui_config = mw.addonManager.getConfig(__name__).get('utilizationReport', {})

    text_edit = qt.QPlainTextEdit("")
    text_edit.setReadOnly(True)
    text_edit.setSizePolicy(qt.QSizePolicy.Policy.Expanding, qt.QSizePolicy.Policy.Expanding)

    check_boxes = {
        'empty': qt.QCheckBox("Empty"),
        'noLimit': qt.QCheckBox("No defined limit"),
        'notStarted': qt.QCheckBox("Not started"),
        'complete': qt.QCheckBox("Complete"),
        'overLimit': qt.QCheckBox("Over limit"),
        'underLimit': qt.QCheckBox("Under limit"),
        'subDeck': qt.QCheckBox("Sub deck")
    }

    detail_level = qt.QComboBox()
    detail_level.addItem('Summary')
    detail_level.addItem('Verbose')

    filters = qt.QHBoxLayout()
    filters.addWidget(detail_level)

    layout = qt.QVBoxLayout()
    layout.addLayout(filters)
    layout.addWidget(text_edit)

    dialog = qt.QDialog(mw)
    dialog.setWindowTitle('Limit Utilization Report')
    dialog.setGeometry(0, 0, 800, 800)
    dialog.setLayout(layout)

    def save_config():
        config = mw.addonManager.getConfig(__name__)
        if not config.get('rememberLastUiSettings', True):
            return
        config['utilizationReport'] = {
                "detailLevel": detail_level.currentText(),
                "empty": check_boxes['empty'].isChecked(),
                "noLimit": check_boxes['noLimit'].isChecked(),
                "notStarted": check_boxes['notStarted'].isChecked(),
                "complete": check_boxes['complete'].isChecked(),
                "overLimit": check_boxes['overLimit'].isChecked(),
                "underLimit": check_boxes['underLimit'].isChecked(),
                "subDeck": check_boxes['subDeck'].isChecked()
            }
        mw.addonManager.writeConfig(__name__, config)

    def render():
        d = [x for x in data]
        d = [x for x in d if check_boxes['empty'].isChecked() or x.deck_size > 0]
        d = [x for x in d if check_boxes['noLimit'].isChecked() or x.deck_has_limits]
        d = [x for x in d if check_boxes['notStarted'].isChecked() or x.learned > 0]
        d = [x for x in d if check_boxes['complete'].isChecked() or x.learned < x.deck_size]
        d = [x for x in d if check_boxes['overLimit'].isChecked() or x.value < x.limit]
        d = [x for x in d if check_boxes['underLimit'].isChecked() or x.value >= x.limit]
        d = [x for x in d if check_boxes['subDeck'].isChecked() or '::' not in x.deck_name]

        lines = []

        if detail_level.currentText() == 'Summary':
            lines.append('=== Limit Summary ===')
            lines.append('')
            lines.extend([str(x) for x in d if x.detail_level == 'Summary'])
        else:
            lines.append('=== Young Limit ===')
            lines.append('')
            lines.extend([str(x) for x in d if x.limit_type == 'youngCardLimit' and x.detail_level == 'Verbose'])

            lines.append('')
            lines.append('')

            lines.append('=== Daily Load Limit ===')
            lines.append('')
            lines.extend([str(x) for x in d if x.limit_type == 'loadLimit' and x.detail_level == 'Verbose'])

            lines.append('')
            lines.append('')

            lines.append('=== Soon Limit ===')
            lines.append('')
            lines.extend([str(x) for x in d if x.limit_type == 'soonLimit' and x.detail_level == 'Verbose'])

        message = '\n'.join(lines)
        text_edit.setPlainText(message)

    for config_name, check_box in check_boxes.items():
        filters.addWidget(check_box)
        check_box.setChecked(bool(ui_config.get(config_name, True)))
        check_box.stateChanged.connect(render)
        check_box.stateChanged.connect(save_config)
    detail_level.setCurrentText(ui_config.get('detailLevel', 'Verbose'))
    detail_level.activated.connect(render)
    detail_level.activated.connect(save_config)

    render()
    dialog.show()

def rule_mapping_report() -> str:
    limits = mw.addonManager.getConfig(__name__)['limits']
    deck_names = {x.id: x.name for x in mw.col.decks.all_names_and_ids(include_filtered=False)}
    mapping = rule_mapping()

    lines = []
    for idx, limit in enumerate(limits):
        lines.append(f'rule #{idx + 1}: {str(limit)}')

        applies = [k for (k,v) in mapping.items() if v[0:1] == [idx]]
        matches = [k for (k,v) in mapping.items() if idx in v and k not in applies]

        lines.append('\tApplies to:')
        for name in sorted([deck_names[x] for x in applies]):
            lines.append(f'\t\t{name}')

        if matches:
            lines.append('\tMatches, but is already covered by an earlier rule:')
            for name, rule in sorted([(deck_names[x], mapping[x][0] + 1) for x in matches]):
                lines.append(f'\t\t{name} -> rule #{rule}')

        lines.append('')

    lines.append('not covered by any rules:')
    for name in sorted([deck_names[k] for (k,v) in mapping.items() if not v]):
        lines.append(f'\t{name}')

    return '\n'.join(lines)

@dataclass(order=True)
class UtilizationRow:
    display_ordinal: (float, float, float)
    summary_ordinal: (float, int, float, float)
    utilization: float
    value: int | float
    limit: int | float
    detail_level: str
    limit_type: str
    ###
    deck_id: int
    deck_name: str
    deck_size: int
    learned: int
    deck_has_limits: bool

    def __str__(self):
        utilization = f'{min(9999.99, self.utilization):.2f}'
        value = f'{self.value:.2f}' if isinstance(self.value, float) else self.value
        limit = '∞' if self.limit == float('inf') else self.limit
        limit = f'{limit:.2f}' if isinstance(limit, float) else limit
        limit_type = '' if self.detail_level == 'Verbose' else f'\t[{self.limit_type}]'
        limit_type = re.sub('[A-Z][a-zA-Z]*', '', limit_type) # `young, soon, load` rather than `youngCardLimit, ...`
        return f'{utilization}% ({value} of {limit}){limit_type}\t{self.deck_name}'

def limit_utilization_report_data() -> [UtilizationRow]:
    limits = mw.addonManager.getConfig(__name__)['limits']
    deck_names = {x.id: x.name for x in mw.col.decks.all_names_and_ids(include_filtered=False)}
    mapping = rule_mapping()

    def utilization_for_limit(limit_config_key, deck_indentifer_limit_func):
        rows = []
        for did, deck_name in sorted(deck_names.items(), key=lambda x: x[1]):
            deck_indentifer = {'id': did, 'name': deck_name}
            rule = {} if not mapping[did] else limits[mapping[did][0]]
            limit = rule.get(limit_config_key, float('inf'))
            value = deck_indentifer_limit_func(deck_indentifer, rule)
            utilization = 100.0 * (value / max(limit, sys.float_info.epsilon))
            deck_size = len(list(mw.col.find_cards(f'deck:"{deck_name}" -is:suspended')))
            learned = len(list(mw.col.find_cards(f'deck:"{deck_name}" (is:learn OR is:review) -is:suspended')))
            deck_has_limits = not math.isinf(limit)
            report_ordinal = (-utilization, -value, limit, deck_name)
            summary_ordinal = (-utilization, 0 if deck_has_limits else 1, -value, limit, deck_name) # prefer decks with defined limit should they all have 0 utilization

            row = UtilizationRow(report_ordinal, summary_ordinal, utilization, value, limit, 'Verbose', limit_config_key, did, deck_name, deck_size, learned, deck_has_limits)
            rows.append(row)
        return rows

    ret = []
    ret.extend(utilization_for_limit('youngCardLimit', lambda deck_indentifer, rule: young(deck_indentifer['name'])))
    ret.extend(utilization_for_limit('loadLimit', lambda deck_indentifer, rule: daily_load(deck_indentifer['id'])))
    ret.extend(utilization_for_limit('soonLimit', lambda deck_indentifer, rule: soon(deck_indentifer['name'], rule.get('soonDays', 7))))
    ret.sort()

    summary = {}
    for row in sorted(ret, key=lambda x: x.summary_ordinal):
        deck_rows = summary.get(row.deck_id, [])
        row = dataclasses.replace(row)
        row.detail_level = 'Summary'
        row.deck_has_limits = len([x for x in ret if x.deck_id == row.deck_id and x.deck_has_limits]) > 0
        deck_rows.append(row)
        summary[row.deck_id] = deck_rows
    summary = sorted([x[0] for x in summary.values()])
    ret.extend(summary)

    return ret

def exec_in_background(func: Callable) -> Callable:
    return lambda: QueryOp(parent=mw, op=lambda col: func(), success=lambda *a, **k: None).run_in_background()

def update_limits_on_interval_loop():
    while mw.state == 'startup':
        time.sleep(60) # wait for config to be accessible
    while True:
        addon_config = mw.addonManager.getConfig(__name__)
        sleep_interval = max(60, addon_config['updateLimitsIntervalTimeInMinutes'] * 60)
        time.sleep(sleep_interval)

        update_limits(hook_enabled_config_key='updateLimitsOnInterval')

update_limits_on_interval_thread = threading.Thread(target=update_limits_on_interval_loop, daemon=True)
update_limits_on_interval_thread.start()

gui_hooks.main_window_did_init.append(exec_in_background(lambda: update_limits(hook_enabled_config_key='updateLimitsOnApplicationStartup')))
gui_hooks.sync_did_finish.append(lambda: update_limits(hook_enabled_config_key='updateLimitsAfterSync'))

menu = qt.QMenu("Limit New by Young", mw)
mw.form.menuTools.addMenu(menu)

recalculate = qt.QAction("Recalculate today's new card limit for all decks", menu)
qconnect(recalculate.triggered, exec_in_background(lambda: update_limits(force_update=True)))
menu.addAction(recalculate)

rule_mapping_report_action = qt.QAction("Show rule mapping report", menu)
qconnect(rule_mapping_report_action.triggered, lambda: text_dialog(rule_mapping_report(), 'Rule Mapping Report'))
menu.addAction(rule_mapping_report_action)

limit_utilization_report_action = qt.QAction("Show limit utilization report", menu)
qconnect(limit_utilization_report_action.triggered, lambda: utilization_dialog())
menu.addAction(limit_utilization_report_action)

documentation_action = qt.QAction("Documentation", menu)
qconnect(documentation_action.triggered, lambda: openLink('https://github.com/lune-stone/anki-addon-limit-new-by-young'))
menu.addAction(documentation_action)

report_bug_action = qt.QAction("Report a bug", menu)
qconnect(report_bug_action.triggered, lambda: openLink('https://github.com/lune-stone/anki-addon-limit-new-by-young/issues'))
menu.addAction(report_bug_action)
