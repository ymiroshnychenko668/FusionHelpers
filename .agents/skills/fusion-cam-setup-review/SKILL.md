---
name: fusion-cam-setup-review
description: Extract a Fusion 360 Manufacture CAM setup and review whether each operation's feed rates and spindle speed fit the actual cutter, workpiece material, and engagement, alongside strategy, pass/linking/height parameters and toolpath state. Use for CAM setup audits, exports, comparisons, or machining guidance; do not edit or regenerate toolpaths unless the user explicitly asks.
---

# Fusion CAM setup review

Produce a traceable, read-only snapshot before reviewing a setup. Separate values read from Fusion from machining recommendations, and never describe a setup as safe or collision-free from parameters alone.

## Primary responsibility: cutting-data review

The main task is not to repeat CAM parameters. Determine whether each operation's spindle speed and feed rates make sense for the combination of:

- cutter type and geometry, including diameter, flute count, tool material/coating, cutting length, and relevant holder or stickout data;
- exact workpiece material and condition, including alloy/grade, temper or hardness when it materially changes the recommendation;
- strategy and engagement, including axial/radial depth, stepover, stepdown, slotting versus peripheral cutting, stock to leave, entry mode, and finishing versus roughing duty;
- drilling, boring, and helical-entry kinematics, including the programmed path feed, ramp or helix angle, tool-center orbit radius, axial feed component, pitch per revolution, number of revolutions, and room for chip evacuation;
- coolant/chip-evacuation conditions and known machine limits.

### Mandatory user-input gate

Before issuing a final cutting-data verdict or recommending concrete feeds,
speeds, or engagement, verify that the user has supplied all three categories
below. If any category or decision-relevant field is absent, ask one concise,
bundled question for the missing facts. Extraction and parameter inspection may
continue while waiting, but every affected feeds-and-speeds verdict stays
`pending`; do not fill gaps from Fusion metadata or assumptions.

- **Workpiece:** exact material designation/alloy or grade, plus temper,
  condition, or hardness when it materially affects machining.
- **Physical cutter for every tool used:** cutter type, diameter, flute/tooth
  count, carbide/HSS or other cutter material, coating, usable flute/cutting
  length, and actual stickout. Also request manufacturer/product or its cutting
  limits when available, and center-cutting/ramp capability when the operation
  plunges or ramps.
- **Spindle:** rated power, maximum RPM and usable RPM range, plus motor/pole/VFD
  or known low-speed torque behavior. Request the spindle model and power/torque
  curve when available; if the user does not have them, record that limitation
  after asking rather than inventing it.

Facts already supplied by the user in the current conversation or preserved as
explicit user-sourced shop context count as supplied and must not be requested
again unless their scope is ambiguous or the machine/tool has changed. A Fusion
stock-material field, tool-library definition, preset, operation name, or CAM
machine definition never counts as user confirmation of physical reality. If
the user says a requested fact is unknown, proceed with an explicitly limited,
lower-confidence review; do not silently upgrade `pending` to `pass`.

After checking blocking CAM errors, prioritize this tool-material-cutting-data relationship over secondary naming or efficiency observations. Calculate and interpret the applicable quantities instead of merely listing them: cutting speed, feed per tooth or feed per revolution, entry/ramp/plunge ratios, engagement ratios, and chip-thinning-adjusted chip thickness when radial engagement is known. Never label a value conservative, aggressive, or correct from feed or RPM alone.

The workpiece material designation is a required user-supplied input for the cutting-data verdict. Do not infer it from geometry, operation names, coolant, a preset material filter, or Fusion's stock-material field. Treat `setup.context.stock_material` only as exported Fusion evidence for comparison. If the user has not supplied a material, extraction may proceed, but ask for the exact designation and mark every feeds-and-speeds verdict as pending rather than deciding whether the values are safe or suitable. Ask for temper, condition, or hardness only when it can materially change the recommendation.

Use the user-supplied material designation as the governing material input. Use authoritative material standards or producer data to interpret that designation, never to replace it with a guessed material. Use authoritative cutter-manufacturer cutting data when the exact tool is identifiable, and treat generic tables as context, not proof for an unidentified cutter. Clearly state when missing tool, machine, or workholding data prevents a firm verdict, then identify the smallest concrete facts needed to resolve it.

