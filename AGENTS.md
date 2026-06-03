# FusionHelpers

A Fusion 360 **add-in** named `Helpers` that provides a "Helpers" menu of
modelling **instruments** (commands). The add-in lives in `Helpers/`.

## Golden rule: one instrument per folder

Every instrument is a self-contained sub-package under
`Helpers/commands/<instrument_name>/`. Cross-instrument, UI-free helpers
live in `Helpers/lib/`. Add-in infrastructure stays at `Helpers/` root.
Do not put instrument logic at the root or in `lib/`.

## Delivery cycle (MANDATORY — every code change)

After **every** code change, before reporting back to the user, restart
the plugin via MCP and check the log. Do **not** ask the user to click
Run/Stop for iteration — Fusion's add-in loader is unreliable and the MCP
path bypasses it.

1. **Restart via MCP** (`fusion_mcp_execute`, server
   `http://127.0.0.1:27182/mcp`). Run a Fusion script that:
   - inserts `…/FusionHelpers/Helpers` on `sys.path`;
   - truncates `Helpers/helpers.log`;
   - deletes cached modules from `sys.modules` (`Helpers`, `log`,
     `config`, `command_base`, `lib`/`lib.*`, `commands`/`commands.*`) so
     the newest code on disk is loaded;
   - `import Helpers; Helpers.stop({}); Helpers.run({})`;
   - prints `helpers.log`.
   `run()` is idempotent (self-heals stale UI by id), so stop()+run() is
   safe to repeat.
2. **Check the log** (`Helpers/helpers.log`). Success looks like
   `run() COMPLETE; instruments=N` with no traceback. If a traceback
   appears, fix it and restart again before reporting.

An MCP-started instance lives only for the current Fusion session and is
not tracked by the Add-Ins dialog (its Stop won't control it; no
auto-load on next launch).

## Layout

```
Helpers/
  Helpers.manifest              # type:addin, runOnStartup:true
  Helpers.py                    # add-in run()/stop(); builds menu; auto-discovers instruments
  config.py                     # all Fusion ids/names (prefix FusionHelpers_)
  command_base.py               # InstrumentCommand base + command-lifecycle plumbing
  lib/                          # shared, UI-free, reusable helpers
    selection.py  parameters.py  features.py
  commands/                     # one sub-package per instrument
    <instrument_name>/
      __init__.py
      entry.py                  # MUST expose: COMMAND = <InstrumentCommand subclass>
      (optional) resources/, instrument-specific helper modules
```

## Adding a new instrument

1. Create `Helpers/commands/<name>/` with `__init__.py` and `entry.py`.
2. In `entry.py`: subclass `command_base.InstrumentCommand`, set
   `CMD_ID = config.cmd_id('<Unique>')`, `NAME`, `TOOLTIP`; implement
   `build_inputs(self, inputs)` (dialog) and `on_execute(self, inputs)`
   (the operation). End the file with `COMMAND = <YourClass>`.
3. Put reusable, UI-free logic in `lib/`; keep instrument-specific logic
   inside the instrument folder.
4. Nothing else — `Helpers.py` discovers `commands/*/entry.py`
   automatically and adds a button directly to the Helpers panel.

## Import rules

- The add-in root (`Helpers/`) is put on `sys.path` by `Helpers.py`.
- From an `entry.py`: `import config`,
  `from command_base import InstrumentCommand`, `from lib import features`.
- Inside `lib/`, use relative imports (`from .selection import ...`).

## Gotchas (do not regress these)

- **sys.path**: Fusion does NOT add the add-in folder to `sys.path`;
  `Helpers.py` inserts it before importing siblings.
- **Selection**: never use `ui.selectEntity` from a script/add-in (it
  asserts: `InternalValidationError: selections.size() > 0`). Use a
  command `SelectionCommandInput` (see the offset_outer_faces instrument).
- **Handler lifetime**: Fusion garbage-collects unreferenced event
  handlers; `command_base` keeps them in a module-level list. Keep it.
