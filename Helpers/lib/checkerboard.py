"""Checkerboard ("chess") sketch pattern (UI-free, fully parametric).

Given one existing sketch circle, this builds a native
``RectangularPatternConstraint`` aligned to the sketch X/Y axes,
extending in both directions from the seed, then suppresses every cell
whose (row+col) parity differs from the seed cell's. The selected circle
stays in place. With even quantities, Fusion puts the extra row or column
on the positive sketch-axis side.

Everything is a real Fusion sketch constraint with auto-created
``ModelParameter`` quantity/distance values — exactly like the native
Rectangular Pattern dialog — so spacing/quantity edits re-flow. Leaving
Direction 1 unset selects the sketch X axis; leaving Direction 2 unset
selects the perpendicular sketch Y axis. The
``isSuppressed`` mask is the supported, persisted mechanism for the
checkerboard.

API note (verified against the version-pinned FusionAPIReference):
``RectangularPatternConstraint.isSuppressed`` is laid out in row-column
order with the original/seed cell NOT counted — a q1*q2 grid yields a
list of length q1*q2-1 (FusionAPIReference/Fusion_API_Python_Reference/
defs/adsk/fusion.py:52696-52727).
"""

import adsk.core
import adsk.fusion

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
# Idempotent cleanup of a prior build for this seed
# ---------------------------------------------------------------------------
def _cleanup_prior(sk, circle):
    """Delete prior rectangular patterns seeded by ``circle``.

    Pattern constraints have no instrument-owned name, so detection is
    structural: their input ``entities`` must include this seed circle.
    Fusion leaves pattern-created geometry behind when the constraint is
    deleted, so capture each pattern's ``createdEntities`` first, delete
    the constraint, then delete only those generated copies. The API
    guarantees that ``createdEntities`` excludes the original seed.
    """
    removed = 0
    gcs = sk.geometricConstraints
    circle_tok = circle.entityToken

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
            generated = list(rp.createdEntities)
        except Exception as exc:  # pylint: disable=broad-except
            raise RuntimeError(
                'Could not inspect the prior checkerboard pattern.') from exc

        try:
            if not rp.deleteMe():
                raise RuntimeError(
                    'Fusion did not delete the prior checkerboard pattern.')
        except Exception as exc:  # pylint: disable=broad-except
            raise RuntimeError(
                'Could not delete the prior checkerboard pattern.') from exc

        removed += 1
        for entity in generated:
            if entity is None or not entity.isValid:
                continue
            try:
                if not entity.deleteMe():
                    raise RuntimeError(
                        'Fusion did not delete a prior pattern copy.')
            except Exception as exc:  # pylint: disable=broad-except
                raise RuntimeError(
                    'Could not delete a prior checkerboard copy.') from exc

    return removed


# ---------------------------------------------------------------------------
# Public: validate
# ---------------------------------------------------------------------------
def validate(sketch, circle):
    """Cheap structural check used to enable the dialog's OK button.

    Returns True only when the selected circle belongs to the active
    sketch. Never raises (returns False on any problem).
    """
    try:
        if sketch is None or circle is None:
            return False
        _assert_in_sketch(sketch, [circle], 'Circle')
        return True
    except Exception:  # pylint: disable=broad-except
        return False


# ---------------------------------------------------------------------------
# Checkerboard mask
# ---------------------------------------------------------------------------
def _checkerboard_mask(q1, q2):
    """Return (mask, seed_flat, filled_count) for a q1 x q2 grid.

    ``q1`` = Direction-1 quantity (columns along sketch X),
    ``q2`` = Direction-2 quantity (rows along sketch Y). The native
    isSuppressed array
    is row-column order with the seed cell excluded, so it has length
    q1*q2-1. With both directions symmetric the seed lands on the
    deterministic cell (c0, r0); for an even quantity that is the
    lower-index middle cell and Fusion adds the extra instance on the
    positive-axis side. A cell is kept (filled) when its parity matches
    the seed's; the rest are suppressed.
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
def build(app, *, circle, dist_type, q1, d1, q2, d2, preview):
    """Build a sketch-axis-aligned checkerboard around ``circle``.

    ``circle``     : the seed SketchCircle.
    ``dist_type``  : adsk.fusion.PatternDistanceType value.
    ``q1, q2``     : integer quantities (sketch X and Y directions).
    ``d1, d2``     : distance expression strings (e.g. ``'40 mm'``).
    ``preview``    : informational only — the build path is identical;
                     Fusion's preview transaction discards it on cancel.

    Returns a :class:`CheckerboardResult`.
    """
    sk = _active_sketch(app)
    _assert_in_sketch(sk, [circle], 'Circle')

    q1 = int(q1)
    q2 = int(q2)
    if q1 < 1 or q2 < 1:
        raise ValueError('Quantities must be at least 1.')

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
    removed = _cleanup_prior(sk, circle)
    if removed:
        res.notes.append('rebuilt (removed %d prior entit%s)'
                         % (removed, 'y' if removed == 1 else 'ies'))

    # --- native rectangular pattern -----------------------------------
    pinput = gcs.createRectangularPatternInput([circle], dist_type)
    if pinput is None:
        raise RuntimeError('Could not create the rectangular pattern '
                           'input.')

    # Direction entities default to None: sketch X for Direction 1 and
    # the perpendicular sketch Y for Direction 2. The Python binding
    # rejects setDirectionOne(None, ...), despite None being documented,
    # so set only the quantity/distance properties and keep the defaults.
    pinput.quantityOne = adsk.core.ValueInput.createByString(str(q1))
    pinput.distanceOne = adsk.core.ValueInput.createByString(str(d1))
    pinput.quantityTwo = adsk.core.ValueInput.createByString(str(q2))
    pinput.distanceTwo = adsk.core.ValueInput.createByString(str(d2))
    pinput.isSymmetricInDirectionOne = True
    pinput.isSymmetricInDirectionTwo = True

    # Apply the mask to the input after both quantities are defined. On
    # a newly added constraint Fusion may initially expose only the first
    # direction's suppression entries; input-level suppression avoids
    # that deferred-compute race and creates the right geometry atomically.
    mask, _seed_flat, filled = _checkerboard_mask(q1, q2)
    expected = q1 * q2 - 1
    pinput.isSuppressed = mask
    try:
        live = list(pinput.isSuppressed)
    except Exception:  # pragma: no cover
        live = []
    if len(live) != expected or live != mask:
        raise RuntimeError(
            'Unexpected pattern input size: isSuppressed has %d entries, '
            'expected %d for a %dx%d grid.'
            % (len(live), expected, q1, q2))

    constraint = gcs.addRectangularPattern(pinput)
    if constraint is None:
        raise RuntimeError('Fusion rejected the rectangular pattern.')

    res.filled_count = filled
    return res