Assume the user may not know milling terminology, cutter selection, or material behavior. Compensate by proactively finding inconsistencies, explaining each important quantity and consequence in plain language, and giving an actionable recommendation or verification step. Do not shift the analysis burden back to the user with unexplained jargon. When the user supplies factual shop-floor context that is absent from Fusion, incorporate it, distinguish it from exported evidence, and revise or retract earlier findings when appropriate.

## Read-only boundary

The bundled extractor only reads the active document. Do not activate a setup, call `CAM.checkValidity`, generate or clear toolpaths, change parameters, save the document, or run simulation as part of extraction. Any later mutation needs an explicit user request.

Use the local `fusion-api-lookup` skill before changing `scripts/extract_setup.py`; the extractor depends on version-pinned `adsk.cam` API shapes.

## Select the setup

Honor a setup name, operation id, or zero-based index supplied by the user. If none is supplied, the extractor chooses exactly one selected setup, then exactly one active setup, then the document's only setup. Ambiguity is an error that lists the available setups; show that list and ask the user which one to use.

For comparison requests, export each named setup separately with the same time assumptions.

## Extract

1. Resolve this skill's `scripts/` directory and create an isolated output directory with `mktemp -d`.
2. Invoke `fusion_mcp_execute` with a pure-ASCII wrapper that imports `extract_setup`, reloads it, and calls `extract_setup.run` with JSON context. Encode non-ASCII selector text as JSON escapes in the wrapper source.
3. Pass an absolute `output_dir`. It must be empty. Read `setup.json` and the referenced files under `operations/` locally; do not rely on a possibly truncated MCP console payload.
4. Run `python3 scripts/build_intensity_checklists.py <output_dir>`. This
   creates `intensity-checklists.md`, one evidence-backed checklist skeleton
   per operation. An empty setup is an error, not a successful review. The
   generated Markdown is a review artifact, not part of the export schema.

Use this wrapper shape, replacing paths and config values:

```python
import importlib
import json
import sys

SCRIPT_DIR = "/absolute/path/to/this/skill/scripts"
CONFIG = {
    "setup": {"name": "Setup1"},
    "output_dir": "/absolute/temp/path/setup-export",
    "review_context": {
        "workpiece": {
            "material_designation": "D16 aluminum",
            "source": "user"
        },
        "tools": [
            {
                "tool_number": 8,
                "actual_overall_length_mm": 75.0,
                "source": "user"
            }
        ]
    },
    "time_assumptions": {
        "feed_scale_percent": 100.0,
        "rapid_feed_cm_s": 100.0,
        "tool_change_seconds": 0.0
    }
}

def run(_context: str):
    if SCRIPT_DIR not in sys.path:
        sys.path.insert(0, SCRIPT_DIR)
    import extract_setup
    importlib.reload(extract_setup)
    extract_setup.run(json.dumps(CONFIG, ensure_ascii=True))
```

Supported selectors are `{"name": "..."}`, `{"operation_id": 123}`, `{"index": 0}`, `{"mode": "selected"}`, and `{"mode": "active"}`. Omit `setup` for the default selection rules.

Always place the material designation supplied by the user in `review_context.workpiece.material_designation` with `source: user`; this value governs the machining review. Keep Fusion's stock-material value separate in the exported setup context. If they differ, report both and the discrepancy instead of merging them. Pass every other relevant fact already supplied by the user but absent or known to be stale in Fusion through `review_context`, including temper when relevant, real cutter dimensions or stickout, holder/workholding facts, and a completed verification result. Preserve a short `source` label. When a setup has multiple tools, scope each shop-floor tool fact by tool number, description, product id, or another exported identifier. If the intended tool cannot be determined, mark the scope unresolved instead of applying the fact globally. Do not invent missing context or silently replace the exported Fusion value; the JSON must retain both so discrepancies remain reviewable.

The output layout is:

```text
<output_dir>/
|-- setup.json
|-- intensity-checklists.md
`-- operations/
    |-- 001-op-<id>-<name>.json
    `-- ...
```

