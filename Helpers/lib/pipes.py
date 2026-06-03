"""Pipe joint calibration pipeline (UI-free, assembly-correct).

From Pipe A's planar end profile (selected as an assembly proxy face) this
auto-detects the perpendicular Pipe B, cuts a socket into B, extends Pipe A
into that socket so it physically plugs in, and adds a length-limited
calibration relief band so a CNC mill can finish a square/rectangular
hollow-tube saddle joint to a guaranteed fit.

Sketch strategy (mirrors the manual Fusion workflow the user prescribed):

  1. create a sketch on the selected end face (a root sketch ON the proxy
     face — `modelToSketchSpace` is occurrence-aware so world geometry
     converts correctly with no transform/BaseFeature machinery);
  2. draw the squared OUTER rectangle S of the tube (rounded corners
     squared off, inner bore ignored — a clean rectangle is drawn, not the
     real edges);
  3. draw the calibrated inner rectangle S-c directly from the same
     extents (deterministic — no fragile sketch-offset direction);
  4. project Pipe B onto the sketch (diagnostic / 2nd intersection signal);
  5. extrude-CUT the socket into Pipe B;
  6. extend Pipe A into the socket by offsetting its native end face;
  7. extrude-CUT the calibration relief over the band [0, clearance_length].

Every mutating op is a Cut-extrude (cross-occurrence via
`participantBodies`, proxies accepted) or the proven end-face offset on
Pipe A's native body — there is NO cross-occurrence Join (the historically
hardest operation). Detection stays a pure `TemporaryBRepManager`
measurement (timeline-neutral). Outer perimeter only; no Fusion user
parameters.
"""

import adsk.core
import adsk.fusion

from .selection import face_normal, is_planar, is_perpendicular  # noqa: F401

try:
    from log import log, banner
except Exception:  # pragma: no cover
    def log(_m):
        pass

    def banner(_m):
        pass

_VOL_EPS = 1e-7        # cm^3 — minimum meaningful intersection volume
_PAD = 1e-4            # cm — outward pad so cuts are not zero-gap coincident
_PERP_DOT = 0.035      # |axisA·axisB| below this ≈ within ~2° of perpendicular
_PROF_TOL = 5e-4       # cm — sketch-space bbox tolerance for profile match


class PipeJointResult:
    """Plain summary returned to the instrument for its messageBox."""

    def __init__(self):
        self.pipe_a_name = ''
        self.pipe_b_name = ''
        self.socket_feature_name = ''
        self.band_feature_name = ''
        self.offset_mm = 0.0
        self.clearance_mm = 0.0
        self.band_length_mm = 0.0
        self.entry_depth_mm = 0.0
        self.axis_dot = 0.0
        self.overlap_cm3 = 0.0
        self.faces_affected = 0
        self.notes = []
        self.error = ''   # set by the batch wrapper if this profile failed


# ---- vector helpers -----------------------------------------------------

def _v(a, b):
    return adsk.core.Vector3D.create(a.x - b.x, a.y - b.y, a.z - b.z)


def _unit(vec):
    w = vec.copy()
    w.normalize()
    return w


def _axial(pt, p0, u):
    return _v(pt, p0).dotProduct(u)


def _inv(matrix):
    m = matrix.copy()
    m.invert()
    return m


# ---- selection / validation --------------------------------------------

def _line_edges(face):
    out = []
    for e in face.edges:
        c = e.geometry
        if c is not None and \
                c.curveType == adsk.core.Curve3DTypes.Line3DCurveType:
            out.append(e)
    return out


def _validate_end_face(face):
    """Return the selected face after basic validation (kept AS-IS — a
    proxy stays a proxy so its geometry is world-space)."""
    if not is_planar(face):
        raise ValueError(
            'Select the flat end face of the tube — it is not planar.')
    body = face.body
    if body is None or not body.isSolid:
        raise ValueError('The selected face is not on a solid body.')
    if not _line_edges(face):
        raise ValueError(
            'Pipe Joint Calibration supports square/rectangular hollow '
            'tube only — the selected end has no straight sides '
            '(looks round/oval).')
    return face


# ---- world-space squared-outer-rectangle frame ------------------------

def _face_centroid(face):
    c = face.centroid
    return c if c is not None else face.pointOnFace


