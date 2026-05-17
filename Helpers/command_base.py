"""Fusion command lifecycle plumbing shared by every Helpers instrument.

A subclass of :class:`InstrumentCommand` only has to set its id/name/tooltip
and implement :meth:`build_inputs` and :meth:`on_execute`. This module owns
the tricky parts: creating the command definition, wiring the
created/execute event handlers, keeping handler references alive (Fusion
garbage-collects unreferenced handlers), and tearing the control down.
"""

import traceback

import adsk.core

try:
    from log import log
except Exception:  # pragma: no cover
    def log(_msg):
        pass

_app = adsk.core.Application.get()
_ui = _app.userInterface

# Event handlers must be kept referenced for the life of the add-in or
# Fusion will garbage-collect them and the buttons stop responding.
_handlers = []


def clear_handlers():
    """Drop all handler references (called from the add-in's stop())."""
    _handlers.clear()


class InstrumentCommand:
    """Base class for one entry in the Helpers menu."""

    CMD_ID = ''             # set with config.cmd_id(...)
    NAME = ''               # button text
    TOOLTIP = ''            # hover help
    RESOURCE_FOLDER = ''    # '' => Fusion's default icon

    def __init__(self):
        self._definition = None
        self._control = None

    # ---- subclass hooks ------------------------------------------------
    def build_inputs(self, inputs: adsk.core.CommandInputs):
        """Add the command dialog inputs. Override in the subclass."""

    def on_execute(self, inputs: adsk.core.CommandInputs):
        """Perform the operation. Override. Raise on failure; the base
        class reports it to the user and the TEXT COMMANDS log."""
        raise NotImplementedError

    # The next three are OPTIONAL no-op hooks (live preview / input
    # change / OK-enable validation). Existing instruments that do not
    # override them are completely unaffected.
    def on_preview(self, inputs: adsk.core.CommandInputs, args):
        """Build the live preview (executePreview transaction). Set
        ``args.isValidResult = True`` to have the preview geometry reused
        when the user presses OK. Default: do nothing."""

    def on_input_changed(self, inputs: adsk.core.CommandInputs,
                         changed_input):
        """React to a single input changing. Default: do nothing."""

    def on_validate(self, inputs: adsk.core.CommandInputs, args):
        """Set ``args.areInputsValid`` to enable/disable OK. Default:
        leave Fusion's own per-input validation in charge."""

    # ---- lifecycle -----------------------------------------------------
    def register(self, controls: adsk.core.ToolbarControls):
        """Create the command definition and add its button to ``controls``."""
        cmd_defs = _ui.commandDefinitions
        stale_def = cmd_defs.itemById(self.CMD_ID)
        if stale_def:
            stale_def.deleteMe()
        self._definition = cmd_defs.addButtonDefinition(
            self.CMD_ID, self.NAME, self.TOOLTIP, self.RESOURCE_FOLDER)

        created = _CommandCreatedHandler(self)
        self._definition.commandCreated.add(created)
        _handlers.append(created)

        stale_ctrl = controls.itemById(self.CMD_ID)
        if stale_ctrl:
            stale_ctrl.deleteMe()
        self._control = controls.addCommand(self._definition)
        log('registered control %s' % self.CMD_ID)

    def unregister(self):
        """Remove the button and command definition (called on stop())."""
        for obj in (self._control, self._definition):
            try:
                if obj:
                    obj.deleteMe()
            except Exception:  # pylint: disable=broad-except
                pass
        self._control = None
        self._definition = None


class _CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    """Builds the dialog and attaches the execute handler when the button
    is clicked."""

    def __init__(self, owner: InstrumentCommand):
        super().__init__()
        self._owner = owner

    def notify(self, args):
        try:
            cmd = adsk.core.CommandCreatedEventArgs.cast(args).command
            self._owner.build_inputs(cmd.commandInputs)
            execute = _CommandExecuteHandler(self._owner)
            cmd.execute.add(execute)
            _handlers.append(execute)

            # Optional live-preview / input-change / validate handlers.
            # Attached unconditionally; the base hooks are no-ops so
            # instruments that don't override them see no behaviour change.
            preview = _CommandPreviewHandler(self._owner)
            cmd.executePreview.add(preview)
            _handlers.append(preview)

            changed = _CommandInputChangedHandler(self._owner)
            cmd.inputChanged.add(changed)
            _handlers.append(changed)

            validate = _CommandValidateHandler(self._owner)
            cmd.validateInputs.add(validate)
            _handlers.append(validate)
        except Exception:  # pylint: disable=broad-except
            log('%s commandCreated FAILED:\n%s'
                % (self._owner.NAME, traceback.format_exc()))
            _ui.messageBox(
                f'{self._owner.NAME} — could not open:\n'
                f'{traceback.format_exc()}')


class _CommandExecuteHandler(adsk.core.CommandEventHandler):
    """Runs the instrument's operation when the dialog's OK is pressed."""

    def __init__(self, owner: InstrumentCommand):
        super().__init__()
        self._owner = owner

    def notify(self, args):
        try:
            cmd = adsk.core.CommandEventArgs.cast(args).command
            self._owner.on_execute(cmd.commandInputs)
        except Exception as exc:  # pylint: disable=broad-except
            log('%s execute FAILED:\n%s'
                % (self._owner.NAME, traceback.format_exc()))
            _app.log(f'{self._owner.NAME} failed:\n{traceback.format_exc()}')
            _ui.messageBox(str(exc), self._owner.NAME)


class _CommandPreviewHandler(adsk.core.CommandEventHandler):
    """Runs the instrument's live preview each time inputs settle.

    Fires inside Fusion's preview transaction. Failures are logged only
    (never a message box per keystroke) and ``isValidResult`` is left
    False so OK still recomputes from scratch.
    """

    def __init__(self, owner: InstrumentCommand):
        super().__init__()
        self._owner = owner

    def notify(self, args):
        try:
            ev = adsk.core.CommandEventArgs.cast(args)
            self._owner.on_preview(ev.command.commandInputs, ev)
        except Exception:  # pylint: disable=broad-except
            log('%s preview FAILED:\n%s'
                % (self._owner.NAME, traceback.format_exc()))


class _CommandInputChangedHandler(adsk.core.InputChangedEventHandler):
    """Notifies the instrument that a single input changed."""

    def __init__(self, owner: InstrumentCommand):
        super().__init__()
        self._owner = owner

    def notify(self, args):
        try:
            ev = adsk.core.InputChangedEventArgs.cast(args)
            self._owner.on_input_changed(ev.inputs, ev.input)
        except Exception:  # pylint: disable=broad-except
            log('%s inputChanged FAILED:\n%s'
                % (self._owner.NAME, traceback.format_exc()))


class _CommandValidateHandler(adsk.core.ValidateInputsEventHandler):
    """Lets the instrument enable/disable the dialog's OK button."""

    def __init__(self, owner: InstrumentCommand):
        super().__init__()
        self._owner = owner

    def notify(self, args):
        try:
            ev = adsk.core.ValidateInputsEventArgs.cast(args)
            self._owner.on_validate(ev.inputs, ev)
        except Exception:  # pylint: disable=broad-except
            log('%s validate FAILED:\n%s'
                % (self._owner.NAME, traceback.format_exc()))