`setup.json` contains the setup-level parameters and context, tree, containers, counts, and an `operation_files` manifest. It contains no tool collection. Each operation file is self-contained and includes document/setup provenance plus the complete operation record. That record has exactly one `operation.tool` object, or `null` when Fusion reports that the operation has no tool. There is no separate `tool_ref`, top-level tool, or shared tool manifest. The extractor does not write a combined monolithic JSON. Read [references/export-schema.md](references/export-schema.md) when consuming or changing the JSON contract.

Every accessible item in Fusion's `CAMParameters` collection is exported once into a `parameters` object keyed by the stable internal `CAMParameter.name`. Each value contains the unit-aware `expression`, current `resolved` value where the API exposes one, compact value/unit types, and `enabled`/`visible` state. Choice parameters contain only the selected value, never the list of available choices. `parameter_count` must equal the number of keys in `parameters`. Tool preset parameter arrays and tool CAM-parameter arrays are omitted because the operation parameters already contain the effective values. The single attached tool retains the informative `Tool.toJson()` definition except volatile `guid` and duplicated `start-values`.

The tool also contains a compact `library_context` with safety-relevant tool-library fields not repeated by the operation, such as coolant support and preset material applicability. `tool_preset.material_context` preserves the selected preset's material filter without copying redundant preset feed/speed defaults. `snapshot_coverage` states what the snapshot includes and what still requires simulation or external shop context.

Cycle-time values are estimates. Preserve the extractor's feed-scale, rapid-feed, and tool-change assumptions in the report. If the user gives machine-specific values, pass those instead of the defaults.

## Review

Read [references/review-framework.md](references/review-framework.md) after extraction. Treat each `parameters.<internal_name>.expression` as the unit-aware source of truth; resolved numeric values use the semantics identified by `unit_type` and must not be compared across unlike parameter types.

For milling or drilling work, also read
[references/strategy-intensity-checklists.md](references/strategy-intensity-checklists.md).
Apply its universal checklist and the checklist selected by the operation's
exact `strategy` identifier to **every operation separately**. Record each
item as pass, change required, unknown, or not applicable, with the exact
parameter keys and calculations that support the result. An operation table
alone is not a substitute for these per-operation checks.

Always report **TABS and part retention** as its own checklist group for every
operation. Do not bury it under engagement, passes, heights, or workholding.
For an operation that can cut a closed contour to the stock bottom, inspect
the exported tab-enable switch and all tab geometry/placement parameters, then
decide whether tabs are required in view of the real workholding, bottom stock,
onion skin, screws, vacuum, or another positive retention method. A disabled
tab switch makes its child width/height/count values inactive; it is not proof
that the part remains held. Mark the group not applicable only when the
operation cannot release or destabilize the part.

Always report **Thread Offset (Pitch Diameter Offset)** as its own checklist
group. Mark it not applicable for operations whose exact strategy is not
`thread`. For a Thread operation, inspect the enabled parameter whose exported
name or title represents Pitch Diameter Offset, and verify it as the positive
diametral difference `major diameter - minor diameter`, not as a radial depth.
Reconcile it with the selected internal/external thread, definition method,
modeled cylinder diameter, nominal thread specification, and pitch. Do not
confuse it with the thread-mill cutter's `tool_tipOffset`, the tool diameter
compensation offset, or any machining-height offset. If the required major and
minor diameters cannot be established, mark the verdict unknown rather than
accepting a plausible-looking value.

The snapshot includes every accessible setup, container, and operation parameter. Use the complete `parameters` arrays when reviewing; `enabled` distinguishes parameters active for the current strategy state. Tool and preset defaults are not repeated because effective operation values are already present.

## Deliver

Return:

- a concise overall assessment;
- an operation table with strategy, tool, calculated cutting-data verdict, key feeds/speeds, key pass settings, and toolpath state;
- findings ordered by severity, each with exact evidence, impact, recommendation, and confidence;
- plain-language explanations of material/tool/feed interactions that the user should not be expected to infer;
- missing machining context that limits recommendations, stated as concrete facts to obtain;
- clickable links to `setup.json`, `intensity-checklists.md`, and the relevant operation JSON files.

State explicitly that parameter review does not replace toolpath simulation, collision checking, workholding verification, or a controlled prove-out on the actual machine.