def _outer_frame(face):
    """Compute the squared OUTER rectangle of the tube end in WORLD space.

    Returns (axis, o, d1, d2, a0, a1, b0, b1) where axis is the face-plane
    normal (unit, world), o the face centroid, d1/d2 the in-plane section
    axes, and a/b the half-extents of the OUTER perimeter (inner loop &
    rounded corners excluded naturally by the bounding box).
    """
    plane = adsk.core.Plane.cast(face.geometry)
    axis = _unit(plane.normal)
    o = _face_centroid(face)

    # arbitrary in-plane basis from the first line edge
    seed = None
    for e in _line_edges(face):
        d = _v(e.endVertex.geometry, e.startVertex.geometry)
        d = adsk.core.Vector3D.create(
            d.x - axis.x * d.dotProduct(axis),
            d.y - axis.y * d.dotProduct(axis),
            d.z - axis.z * d.dotProduct(axis))
        if d.length > 1e-6:
            seed = _unit(d)
            break
    if seed is None:
        raise ValueError('Selected end has no straight sides (round/oval).')
    e0 = seed
    e1 = _unit(axis.crossProduct(e0))

    # pick the OUTER loop = largest in-plane bounding-box area
    best_loop, best_area = None, -1.0
    for loop in face.loops:
        a = []
        b = []
        for ed in loop.edges:
            for vx in (ed.startVertex.geometry, ed.endVertex.geometry):
                a.append(_v(vx, o).dotProduct(e0))
                b.append(_v(vx, o).dotProduct(e1))
        if not a:
            continue
        area = (max(a) - min(a)) * (max(b) - min(b))
        if area > best_area:
            best_area, best_loop = area, loop
    if best_loop is None:
        raise ValueError('Could not determine the outer profile loop.')

    # d1 = direction of the LONGEST straight flat of the outer loop.
    # (An angle-doubled "vote" is degenerate for a 90°-symmetric square —
    # it cancels to ~0 and atan2 of numerical noise yields a ~45° rotated
    # box. The flat direction taken directly is exact for square AND
    # rectangle; corner arcs are short and skipped.)
    best_dir, best_len = None, -1.0
    for ed in best_loop.edges:
        g = ed.geometry
        if g is None or g.curveType != adsk.core.Curve3DTypes.Line3DCurveType:
            continue
        d = _v(ed.endVertex.geometry, ed.startVertex.geometry)
        d = adsk.core.Vector3D.create(
            d.x - axis.x * d.dotProduct(axis),
            d.y - axis.y * d.dotProduct(axis),
            d.z - axis.z * d.dotProduct(axis))
        if d.length > best_len + 1e-9:
            best_len, best_dir = d.length, d
    if best_dir is None or best_len < 1e-6:
        raise ValueError(
            'Selected end has no straight outer sides (round/oval).')
    d1 = _unit(best_dir)
    d2 = _unit(axis.crossProduct(d1))

    # extents over the OUTER loop (vertices + an on-edge sample per edge,
    # so rounded-corner arcs are bounded too)
    a_vals = []
    b_vals = []
    for ed in best_loop.edges:
        pts = [ed.startVertex.geometry, ed.endVertex.geometry]
        try:
            pts.append(ed.pointOnEdge)
        except Exception:
            pass
        for p in pts:
            a_vals.append(_v(p, o).dotProduct(d1))
            b_vals.append(_v(p, o).dotProduct(d2))
    return (axis, o, d1, d2,
            min(a_vals), max(a_vals), min(b_vals), max(b_vals))


def _make_plug(tmp, frame, sgn, depth):
    """Create a world-space solid box plug for one axis sign (detection
    only — never committed to the timeline)."""
    axis, o, d1, d2, a0, a1, b0, b1 = frame
    ca, cb = (a0 + a1) / 2.0, (b0 + b1) / 2.0
    center = adsk.core.Point3D.create(
        o.x + d1.x * ca + d2.x * cb + axis.x * sgn * depth / 2.0,
        o.y + d1.y * ca + d2.y * cb + axis.y * sgn * depth / 2.0,
        o.z + d1.z * ca + d2.z * cb + axis.z * sgn * depth / 2.0)
    obb = adsk.core.OrientedBoundingBox3D.create(
        center, axis, d1, depth,
        (a1 - a0) + 2 * _PAD, (b1 - b0) + 2 * _PAD)
    box = tmp.createBox(obb)
    if box is None or box.volume <= 0:
        raise RuntimeError(
            'Internal error: could not build the rectangular penetration '
            'tool from the selected end.')
    return box


# ---- detection ----------------------------------------------------------

def _bbox_long_axis(body):
    """Unit vector along the body's longest world bounding-box dimension."""
    bb = body.boundingBox
    dx = bb.maxPoint.x - bb.minPoint.x
    dy = bb.maxPoint.y - bb.minPoint.y
    dz = bb.maxPoint.z - bb.minPoint.z
    if dx >= dy and dx >= dz:
        return adsk.core.Vector3D.create(1, 0, 0)
    if dy >= dx and dy >= dz:
        return adsk.core.Vector3D.create(0, 1, 0)
    return adsk.core.Vector3D.create(0, 0, 1)


