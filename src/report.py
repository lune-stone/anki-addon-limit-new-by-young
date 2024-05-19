from __future__ import annotations

import dataclasses
import math
import re
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

import aqt
import aqt.qt as qt

if TYPE_CHECKING:
    from .anki_api import AnkiApi as Anki

from .limit import daily_load, rule_mapping, soon, young


def text_dialog(message: str, title: str) -> None:
    text_edit = qt.QPlainTextEdit(message)
    text_edit.setReadOnly(True)
    text_edit.setSizePolicy(qt.QSizePolicy.Policy.Expanding, qt.QSizePolicy.Policy.Expanding)

    layout = qt.QVBoxLayout()
    layout.addWidget(text_edit)

    dialog = qt.QMainWindow(aqt.mw)
    dialog.setWindowTitle(title)
    dialog.setGeometry(0, 0, 800, 800)

    widget = qt.QWidget(dialog)
    widget.setLayout(layout)
    dialog.setCentralWidget(widget)

    def on_key_press(e: qt.PyQt6.QtGui.QKeyEvent) -> None:
        if e.key() == qt.PyQt6.QtCore.Qt.Key.Key_Escape:
            dialog.close()
    dialog.keyPressEvent = on_key_press #type: ignore[assignment, method-assign]

    dialog.show()

def utilization_dialog(anki: Anki) -> None:
    data = limit_utilization_report_data(anki)
    ui_config = anki.get_config().get('utilizationReport', {})

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

    dialog = qt.QMainWindow(aqt.mw)
    dialog.setWindowTitle('Limit Utilization Report')
    dialog.setGeometry(0, 0, 800, 800)

    widget = qt.QWidget(dialog)
    widget.setLayout(layout)
    dialog.setCentralWidget(widget)

    def save_config() -> None:
        config = anki.get_config()
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
        anki.write_config(config)

    def render() -> None:
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

    def on_key_press(e: qt.PyQt6.QtGui.QKeyEvent) -> None:
        if e.key() == qt.PyQt6.QtCore.Qt.Key.Key_Escape:
            dialog.close()
    dialog.keyPressEvent = on_key_press #type: ignore[assignment, method-assign]

    dialog.show()

def rule_mapping_report(anki: Anki) -> str:
    limits = anki.get_config().get('limits', [])
    deck_names = {x.id: x.name for x in anki.get_deck_identifiers()}
    mapping = rule_mapping(anki)

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
    display_ordinal: tuple
    summary_ordinal: tuple
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

    def __str__(self: UtilizationRow) -> str:
        utilization = f'{min(9999.99, self.utilization):.2f}'
        value = f'{self.value:.2f}' if isinstance(self.value, float) else self.value
        limit = '∞' if self.limit == float('inf') else self.limit
        limit = f'{limit:.2f}' if isinstance(limit, float) else limit
        limit_type = '' if self.detail_level == 'Verbose' else f'\t[{self.limit_type}]'
        limit_type = re.sub('[A-Z][a-zA-Z]*', '', limit_type) # `young, soon, load` rather than `youngCardLimit, ...`
        return f'{utilization}% ({value} of {limit}){limit_type}\t{self.deck_name}'

def limit_utilization_report_data(anki: Anki) -> list[UtilizationRow]:
    limits = anki.get_config().get('limits', [])
    deck_names = {x.id: x.name for x in anki.get_deck_identifiers()}
    mapping = rule_mapping(anki)

    def utilization_for_limit(limit_config_key: str, deck_indentifer_limit_func: Callable) -> list[UtilizationRow]:
        rows = []
        for did, deck_name in sorted(deck_names.items(), key=lambda x: x[1]):
            deck_indentifer = {'id': did, 'name': deck_name}
            rule = {} if not mapping[did] else limits[mapping[did][0]]
            limit = rule.get(limit_config_key, float('inf'))
            value = deck_indentifer_limit_func(deck_indentifer, rule)
            utilization = 100.0 * (value / max(limit, sys.float_info.epsilon))
            deck_size = len(list(anki.col().find_cards(f'deck:"{deck_name}" -is:suspended')))
            learned = len(list(anki.col().find_cards(f'deck:"{deck_name}" (is:learn OR is:review) -is:suspended')))
            deck_has_limits = not math.isinf(limit)
            report_ordinal = (-utilization, -value, limit, deck_name)
            summary_ordinal = (-utilization, 0 if deck_has_limits else 1, -value, limit, deck_name) # prefer decks with defined limit should they all have 0 utilization

            row = UtilizationRow(report_ordinal, summary_ordinal, utilization, value, limit, 'Verbose', limit_config_key, did, deck_name, deck_size, learned, deck_has_limits)
            rows.append(row)
        return rows

    ret = []
    ret.extend(utilization_for_limit('youngCardLimit', lambda deck_indentifer, rule: young(anki, deck_indentifer['name'])))
    ret.extend(utilization_for_limit('loadLimit', lambda deck_indentifer, rule: daily_load(anki, deck_indentifer['id'])))
    ret.extend(utilization_for_limit('soonLimit', lambda deck_indentifer, rule: soon(anki, deck_indentifer['name'], rule.get('soonDays', 7))))
    ret.sort()

    summary: dict[int, list[UtilizationRow]] = {}
    for row in sorted(ret, key=lambda x: x.summary_ordinal):
        deck_rows = summary.get(row.deck_id, [])
        row = dataclasses.replace(row)
        row.detail_level = 'Summary'
        row.deck_has_limits = len([x for x in ret if x.deck_id == row.deck_id and x.deck_has_limits]) > 0
        deck_rows.append(row)
        summary[row.deck_id] = deck_rows
    ret.extend(sorted([x[0] for x in summary.values()]))

    return ret
