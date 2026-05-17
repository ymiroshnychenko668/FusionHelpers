"""Tiny file logger shared by the add-in.

Stdlib only and never raises, so it works even when the add-in fails to
import. Writes to helpers.log next to this file.
"""

import datetime
import os

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'helpers.log')


def log(msg):
    try:
        with open(LOG_PATH, 'a', encoding='utf-8') as fh:
            fh.write('%s  %s\n'
                     % (datetime.datetime.now().isoformat(timespec='seconds'),
                        msg))
    except Exception:  # pragma: no cover - logging must never break the add-in
        pass


def banner(msg):
    log('=' * 18 + ' %s ' % msg + '=' * 18)