def _candidates(design, skip_tokens):
    out = []
    root = design.rootComponent
    for b in root.bRepBodies:
        if b.isSolid and b.entityToken not in skip_tokens:
            out.append(b)
    for occ in root.allOccurrences:
        for b in occ.bRepBodies:
            if b.isSolid and b.entityToken not in skip_tokens:
                out.append(b)
    return out


def _detect_b(tmp, plug, candidates, axis, strict_multi):
    """Return (proxyB, overlap_cm3, axis_dot, note). Gate on genuine
    perpendicularity and a real transverse saddle, not first contact."""
    plug_vol = plug.volume
    hits = []
    for cand in candidates:
        cc = tmp.copy(cand)
        ok = tmp.booleanOperation(
            cc, tmp.copy(plug),
            adsk.fusion.BooleanTypes.IntersectionBooleanType)
        if not ok or cc.volume <= _VOL_EPS:
            continue
        b_axis = _bbox_long_axis(cand)
        dot = abs(axis.dotProduct(b_axis))
        perp = dot < _PERP_DOT
        saddle = cc.volume >= 0.02 * plug_vol
        if perp and saddle:
            hits.append((cand, cc.volume, dot))
    if not hits:
        return None, 0.0, 1.0, ''
    hits.sort(key=lambda h: h[1], reverse=True)
    note = ''
    if len(hits) > 1:
        if strict_multi:
            raise ValueError(
                f'{len(hits)} perpendicular bodies intersect the extended '
                f'Pipe A. Hide the extras or turn off "Fail if multiple '
                f'bodies".')
        note = f'{len(hits)} candidate bodies; chose the largest overlap.'
    return hits[0][0], hits[0][1], hits[0][2], note


def _entry_depth(tmp, plug, proxy_b, p0, u):
    """Axial thickness of B's entry wall (the pocket lump that touches the
    joint mouth). Diagnostic only — never gates the band length."""
    pocket = tmp.copy(plug)
    if not tmp.booleanOperation(
            pocket, tmp.copy(proxy_b),
            adsk.fusion.BooleanTypes.IntersectionBooleanType):
        return 0.0
    best = None
    for lump in pocket.lumps:
        ts = []
        for f in lump.faces:
            for vx in f.vertices:
                ts.append(_axial(vx.geometry, p0, u))
        if not ts:
            continue
        lo, hi = min(ts), max(ts)
        if best is None or lo < best[0]:
            best = (lo, hi)
    if best is None:
        return 0.0
    return best[1] - best[0]


# ---- assembly helpers ---------------------------------------------------

def _occ_of(entity):
    return entity.assemblyContext   # Occurrence or None


def _native_body(body):
    return body.nativeObject if body.assemblyContext else body


def _offset_face(comp, native_face, distance, name):
    """Parametrically offset ``native_face`` (a planar BRepFace) by
    ``distance`` cm along its outward normal — used to EXTEND Pipe A's
    end into B's socket on A's own body (no BaseFeature appended).
    ``OffsetFacesFeatures.createInput`` needs a python list, not an
    ObjectCollection."""
    offs = comp.features.offsetFacesFeatures
    inp = offs.createInput([native_face],
                           adsk.core.ValueInput.createByReal(distance))
    if not inp:
        raise RuntimeError(
            'Internal error: could not build the end-face offset for '
            f'"{native_face.body.name}".')
    try:
        feat = offs.add(inp)
    except Exception as exc:  # pylint: disable=broad-except
        raise RuntimeError(
            f'Extending "{native_face.body.name}" by offsetting its end '
            f'face failed: {exc}') from exc
    try:
        feat.name = name
    except Exception:  # pragma: no cover
        pass
    return feat


# ---- sketch pipeline ----------------------------------------------------

def _make_face_sketch(root, proxy_face, name):
    """Root sketch ON the selected proxy face (no projected edges, so the
    only profiles are the rectangles we draw). No ``occurrenceForCreation``
    is needed: the sketch lives in root (verified API rule)."""
    sk = root.sketches.addWithoutEdges(proxy_face)
    if sk is None:
        raise RuntimeError(
            'Could not create a sketch on the selected end face.')
    try:
        sk.name = name
    except Exception:  # pragma: no cover
        pass
    return sk


def _w2s(sk, world_pt):
    """World/root point -> sketch space (occurrence-aware; the single
    audited conversion site)."""
    return sk.modelToSketchSpace(world_pt)


