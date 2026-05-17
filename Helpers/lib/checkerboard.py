"""Checkerboard ("chess") sketch pattern (UI-free, fully parametric).

Given the 4 lines of a sketched rectangle and one existing sketch
circle, this:

  1. parametrically re-centres the circle in the rectangle (a single
     construction-diagonal + midpoint constraint that survives a later
     rectangle resize);
  2. builds a native ``RectangularPatternConstraint`` aligned to the
     rectangle's edges, symmetric in both directions so the centred
     circle is the array's central cell;
  3. suppresses every cell whose (row+col) parity differs from the seed
     cell's, leaving a checkerboard of filled circles.

Everything is a real Fusion sketch constraint with auto-created
``ModelParameter`` quantity/distance values — exactly like the native
Rectangular Pattern dialog — so spacing/quantity edits re-flow. The
``isSuppressed`` mask is the supported, persisted mechanism for the
checkerboard. A documented diagonal-lattice fallback
(:func:`build_checkerboard_p2`) is kept for the contingency that the
mask proves non-persistent in a particular Fusion build.

API note (verified against the version-pinned FusionAPIReference):
``RectangularPatternConstraint.isSuppressed`` is laid out in row-column
order with the original/seed cell NOT counted — a q1*q2 grid yields a
list of length q1*q2-1 (FusionAPIReference/Fusion_API_Python_Reference/
defs/adsk/fusion.py:52696-52727).
"""

import adsk.core
import adsk.fusion

try:
    from log import log
except Exception:  # pragma: no cover
    def log(_m):
        pass

# Sketch-space tolerances (sketch units are centimetres internally).
_COINC_TOL = 1e-6      # cm — endpoint coincidence for the rectangle loop
_PERP_TOL = 1e-4       # on the normalized dot product (~0.006 deg)
_LEN_TOL = 1e-6        # cm — opposite-edge equal-length tolerance

# Marker used to recognise an instrument-owned centring diagonal on
# re-run (a construction line spanning two opposite rectangle corners).
_DIAG_TAG = 'FusionHelpers_CheckerboardCenterDiag'


class CheckerboardResult:
    """Plain summary handed back to the instrument for its messageBox."""

    def __init__(self):
        self.q1 = 0
        self.q2 = 0
        self.total_cells = 0
        self.filled_count = 0
        self.dist_type_name = ''
        self.preview = False
        self.notes = []


# ---------------------------------------------------------------------------
# Vector helpers (Point3D / Vector3D in sketch space)
# ---------------------------------------------------------------------------
def _vec(p_from, p_to):
    return adsk.core.Vector3D.create(p_to.x - p_from.x,
                                     p_to.y - p_from.y,
                                     p_to.z - p_from.z)


def _unit(v):
    u = v.copy()
    u.normalize()
    return u


def _dist(a, b):
    return _vec(a, b).length


# ---------------------------------------------------------------------------
# Rectangle analysis
# ---------------------------------------------------------------------------
class _Rect:
    """Ordered rectangle frame derived from 4 SketchLines."""

    def __init__(self, corners, ordered_lines, center, dir_u, dir_v,
                 len_u, len_v, line_u, line_v, diag_a, diag_b):
        self.corners = corners            # 4 SketchPoints, loop order
        self.ordered_lines = ordered_lines
        self.center = center              # Point3D
        self.dir_u = dir_u                # unit Vector3D (longer edge)
        self.dir_v = dir_v                # unit Vector3D (perpendicular)
        self.len_u = len_u                # longer edge length
        self.len_v = len_v                # shorter (perpendicular) length
        self.line_u = line_u              # a SketchLine along dir_u
        self.line_v = line_v              # a SketchLine along dir_v
        self.diag_a = diag_a              # SketchPoint corner
        self.diag_b = diag_b              # opposite SketchPoint corner


