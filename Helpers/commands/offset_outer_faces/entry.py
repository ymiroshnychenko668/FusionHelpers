"""Instrument: Offset Outer Faces.

Press/Pull the outer faces of one or more selected solid bodies by a
plain offset value. Discovered automatically by the add-in because this
package contains ``entry.py`` exposing ``COMMAND``.
"""

import adsk.core
import adsk.fusion

import config
from command_base import InstrumentCommand
from lib import features


def _native(entity):
    """Native object for an occurrence-proxy entity, else the entity."""
    return entity.nativeObject if entity.assemblyContext else entity


def _selected(sel_input):
    """All entities currently in a SelectionCommandInput (native)."""
    return [_native(sel_input.selection(i).entity)
            for i in range(sel_input.selectionCount)]


class OffsetOuterFacesCommand(InstrumentCommand):
    CMD_ID = config.cmd_id('OffsetOuterFaces')
    NAME = 'Offset Outer Faces'
    TOOLTIP = ('Offset (Press/Pull) the outer faces of the selected solid '
               'bodies by the entered distance. Holes are kept by default; '
               'you can also pick specific faces to leave untouched.')

    _SEL = 'bodies'
    _EXCL = 'excludeFaces'
    _DIST = 'distance'
    _HOLES = 'excludeHoles'

    def build_inputs(self, inputs: adsk.core.CommandInputs):
        bodies = inputs.addSelectionInput(self._SEL, 'Bodies',
                                          'Select one or more solid bodies')
        bodies.addSelectionFilter('SolidBodies')
        bodies.setSelectionLimits(1, 0)   # min 1, max 0 = unlimited

        excl = inputs.addSelectionInput(
            self._EXCL, 'Faces to exclude',
            'Optional: faces to leave un-offset')
        excl.addSelectionFilter('SolidFaces')
        excl.setSelectionLimits(0, 0)     # optional, unlimited

        app = adsk.core.Application.get()
        design = adsk.fusion.Design.cast(app.activeProduct)
        units = design.unitsManager.defaultLengthUnits if design else 'mm'
        inputs.addValueInput(self._DIST, 'Offset size', units,
                             adsk.core.ValueInput.createByString('1 mm'))

        # Checkbox, enabled by default: skip concave cylindrical bores so
        # holes keep their size when the bodies are offset.
        inputs.addBoolValueInput(self._HOLES, 'Exclude holes', True,
                                 '', True)

    def on_execute(self, inputs: adsk.core.CommandInputs):
        app = adsk.core.Application.get()

        body_sel = inputs.itemById(self._SEL)
        if body_sel.selectionCount == 0:
            raise ValueError('Select at least one solid body.')
        bodies = _selected(body_sel)
        exclude_faces = _selected(inputs.itemById(self._EXCL))

        # Plain value in internal units (cm) — no parameter is created.
        distance = inputs.itemById(self._DIST).value
        exclude_holes = inputs.itemById(self._HOLES).value

        feature = features.offset_outer_faces(
            app, distance, bodies=bodies, exclude_holes=exclude_holes,
            exclude_faces=exclude_faces)

        notes = ['holes excluded' if exclude_holes else 'holes included']
        if exclude_faces:
            notes.append(f'{len(exclude_faces)} face(s) kept')
        app.userInterface.messageBox(
            f'Created "{feature.name}" — outer faces of {len(bodies)} '
            f'body(ies) offset ({", ".join(notes)}).', config.ADDIN_NAME)


COMMAND = OffsetOuterFacesCommand
