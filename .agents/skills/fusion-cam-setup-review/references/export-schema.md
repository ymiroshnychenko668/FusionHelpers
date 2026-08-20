# Fusion CAM AI export schema

Schema identifier: `fusion-cam-ai-export/v6`.

## Files

- `setup.json` has `kind: fusion_cam_setup` and owns setup-level context plus the operation-file manifest.
- Every `operations/*.json` has `kind: fusion_cam_operation` and is self-contained for one operation.

All files from one export share `extracted_at_utc`, document provenance, time assumptions, `review_context`, and `snapshot_coverage`. Paths in `setup.json` are relative to the export directory. An operation's `setup_ref.file` is relative to that operation file.

## Review and coverage context

`review_context` contains relevant facts supplied outside Fusion, with an explicit source, such as the real alloy/temper, cutter dimensions or stickout, holder/workholding facts, or a completed verification result. `review_context.workpiece.material_designation` must come from the user and is the governing material input for cutting-data review. Fusion's stock-material value remains separately exported in `setup.context.stock_material` for comparison and must not populate or override the user value. A missing user material leaves feeds-and-speeds verdicts pending; a mismatch with Fusion must remain explicit. Tool facts must be scoped to an exported tool identifier when multiple tools exist; unresolved scope must remain explicit. The context is intentionally separate from exported Fusion values so stale tool-library data remains visible instead of being silently overwritten.

`snapshot_coverage` distinguishes data captured by the exporter from facts that the public CAM snapshot cannot provide. In particular, toolpath validity is not equivalent to completed simulation or collision verification.

## Parameters

`parameters` is an object keyed by Fusion's stable internal `CAMParameter.name`:

```json
"parameters": {
  "tool_feedCutting": {
    "expression": "200 mmpm",
    "enabled": true,
    "visible": true,
    "value_type": "float",
    "resolved": 200.0,
    "unit_type": "FeedRateParameterType"
  }
}
```

- `expression` is the authoritative unit-aware Fusion expression.
- `resolved` is the current evaluated value when the parameter value type exposes one.
- `unit_type` identifies the meaning of a resolved float; do not compare numeric values with different unit types.
- `enabled` says whether the parameter affects the current strategy state. Disabled parameters remain present for completeness.
- `visible` records whether Fusion currently exposes the parameter in its operation dialog.
- Selection parameter types use `selection_count` or `group_count`; CAD-object values contain compact object type/name summaries.
- `warning`, `error`, and read-error fields are sparse and appear only when applicable.
- Choice parameters contain only their selected `resolved` value. Available-choice catalogs are intentionally omitted.

`parameter_count` must equal the number of keys in `parameters`. A mismatch means the export is incomplete.

## Tool ownership

An operation has exactly one `operation.tool` object or `null`. Setup files contain no tool collection. The tool has:

- `key`: a stable hash of the normalized definition;
- `description`: Fusion's human-readable tool description;
- `definition`: `Tool.toJson()` with volatile `guid` and redundant feed/speed `start-values` removed.
- `library_context`: selected tool-library parameters that affect review but are not repeated in operation parameters, including coolant support and material applicability/hardness filters.

Effective feeds, speeds, coolant, and pass settings live only in the operation parameter map. Tool geometry, material, vendor/product metadata, and post-process offsets remain in the tool definition.

`operation.tool_preset.material_context` preserves only the selected preset's material applicability parameters. Preset feed/speed arrays remain omitted because the operation parameter map is the authoritative effective state.

## Completeness invariants

- One setup file per requested setup.
- One operation file per Fusion operation, preserving browser order through `sequence` and `tree`.
- One tool maximum per operation.
- No monolithic duplicate of all operation records.
- No duplicate CAM parameter names, choice catalogs, entity tokens, or repeated preset/tool parameter arrays.
- Relevant external shop facts are preserved in `review_context`, never merged into or substituted for Fusion values.
- Extraction is read-only and does not validate, generate, clear, activate, or edit toolpaths.
