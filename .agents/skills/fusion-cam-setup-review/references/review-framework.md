# CAM setup review framework

Use this framework after reading the extractor JSON. It is a review aid, not a universal machining recipe.

## Evidence rules

- Quote the setup and operation names plus parameter-map keys and expressions. Parameter keys are Fusion's internal names; do not rely on localized UI titles.
- Distinguish `observed` facts from `inferred` risks and `recommended` changes.
- Use `expression` for human-facing values and units. A numeric `resolved` value is in Fusion's internal units identified by `unit_type`.
- Do not infer material, machine rigidity, spindle power curve, holder reach, workholding strength, tool-material limits, or acceptable surface finish when they are absent.
- Treat the material designation supplied by the user as authoritative for the cutting-data review. Fusion's stock-material field and preset material filters are comparison evidence only; if they differ, report the discrepancy explicitly.
- If the user has not supplied a material designation, complete the requested extraction, ask for the exact designation, and keep feeds-and-speeds verdicts pending. Ask for temper, condition, or hardness only when it can materially change the recommendation.
- Never claim collision safety from parameter inspection. Require simulation and a machine prove-out for that conclusion.
- Treat shop-floor facts supplied by the user as explicit external context. Do not silently overwrite exported Fusion values; show the discrepancy and base the machining verdict on the confirmed real condition.
- Before a final cutting-data verdict, require user-sourced workpiece material,
  physical cutter characteristics for every used tool, and spindle
  characteristics. Fusion tool, material, preset, and machine metadata are
  comparison evidence only. Ask one bundled question for missing facts and
  keep the affected verdicts pending while waiting.

## Review order

### 1. Program integrity

Check setup and operation errors/warnings first. Flag operations that are generating, lack a toolpath, have an invalid toolpath, are suppressed, or have no tool when their strategy requires one. Explain protected and optional states; they are not failures by themselves.

### 2. Tool and material context

Identify the cutter type, diameter, flute count, tool material/coating, cutting length, holder/stickout information, and manufacturer/product when available. Require the workpiece alloy or grade from the user before issuing a final feeds-and-speeds verdict; identify its temper, condition, or hardness when relevant. Require the user to confirm the physical cutter facts for every used tool instead of treating the Fusion library as confirmation. Also require user-sourced spindle power, maximum and usable RPM range, and known motor/VFD or low-speed torque behavior. Ask only for missing fields when other facts are already established. Do not treat overall tool length as cutting length or usable reach.

If exact cutter data is available, prefer its manufacturer's cutting recommendations. If only a generic cutter is known, give a bounded, lower-confidence assessment and say which missing property could change it. Interpret the user's material designation through authoritative standards or producer data before comparing cutting values; do not substitute a guessed designation.

### 3. Feeds and speeds — primary machining verdict

For every operation, decide whether the effective feeds and spindle speed are coherent with the cutter, material, strategy, and engagement. This verdict is the central result of the review, not a transcription exercise.

For every enabled feed/speed parameter, report the internal name, expression, and resolved value. Prefer the operation value over tool or preset defaults when both are present.

Normalize units and calculate the applicable quantities:

- milling: `vc`, programmed `fz`, and maximum chip thickness when radial chip thinning applies;
- drilling/boring: feed per revolution, peck or helical pitch, and entry conditions as applicable;
- ramping/plunging: ratios to cutting feed and whether the cutter is suited to the entry mode;
- engagement: `ae/D` and `ap/D` or comparison to cutting/flute length where geometry is known.

For every drilling-like move made with an end mill, including Bore and helical/ramp entry, never judge the programmed feed independently of the entry angle. Calculate the motion at the tool center:

- tool-center orbit radius: `(hole diameter - cutter diameter) / 2`;
- pitch per orbit: `2 * pi * orbit radius * tan(entry angle)`;
- axial feed component: `programmed path feed * sin(entry angle)`;
- approximate orbit count: axial depth / pitch.

Treat a zero or very small orbit radius as a separate process risk even when Fusion generates a valid path: the cutter is effectively plunging, chip space collapses, and a non-center-cutting end mill may not cut at all. Compare the axial component and pitch with the cutter maker's ramp/plunge limits, flute volume, depth, coolant or air blast, spindle torque curve, and observed chip evacuation. A high-power spindle does not by itself make a large axial feed or near-diameter helical bore acceptable. For a true drill cycle, calculate feed per revolution instead and check peck depth and chip-breaking behavior.