- **Module reload**: Fusion keeps one Python interpreter for the whole
  session, so `run()` reloads project + instrument modules so edits apply
  on Stop/Run without restarting Fusion. Maintain `_RELOAD_ORDER`
  (dependencies before dependents).
- **Face normals**: `BRepFace.evaluator.getNormalAtPoint` already returns
  the solid-outward (face-oriented) normal — do NOT additionally flip by
  `face.isParamReversed` (that double-flip broke hole detection in
  `lib/selection.is_hole_face`).
- **No nested dropdown**: instruments are command buttons added directly
  to the "Helpers" panel. A dropdown named "Helpers" inside the "Helpers"
  panel duplicated the name — do not reintroduce it. `run()` deletes a
  stale legacy dropdown (`config.LEGACY_DROPDOWN_ID`) from older sessions.
- **Assembly = native-commit, world-compute** (BaseFeature/Combine route).
  Features created that way MUST target the *native* body in its *owning*
  component: compute geometry in world space, build a temp tool,
  `TemporaryBRepManager.transform(tool, occ.transform2.inverse)` into the
  native component, stage it via a one-shot `BaseFeature`, then
  `CombineFeatures` on the native body. Still valid generally, but
  `pipe_joint_calibration` no longer uses it — the sketch-in-root +
  `participantBodies` route below is simpler and is the proven path.
- **`Occurrence.transform2` is root-relative** (full nesting chain, no
  manual parent compose; `Occurrence.transform` is retired/incorrect).
- **`BRepBodies.add(tempBody, baseFeature)`**: the returned handle is
  only valid until `BaseFeature.finishEdit()`. Call `startEdit()` → add →
  `finishEdit()`, then **re-acquire the persistent body from
  `baseFeature.bodies`** (using the stale handle → `Combine`
  `ALL_TOOL_BODY_REFERENCE_LOST`).
- **Detecting bodies in an assembly**: enumerate
  `rootComponent.bRepBodies` + every `occ.bRepBodies` proxy (world
  space) — `pipes._candidates`. Gate B on perpendicularity + real
  saddle, not first overlap.
- **Section in-plane axis = direction of the LONGEST straight flat edge**
  of the outer loop (`pipes._outer_frame`). Do NOT use an angle-doubled
  "vote": it is degenerate for a 90°-symmetric square (votes cancel to
  ≈0, `atan2` of numerical noise → a ~45°-rotated box / diamond plug).