def _analyze_rectangle(rect_lines):
    """Validate the 4 lines form a rectangle; return an ordered _Rect.

    Walks the lines into a closed 4-corner loop by endpoint coincidence,
    verifies adjacent edges are perpendicular and opposite edges equal,
    then picks Direction 1 = the longer edge.
    """
    if len(rect_lines) != 4:
        raise ValueError('Select exactly 4 sketch lines for the '
                          'rectangle (got %d).' % len(rect_lines))

    # Endpoint coordinates for each line.
    segs = []
    for ln in rect_lines:
        a = ln.startSketchPoint.geometry
        b = ln.endSketchPoint.geometry
        if _dist(a, b) < _COINC_TOL:
            raise ValueError('A selected rectangle line is degenerate '
                             '(zero length).')
        segs.append((ln, ln.startSketchPoint, ln.endSketchPoint, a, b))

    # Walk a closed loop: start at seg 0's start, chain by coincidence.
    used = [False] * 4
    used[0] = True
    chain = [segs[0]]
    cur_pt = segs[0][4]          # current open endpoint (geometry)
    cur_corner = segs[0][1]      # SketchPoint that started the loop
    corners = [segs[0][1]]       # ordered corner SketchPoints

    for _ in range(3):
        nxt = None
        for i in range(4):
            if used[i]:
                continue
            _, sp, ep, a, b = segs[i]
            if _dist(cur_pt, a) < _COINC_TOL:
                nxt, used[i] = (segs[i], sp, b), True
                break
            if _dist(cur_pt, b) < _COINC_TOL:
                nxt, used[i] = (segs[i], ep, a), True
                break
        if nxt is None:
            raise ValueError('The 4 selected lines do not form a closed '
                             'rectangle loop (endpoints do not meet).')
        seg, shared_corner, new_open = nxt
        chain.append(seg)
        corners.append(shared_corner)
        cur_pt = new_open

    # Loop must close back onto the very first corner.
    if _dist(cur_pt, corners[0].geometry) >= _COINC_TOL:
        raise ValueError('The 4 selected lines do not close into a '
                         'rectangle (loop is open).')

    ordered_lines = [c[0] for c in chain]
    p = [c.geometry for c in corners]   # corner positions in loop order

    # Edge vectors around the loop.
    e0 = _vec(p[0], p[1])
    e1 = _vec(p[1], p[2])
    e2 = _vec(p[2], p[3])
    e3 = _vec(p[3], p[0])

    # Adjacent edges perpendicular.
    if abs(_unit(e0).dotProduct(_unit(e1))) > _PERP_TOL:
        raise ValueError('Selected lines are not a rectangle '
                         '(adjacent edges not perpendicular).')

    # Opposite edges equal length.
    if abs(e0.length - e2.length) > _LEN_TOL or \
            abs(e1.length - e3.length) > _LEN_TOL:
        raise ValueError('Selected lines are not a rectangle '
                         '(opposite edges differ in length).')

    center = adsk.core.Point3D.create(
        sum(q.x for q in p) / 4.0,
        sum(q.y for q in p) / 4.0,
        sum(q.z for q in p) / 4.0)

    len_e0 = e0.length
    len_e1 = e1.length
    # Direction 1 = the LONGER edge (predictable). Ties -> e0.
    if len_e0 >= len_e1:
        dir_u, len_u, line_u = _unit(e0), len_e0, ordered_lines[0]
        dir_v, len_v, line_v = _unit(e1), len_e1, ordered_lines[1]
    else:
        dir_u, len_u, line_u = _unit(e1), len_e1, ordered_lines[1]
        dir_v, len_v, line_v = _unit(e0), len_e0, ordered_lines[0]

    # Opposite corners for the centring diagonal (loop order: 0 & 2).
    return _Rect(corners, ordered_lines, center, dir_u, dir_v,
                 len_u, len_v, line_u, line_v, corners[0], corners[2])


# ---------------------------------------------------------------------------
# Selection plumbing
# ---------------------------------------------------------------------------
def _active_sketch(app):
    sk = adsk.fusion.Sketch.cast(app.activeEditObject)
    if sk is None:
        raise ValueError(
            'No active sketch. Double-click a sketch to edit it, then '
            'run Checkerboard Pattern.')
    return sk


def _assert_in_sketch(sk, entities, label):
    for e in entities:
        ps = e.parentSketch
        if ps is None or ps.entityToken != sk.entityToken:
            raise ValueError(
                '%s must belong to the active sketch.' % label)


# ---------------------------------------------------------------------------
# Idempotent cleanup of a prior instrument-owned build
# ---------------------------------------------------------------------------
def _corner_token_set(rect):
    toks = set()
    for cp in rect.corners:
        t = cp.entityToken
        if t:
            toks.add(t)
    return toks


