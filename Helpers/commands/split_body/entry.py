"""Instrument: Split Body.

Mirrors Fusion's native **Split Body** command, with these deliberate
differences requested for this workflow:

* one or more **bodies to split** may be selected (across components);
* the **splitting tool(s)** are restricted to *solid bodies only* (no
  faces, construction planes or sketch profiles), and may be many — each
  is applied in turn;
* there is **no "Extend Splitting Tool(s)"** option (the tool is never
  auto-extended — ``isSplittingToolExtended`` is always ``False``);
* an extra **"Remove intersections"** checkbox (**on by default**): after
  the split, any resulting piece that lies wholly inside one of the
  splitting tools is deleted automatically (a parametric Remove
  feature), so only the material outside the tools is kept.

Discovered automatically by the add-in because this package contains
``entry.py`` exposing ``COMMAND``.
"""

import traceback

import adsk.core
import adsk.fusion

import config
from command_base import InstrumentCommand

try:
    from log import log
except Exception:  # pragma: no cover
    def log(_msg):
        pass

# A split piece counts as "inside" a tool when its intersection with the
# tool is at least this fraction of its own volume. Split pieces are
# bounded exactly by the tool surface, so an interior piece intersects at
# ~1.0; this threshold only absorbs numeric noise.
_INSIDE_RATIO = 0.90
_VOL_EPS = 1e-6


def _native(entity):
    """Native object for an occurrence-proxy entity, else the entity."""
    return entity.nativeObject if entity.assemblyContext else entity


def _token(body):
    """entityToken if available, else '' (transient/edge cases)."""
    try:
        return body.entityToken
    except Exception:  # pylint: disable=broad-except
        return ''


