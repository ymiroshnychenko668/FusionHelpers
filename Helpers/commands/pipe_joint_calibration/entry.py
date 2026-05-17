"""Instrument: Pipe Joint Calibration.

Select Pipe A's planar end profile face; the helper sockets the
perpendicular Pipe B it runs into and adds a length-limited calibration
relief band on Pipe A so milled parts always fit. Discovered
automatically because this package contains entry.py exposing COMMAND.
"""

import adsk.core
import adsk.fusion

import config
from command_base import InstrumentCommand
from lib import pipes


def _native(entity):
    """Native object for an occurrence-proxy entity, else the entity."""
    return entity.nativeObject if entity.assemblyContext else entity


class PipeJointCalibrationCommand(InstrumentCommand):
    CMD_ID = config.cmd_id('PipeJointCalibration')
    NAME = 'Pipe Joint Calibration'
    TOOLTIP = ('Select Pipe A\'s flat end profile (square/rectangular '
               'hollow tube). Cuts a socket into the perpendicular Pipe B '
               'it meets and adds a calibration relief band on Pipe A so '
               'milled joints always fit.')

    _FACE = 'endFace'
    _OFFSET = 'offsetSize'
    _CLR = 'clearance'
    _CLRLEN = 'clearanceLength'
    _SIDE = 'clearanceSide'
    _STRICT = 'strictMulti'
    _PREVIEW = 'previewOnly'

    _SIDES = ('Both', 'A only', 'B only')

    def build_inputs(self, inputs: adsk.core.CommandInputs):
        face = inputs.addSelectionInput(
            self._FACE, 'Pipe A end face',
            'Select Pipe A\'s flat end profile face')
        face.addSelectionFilter('SolidFaces')
        face.setSelectionLimits(1, 1)

        app = adsk.core.Application.get()
        design = adsk.fusion.Design.cast(app.activeProduct)
        units = design.unitsManager.defaultLengthUnits if design else 'mm'

        inputs.addValueInput(self._OFFSET, 'Offset size (penetration)',
                             units,
                             adsk.core.ValueInput.createByString('30 mm'))
        inputs.addValueInput(self._CLR, 'Calibration clearance', units,
                             adsk.core.ValueInput.createByString('0.5 mm'))
        inputs.addValueInput(
            self._CLRLEN, 'Calibration distance (band length)', units,
            adsk.core.ValueInput.createByString('10 mm'))

        side = inputs.addDropDownCommandInput(
            self._SIDE, 'Clearance side',
            adsk.core.DropDownStyles.TextListDropDownStyle)
        for name in self._SIDES:
            side.listItems.add(name, name == 'Both', '')
        side.tooltip = ('"Both" relieves Pipe A and enlarges Pipe B\'s '
                        'socket — total gap is about 2 x clearance.')

        inputs.addBoolValueInput(self._STRICT, 'Fail if multiple bodies',
                                 True, '', False)
        inputs.addBoolValueInput(self._PREVIEW,
                                 'Preview only (no model change)',
                                 True, '', False)

    def on_execute(self, inputs: adsk.core.CommandInputs):
        app = adsk.core.Application.get()

        face_sel = inputs.itemById(self._FACE)
        if face_sel.selectionCount != 1:
            raise ValueError('Select exactly one planar end face of Pipe A.')
        # Keep the selection AS-IS (an assembly proxy stays a proxy) so the
        # pipeline works in world space; pipes.py handles native/context.
        face = face_sel.selection(0).entity

        offset = inputs.itemById(self._OFFSET).value
        clearance = inputs.itemById(self._CLR).value
        clearance_length = inputs.itemById(self._CLRLEN).value
        side = self._SIDES[inputs.itemById(self._SIDE).selectedItem.index]
        strict_multi = inputs.itemById(self._STRICT).value
        preview_only = inputs.itemById(self._PREVIEW).value

        result = pipes.calibrate_pipe_joint(
            app, face, offset, clearance, clearance_length,
            clearance_side=side.split()[0].lower(),
            strict_multi=strict_multi, preview_only=preview_only)

        head = ('Preview — no model change.\n' if result.preview_only
                else '')
        lines = [
            f'Pipe A: "{result.pipe_a_name}"',
            f'Pipe B: "{result.pipe_b_name or "(not detected)"}"',
            f'Offset {result.offset_mm:.2f} mm, clearance '
            f'{result.clearance_mm:.3f} mm over '
            f'{result.band_length_mm:.2f} mm, '
            f'{result.faces_affected} face(s).',
        ]
        if result.notes:
            lines.append('Notes: ' + '; '.join(result.notes))
        app.userInterface.messageBox(head + '\n'.join(lines),
                                     config.ADDIN_NAME)


COMMAND = PipeJointCalibrationCommand