def _rect_corners_world(frame, inset):
    """The 4 world corners of the section rectangle, each side moved
    inward by ``inset`` (0 = outer S; clearance = inner S-c). No axis term
    — corners lie ON the face plane (depth is the extrude extent)."""
    axis, o, d1, d2, a0, a1, b0, b1 = frame
    a0 += inset
    a1 -= inset
    b0 += inset
    b1 -= inset

    def P(sa, sb):
        return adsk.core.Point3D.create(
            o.x + d1.x * sa + d2.x * sb,
            o.y + d1.y * sa + d2.y * sb,
            o.z + d1.z * sa + d2.z * sb)

    return [P(a0, b0), P(a1, b0), P(a1, b1), P(a0, b1)]


def _draw_rect(sk, world_pts):
    """Draw a closed 4-line rectangle from world corners; return its
    sketch-space AABB (minx,miny,maxx,maxy). Chained sketch points keep
    the loop topologically closed so a profile forms."""
    s = [_w2s(sk, p) for p in world_pts]
    L = sk.sketchCurves.sketchLines
    l0 = L.addByTwoPoints(s[0], s[1])
    l1 = L.addByTwoPoints(l0.endSketchPoint, s[2])
    l2 = L.addByTwoPoints(l1.endSketchPoint, s[3])
    L.addByTwoPoints(l2.endSketchPoint, l0.startSketchPoint)
    xs = [p.x for p in s]
    ys = [p.y for p in s]
    return (min(xs), min(ys), max(xs), max(ys))


def _project_b_section(sk, proxy_b):
    """Project Pipe B's section onto the sketch (the user's step 3).
    Returns (count, sketch-space bbox (minx,miny,maxx,maxy) or None) then
    deletes the curves so they cannot pollute profile resolution. NOT a
    detection gate — `_detect_b` already confirmed B with the depth plug,
    and a valid saddle joint can have its end-face plane merely grazing B.
    The bbox is used to skip Pipe A relief when B's footprint coincides
    with Pipe A's own profile (a flush/aligned joint)."""
    try:
        proj = sk.projectCutEdges(proxy_b)
    except Exception:
        return 0, None
    items = [proj.item(i) for i in range(proj.count)] if proj else []
    n = len(items)
    bb = None
    for it in items:
        try:
            box = it.boundingBox
        except Exception:
            box = None
        if box is not None:
            mn, mx = box.minPoint, box.maxPoint
            if bb is None:
                bb = [mn.x, mn.y, mx.x, mx.y]
            else:
                bb[0] = min(bb[0], mn.x)
                bb[1] = min(bb[1], mn.y)
                bb[2] = max(bb[2], mx.x)
                bb[3] = max(bb[3], mx.y)
    for it in items:
        try:
            it.deleteMe()
        except Exception:  # pragma: no cover
            pass
    return n, (tuple(bb) if bb else None)


def _bbox_corresponds(b1, b2, tol):
    """True if two sketch-space AABBs coincide on every side within tol."""
    if b1 is None or b2 is None:
        return False
    return (abs(b1[0] - b2[0]) <= tol and abs(b1[1] - b2[1]) <= tol and
            abs(b1[2] - b2[2]) <= tol and abs(b1[3] - b2[3]) <= tol)


def _resolve_profiles(sk, bbox_outer, bbox_inner):
    """Classify the sketch's profiles (inner S-c solid + the S..S-c ring)
    by sketch-space bbox. Returns (inner_profile, ring_profile)."""
    profs = sk.profiles

    def matches(pb, box):
        return (abs(pb.minPoint.x - box[0]) < _PROF_TOL and
                abs(pb.minPoint.y - box[1]) < _PROF_TOL and
                abs(pb.maxPoint.x - box[2]) < _PROF_TOL and
                abs(pb.maxPoint.y - box[3]) < _PROF_TOL)

    inner = ring = None
    for i in range(profs.count):
        p = profs.item(i)
        pb = p.boundingBox
        if matches(pb, bbox_inner):
            inner = p
        elif matches(pb, bbox_outer):
            ring = p
    if inner is None or ring is None:
        raise RuntimeError(
            'Sketch profiles did not resolve (got %d; need the inner S-c '
            'profile + the S..S-c ring). Try a different end face or a '
            'smaller clearance.' % profs.count)
    return inner, ring


def _sketch_normal_world(sk):
    """The sketch-plane normal expressed in world/root space."""
    a = sk.sketchToModelSpace(adsk.core.Point3D.create(0, 0, 0))
    b = sk.sketchToModelSpace(adsk.core.Point3D.create(0, 0, 1))
    return _unit(_v(b, a))