An observed shop-floor failure such as chip packing, chip welding, stalled RPM, or abnormal sound overrides a generic parameter verdict. Stop the prove-out, record the failed geometry and settings, and require a lower-load or better-evacuating process before resuming; do not merely reduce the overall feed without checking orbit clearance, entry angle, and axial feed.

Do not compare programmed `fz` values without considering radial engagement. A finishing pass with small radial stock can require a higher programmed `fz` to maintain chip thickness; calculate this before flagging an inconsistency. Conversely, do not apply chip-thinning compensation to full-slot or otherwise high-engagement cutting.

Check for:

- missing, zero, or negative cutting, plunge, ramp, lead-in/out, spindle, or surface-speed values where applicable;
- unusually large differences between cutting, plunge, ramp, and entry feeds, stated as ratios only when units match;
- inconsistent feeds or spindle speeds for the same tool and comparable engagement without an evident reason;
- built-up-edge, chip-evacuation, rubbing, deflection, overload, and finish risks supported by the actual material/tool/engagement evidence;
- values outside identified manufacturer guidance, with the exact source assumptions and the setup's deviation.

Explain the result in plain language: what the value controls, what failure mode is plausible, and what to change or verify. Do not expect the user to translate `fz`, `vc`, radial engagement, or material-condition terminology unaided.

For turning, tapping, probing, additive, and jet strategies, use strategy-appropriate quantities instead of forcing milling formulas.

### 4. Operation sequence and strategy

Walk `tree` in browser order. Assess whether roughing, rest machining, semi-finishing, finishing, drilling, chamfering, and deburring occur in a coherent dependency order. Note unnecessary tool changes, repeated strategies, or finishing before relevant stock is removed. Treat names as hints and `strategy` as the authoritative strategy identifier.

### 5. Pass strategy

Review enabled parameters involving stepdown, stepover, optimal load, tolerance, smoothing, stock to leave, multiple depths, finishing passes, compensation, direction, order, and rest machining. Compare radial/axial engagement with tool diameter and flute length only when those values are known and unit-normalized.

Look for a deliberate finish allowance followed by a finishing operation, a plausible transition from rough to finish tolerances, and pass settings compatible with thin walls or deep features. Without material, tool maker limits, and rigidity, phrase engagement recommendations as items to confirm rather than definitive corrections.

### 6. Entry, linking, and heights

Review ramp/helix/plunge mode, lead-in/out, keep-tool-down/stay-down behavior, safe distance, clearance/retract/top/bottom heights, boundaries, and avoid/touch selections. Identify contradictory or surprisingly aggressive settings, but require simulation to validate clearances and collisions.

### 7. Time and efficiency

Use `machining_time` only when the toolpath exists. Report the configured feed scale, rapid feed, and tool-change time beside the estimate. Fusion can apply document machine/controller data and may not respond to the supplied rapid-feed input, so label these as requested assumptions rather than guaranteed effective values. Compare feed distance, rapid distance, feed time, rapid time, and tool-change count; do not present the estimate as controller-accurate cycle time.

## Severity and confidence

- **Blocker:** Fusion reports an error, a required operation lacks a valid path/tool, or an enabled applicable cutting value is invalid.
- **High:** strong evidence of a likely unsafe or nonfunctional process, but Fusion has not emitted a blocker.
- **Medium:** likely quality, tool-life, or efficiency issue that depends on machining context.
- **Low:** cleanup, consistency, naming, or optimization opportunity.

Give each finding a confidence of high, medium, or low. Reduce confidence when material, machine, workholding, tool specification, stock state, or simulation evidence is missing.

## Report shape

1. Overall assessment and counts.
2. Setup assumptions and missing context.
3. Browser-order operation table: order, name, strategy, tool/preset, calculated cutting-data verdict, key feeds, key passes, toolpath status.
4. Findings: severity, operation, evidence, impact, recommendation, confidence.
5. Plain-language explanation of the important tool/material/feed interactions and the concrete missing facts.
6. Efficiency and estimated-time notes.
7. Required validation: simulation, collision checking, workholding check, and controlled prove-out.