- **Cross-occurrence Cut WITHOUT BaseFeature (verified, the pipe-joint
  path):** create the sketch in ROOT on the selected *proxy* face via
  `Sketches.addWithoutEdges(face)` (NO `occurrenceForCreation` when the
  sketch is in root; `Sketch.modelToSketchSpace` is occurrence-aware so
  world geometry converts correctly), then a Cut-extrude with
  `ExtrudeFeatureInput.participantBodies=[proxy]` (proxies accepted). KEY:
  Fusion RE-HOMES each extrude to its participant body's owning component
  (NOT root) — only the sketch stays in root; never scan
  `rootComponent.features` for the cut (it isn't there). Pin every
  extrude's
  `ExtentDirections` from the world into-B vector
  (`sign(sketchToModelSpace-normal · u)`), never the default
  sketch-normal sign — that was the old sketch sign/space bug. Draw the
  squared rectangle as an explicit chained 4-line loop from
  `_outer_frame` world extents (corners ON the face plane — depth is the
  extrude extent, NEVER an `axis*depth` term in a sketch point). The old
  `TemporaryBRepManager.createBox(OBB)` plug remains the detection
  tool (timeline-neutral); it is no longer used to commit geometry.
- **MCP `fusion_mcp_execute` corrupts non-ASCII in the SCRIPT SOURCE**
  (runtime API strings like `dataFile.name` are fine). Build any
  Cyrillic/Unicode literal at runtime via `chr(0x..)` codepoints; keep
  the script body pure ASCII.
- **Verify against the REAL model, not a generator.** The old synthetic
  `_tube` fixture (area-sorted profile) built a solid bar with an
  inner-rect end face → ~10 wasted debug cycles. Detection is pure
  TemporaryBRep (timeline-neutral) so it can be exercised read-only;
  destructive runs only on a `saveAs` scratch copy (never production).

## Instruments

- **Offset Outer Faces** (`commands/offset_outer_faces`) — offsets a body's
  outer faces; excludes concave-cylinder holes; multi-body + face-exclude.
- **Pipe Joint Calibration** (`commands/pipe_joint_calibration`,
  `lib/pipes.py`) — pick Pipe A's planar end profile; auto-detects the
  perpendicular Pipe B, cuts a socket into B, **extends Pipe A into that
  socket so it physically plugs in**, and relieves the joint over the
  calibration band so milled square/rect-tube saddle joints fit.
  **Sketch-based parametric pipeline** (the user-prescribed manual
  workflow, made robust): (1) root sketch on the proxy end face
  (`addWithoutEdges`); (2) draw the squared OUTER rectangle S from
  `_outer_frame` world extents; (3) draw the calibrated inner rectangle
  S−c directly from the same extents (deterministic — NOT the retired
  sketch-offset tool); (4) project Pipe B (diagnostic / 2nd intersection
  signal — non-fatal: a valid saddle can graze the end plane, `_detect_b`
  is the real gate); (5) Cut the socket into B via `participantBodies`
  (inner S−c full depth + the S..S−c ring over the deep region so the
  socket is S−c in the band and S beyond); (6) extend A by
  `_offset_face` on its native end face; (7) Cut the S..S−c ring from A
  SYMMETRICALLY about the joint plane (`setSymmetricExtent(dist, False)`
  → calibration distance on BOTH sides): the exposed length (millable,
  away from B) AND the plugged-in length (so A's inserted wall is S−c and
  fits B's S−c socket). Per-side length = the full calibration distance,
  independent of penetration.
  **Parameter semantics (do not regress):** penetration / slot depth is
  ALWAYS `offset` — never driven by the calibration distance. The
  calibration distance is `clearance_length`, an INDEPENDENT band length
  measured from the joint along the insertion axis, **NOT clamped** to
  the penetration. Pipe A's outer-wall relief is cut over the full
  distance (it only removes where A actually exists); Pipe B's slot is
  S−c over the engaged portion only (`min(distance, offset)` — the socket
  is `offset` deep, so a distance ≥ offset calibrates the whole socket
  with no nominal-S deep step). They are orthogonal: distance can be
  shorter OR longer than the penetration.
  **After calibration**: each pipe body must be single in its own
  component — if a pipe body is alone in its component it is left as-is,
  otherwise `BRepBody.createComponent()` splits it out — then a rigid
  `AsBuiltJoint` (`createInput(occA, occB, None)` + `setAsRigidJointMotion`)
  is added between Pipe A's and Pipe B's occurrences. This post-step has
  its own try/except: a failure is noted but NEVER rolls back the
  calibration. `clearance_side` {both,a,b} selects the slot/A relief; the Pipe A side
  relief is also skipped when the projected Pipe B section coincides with
  Pipe A's own profile (flush/aligned butt — `_bbox_corresponds`, socket
  + extend still run). Each run's sketch + extrudes + offset-face are
  collapsed into one named, collapsed `PipeJoint_<A>_<B>` timeline group
  — purely cosmetic and correctness-safe (`_group_timeline` groups only a
  verified-contiguous run of its own items and ALWAYS leaves the timeline
  fully computed via `moveToEnd` in a finally, so grouping can never roll
  a feature back / unapply the A relief). Detection stays pure
  `TemporaryBRepManager` (timeline-neutral). Feature/sketch names are
  per-pipe/per-end keyed (component + body + end-tag) so distinct
  pipes/ends don't collide. **No "already calibrated" gate and no
  preview mode (both removed on request)** — re-running on an
  already-calibrated end is allowed and STACKS another socket/relief/
  joint (user manages with undo). Outer perimeter only; no Fusion user
  parameters. **S5 + the follow-ups objectively verified on a real
  production tube assembly (scratch `saveAs`, production untouched):**
  Pipe A wall = S−c over the calibration distance on BOTH sides of the
  joint (exposed + plugged-in), nominal beyond; B slot S−c over the
  engaged portion; penetration = offset even when offset <
  clearance_length, distance honored independent of penetration
  (verified offset30/dist10, offset5/dist10); timeline group all
  members & collapsed.
- **Split Body** (`commands/split_body`) — native Split Body, restricted:
  one or more solid **Bodies to Split** (may span components),
  **solid-body splitting tool(s) only** (no faces/planes/profiles), tool
  **never auto-extended** (`isSplittingToolExtended=False`, no extend
  checkbox). The API takes one tool per `SplitBodyFeature`, so multiple
  tools are applied in turn — every surviving piece is fed into the next
  tool's split, pieces tracked by `entityToken` across the union of the
  selected bodies' components (cut bodies replaced, uncut ones survive,
  unrelated component bodies ignored). **Remove intersections (on by
  default)**: each final piece is intersected (timeline-neutral
  `TemporaryBRepManager`, world space via the pipes.py proxy-copy +
  per-component-occurrence `transform2`, keyed by component
  `entityToken`) against every tool; a piece whose intersection ≥ 0.90
  of its own volume (wholly inside a tool) is deleted via a parametric
  `RemoveFeature` in that piece's own component. Drops any
  body-to-split also picked as a tool; raises if no tool intersects.
  This run's features collapse into one named, collapsed timeline group
  (`SplitBody_<name>` / `SplitBody_<n>bodies`) via the pipes.py
  contiguous-run guard.

