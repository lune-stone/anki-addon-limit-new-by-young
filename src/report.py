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

from .limit import (
    cards,
    daily_load,
    group_daily_load,
    group_soon,
    group_young,
    rule_mapping,
    seen,
    soon,
    young,
    young_card_ids,
)


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

    def on_key_press(e: qt.QKeyEvent) -> None:
        if e.key() == qt.Qt.Key.Key_Escape:
            dialog.close()
    dialog.keyPressEvent = on_key_press #type: ignore[assignment, method-assign]

    dialog.show()


def collective_young_diagnostic_report(anki: Anki) -> str:
    """Explain how collective youngCardLimit rules arrive at their young-card count.

    Collective rules count every card once, even when a rule lists both a parent
    deck and its subdecks. This report shows the unique total the add-on uses,
    how much parent/subdeck overlap was removed, and the per-deck breakdown.
    """
    limits = anki.get_config().get('limits', [])
    deck_names = {x.id: x.name for x in anki.get_deck_identifiers()}
    mapping = rule_mapping(anki)

    rule_groups: dict[int, list[int]] = {}
    for did in deck_names:
        if mapping[did]:
            rule_groups.setdefault(mapping[did][0], []).append(did)

    lines: list[str] = []
    for rule_idx, group_dids in sorted(rule_groups.items()):
        rule = limits[rule_idx]
        if 'youngCardLimit' not in rule or not rule.get('collective', False):
            continue

        limit = rule['youngCardLimit']
        per_deck: list[tuple[int, str]] = []
        unique_card_ids: set = set()

        for did in group_dids:
            ids = set(young_card_ids(anki, [did]))
            unique_card_ids.update(ids)
            if ids:
                per_deck.append((len(ids), deck_names[did]))

        unique = len(unique_card_ids)
        overlap = sum(count for count, _ in per_deck) - unique
        remaining = limit - unique
        utilization = 100.0 * (unique / max(limit, sys.float_info.epsilon))

        lines.append(f'Rule #{rule_idx + 1}: {unique} of {limit} young cards used ({utilization:.2f}%).')
        lines.append(f'\tRemaining collective new-card budget: {remaining}')

        if remaining < 0:
            lines.append('\tStatus: over limit, so new cards are reduced to 0 (or the rule\'s minimum).')
        elif remaining == 0:
            lines.append('\tStatus: exactly at limit, so no new-card budget remains.')
        else:
            lines.append('\tStatus: under limit, so this many new cards may be shared across the group.')

        if overlap > 0:
            lines.append(f'\tNote: the rule lists parent decks together with their subdecks; {overlap} overlapping young cards were counted only once.')

        if per_deck:
            lines.append('\tYoung cards per listed deck (including its subdecks):')
            for count, name in sorted(per_deck, key=lambda x: (-x[0], x[1])):
                lines.append(f'\t\t{count}\t{name}')
        else:
            lines.append('\tNo young cards in this rule group.')
        lines.append('')

    if not lines:
        lines.append('No collective youngCardLimit rules matched any decks.')

    return '\n'.join(lines)

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
            lines.append('=== Collective Young Count Diagnostic ===')
            lines.append('')
            lines.extend(collective_young_diagnostic_report(anki).splitlines())

            lines.append('')
            lines.append('')

            lines.append('=== Young Limit ===')
            lines.append('')
            lines.extend(utilization_rows_report([x for x in d if x.limit_type == 'youngCardLimit' and x.detail_level == 'Verbose']))

            lines.append('')
            lines.append('')

            lines.append('=== Daily Load Limit ===')
            lines.append('')
            lines.extend(utilization_rows_report([x for x in d if x.limit_type == 'loadLimit' and x.detail_level == 'Verbose']))

            lines.append('')
            lines.append('')

            lines.append('=== Soon Limit ===')
            lines.append('')
            lines.extend(utilization_rows_report([x for x in d if x.limit_type == 'soonLimit' and x.detail_level == 'Verbose']))

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

    def on_key_press(e: qt.QKeyEvent) -> None:
        if e.key() == qt.Qt.Key.Key_Escape:
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
    rule_idx: int | None = dataclasses.field(compare=False)
    is_collective: bool = dataclasses.field(compare=False)
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