def _cleanup_prior(sk, rect, circle):
    """Delete a prior instrument-owned pattern + centring diagonal so a
    re-run with new quantity/spacing reflows cleanly.

    Detection is structural (no fragile naming): the prior pattern is the
    RectangularPatternConstraint whose input ``entities`` include this
    seed circle; the centring diagonal is a construction line whose two
    endpoints are rectangle corners, plus its midpoint constraint on the
    circle centre.
    """
    removed = 0
    gcs = sk.geometricConstraints
    circle_tok = circle.entityToken

    # 1. Prior rectangular pattern(s) seeded by this circle.
    victims = []
    for gc in gcs:
        rp = adsk.fusion.RectangularPatternConstraint.cast(gc)
        if rp is None:
            continue
        try:
            ents = rp.entities
        except Exception:  # pylint: disable=broad-except
            continue
        for e in ents:
            if e is not None and e.entityToken == circle_tok:
                victims.append(rp)
                break
    for rp in victims:
        try:
            rp.deleteMe()
            removed += 1
        except Exception:  # pylint: disable=broad-except
            log('checkerboard: prior pattern deleteMe failed')

    # 2. Prior centring midpoint constraint on the circle centre.
    center_tok = circle.centerSketchPoint.entityToken
    mids = []
    for gc in gcs:
        mp = adsk.fusion.MidPointConstraint.cast(gc)
        if mp is None:
            continue
        try:
            pt = mp.point
        except Exception:  # pylint: disable=broad-except
            continue
        if pt is not None and pt.entityToken == center_tok:
            mids.append(mp)
    for mp in mids:
        try:
            mp.deleteMe()
            removed += 1
        except Exception:  # pylint: disable=broad-except
            log('checkerboard: prior midpoint deleteMe failed')

    # 3. Prior centring construction diagonal (line spanning two
    #    rectangle corners; idempotent so we don't pile up diagonals).
    corner_toks = _corner_token_set(rect)
    lines = sk.sketchCurves.sketchLines
    diag_victims = []
    for ln in lines:
        if not ln.isConstruction:
            continue
        st = ln.startSketchPoint.entityToken
        et = ln.endSketchPoint.entityToken
        if st in corner_toks and et in corner_toks and st != et:
            diag_victims.append(ln)
    for ln in diag_victims:
        try:
            ln.deleteMe()
            removed += 1
        except Exception:  # pylint: disable=broad-except
            log('checkerboard: prior diagonal deleteMe failed')

    return removed


# ---------------------------------------------------------------------------
# Public: validate
# ---------------------------------------------------------------------------
def validate(sketch, rect_lines, circle):
    """Cheap structural check used to enable the dialog's OK button.

    Returns True only if there is an active sketch, exactly 4 rectangle
    lines + 1 circle all in that sketch, and the lines form a rectangle.
    Never raises (returns False on any problem).
    """
    try:
        if sketch is None or circle is None:
            return False
        if not rect_lines or len(rect_lines) != 4:
            return False
        _assert_in_sketch(sketch, list(rect_lines), 'Rectangle lines')
        _assert_in_sketch(sketch, [circle], 'Circle')
        _analyze_rectangle(list(rect_lines))
        return True
    except Exception:  # pylint: disable=broad-except
        return False


# ---------------------------------------------------------------------------
# Checkerboard mask
# ---------------------------------------------------------------------------
def _checkerboard_mask(q1, q2):
    """Return (mask, seed_flat, filled_count) for a q1 x q2 grid.

    ``q1`` = Direction-1 quantity (columns along the longer edge),
    ``q2`` = Direction-2 quantity (rows). The native isSuppressed array
    is row-column order with the seed cell excluded, so it has length
    q1*q2-1. With both directions symmetric the (already centred) seed
    lands on the deterministic central cell (c0, r0). A cell is kept
    (filled) when its parity matches the seed's; the rest are suppressed.
    """
    c0 = (q1 - 1) // 2          # seed column (Direction 1)
    r0 = (q2 - 1) // 2          # seed row (Direction 2)
    seed_flat = r0 * q1 + c0
    seed_parity = (r0 + c0) % 2

    mask = []
    filled = 1                  # the seed itself is a filled cell
    for flat in range(q1 * q2):
        if flat == seed_flat:
            continue            # original/seed not represented in array
        r, c = divmod(flat, q1)
        keep = ((r + c) % 2) == seed_parity
        mask.append(not keep)   # True => suppressed
        if keep:
            filled += 1
    return mask, seed_flat, filled


