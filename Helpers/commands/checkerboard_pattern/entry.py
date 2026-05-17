"""Instrument: Checkerboard Pattern (works IN SKETCH EDIT MODE).

Select the 4 lines of a sketched rectangle and one existing sketch
circle. The tool parametrically re-centres the circle in the rectangle
and builds a checkerboard ("chess") grid of that circle: a full N x M
native sketch RectangularPattern, symmetric in both directions, with the
non-seed-parity cells suppressed so only the "dark squares" remain.

The dialog mirrors Fusion's native Rectangular Pattern (Distribution +
Quantity/Distance per direction) but is ALWAYS symmetric in both
directions (no per-direction One/Symmetric choice) and shows a live
preview. The result is fully parametric: real ModelParameters drive the
quantities and spacing, so later edits reflow.

Discovered automatically because this package contains entry.py exposing
COMMAND.
"""

import adsk.core
import adsk.fusion

import config
from command_base import InstrumentCommand
from lib import checkerboard


def _native(entity):
    """Native object for an occurrence-proxy entity, else the entity.

    Sketch work happens in the native sketch; a proxy selected in an
    assembly context resolves to its native sketch entity.
    """
    return entity.nativeObject if entity.assemblyContext else entity


def _selected(sel_input):
    """All entities currently in a SelectionCommandInput (native)."""
    return [_native(sel_input.selection(i).entity)
            for i in range(sel_input.selectionCount)]


class CheckerboardPatternCommand(InstrumentCommand):
    CMD_ID = config.cmd_id('CheckerboardPattern')
    NAME = 'Checkerboard Pattern'
    TOOLTIP = ('In an active sketch: select the 4 lines of a rectangle '
               'and one circle. The circle is re-centred in the '
               'rectangle (parametrically) and a checkerboard ("chess") '
               'pattern of it is built as a fully parametric, edge-'
               'aligned, symmetric rectangular sketch pattern.')

    _RECT = 'rectLines'
    _CIRCLE = 'seedCircle'
    _DIST = 'distribution'
    _Q1 = 'quantity1'
    _D1 = 'distance1'
    _Q2 = 'quantity2'
    _D2 = 'distance2'
    _INFO = 'info'

    _DIST_ITEMS = ('Extent', 'Spacing')

    def __init__(self):
        super().__init__()
        # Set True by on_preview when it produces a valid result so
        # on_execute can pass through (Fusion reuses the preview build).
        self._preview_ok = False

    # ---- dialog -------------------------------------------------------
    def build_inputs(self, inputs: adsk.core.CommandInputs):
        rect = inputs.addSelectionInput(
            self._RECT, 'Rectangle',
            'Select the 4 lines of the rectangle')
        rect.addSelectionFilter('SketchLines')
        rect.setSelectionLimits(4, 4)

        circle = inputs.addSelectionInput(
            self._CIRCLE, 'Objects',
            'Select the circle to pattern')
        circle.addSelectionFilter('SketchCircles')
        circle.setSelectionLimits(1, 1)

        dist = inputs.addDropDownCommandInput(
            self._DIST, 'Distribution',
            adsk.core.DropDownStyles.TextListDropDownStyle)
        for name in self._DIST_ITEMS:
            dist.listItems.add(name, name == 'Extent', '')
        dist.tooltip = ('Extent: Distance is the total span. Spacing: '
                        'Distance is the gap between adjacent cells.')

        app = adsk.core.Application.get()
        design = adsk.fusion.Design.cast(app.activeProduct)
        units = design.unitsManager.defaultLengthUnits if design else 'mm'

        inputs.addIntegerSpinnerCommandInput(
            self._Q1, 'Quantity 1', 1, 999, 1, 5)
        inputs.addValueInput(
            self._D1, 'Distance 1', units,
            adsk.core.ValueInput.createByString('40 mm'))
        inputs.addIntegerSpinnerCommandInput(
            self._Q2, 'Quantity 2', 1, 999, 1, 5)
        inputs.addValueInput(
            self._D2, 'Distance 2', units,
            adsk.core.ValueInput.createByString('40 mm'))

        inputs.addTextBoxCommandInput(
            self._INFO, '',
            'Pattern is symmetric in both directions; the circle is '
            'centred in the rectangle. Direction 1 = the rectangle\'s '
            'longer edge.', 3, True)

    # ---- parameter collection ----------------------------------------
    def _params(self, inputs):
        rect_sel = inputs.itemById(self._RECT)
        circ_sel = inputs.itemById(self._CIRCLE)
        if rect_sel.selectionCount != 4:
            raise ValueError('Select exactly 4 rectangle lines.')
        if circ_sel.selectionCount != 1:
            raise ValueError('Select exactly one circle.')

        rect_lines = _selected(rect_sel)
        circle = _selected(circ_sel)[0]

        idx = inputs.itemById(self._DIST).selectedItem.index
        if self._DIST_ITEMS[idx] == 'Spacing':
            dist_type = (adsk.fusion.PatternDistanceType
                         .SpacingPatternDistanceType)
        else:
            dist_type = (adsk.fusion.PatternDistanceType
                         .ExtentPatternDistanceType)

        q1 = inputs.itemById(self._Q1).value
        q2 = inputs.itemById(self._Q2).value
        # Use the ValueInput EXPRESSION so the user's units/equation flow
        # straight into the auto-created ModelParameter.
        d1 = inputs.itemById(self._D1).expression
        d2 = inputs.itemById(self._D2).expression

        return dict(rect_lines=rect_lines, circle=circle,
                    dist_type=dist_type, q1=q1, d1=d1, q2=q2, d2=d2)

    def _active_sketch(self, app):
        return adsk.fusion.Sketch.cast(app.activeEditObject)

    # ---- lifecycle hooks ---------------------------------------------
    def on_validate(self, inputs, args):
        app = adsk.core.Application.get()
        try:
            rect_sel = inputs.itemById(self._RECT)
            circ_sel = inputs.itemById(self._CIRCLE)
            if rect_sel.selectionCount != 4 or \
                    circ_sel.selectionCount != 1:
                args.areInputsValid = False
                return
            sketch = self._active_sketch(app)
            rect_lines = _selected(rect_sel)
            circle = _selected(circ_sel)[0]
            args.areInputsValid = checkerboard.validate(
                sketch, rect_lines, circle)
        except Exception:  # pylint: disable=broad-except
            args.areInputsValid = False

    def on_preview(self, inputs, args):
        app = adsk.core.Application.get()
        self._preview_ok = False
        params = self._params(inputs)
        checkerboard.build(app, preview=True, **params)
        # Preview built cleanly: let Fusion reuse it when OK is pressed.
        args.isValidResult = True
        self._preview_ok = True

    def on_input_changed(self, inputs, changed_input):
        # The preview handler drives all redraw; nothing to do here.
        return

    def on_execute(self, inputs: adsk.core.CommandInputs):
        app = adsk.core.Application.get()

        # build() is idempotent (it deletes the prior instrument-owned
        # pattern + centring constraints first), so running it once here
        # is deterministic whether or not a preview already ran — the
        # preview transaction is discarded by Fusion before execute.
        result = checkerboard.build(app, preview=False,
                                    **self._params(inputs))

        notes = ('  ' + '; '.join(result.notes)) if result.notes else ''
        app.userInterface.messageBox(
            'Checkerboard built: %d of %d cells filled '
            '(%d x %d, %s distribution).%s'
            % (result.filled_count, result.total_cells,
               result.q1, result.q2, result.dist_type_name, notes),
            config.ADDIN_NAME)


COMMAND = CheckerboardPatternCommand
