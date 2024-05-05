from __future__ import annotations

import os
import threading
import time
from typing import Callable

import aqt
import aqt.qt as qt
from aqt import gui_hooks
from aqt.operations import QueryOp
from aqt.utils import openLink, qconnect

from .anki_api import AnkiApi as Anki
from .limit import update_limits
from .report import rule_mapping_report, text_dialog, utilization_dialog


def exec_in_background(func: Callable) -> Callable:
    return lambda: QueryOp(parent=aqt.mw, op=lambda col: func(), success=lambda *a, **k: None).run_in_background() # type: ignore[arg-type]

def update_limits_on_interval_loop(anki: Anki) -> None:
    while not anki.is_ready():
        time.sleep(60) # wait for config to be accessible
    while True:
        addon_config = anki.get_config()
        sleep_interval = max(60, addon_config['updateLimitsIntervalTimeInMinutes'] * 60)
        time.sleep(sleep_interval)

        update_limits(anki, hook_enabled_config_key='updateLimitsOnInterval')

def init() -> None:
    anki = Anki(__name__)

    update_limits_on_interval_thread = threading.Thread(target=lambda: update_limits_on_interval_loop(anki), daemon=True)
    update_limits_on_interval_thread.start()

    gui_hooks.main_window_did_init.append(exec_in_background(lambda: update_limits(anki, hook_enabled_config_key='updateLimitsOnApplicationStartup')))
    gui_hooks.sync_did_finish.append(lambda: update_limits(anki, hook_enabled_config_key='updateLimitsAfterSync'))

    menu = qt.QMenu("Limit New by Young", aqt.mw)
    aqt.mw.form.menuTools.addMenu(menu) # type: ignore[union-attr]

    recalculate = qt.QAction("Recalculate today's new card limit for all decks", menu)
    qconnect(recalculate.triggered, exec_in_background(lambda: update_limits(anki, force_update=True)))
    menu.addAction(recalculate)

    rule_mapping_report_action = qt.QAction("Show rule mapping report", menu)
    qconnect(rule_mapping_report_action.triggered, lambda: text_dialog(rule_mapping_report(anki), 'Rule Mapping Report'))
    menu.addAction(rule_mapping_report_action)

    limit_utilization_report_action = qt.QAction("Show limit utilization report", menu)
    qconnect(limit_utilization_report_action.triggered, lambda: utilization_dialog(anki))
    menu.addAction(limit_utilization_report_action)

    documentation_action = qt.QAction("Documentation", menu)
    qconnect(documentation_action.triggered, lambda: openLink('https://github.com/lune-stone/anki-addon-limit-new-by-young'))
    menu.addAction(documentation_action)

    report_bug_action = qt.QAction("Report a bug", menu)
    qconnect(report_bug_action.triggered, lambda: openLink('https://github.com/lune-stone/anki-addon-limit-new-by-young/issues'))
    menu.addAction(report_bug_action)

if not os.environ.get('TEST'):
    init()