## API reference (the only API this project uses)

This add-in targets exactly one API: the **Fusion 360 API**. The full
reference is vendored locally — consult it instead of guessing API
shapes. **Use the `fusion-api-lookup` skill** for the how-to.

- `FusionAPIReference/` — git submodule (the authoritative, version-pinned
  source):
  - `Fusion_API_Python_Reference/defs/adsk/*.py` — type-hinted Python
    stubs (`core`, `fusion`, `cam`, `drawing`, `sim`, `volume`): exact
    signatures, params, return types. Best for *how to call* something.
  - `Fusion_API_Documentation/files/<Class>.htm` /
    `<Class>_<member>.htm` — 16k+ HTML pages: descriptions, behavior,
    examples. `fusion_mcp_read` also serves these in-session.
- `fusion_api_reference.md` / `fusion_api_reference.json` — flat scraped
  index (1228 Objects + 260 Enums, 14853 members) with autodesk.com
  detail URLs. Good for discovery and giving the user a clickable link.
- Update the submodule only on request: `git submodule update --remote`.
  Never edit anything under `FusionAPIReference/` (it's reference, CC
  BY-NC-SA 3.0 — inform code, don't copy prose).

When unsure of a class, method signature, parameter, or enum value, look
it up via the `fusion-api-lookup` skill — do not invent API names.

## Build / test

- Load: Fusion → Utilities → Scripts and Add-Ins → Add-Ins → add the
  `Helpers` folder → Run. Menu appears in Design workspace, UTILITIES tab
  (`config.TAB_ID = 'ToolsTab'`), "Helpers" panel with instrument buttons
  directly in it (no nested dropdown — that duplicated "Helpers").
  `runOnStartup` only auto-runs on the next Fusion launch; mid-session
  you must click Run once.
- A live Fusion MCP server runs at `http://127.0.0.1:27182/mcp`
  (`fusion_mcp_execute` runs Python in the session, `fusion_mcp_read`
  for API docs/screenshots). Use it for non-destructive import/logic
  checks; do not mutate the user's open production documents.
- Quick syntax check: `cd Helpers && python3 -m py_compile **/*.py`.

## Working agreements

- Every code change ends with the **Delivery cycle** above: restart via
  MCP and check `helpers.log`. Never ask the user to click Run to iterate.
- No auto-commits; commit only when explicitly asked.
- Git is scoped to `FusionHelpers/`; the parent `~/Projects` is a
  separate (broken) repo — never run git from the parent.
