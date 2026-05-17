"""Body selection and outer-face traversal helpers."""

import adsk.core
import adsk.fusion


def _native(body: adsk.fusion.BRepBody) -> adsk.fusion.BRepBody:
    """Return the native body when given an assembly-context proxy.

    Features must be created on the native object in its owning component,
    not on an occurrence proxy.
    """
    return body.nativeObject if body.assemblyContext else body


def face_normal(face: adsk.fusion.BRepFace) -> adsk.core.Vector3D:
    """Return the normalized solid-outward normal of ``face``.

    ``BRepFace.evaluator.getNormalAtPoint`` already returns the face-oriented
    (solid-outward) normal — do NOT re-apply ``isParamReversed`` (that
    double-flips it; see the hole-detection regression in CLAUDE.md).
    """
    ok, normal = face.evaluator.getNormalAtPoint(face.pointOnFace)
    if not ok:
        raise RuntimeError('Could not evaluate face normal.')
    normal = normal.copy()
    normal.normalize()
    return normal


def is_planar(face: adsk.fusion.BRepFace) -> bool:
    """True if ``face``'s surface is a plane."""
    geom = face.geometry
    return geom is not None and \
        geom.surfaceType == adsk.core.SurfaceTypes.PlaneSurfaceType


def is_perpendicular(face: adsk.fusion.BRepFace,
                     axis: adsk.core.Vector3D,
                     angtol: float = 1e-4) -> bool:
    """True if ``face`` is planar and its normal is perpendicular to ``axis``.

    ``angtol`` is on the normalized dot product (~0.006 deg at 1e-4).
    """
    if not is_planar(face):
        return False
    ax = axis.copy()
    ax.normalize()
    return abs(face_normal(face).dotProduct(ax)) < angtol


def faces_adjacent_to(face: adsk.fusion.BRepFace) -> list:
    """Return the distinct faces sharing an edge with ``face``.

    Faces belong to the same body, so ``tempId`` is a safe dedup key
    within this (unmodified) model state.
    """
    seen = {face.tempId}
    adjacent = []
    for edge in face.edges:
        for nbr in edge.faces:
            if nbr.tempId not in seen:
                seen.add(nbr.tempId)
                adjacent.append(nbr)
    return adjacent


def resolve_body(ui: adsk.core.UserInterface) -> adsk.fusion.BRepBody:
    """Return the solid body implied by the current selection.

    - A selected body is used directly.
    - A selected face resolves to its parent body (convenient UX).

    The interactive ``ui.selectEntity`` picker is intentionally not used: it
    asserts/aborts unreliably when a script is launched from the Scripts and
    Add-Ins dialog. Commands use a ``SelectionCommandInput`` instead.
    """
    for sel in ui.activeSelections:
        ent = sel.entity
        if isinstance(ent, adsk.fusion.BRepBody):
            return _native(ent)
        if isinstance(ent, adsk.fusion.BRepFace):
            return _native(ent.body)

    raise ValueError(
        'Select a solid body (or one of its faces) first, '
        'then run Helpers again.')


def is_hole_face(face: adsk.fusion.BRepFace) -> bool:
    """True if ``face`` is a concave cylindrical face (a bore / hole wall).

    A cylinder is a hole when the solid material wraps *around* it, i.e. the
    face's outward normal points back toward the cylinder axis. A boss/pin
    is the convex case (normal points away from the axis) and is kept.
    Only cylinders are treated as holes (per project decision); cones and
    other surfaces are not.
    """
    geom = face.geometry
    if geom is None or geom.surfaceType != \
            adsk.core.SurfaceTypes.CylinderSurfaceType:
        return False
    cyl = adsk.core.Cylinder.cast(geom)
    ok, origin, axis, _radius = cyl.getData()
    if not ok:
        return False

    point = face.pointOnFace
    ok, normal = face.evaluator.getNormalAtPoint(point)
    if not ok:
        return False
    # BRepFace.evaluator.getNormalAtPoint already returns the solid-outward
    # (face-oriented) normal: for a bore it points toward the axis. Do NOT
    # re-apply isParamReversed — that double-flips and misses every hole.

    axis = axis.copy()
    axis.normalize()
    radial = adsk.core.Vector3D.create(point.x - origin.x,
                                       point.y - origin.y,
                                       point.z - origin.z)
    along = axis.copy()
    along.scaleBy(radial.dotProduct(axis))
    radial = adsk.core.Vector3D.create(radial.x - along.x,
                                       radial.y - along.y,
                                       radial.z - along.z)
    if radial.length < 1e-9:
        return False
    radial.normalize()
    # Concave (hole): outward normal opposes the radial-outward direction.
    return normal.dotProduct(radial) < 0.0


def collect_outer_faces(bodies, exclude_holes: bool = True,
                        exclude_faces=None) -> list:
    """Outer faces across one or more solid bodies.

    A solid's boundary is split into shells; ``BRepShell.isVoid`` is True for
    shells bounding internal cavities, so skipping them leaves exactly the
    outer faces. With ``exclude_holes`` (default) concave cylindrical bores
    are also dropped via :func:`is_hole_face`. Any face in ``exclude_faces``
    is dropped too — matched by ``entityToken`` (globally unique in the doc;
    ``tempId`` would collide across bodies) after normalising occurrence
    proxies to their native object.

    Returns a plain ``list`` of BRepFace: ``OffsetFacesFeatures.createInput``
    requires ``list[BRepFace]`` and raises a TypeError on an ObjectCollection
    (its argument is a ``std::vector<BRepFace>``, not auto-converted).
    """
    excluded_tokens = set()
    for face in (exclude_faces or []):
        token = _native(face).entityToken
        if token:
            excluded_tokens.add(token)

    faces = []
    for body in bodies:
        for lump in body.lumps:
            for shell in lump.shells:
                if shell.isVoid:
                    continue
                for face in shell.faces:
                    if exclude_holes and is_hole_face(face):
                        continue
                    if excluded_tokens and face.entityToken in \
                            excluded_tokens:
                        continue
                    faces.append(face)
    if not faces:
        raise ValueError('No outer faces to offset (after exclusions).')
    return faces


def outer_faces(body: adsk.fusion.BRepBody,
                exclude_holes: bool = True) -> list:
    """Single-body convenience wrapper around :func:`collect_outer_faces`."""
    return collect_outer_faces([body], exclude_holes=exclude_holes)