def _extrude_dir(sk, u):
    """(ExtentDirections value, start-offset sign) so the extrude advances
    from the joint mouth in +u (into B / into the engagement). Pinned by
    the world geometry, never by the default sketch-normal sign."""
    pos = _sketch_normal_world(sk).dotProduct(u) >= 0.0
    if pos:
        return adsk.fusion.ExtentDirections.PositiveExtentDirection, 1.0
    return adsk.fusion.ExtentDirections.NegativeExtentDirection, -1.0


def _extrude(root, profile, operation, dist_cm, direction,
             participant_bodies=None, name=None, start_off_cm=0.0,
             symmetric=False):
    """One audited extrude builder. ``creationOccurrence`` is never set
    (sketch + profiles + extrude all live in root; cross-occurrence
    targeting is done purely via ``participantBodies`` — proxies
    accepted). ``symmetric`` extrudes ``dist_cm`` on BOTH sides of the
    sketch plane (per-side), so the relief straddles the joint."""
    exf = root.features.extrudeFeatures
    cin = exf.createInput(profile, operation)
    if symmetric:
        cin.setSymmetricExtent(
            adsk.core.ValueInput.createByReal(dist_cm), False)
    else:
        if abs(start_off_cm) > 1e-9:
            cin.startExtent = adsk.fusion.OffsetStartDefinition.create(
                adsk.core.ValueInput.createByReal(start_off_cm))
        ext = adsk.fusion.DistanceExtentDefinition.create(
            adsk.core.ValueInput.createByReal(dist_cm))
        cin.setOneSideExtent(ext, direction)
    if participant_bodies:
        cin.participantBodies = participant_bodies
    try:
        feat = exf.add(cin)
    except Exception as exc:  # pylint: disable=broad-except
        raise RuntimeError('Extrude (%s) failed: %s'
                           % (name or 'unnamed', exc)) from exc
    if name:
        try:
            feat.name = name
        except Exception:  # pragma: no cover
            pass
    return feat


def _group_timeline(design, created, sketch, name):
    """Collapse exactly this run's items into one named timeline group.

    PURELY COSMETIC and correctness-safe: cross-occurrence features get
    re-homed by Fusion so they are NOT a simple [start..count-1] run —
    grouping is therefore done over the actual `timelineObject.index`
    set, and ONLY when those form a clean contiguous run of just our
    items (otherwise skipped). The timeline is ALWAYS left fully computed
    (marker at end) via the finally, so grouping can never leave a
    feature rolled back / unapplied (that bug made the A relief vanish)."""
    try:
        idx = []
        for feat in created:
            try:
                idx.append(feat.timelineObject.index)
            except Exception:
                pass
        if sketch is not None:
            try:
                idx.append(sketch.timelineObject.index)
            except Exception:
                pass
        if len(idx) >= 2:
            lo, hi = min(idx), max(idx)
            if hi - lo + 1 == len(idx):     # contiguous & all ours
                grp = design.timeline.timelineGroups.add(lo, hi)
                if grp is not None:
                    try:
                        grp.name = name
                    except Exception:  # pragma: no cover
                        pass
                    try:
                        grp.isCollapsed = True
                    except Exception:  # pragma: no cover
                        pass
                return grp
        return None
    except Exception:
        return None
    finally:
        try:
            design.timeline.moveToEnd()
        except Exception:  # pragma: no cover
            pass


def _key(comp, body):
    """A per-pipe-unique name key. Many tube components each contain a
    body literally named 'Body1', so feature/sketch names keyed on the
    body name alone collide across DIFFERENT pipes (multi-profile would
    then falsely report 'already calibrated'). The component name is
    unique within a Fusion design, so qualify by it."""
    try:
        return '%s_%s' % (comp.name, body.name)
    except Exception:
        return body.name


def _end_tag(axis):
    """Short, stable tag distinguishing the TWO ends of ONE pipe body.

    A pipe is a single body with two end faces whose outward normals are
    antiparallel; keying the idempotency marker by component+body alone
    flags the OPPOSITE end (a genuinely different joint) as 'already
    calibrated'. The selected end-face plane normal is stable across the
    calibration (the extend only slides the face ALONG its normal, never
    rotates it), so the two ends always get distinct (negated) tags while
    re-selecting the same end stays identical."""
    return 'e%+d%+d%+d' % (round(axis.x * 8), round(axis.y * 8),
                           round(axis.z * 8))


