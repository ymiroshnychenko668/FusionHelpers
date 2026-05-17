"""Helpers add-in entry point.

Builds the "Helpers" panel in the Design UTILITIES tab and registers
every instrument under commands/ directly in it. Every step is written to
helpers.log next to this file so silent Fusion failures are diagnosable.

Adding a new instrument: create commands/<name>/entry.py exposing a
``COMMAND`` class (subclass of command_base.InstrumentCommand). See
CLAUDE.md.
"""

import importlib
import os
import sys
import traceback

import adsk.core

# Fusion does not reliably put the add-in folder on sys.path.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Logging must work even if every other import fails. Fall back to an
# inline writer if even log.py cannot be imported.
try:
    from log import log, banner
except Exception:  # pragma: no cover
    import datetime
    _LOGP = os.path.join(_HERE, 'helpers.log')

    def log(msg):
        try:
            with open(_LOGP, 'a', encoding='utf-8') as fh:
                fh.write('%s  %s\n' % (datetime.datetime.now(), msg))
        except Exception:
            pass

    def banner(msg):
        log('==== %s ====' % msg)

# State kept so stop() can tear the exact same UI down.
_instruments = []
_panel = None
_panel_created = False

_RELOAD_ORDER = ('config', 'command_base', 'lib', 'lib.selection',
                 'lib.parameters', 'lib.features', 'lib.pipes',
                 'lib.checkerboard')


def run(_context):
    global _panel, _panel_created
    banner('run() called')
    log('python: %s' % sys.version.replace('\n', ' '))
    log('_HERE: %s' % _HERE)
    try:
        # All project imports happen here (not at module top) so that any
        # import error is logged instead of silently killing the add-in.
        import config
        import command_base
        import lib.selection      # noqa: F401
        import lib.parameters     # noqa: F401
        import lib.features       # noqa: F401
        import lib.pipes          # noqa: F401
        import lib.checkerboard   # noqa: F401
        for name in _RELOAD_ORDER:
            if name in sys.modules:
                importlib.reload(sys.modules[name])
        log('project imports OK')

        app = adsk.core.Application.get()
        ui = app.userInterface

        workspace = ui.workspaces.itemById(config.WORKSPACE_ID)
        log('workspace %s -> %s' % (config.WORKSPACE_ID, bool(workspace)))
        if not workspace:
            raise RuntimeError('workspace %r not found' % config.WORKSPACE_ID)

        tab = workspace.toolbarTabs.itemById(config.TAB_ID)
        log('tab %s -> %s' % (config.TAB_ID, bool(tab)))
        if not tab:
            raise RuntimeError('tab %r not found' % config.TAB_ID)

        _panel = tab.toolbarPanels.itemById(config.PANEL_ID)
        if not _panel:
            _panel = tab.toolbarPanels.add(config.PANEL_ID,
                                           config.PANEL_NAME)
            _panel_created = True
        log('panel ready id=%s created=%s' % (config.PANEL_ID,
                                               _panel_created))

        # Remove the legacy nested "Helpers" dropdown if an older session
        # created one (instruments now sit directly in the Helpers panel).
        legacy = _panel.controls.itemById(config.LEGACY_DROPDOWN_ID)
        if legacy:
            legacy.deleteMe()
            log('removed legacy dropdown')

        commands_dir = os.path.join(_HERE, 'commands')
        for name in sorted(os.listdir(commands_dir)):
            if not os.path.isfile(os.path.join(commands_dir, name,
                                               'entry.py')):
                continue
            log('importing instrument: %s' % name)
            module = importlib.import_module('commands.%s.entry' % name)
            importlib.reload(module)
            command_cls = getattr(module, 'COMMAND', None)
            if command_cls is None:
                log('  no COMMAND in %s, skipped' % name)
                continue
            instrument = command_cls()
            instrument.register(_panel.controls)
            _instruments.append(instrument)
            log('  registered %s (%s)' % (command_cls.NAME,
                                          command_cls.CMD_ID))

        log('run() COMPLETE; instruments=%d' % len(_instruments))
        if not _instruments:
            ui.messageBox('Helpers: no instruments found under commands/.',
                           config.ADDIN_NAME)
    except Exception:
        tb = traceback.format_exc()
        log('run() FAILED:\n' + tb)
        try:
            adsk.core.Application.get().userInterface.messageBox(
                'Helpers failed to start (see helpers.log):\n' + tb)
        except Exception:
            log('(messageBox also failed)')


def stop(_context):
    global _panel, _panel_created
    banner('stop() called')
    try:
        for instrument in _instruments:
            try:
                instrument.unregister()
            except Exception:
                log('unregister failed:\n' + traceback.format_exc())
        _instruments.clear()

        if _panel and _panel_created:
            try:
                _panel.deleteMe()
            except Exception:
                pass
        _panel = None
        _panel_created = False

        try:
            import command_base
            command_base.clear_handlers()
        except Exception:
            pass
        log('stop() COMPLETE')
    except Exception:
        log('stop() FAILED:\n' + traceback.format_exc())