# ---------------------------------------------------------------------------
# Public: build (P1 — native RectangularPatternConstraint)
# ---------------------------------------------------------------------------
def build(app, *, rect_lines, circle, dist_type, q1, d1, q2, d2,
          preview):
    """Re-centre the circle and build the checkerboard pattern.

    ``rect_lines`` : list of exactly 4 SketchLines (rectangle).
    ``circle``     : the seed SketchCircle.
    ``dist_type``  : adsk.fusion.PatternDistanceType value.
    ``q1, q2``     : integer quantities (Direction 1 = longer edge).
    ``d1, d2``     : distance expression strings (e.g. ``'40 mm'``).
    ``preview``    : informational only — the build path is identical;
                     Fusion's preview transaction discards it on cancel.

    Returns a :class:`CheckerboardResult`.
    """
    sk = _active_sketch(app)
    rect_lines = list(rect_lines)

    _assert_in_sketch(sk, rect_lines, 'Rectangle lines')
    _assert_in_sketch(sk, [circle], 'Circle')

    q1 = int(q1)
    q2 = int(q2)
    if q1 < 1 or q2 < 1:
        raise ValueError('Quantities must be at least 1.')

    rect = _analyze_rectangle(rect_lines)

    res = CheckerboardResult()
    res.q1, res.q2 = q1, q2
    res.total_cells = q1 * q2
    res.preview = bool(preview)
    res.dist_type_name = (
        'Spacing'
        if dist_type == adsk.fusion.PatternDistanceType
        .SpacingPatternDistanceType
        else 'Extent')

    gcs = sk.geometricConstraints

    # --- idempotent replace -------------------------------------------
    removed = _cleanup_prior(sk, rect, circle)
    if removed:
        res.notes.append('rebuilt (removed %d prior entit%s)'
                         % (removed, 'y' if removed == 1 else 'ies'))

    # --- parametric centring ------------------------------------------
    # One construction diagonal between two opposite corners + a single
    # midpoint constraint pins the circle centre to the rectangle centre
    # and keeps it centred if the rectangle is later resized.
    diagonal = sk.sketchCurves.sketchLines.addByTwoPoints(
        rect.diag_a, rect.diag_b)
    diagonal.isConstruction = True

    cen = circle.centerSketchPoint.geometry
    delta = adsk.core.Vector3D.create(rect.center.x - cen.x,
                                      rect.center.y - cen.y,
                                      rect.center.z - cen.z)
    if delta.length > 1e-9:
        circle.centerSketchPoint.move(delta)
    gcs.addMidPoint(circle.centerSketchPoint, diagonal)

    # --- native rectangular pattern -----------------------------------
    pinput = gcs.createRectangularPatternInput([circle], dist_type)
    if pinput is None:
        raise RuntimeError('Could not create the rectangular pattern '
                           'input.')

    ok1 = pinput.setDirectionOne(
        rect.line_u,
        adsk.core.ValueInput.createByString(str(q1)),
        adsk.core.ValueInput.createByString(str(d1)))
    ok2 = pinput.setDirectionTwo(
        rect.line_v,
        adsk.core.ValueInput.createByString(str(q2)),
        adsk.core.ValueInput.createByString(str(d2)))
    if not (ok1 and ok2):
        raise RuntimeError('Could not set the pattern directions '
                           '(direction lines or values rejected).')

    pinput.isSymmetricInDirectionOne = True
    pinput.isSymmetricInDirectionTwo = True

    constraint = gcs.addRectangularPattern(pinput)
    if constraint is None:
        raise RuntimeError('Fusion rejected the rectangular pattern.')

    # --- checkerboard suppression mask --------------------------------
    mask, _seed_flat, filled = _checkerboard_mask(q1, q2)
    expected = q1 * q2 - 1
    try:
        live = list(constraint.isSuppressed)
    except Exception:  # pragma: no cover
        live = []
    if len(live) != expected:
        # Length mismatch would corrupt the parity; surface it instead
        # of silently building a wrong pattern.
        raise RuntimeError(
            'Unexpected pattern size: isSuppressed has %d entries, '
            'expected %d for a %dx%d grid.'
            % (len(live), expected, q1, q2))
    constraint.isSuppressed = mask

    res.filled_count = filled
    return res


# ---------------------------------------------------------------------------
# Documented fallback (P2 — diagonal lattice). NOT the default.
# ---------------------------------------------------------------------------
def build_checkerboard_p2(app, *, rect_lines, circle, dist_type,
                          q1, d1, q2, d2, preview):  # noqa: D401
    """Contingency builder kept for the unlikely case that the native
    ``isSuppressed`` mask proves non-persistent in a particular Fusion
    build (it survives save/reopen in every version verified here).

    Strategy: instead of one square pattern + a checkerboard mask, build
    the filled cells as a single rectangular pattern on a 45-degree
    rotated lattice (spacing = sqrt(2) * cell, axes along the two
    rectangle diagonals). This yields the identical dark-square set
    without any per-instance suppression, at the cost of the
    quantity/distance parameters no longer reading "5 x 40 mm" like the
    native dialog. Switch by calling this from ``entry.py`` instead of
    :func:`build` — a one-line change.

    Implemented as an explicit error until/unless the contingency is hit,
    so it is never silently used and never ships untested behaviour.
    """
    raise NotImplementedError(
        'build_checkerboard_p2 is a documented contingency only; the '
        'default P1 build() uses the native, persisted isSuppressed '
        'mask. Wire this in only if mask persistence regresses.')