def _ensure_component(native_body, occ):
    """Make ``native_body`` single in its own component for jointing.

    If the body is already the only body in its component, nothing is
    changed and its existing assembly occurrence is returned. Otherwise
    ``BRepBody.createComponent()`` moves it into a fresh component (a new
    occurrence inside the owning component); that new occurrence — on the
    same assembly path as ``occ`` — is found and returned. Returns
    ``(occurrence_or_None, created_bool)``."""
    comp = native_body.parentComponent
    if comp.bRepBodies.count <= 1:
        return occ, False
    nb = native_body.createComponent()
    if nb is None:
        raise RuntimeError(
            'Could not create a component from body "%s".'
            % native_body.name)
    newtok = nb.parentComponent.entityToken
    if occ is not None:
        for ch in occ.childOccurrences:
            if ch.component.entityToken == newtok:
                return ch, True
    # body was in root (no occurrence) — find the new root occurrence
    rc = nb.parentComponent.parentDesign.rootComponent
    for i in range(rc.occurrences.count):
        oc = rc.occurrences.item(i)
        if oc.component.entityToken == newtok:
            return oc, True
    return None, True


def _rigid_joint(root, occ_a, occ_b, name):
    """Add a rigid as-built joint between two occurrences (geometry is
    None for a rigid joint — they stay exactly where they are)."""
    if occ_a is None or occ_b is None:
        return None
    j = root.asBuiltJoints
    inp = j.createInput(occ_a, occ_b, None)
    inp.setAsRigidJointMotion()
    jt = j.add(inp)
    if jt is not None and name:
        try:
            jt.name = name
        except Exception:  # pragma: no cover
            pass
    return jt


# ---- orchestration ------------------------------------------------------

