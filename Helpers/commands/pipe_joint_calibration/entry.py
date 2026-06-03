"""Instrument: Pipe Joint Calibration.

Select one or more Pipe A planar end profile faces; the helper sockets
the perpendicular Pipe B each runs into and adds a length-limited
calibration relief band on Pipe A so milled parts always fit. The
operation is repeated per selected profile. Discovered automatically
because this package contains entry.py exposing COMMAND.
"""

import json
import os

import adsk.core
import adsk.fusion

import config
from command_base import InstrumentCommand
from lib import pipes


def _native(entity):
    """Native object for an occurrence-proxy entity, else the entity."""
    return entity.nativeObject if entity.assemblyContext else entity


# Last-used dialog values are persisted here (per user, outside the repo,
# survives Fusion restarts AND add-in reloads) so the dialog prefills
# with the previous run's parameters. All IO is best-effort: a missing
# or corrupt file simply falls back to the built-in defaults, and a
# save failure never disrupts the command.
_PREFS_PATH = os.path.join(os.path.expanduser('~'), '.fusionhelpers',
                           'pipe_joint_calibration.json')


def _load_prefs():
    try:
        with open(_PREFS_PATH, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_prefs(prefs):
    try:
        os.makedirs(os.path.dirname(_PREFS_PATH), exist_ok=True)
        with open(_PREFS_PATH, 'w', encoding='utf-8') as fh:
            json.dump(prefs, fh, indent=2)
    except Exception:
        pass


class PipeJointCalibrationCommand(InstrumentCommand):
    CMD_ID = config.cmd_id('PipeJointCalibration')
    NAME = 'Pipe Joint Calibration'
    TOOLTIP = ('Select one or more Pipe A flat end profiles '
               '(square/rectangular hollow tube). For each, cuts a '
               'socket into the perpendicular Pipe B it meets and adds a '
               'calibration relief band on Pipe A so milled joints '
               'always fit.')

    _FACE = 'endFace'
    _OFFSET = 'offsetSize'
    _CLR = 'clearance'
    _CLRLEN = 'clearanceLength'
    _SIDE = 'clearanceSide'
    _STRICT = 'strictMulti'

    _SIDES = ('Both', 'A only', 'B only')

    def build_inputs(self, inputs: adsk.core.CommandInputs):
        face = inputs.addSelectionInput(
            self._FACE, 'Pipe A end faces',
            'Select one or more Pipe A flat end profile faces — the '
            'operation is repeated for each')
        face.addSelectionFilter('SolidFaces')
        face.setSelectionLimits(1, 0)   # 1+, no upper limit (multi)

        app = adsk.core.Application.get()
        design = adsk.fusion.Design.cast(app.activeProduct)
        units = design.unitsManager.defaultLengthUnits if design else 'mm'

        # Prefill from the previous run's values (else built-in defaults).
        prefs = _load_prefs()

        def _expr(key, default):
            v = prefs.get(key)
            return v if isinstance(v, str) and v.strip() else default

        inputs.addValueInput(
            self._OFFSET, 'Offset size (penetration)', units,
            adsk.core.ValueInput.createByString(_expr('offset', '30 mm')))
        inputs.addValueInput(
            self._CLR, 'Calibration clearance', units,
            adsk.core.ValueInput.createByString(_expr('clearance',
                                                      '0.5 mm')))
        inputs.addValueInput(
            self._CLRLEN, 'Calibration distance (band length)', units,
            adsk.core.ValueInput.createByString(
                _expr('clearance_length', '10 mm')))

        saved_side = prefs.get('side')
        if saved_side not in self._SIDES:
            saved_side = 'Both'
        side = inputs.addDropDownCommandInput(
            self._SIDE, 'Clearance side',
            adsk.core.DropDownStyles.TextListDropDownStyle)
        for name in self._SIDES:
            side.listItems.add(name, name == saved_side, '')
        side.tooltip = ('"Both" relieves Pipe A and enlarges Pipe B\'s '
                        'socket — total gap is about 2 x clearance.')

        inputs.addBoolValueInput(self._STRICT, 'Fail if multiple bodies',
                                 True, '',
                                 bool(prefs.get('strict', False)))

    def on_execute(self, inputs: adsk.core.CommandInputs):
        app = adsk.core.Application.get()

        face_sel = inputs.itemById(self._FACE)
        if face_sel.selectionCount < 1:
            raise ValueError('Select at least one planar end face of '
                             'Pipe A.')
        # Keep each selection AS-IS (an assembly proxy stays a proxy) so
        # the pipeline works in world space; pipes.py handles
        # native/context. The operation is repeated for every profile.
        faces = [face_sel.selection(i).entity
                 for i in range(face_sel.selectionCount)]

        offset = inputs.itemById(self._OFFSET).value
        clearance = inputs.itemById(self._CLR).value
        clearance_length = inputs.itemById(self._CLRLEN).value
        side = self._SIDES[inputs.itemById(self._SIDE).selectedItem.index]
        strict_multi = inputs.itemById(self._STRICT).value

        # Persist these values now (before running) so the next dialog
        # open prefills them even if this run errors. Store the unit-
        # bearing expressions so prefill round-trips exactly.
        _save_prefs({
            'offset': inputs.itemById(self._OFFSET).expression,
            'clearance': inputs.itemById(self._CLR).expression,
            'clearance_length': inputs.itemById(self._CLRLEN).expression,
            'side': side,
            'strict': strict_multi,
        })

        results = pipes.calibrate_pipe_joints(
            app, faces, offset, clearance, clearance_length,
            clearance_side=side.split()[0].lower(),
            strict_multi=strict_multi)

        ok = sum(1 for r in results if not r.error)
        failed = len(results) - ok
        head = '%d profile(s): %d succeeded%s\n' % (
            len(results), ok,
            (', %d failed' % failed) if failed else '')
        blocks = []
        for i, r in enumerate(results, 1):
            if r.error:
                blocks.append('#%d  "%s" — FAILED: %s'
                              % (i, r.pipe_a_name, r.error))
                continue
            txt = ('#%d  A:"%s"  B:"%s"  off %.2f / clr %.3f / dist '
                   '%.2f mm  %d feat.'
                   % (i, r.pipe_a_name,
                      r.pipe_b_name or '(not detected)',
                      r.offset_mm, r.clearance_mm, r.band_length_mm,
                      r.faces_affected))
            if r.notes:
                txt += '\n     ' + '; '.join(r.notes)
            blocks.append(txt)
        app.userInterface.messageBox(head + '\n'.join(blocks),
                                     config.ADDIN_NAME)


COMMAND = PipeJointCalibrationCommand