class SplitBodyCommand(InstrumentCommand):
    CMD_ID = config.cmd_id('SplitBody')
    NAME = 'Split Body'
    TOOLTIP = ('Split one or more solid bodies with one or more solid '
               'tool bodies (applied in turn). The tool is never '
               'auto-extended. Optionally (default on) remove the pieces '
               'that fall inside the tools.')

    _BODY = 'bodyToSplit'
    _TOOLS = 'splittingTools'
    _REMOVE = 'removeIntersections'

    def build_inputs(self, inputs: adsk.core.CommandInputs):
        body = inputs.addSelectionInput(
            self._BODY, 'Bodies to Split',
            'Select one or more solid bodies to split')
        body.addSelectionFilter('SolidBodies')
        body.setSelectionLimits(1, 0)    # min 1, max 0 = unlimited

        tools = inputs.addSelectionInput(
            self._TOOLS, 'Splitting Tool(s)',
            'Select one or more solid bodies to split with')
        tools.addSelectionFilter('SolidBodies')
        tools.setSelectionLimits(1, 0)   # min 1, max 0 = unlimited

        # Replaces the omitted "Extend Splitting Tool(s)" option.
        # Enabled by default.
        inputs.addBoolValueInput(
            self._REMOVE, 'Remove intersections', True, '', True)

    def on_execute(self, inputs: adsk.core.CommandInputs):
        app = adsk.core.Application.get()

        body_sel = inputs.itemById(self._BODY)
        tools_sel = inputs.itemById(self._TOOLS)
        if body_sel.selectionCount == 0:
            raise ValueError('Select a solid body to split.')
        if tools_sel.selectionCount == 0:
            raise ValueError('Select at least one solid splitting tool.')

        # Resolve every selected body. Bodies may live in different
        # components/occurrences, so track, per component: the live
        # Component (where split pieces land — split keeps pieces in the
        # original body's component) and the body-to-split occurrence's
        # root-relative transform (used to bring native pieces to world
        # for the remove-intersections boolean).
        native_bodies = []
        split_tokens = set()
        scanned = {}        # comp entityToken -> Component
        comp_xform = {}     # comp entityToken -> Matrix3D | None
        for i in range(body_sel.selectionCount):
            ent = body_sel.selection(i).entity
            occ = ent.assemblyContext            # may be None (root body)
            nb = _native(ent)
            native_bodies.append(nb)
            split_tokens.add(_token(nb))
            comp = nb.parentComponent
            ck = _token(comp)
            if ck not in scanned:
                scanned[ck] = comp
                comp_xform[ck] = occ.transform2 if occ else None

        # Splitting tools: keep them exactly as selected (proxies are fine
        # for the feature input and for world-space temp copies). Drop any
        # body that is itself one of the bodies being split.
        tools = []
        for i in range(tools_sel.selectionCount):
            ent = tools_sel.selection(i).entity
            if _token(_native(ent)) in split_tokens:
                continue
            tools.append(ent)
        if not tools:
            raise ValueError(
                'The splitting tool(s) must be different bodies than the '
                'bodies being split.')

        remove_inside = inputs.itemById(self._REMOVE).value

        # One SplitBodyFeature per tool (the API takes a single splitting
        # tool per feature); created on the first body's component, which
        # Fusion re-homes/resolves for cross-component selections.
        split_feats = native_bodies[0].parentComponent \
            .features.splitBodyFeatures

        def _all_bodies():
            out = []
            for c in scanned.values():
                for b in c.bRepBodies:
                    out.append(b)
            return out

        # Sequentially split every surviving piece with each tool.
        work = list(native_bodies)
        skipped = []
        created = []          # this run's timeline features, for grouping
        for idx, tool in enumerate(tools, 1):
            work_tokens = {_token(b) for b in work}
            before = {_token(b) for b in _all_bodies()}

            coll = adsk.core.ObjectCollection.create()
            for b in work:
                coll.add(b)

            inp = split_feats.createInput(coll, tool, False)
            if not inp:
                skipped.append(idx)
                log('SplitBody: createInput returned None for tool %d' % idx)
                continue
            try:
                feat = split_feats.add(inp)
            except Exception:  # pylint: disable=broad-except
                skipped.append(idx)
                log('SplitBody: tool %d add() failed:\n%s'
                    % (idx, traceback.format_exc()))
                continue
            if feat:
                created.append(feat)

            after = _all_bodies()
            after_by_token = {_token(b): b for b in after}
            new_pieces = [b for tok, b in after_by_token.items()
                          if tok not in before]
            # Work bodies a tool didn't cut keep their token; re-acquire
            # fresh handles for them from the post-split body list.
            survivors = [b for b in after if _token(b) in work_tokens]
            work = survivors + new_pieces

        if len(skipped) == len(tools):
            raise RuntimeError(
                'No tool intersected the bodies — nothing was split. '
                'Check that the tool bodies overlap the bodies to split.')

        final_pieces = work
        removed = 0
        if remove_inside:
            removed = self._remove_inside(final_pieces, tools, comp_xform,
                                          created)

        # Collapse exactly this run's features into one named timeline
        # group (purely cosmetic; the proven pipes.py guard — group only a
        # verified-contiguous run of our own items, and ALWAYS leave the
        # timeline computed via moveToEnd in a finally so grouping can
        # never roll a split / remove back).
        design = adsk.fusion.Design.cast(app.activeProduct)
        grp_name = ('SplitBody_%s' % native_bodies[0].name
                    if len(native_bodies) == 1
                    else 'SplitBody_%dbodies' % len(native_bodies))
        self._group_timeline(design, created, grp_name)

        kept = len(final_pieces) - removed
        parts = [f'Split {len(native_bodies)} body(ies) into '
                 f'{len(final_pieces)} piece(s)']
        if remove_inside:
            parts.append(f'{removed} inside the tool(s) removed, '
                         f'{kept} kept')
        if skipped:
            parts.append(f'{len(skipped)} tool(s) did not intersect '
                         f'(skipped)')
        app.userInterface.messageBox(
            'Split Body — ' + '; '.join(parts) + '.', config.ADDIN_NAME)

    # ---- remove-intersections ------------------------------------------
    def _remove_inside(self, pieces, tools, comp_xform, created):
        """Delete every piece that lies wholly inside any splitting tool.

        Detection is a pure :class:`TemporaryBRepManager` boolean
        (timeline-neutral). Everything is brought to root/world space:
        ``tmp.copy`` of an occurrence-proxy tool already yields world
        geometry (the proven pipes.py pattern); each piece is a native
        body in its component, so it is transformed by that component's
        body-to-split occurrence transform (``comp_xform``, keyed by the
        component entityToken). The Remove feature is created in the
        piece's own component.
        """
        tmp = adsk.fusion.TemporaryBRepManager.get()
        removed = 0
        for piece in list(pieces):
            pv = piece.volume
            if pv <= _VOL_EPS:
                continue
            xform = comp_xform.get(_token(piece.parentComponent))
            inside = False
            for tool in tools:
                pc = tmp.copy(piece)
                if xform:
                    tmp.transform(pc, xform)
                ok = tmp.booleanOperation(
                    pc, tmp.copy(tool),
                    adsk.fusion.BooleanTypes.IntersectionBooleanType)
                if ok and pc.volume >= _INSIDE_RATIO * pv:
                    inside = True
                    break
            if not inside:
                continue
            try:
                rf = piece.parentComponent.features.removeFeatures.add(
                    piece)
                if rf:
                    created.append(rf)
            except Exception:  # pylint: disable=broad-except
                try:
                    piece.deleteMe()
                except Exception:  # pylint: disable=broad-except
                    log('SplitBody: could not remove inside piece:\n%s'
                        % traceback.format_exc())
                    continue
            removed += 1
        return removed

    # ---- timeline grouping ---------------------------------------------
    def _group_timeline(self, design, created, name):
        """Collapse exactly this run's features into one named, collapsed
        timeline group.

        PURELY COSMETIC and correctness-safe (same guard as
        ``lib/pipes._group_timeline``): cross-component features are
        re-homed by Fusion, so group over the actual
        ``timelineObject.index`` set and ONLY when those form a clean
        contiguous run of just our items (otherwise skip). The timeline is
        ALWAYS left fully computed (marker at end) via the ``finally``, so
        grouping can never leave a split / remove rolled back.
        """
        try:
            idx = []
            for feat in created:
                try:
                    idx.append(feat.timelineObject.index)
                except Exception:  # pylint: disable=broad-except
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
        except Exception:  # pylint: disable=broad-except
            return None
        finally:
            try:
                design.timeline.moveToEnd()
            except Exception:  # pragma: no cover
                pass


COMMAND = SplitBodyCommand
