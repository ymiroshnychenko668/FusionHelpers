"""Feature helpers built on the Fusion design timeline."""

import adsk.core
import adsk.fusion

from .selection import resolve_body, collect_outer_faces


def _as_value_input(distance):
    """Coerce ``distance`` to a ValueInput.

    Accepts a ValueInput (used as-is), a number (centimetres — Fusion's
    internal unit), or an expression string such as ``"2 mm"``.
    """
    if isinstance(distance, adsk.core.ValueInput):
        return distance
    if isinstance(distance, str):
        return adsk.core.ValueInput.createByString(distance)
    return adsk.core.ValueInput.createByReal(float(distance))


def offset_outer_faces(app: adsk.core.Application,
                       distance,
                       bodies=None,
                       exclude_holes: bool = True,
                       exclude_faces=None
                       ) -> adsk.fusion.OffsetFacesFeature:
    """Press/Pull the outer faces of one or more solid bodies by ``distance``.

    ``distance`` is a plain offset value (a ValueInput, a number in
    centimetres, or an expression string like ``"2 mm"``). No user
    parameter is created. A positive value moves faces along their normal
    (grows the bodies outward); a negative value shrinks them.

    ``bodies`` is a single BRepBody or a list of them; it defaults to the
    current selection (see :func:`resolve_body`). With ``exclude_holes``
    (default) concave cylindrical bores are skipped, and any face in
    ``exclude_faces`` is left untouched as well.

    A single OffsetFaces feature is created spanning all collected faces
    (the API allows faces from multiple bodies/components).
    """
    if bodies is None:
        bodies = [resolve_body(app.userInterface)]
    elif not isinstance(bodies, (list, tuple)):
        bodies = [bodies]
    if not bodies:
        raise ValueError('No bodies to offset.')

    faces = collect_outer_faces(bodies, exclude_holes=exclude_holes,
                                exclude_faces=exclude_faces)

    offsets = bodies[0].parentComponent.features.offsetFacesFeatures
    inp = offsets.createInput(faces, _as_value_input(distance))
    if not inp:
        raise RuntimeError(
            f'Could not build offset input for {len(faces)} face(s).')

    try:
        return offsets.add(inp)
    except Exception as exc:  # pylint: disable=broad-except
        raise RuntimeError(
            f'Offset of {len(faces)} outer face(s) across '
            f'{len(bodies)} body(ies) failed: {exc}') from exc