def calibrate_pipe_joint(app, face, offset, clearance, clearance_length,
                         clearance_side='both',
                         strict_multi=False) -> PipeJointResult:
    """Socket Pipe B for Pipe A's end and relieve the joint band.

    ``offset``/``clearance``/``clearance_length`` are plain CENTIMETRE
    values (the dialog's ``.value``). No user parameter is created.
    Raises ``ValueError`` for bad input/geometry, ``RuntimeError`` for an
    internal Fusion-operation failure.
    """
    banner('pipe_joint_calibration')
    log('input offset=%.4f clr=%.4f len=%.4f side=%s'
        % (offset, clearance, clearance_length, clearance_side))

    if offset is None or abs(offset) <= 1e-5:
        raise ValueError('Offset size must be non-zero.')
    offset = abs(offset)
    if clearance is None or clearance <= 1e-5:
        raise ValueError('Calibration clearance must be greater than 0.')
    if clearance_length is None or clearance_length <= 1e-5:
        raise ValueError(
            'Calibration clearance length must be greater than 0.')

    face = _validate_end_face(face)
    design = adsk.fusion.Design.cast(app.activeProduct)

    native_a = _native_body(face.body)
    native_face = face.nativeObject if face.assemblyContext else face
    comp_a = native_a.parentComponent
    occ_a = _occ_of(face)

    frame = _outer_frame(face)
    axis, o = frame[0], frame[1]
    s_w = frame[5] - frame[4]
    s_h = frame[7] - frame[6]
    if 2.0 * clearance >= min(s_w, s_h):
        raise ValueError(
            'Calibration clearance is too large for this tube section '
            '(2 x clearance must be less than the smallest side).')

    r = PipeJointResult()
    r.pipe_a_name = native_a.name
    r.offset_mm = offset * 10.0
    r.clearance_mm = clearance * 10.0
    log('pipe A native=%r occ=%s o=(%.2f,%.2f,%.2f) axis=(%.3f,%.3f,%.3f)'
        % (native_a.name, occ_a.fullPathName if occ_a else None,
           o.x, o.y, o.z, axis.x, axis.y, axis.z))

    # Per-pipe/per-end unique name key (component + body so distinct
    # same-named bodies don't collide across a multi-profile run, PLUS an
    # end tag so the two ends of one pipe get distinct feature names).
    # NOTE: no "already calibrated" gate — re-running on an already
    # calibrated end is allowed and will stack another socket/relief/
    # joint (manage with undo); names may then repeat (Fusion permits it).
    a_key = '%s_%s' % (_key(comp_a, native_a), _end_tag(axis))
    sk_name = 'PipeJointSketch_%s' % a_key

    tmp = adsk.fusion.TemporaryBRepManager.get()
    skip = {face.body.entityToken, native_a.entityToken}

    # try both axis signs; keep the one whose plug detects a real B
    plug = proxy_b = note = None
    sgn_used = 1.0
    for sgn in (1.0, -1.0):
        cand_plug = _make_plug(tmp, frame, sgn, offset)
        cands = _candidates(design, skip)
        b, vol, dot, n = _detect_b(tmp, cand_plug, cands, axis,
                                   strict_multi)
        log('sign=%+d candidates=%d B=%s vol=%.4f dot=%.4f'
            % (sgn, len(cands), b.name if b else None, vol, dot))
        if b is not None:
            plug, proxy_b, note, sgn_used = cand_plug, b, n, sgn
            r.overlap_cm3, r.axis_dot = vol, dot
            break

    if proxy_b is None:
        raise ValueError(
            'No perpendicular Pipe B found in the path of the selected '
            'end. Increase the offset size, or check that Pipe B is '
            'positioned across Pipe A\'s end.')

    occ_b = _occ_of(proxy_b)
    native_b = _native_body(proxy_b)
    comp_b = native_b.parentComponent
    b_key = _key(comp_b, native_b)
    r.pipe_b_name = native_b.name
    if note:
        r.notes.append(note)

    u = axis.copy()
    u.scaleBy(sgn_used)                       # world unit into B
    p0 = o

    entry = _entry_depth(tmp, plug, proxy_b, p0, u)
    r.entry_depth_mm = entry * 10.0
    # Penetration / slot depth is ALWAYS the entered offset. The
    # calibration distance is the entered clearance_length — an
    # INDEPENDENT band length, measured from the joint along the
    # insertion axis, NOT clamped to the penetration. Pipe A's outer wall
    # is milled to S-c over the full distance (the cut only removes where
    # A actually exists); Pipe B's slot is S-c over the part that engages
    # (the socket is `offset` deep, so when the band >= offset the whole
    # socket is S-c with no nominal-S deep step).
    depth = offset
    eff_len = clearance_length
    r.band_length_mm = eff_len * 10.0
    log('pipe B native=%r occ=%s entry=%.4f offset=%.4f band=%.4f depth=%.4f'
        % (native_b.name, occ_b.fullPathName if occ_b else None,
           entry, offset, eff_len, depth))

    side = (clearance_side or 'both').lower()
    sock_name = 'PipeJointSocket_%s' % b_key

    root = design.rootComponent
    CUT = adsk.fusion.FeatureOperations.CutFeatureOperation
    created = []
    sk = None
    try:
        # Step 1 — sketch on the proxy end face (root, no projected edges)
        sk = _make_face_sketch(root, face, sk_name)

        # Steps 2-3 — draw outer rectangle S and calibrated inner S-c
        bbox_outer = _draw_rect(sk, _rect_corners_world(frame, 0.0))
        bbox_inner = _draw_rect(sk, _rect_corners_world(frame, clearance))

        # Step 4 — project Pipe B (diagnostic + flush-joint check). If B's
        # footprint coincides with Pipe A's own profile the joint is a
        # flush/aligned butt (no saddle wrap) — Pipe A's sides do not need
        # milling, so skip the Pipe A relief (still socket B + extend A).
        nproj, proj_bbox = _project_b_section(sk, proxy_b)
        log('projected B section curves=%d' % nproj)
        if nproj == 0:
            r.notes.append('Pipe B grazes the end plane (detected by '
                           'penetration depth).')
        skip_a = _bbox_corresponds(proj_bbox, bbox_outer, 0.05)
        if skip_a:
            r.notes.append('Pipe B section matches Pipe A profile — '
                           'skipping Pipe A side calibration.')
            log('skip A relief: projected B contour ~ A primitive')

        inner_p, ring_p = _resolve_profiles(sk, bbox_outer, bbox_inner)
        direction, ssign = _extrude_dir(sk, u)
        affected = 0

        # Step 5 — socket into B. When the slot is calibrated (both/b) it
        # is S-c over the band and nominal S deeper (two cuts); when only
        # A is machined (a) it is a single full-S socket. Depth is the
        # engagement depth (>= the calibration band).
        if side in ('both', 'b'):
            f1 = _extrude(root, inner_p, CUT, depth, direction,
                          [proxy_b], sock_name)
            created.append(f1)
            affected += 1
            deep = depth - eff_len
            if deep > 1e-4:
                f2 = _extrude(root, ring_p, CUT, deep, direction,
                              [proxy_b],
                              'PipeJointSocketDeep_%s' % b_key,
                              start_off_cm=ssign * eff_len)
                created.append(f2)
                affected += 1
            r.notes.append('B slot calibrated to S-%.3f mm over %.2f mm.'
                           % (clearance * 10.0,
                              min(eff_len, depth) * 10.0))
        else:
            full_s = adsk.core.ObjectCollection.create()
            full_s.add(inner_p)
            full_s.add(ring_p)
            f1 = _extrude(root, full_s, CUT, depth, direction,
                          [proxy_b], sock_name)
            created.append(f1)
            affected += 1
        r.socket_feature_name = sock_name
        log('socket cut %r (side=%s)' % (sock_name, side))

        # Step 6 — extend Pipe A into the socket by offsetting its native
        # end face (parametric, on A's own body; the outward normal points
        # out of A toward B so a positive offset lengthens A into B).
        ext = _offset_face(comp_a, native_face, depth,
                           'PipeJointExtendA_%s' % a_key)
        created.append(ext)
        affected += 1
        r.notes.append('Pipe A extended %.2f mm into B.' % (depth * 10.0))
        log('A end face offset %.4fcm to extend into B (%r)'
            % (depth, ext.name))

        # Step 7 — calibration relief on Pipe A: cut the S..S-c ring
        # SYMMETRICALLY about the joint plane, the calibration distance on
        # BOTH sides — the exposed length (millable, away from B) AND the
        # plugged-in length (so A's inserted wall is S-c and fits B's S-c
        # socket). Independent of how far A penetrates B. Skipped for a
        # flush joint (skip_a) or when side excludes A.
        if side in ('both', 'a') and not skip_a:
            fa = _extrude(root, ring_p, CUT, eff_len, direction,
                          [face.body],
                          'PipeJointReliefA_%s' % a_key,
                          symmetric=True)
            created.append(fa)
            affected += 1
            r.band_feature_name = fa.name
            r.notes.append('Pipe A wall reduced %.3f mm over %.2f mm '
                           'each side of the joint.'
                           % (clearance * 10.0, eff_len * 10.0))

        # Collapse the whole run into one named timeline group. Cosmetic
        # and correctness-safe (it always leaves the timeline fully
        # computed; it never disturbs the geometry just produced).
        grp = _group_timeline(
            design, created, sk,
            'PipeJoint_%s_%s' % (a_key, b_key))
        log('timeline group: %s'
            % (repr(grp.name) if grp is not None else 'skipped (non-contiguous)'))

        # AFTER calibration: each pipe body must be single in its own
        # component (split it out if it shares one), then rigidly joint
        # Pipe A's component to Pipe B's. This is a post-step — its own
        # try so a joint failure is reported but NEVER rolls back the
        # (successful) calibration.
        try:
            occ_aj, made_a = _ensure_component(native_a, occ_a)
            if made_a:
                r.notes.append('Created a component from Pipe A body.')
            occ_bj, made_b = _ensure_component(native_b, occ_b)
            if made_b:
                r.notes.append('Created a component from Pipe B body.')
            jt = _rigid_joint(
                design.rootComponent, occ_aj, occ_bj,
                'PipeJointRigid_%s_%s' % (a_key, b_key))
            if jt is not None:
                r.notes.append('Rigid joint added between Pipe A and '
                               'Pipe B components.')
                log('rigid joint %r' % jt.name)
            else:
                r.notes.append('Rigid joint skipped (Pipe A/B have no '
                               'assembly occurrence to joint).')
                log('rigid joint skipped (no occurrences)')
        except Exception as exc:  # pylint: disable=broad-except
            r.notes.append('Component / rigid-joint step failed: %s' % exc)
            log('component/joint step failed: %s' % exc)

        r.faces_affected = affected
        log('DONE B=%r features=%d' % (native_b.name, len(created)))
        return r
    except Exception:
        for feat in reversed(created):
            try:
                feat.deleteMe()
            except Exception:  # pragma: no cover
                pass
        if sk is not None:
            try:
                sk.deleteMe()
            except Exception:  # pragma: no cover
                pass
        raise