def utilization_rows_report(rows: list[UtilizationRow]) -> list[str]:
    line_groups: list[tuple[tuple, list[str]]] = []
    collective_groups: dict[tuple[int, str], list[UtilizationRow]] = {}

    for row in rows:
        if row.detail_level == 'Verbose' and row.is_collective and row.rule_idx is not None:
            collective_groups.setdefault((row.rule_idx, row.limit_type), []).append(row)
        else:
            line_groups.append((row.display_ordinal, [str(row)]))

    for (rule_idx, _limit_type), group_rows in collective_groups.items():
        sample = group_rows[0]
        utilization = f'{min(9999.99, sample.utilization):.2f}'
        value = f'{sample.value:.2f}' if isinstance(sample.value, float) else sample.value
        limit = '∞' if sample.limit == float('inf') else sample.limit
        limit = f'{limit:.2f}' if isinstance(limit, float) else limit

        group_lines = [f'{utilization}% ({value} of {limit})\tCollective rule #{rule_idx + 1}', '\tAffected decks:']
        for row in sorted(group_rows, key=lambda x: x.deck_name):
            group_lines.append(f'\t\t{row.deck_name}')

        line_groups.append((min(row.display_ordinal for row in group_rows), group_lines))

    return [line for _ordinal, group_lines in sorted(line_groups) for line in group_lines]

def limit_utilization_report_data(anki: Anki) -> list[UtilizationRow]:
    limits = anki.get_config().get('limits', [])
    deck_names = {x.id: x.name for x in anki.get_deck_identifiers()}
    mapping = rule_mapping(anki)

    # Group decks by their first-matching rule for collective metric computation
    rule_groups: dict[int, list[int]] = {}
    for did in deck_names:
        if mapping[did]:
            rule_groups.setdefault(mapping[did][0], []).append(did)

    # Pre-compute collective values only for rules with collective: true
    collective_values: dict[tuple[int, str], float] = {}
    for rule_idx, group_dids in rule_groups.items():
        rule = limits[rule_idx]
        if not rule.get('collective', False):
            continue
        # each card counted once, even if the rule lists a parent deck and its subdecks
        if 'youngCardLimit' in rule:
            collective_values[(rule_idx, 'youngCardLimit')] = group_young(anki, group_dids)
        if 'loadLimit' in rule:
            collective_values[(rule_idx, 'loadLimit')] = group_daily_load(anki, group_dids)
        if 'soonLimit' in rule:
            collective_values[(rule_idx, 'soonLimit')] = group_soon(anki, group_dids, rule.get('soonDays', 7))

    def utilization_for_limit(limit_config_key: str, deck_indentifer_limit_func: Callable) -> list[UtilizationRow]:
        rows = []
        for did, deck_name in sorted(deck_names.items(), key=lambda x: x[1]):
            rule_idx = mapping[did][0] if mapping[did] else None
            rule = {} if rule_idx is None else limits[rule_idx]
            limit = rule.get(limit_config_key, float('inf'))

            # Use collective value only when this exact metric is configured collectively.
            uses_collective_value = rule_idx is not None and (rule_idx, limit_config_key) in collective_values
            if uses_collective_value:
                value = collective_values[(rule_idx, limit_config_key)]
            else:
                deck_indentifer = {'id': did, 'name': deck_name}
                value = deck_indentifer_limit_func(deck_indentifer, rule)

            utilization = 100.0 * (value / max(limit, sys.float_info.epsilon))
            deck_size = cards(anki, did)
            learned = seen(anki, did)
            deck_has_limits = not math.isinf(limit)
            report_ordinal = (-utilization, -value, limit, deck_name)
            summary_ordinal = (-utilization, 0 if deck_has_limits else 1, -value, limit, deck_name) # prefer decks with defined limit should they all have 0 utilization

            row = UtilizationRow(
                report_ordinal,
                summary_ordinal,
                utilization,
                value,
                limit,
                'Verbose',
                limit_config_key,
                rule_idx,
                uses_collective_value,
                did,
                deck_name,
                deck_size,
                learned,
                deck_has_limits
            )
            rows.append(row)
        return rows

    ret = []
    ret.extend(utilization_for_limit('youngCardLimit', lambda deck_indentifer, rule: young(anki, deck_indentifer['id'])))
    ret.extend(utilization_for_limit('loadLimit', lambda deck_indentifer, rule: daily_load(anki, deck_indentifer['id'])))
    ret.extend(utilization_for_limit('soonLimit', lambda deck_indentifer, rule: soon(anki, deck_indentifer['id'], rule.get('soonDays', 7))))
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