def calibrate_pipe_joints(app, faces, offset, clearance, clearance_length,
                          clearance_side='both', strict_multi=False):
    """Repeat the calibration for EACH selected Pipe A profile.

    Returns a list of ``PipeJointResult`` (one per face, in selection
    order). A profile that fails does NOT abort the batch — its message
    is captured in that result's ``.error`` and the run continues (each
    single calibration already rolls back its own partial features on
    failure, so a failed profile leaves the model clean)."""
    faces = list(faces)
    banner('pipe_joint_calibration BATCH n=%d' % len(faces))
    results = []
    for idx, face in enumerate(faces):
        try:
            r = calibrate_pipe_joint(
                app, face, offset, clearance, clearance_length,
                clearance_side=clearance_side, strict_multi=strict_multi)
        except Exception as exc:  # pylint: disable=broad-except
            r = PipeJointResult()
            try:
                b = face.body
                r.pipe_a_name = (b.nativeObject.name
                                 if b.assemblyContext else b.name)
            except Exception:
                r.pipe_a_name = 'profile %d' % (idx + 1)
            r.error = str(exc)
            log('BATCH profile %d (%s) FAILED: %s'
                % (idx + 1, r.pipe_a_name, exc))
        results.append(r)
    ok = sum(1 for x in results if not x.error)
    log('BATCH DONE: %d profiles, %d ok, %d failed'
        % (len(results), ok, len(results) - ok))
    return results
