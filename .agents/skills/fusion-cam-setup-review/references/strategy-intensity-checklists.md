# CAM strategy cutting-intensity checklists

Use this reference for milling and drilling operations after extracting the
setup. It identifies parameters that can change cutting load, heat, chip
evacuation, deflection, spindle demand, or tool life. It is not a table of
universal cutting values.

## Required output for every operation

Create a separate checklist for every operation in browser order, even when
several operations use the same strategy and tool. Every row needs one of:
`pass`, `change required`, `unknown`, or `not applicable`.

For each row record:

- the observed Fusion expression and its internal parameter name;
- any external shop fact used instead of stale or missing Fusion metadata;
- the calculated quantity or comparison;
- the consequence and concrete correction or missing fact.

Use only enabled parameters to describe the operation's current behavior.
Also inspect the switches that enable conditional load controls, such as
multiple depths, roughing passes, feed optimization, stock to leave, ramping,
pecking, and finishing passes. A disabled numeric child does not currently
control the path, but its parent switch can materially change the result.

Do not mark a checklist complete merely because no suspicious parameter name
was found. Geometry and stock state can turn an apparently light strategy into
a full-width cut.

## Mandatory user-supplied inputs

Before deciding feeds, speeds, or engagement, confirm all three categories
from explicit user-sourced context. If anything decision-relevant is missing,
ask once for the missing facts and keep the affected verdicts `pending`:

- exact workpiece material designation, plus temper/condition/hardness when it
  changes the cutting recommendation;
- actual cutter type, diameter, flute/tooth count, cutter material, coating,
  usable cutting length, and stickout for every tool; maker/product cutting
  limits and center-cutting/ramp capability when available or relevant;
- spindle rated power, maximum and usable RPM range, motor/pole/VFD or known
  low-speed torque behavior; model and torque/power curve when available.

Previously supplied user facts remain valid for their established scope and
must not be requested repeatedly. Fusion library, preset, stock-material, and
machine-definition values do not satisfy this gate. If the user answers that a
fact is unknown, record the limitation and lower confidence instead of
inventing a value or marking the check passed.

## Persistent facts for this shop

These facts were explicitly supplied by the user and override contradictory
tool-library or machine metadata when this shop is in scope:

- End mills are carbide and have three flutes. A Fusion end-mill definition
  that says HSS or uses another flute count is stale. Report the discrepancy,
  calculate milling chip load with three flutes, and, when CAM editing is
  authorized, correct the tool definition. Do not apply the three-flute rule
  to drills, taps, reamers, or other non-end-mill tools.
- The spindle is 2.2 kW, two-pole, and has little low-speed torque. Do not make
  a cut gentler merely by forcing very low RPM. Keep cutter-appropriate surface
  speed and reduce feed or engagement when load must fall. Nameplate power is
  not proof of available torque at a given RPM.
- Drilling must be programmed deliberately slower. A previous reviewed drill
  operation packed or welded aluminum chips. Lower axial feed is the default
  correction, then verify feed per revolution, pecking, depth, coolant or air,
  and chip escape. For helical boring with an end mill, lower ramp/path feed
  and still calculate the angle-derived axial component; the angle check must
  not be used to justify retaining an excessive feed.
- Stock outside the modeled contour can make a contour operation cut a full
  slot. Unless the actual stock envelope proves one-sided engagement, review
  the worst credible engagement rather than assuming peripheral cutting.

Keep the setup's user-supplied alloy or grade separate from these shop facts.
For example, D16 applies only when the user identifies the current workpiece
as D16.

## Universal checklist

Apply all of these items before the strategy-specific section.

### Tool reality

- Confirm the user-supplied physical type, diameter `D`, corner or tip geometry, flute count `z`, cutting
  length, overall reach, stickout, holder, material, coating, product id, and
  center-cutting capability. Do not confuse overall length with flute length.
- Compare the physical tool facts with `operation.tool.definition` and
  effective `tool_*` parameters. Resolve every discrepancy before using the
  library values in calculations.
- Check whether the deepest axial engagement and every ramp remain on usable
  flute, with chip space and holder clearance.

### Feeds, speed, and spindle demand

- Inspect `tool_spindleSpeed`, `tool_rampSpindleSpeed`, `tool_feedCutting`,
  `tool_feedEntry`, `tool_feedExit`, `tool_feedTransition`, `tool_feedRamp`,
  `tool_feedPlunge`, `tool_feedRetract`, `tool_feedPerTooth`,
  `tool_feedPerRevolution`, and `tool_coolant` when present and enabled.
- Calculate milling surface speed `vc = pi * D * n / 1000` in m/min for `D`
  in mm, and programmed chip load `fz = F / (n * z)` in mm/tooth.
- For drilling calculate feed per revolution `f_rev = F_axial / n`. For
  tapping verify that feed and pitch are synchronized; do not judge it as
  ordinary drilling.
- Compare cutting, entry, ramp, plunge, transition, and reduced feeds as
  ratios only after normalizing units. Explain which physical motion uses each
  value.
- When `ae` and `ap` are known, calculate `ae/D`, `ap/D`, and the material
  removal proxy `MRR = ae * ap * F`. Use maximum chip thickness rather than
  programmed `fz` when radial chip thinning applies. Never apply chip-thinning
  compensation to full-slot cutting.
- Check both ends of the spindle range. Excessive RPM can exceed cutter or
  machine limits; too little RPM can cause rubbing and unusable torque on a
  high-speed, low-torque spindle. Do not infer delivered power from the 2.2 kW
  nameplate alone. If an actual power curve is available, the torque check may
  use `T = 9550 * P / n`.

### Engagement and stock state

- Establish the worst credible radial engagement `ae`, axial engagement `ap`,
  and whether any segment is full slot (`ae/D` approximately 1). Use the setup
  stock, rest material, previous operations, boundaries, stock-to-leave state,
  and model geometry; the strategy name does not prove engagement.
- Inspect tolerance, smoothing, direction, compensation, multiple depths,
  finishing or roughing passes, rest machining, radial stock to leave, and
  axial stock to leave. These can move load between operations or create a
  surprise heavy finish pass.
- Check thin walls, interrupted cuts, narrow pockets, inside corners, and
  small radii. A constant programmed feed does not imply constant cutter load.

### Entry and chip evacuation

- Identify every plunge, helix, profile ramp, zig-zag ramp, predrill entry,
  lead, and re-entry into rest stock. Check its own feed, angle, pitch,
  diameter, stepdown, and clearance rather than assigning cutting feed to it
  implicitly.
- For a helical move calculate tool-center orbit radius
  `r = (hole_diameter - D) / 2`, pitch per orbit
  `p = 2 * pi * r * tan(angle)`, axial feed
  `Fz = F_path * sin(angle)`, and approximate orbit count `depth / p`.
- Treat zero or very small orbit radius as near-plunging. Confirm a
  center-cutting tool and enough chip volume; otherwise require a larger entry,
  predrill, or another strategy.
- Confirm coolant or air delivery and an escape path for aluminum chips.
  Previous chip packing, welding, stalled RPM, or abnormal sound overrides a
  nominally acceptable calculation and requires a lower-load prove-out.

### TABS and part retention

- Report TABS as a separate result for every operation: `pass`,
  `change required`, `unknown`, or `not applicable`. Never merge it into the
  general pass-strategy or workholding verdict.
- For any operation that can reach the stock bottom around a closed contour,
  determine whether the cut can release, tilt, chatter, or pull the part into
  the cutter. Check positive retention from tabs, real fixtures, screws,
  vacuum, an onion skin, or intentional bottom stock; the operation name does
  not prove the part remains held.
- Inspect the exported tab-enable switch first. In current Fusion 2D contour
  exports this can appear as `group_tabs`; also inspect the actual exported
  internal name if another strategy/version uses a different switch. If it is
  false, disabled child defaults such as `tabWidth` and `tabHeight` do not
  affect the path.
- When tabs are enabled, inspect every enabled tab control, including
  `tabShape`, `tabWidth`, `tabHeight`, `tabPositioning`, `tabApproach`,
  `tabsPerContour`, `tabDistance`, `tabPositions`, and `noTabZones` when
  present. Use the exported parameter names rather than assuming all versions
  expose the same set.
- Check tab height against breakthrough/bottom offset and actual stock
  thickness; check width and count against cutter diameter, material, contour
  size, cutting forces, long-tool leverage, and the mass of the released part.
  Confirm tabs are distributed so the final segment cannot pivot about one
  remaining bridge.
- Check the browser sequence. A later finish pass must not unintentionally
  erase roughing tabs unless another retention method is already active.
  Identify the planned tab-removal and deburring operation; leaving tabs with
  no removal plan is incomplete, but removing them before the part is secured
  is unsafe.

### Thread Offset (Pitch Diameter Offset)

- Report Thread Offset as a separate result for every operation. Mark it
  `not applicable` unless the exact operation strategy is `thread`; do not
  infer thread milling from tool-library fields that happen to contain the
  word `thread`.
- For a Thread operation, inspect the enabled parameter whose internal name or
  title represents **Pitch Diameter Offset**. Current or older exports may use
  a name resembling `pitchDiameterOffset`, `threadOffset`, or `threadDepth`;
  use the actual exported name and resolved units rather than assuming one
  spelling.
- Verify the value as the positive **diametral** difference
  `D_major - D_minor`. The corresponding one-side radial thread depth is half
  that value. Explicitly reject a sign error or a factor-of-two mix-up.
- Reconcile the offset with internal versus external thread selection, the
  definition method (manual, standard, or automatic), the selected/modelled
  cylinder diameter, nominal thread size, pitch, hand, starts, tolerance or fit
  class, and any finish/wear compensation. A value that is correct for a hole
  modeled at minor diameter is not automatically correct for a boss or a model
  represented at another diameter.
- Do not substitute `tool_tipOffset`, `tool_diameterOffset`,
  `tool_compensationOffset`, or any `*Height_offset` parameter. They describe
  cutter geometry, controller registers, or height planes, not the thread's
  pitch-diameter geometry.
- If the governing major and minor diameters or the selected reference
  geometry cannot be established, mark the check `unknown`. A generated
  toolpath or a plausible-looking positive number is not sufficient evidence.

## Strategy routing

Use the exact exported `operation.strategy`; operation names are only labels.

| Checklist | Strategy identifiers |
| --- | --- |
| Adaptive and variable-engagement roughing | `adaptive`, `adaptive2d`, `pocket_clearing`, `multiaxis_roughing`, `three_plus_two`, `rotary_pocket` |
| Fixed-step pocket and slot | `pocket2d`, `slot` |
| Contour and wall following | `contour2d`, `contour3d`, `circular`, `ramp`, `trace`, `rotary_contour`, `multi_axis_contour`, `swarf`, `advanced_swarf`, `inclined_walls` |
| Face and flat areas | `face`, `flat`, `horizontal` |
| Helical bore | `bore` |
| Drilling cycles | `drill` |
| Thread milling | `thread` |
| Surface finishing | `blend`, `flow`, `flow2`, `geodesic`, `morph`, `morphed_spiral`, `parallel`, `pencil`, `radial`, `scallop`, `spiral`, `project`, `corner`, `rotary_finishing`, `steep_and_shallow`, `multiaxis_finishing`, `multi_axis_morph` |
| Chamfer, engraving, deburr | `chamfer`, `chamfer2d`, `engrave`, `deburr` |
| Cutting profiles | `profile2d` |
| Non-cutting or container | `folder`, `manual`, `probe`, `probe_geometry`, `hole_recognition`, `inspect_surface`, `feature_construction` |

If a new or unknown strategy appears, apply the universal checklist, inspect
all enabled parameters, and construct an operation-specific checklist from
their physical effects. Do not guess equivalence from the localized title.

## Adaptive and variable-engagement roughing

- Check `optimalLoad`, `optimalLoadOtherWay`, `maximumStepdown`,
  `fineStepdown`, `minimumStepdown`, `minimumCuttingRadius`, `direction`, and
  flat or shallow-area controls. Calculate `optimalLoad/D` and
  `maximumStepdown/D`, but state that actual engagement can deviate around
  corners and remaining stock.
- Check rest-material source and `restMaterialCutterDiameter`. Wrong previous
  stock can cause unexpected full engagement.
- Check `useStockToLeave`, `stockToLeave`, and `verticalStockToLeave`; confirm
  a later operation actually removes the allowance.
- If `useFeedOptimization` is enabled, inspect `reducedFeedrate`,
  `reducedFeedChange`, `reducedFeedRadius`, and `reducedFeedDistance`. Verify
  the reduced feed is lower in the regions that need it.
- Apply the complete ramp checklist to `doRamp`, `rampType`, `rampAngle`,
  `helicalRampDiameter`, `minimumRampDiameter`, `maximumRampZStepdown`, and
  `rampClearanceHeight`.

## Fixed-step pocket and slot

- Check `maximumStepover` or `stepover`, `doMultipleDepths`,
  `maximumStepdown`, `useEvenStepdowns`, roughing and finishing pass switches,
  finish feed, and radial or axial stock to leave.
- Calculate the commanded `ae/D` and `ap/D`, then separately test the first
  cut, islands, narrow channels, and rest-stock transitions for full-width
  engagement.
- Treat `slot` as full-width by default. A `pocket2d` entry or narrow region can
  also become full-width even when the nominal stepover is small.
- Check helix or profile-ramp angle, diameter, radial clearance, ramp feed, and
  maximum ramp stepdown. Verify the tool can center cut if the path collapses
  toward a plunge.

## Contour and wall following

- Prove the stock condition at every contour. If stock may extend outside the
  model, review as a possible full slot and do not apply peripheral-cut or
  chip-thinning assumptions without evidence.
- Check `doMultipleDepths`, `maximumStepdown`, roughing passes,
  `maximumStepover`, finishing stepovers or stepdowns, finish feed, repeat
  pass, compensation side and type, direction, radial stock, and axial stock.
- Check inside radii against tool diameter and `minimumCuttingRadius`; inspect
  feed optimization or reduced-feed settings for corner overload.
- Check lead-in/out radius and sweep, ramp enable/type/angle/feed, maximum ramp
  stepdown, and whether leads occur on all finishing passes.
- Apply the complete **TABS and part retention** checklist above. For a closed
  contour reaching stock bottom, `group_tabs=false` requires affirmative
  evidence of another retention method; a valid Fusion toolpath alone is not
  sufficient.
- For `slot`, `trace`, and single-chain wall paths, confirm whether repeated
  passes deepen the same groove and trap chips.

## Face and flat areas

- Check `stepover`, `maximumStepdown`, finishing stepdown, direction,
  `useChipThinning`, stock allowance, and actual stock thickness above the
  model.
- Calculate `ae/D` and `ap/D`; account for the first and last pass having a
  different engagement from central passes.
- Check whether a small leftover strip creates a near-full-width final pass.
  Check entry and exit outside the stock and whether bidirectional motion uses
  climb and conventional cuts differently.

## Helical bore

- Confirm this is an end-mill orbit, not a drill cycle. Check cutter diameter,
  hole diameter, final depth, usable flute length, `useAngle`, `plungeAngle`,
  `threadPitch`, `tool_feedRamp`, `tool_feedPlunge`, and spindle speed.
- Calculate orbit radius, pitch per orbit, axial feed component, orbit count,
  and feed per tooth at the programmed path feed. Very small radial clearance
  is a high chip-packing risk.
- Check `doMultiplePasses`, `numberOfStepovers`, `stepover`, finishing passes,
  `finishingStepover`, stock to leave, direction, and compensation.
- On this shop's machine, reduce the bore/ramp feed when uncertain or after
  aluminum chip packing. Do not treat spindle power as permission for a fast
  axial component.

## Drilling cycles

- Identify tool type and `cycleType` first: drilling, deep drilling, chip
  breaking, reaming, boring, tapping, counterboring, and circular pocketing do
  not share one load model.
- Inspect `tool_spindleSpeed`, `tool_feedPlunge`,
  `tool_feedPerRevolution`, `tool_feedRetract`, actual depth, drill-tip and
  breakthrough settings, starting depth, feed height, and hole diameter.
- For pecking or chip breaking inspect `peckingDepth`,
  `peckingDepthReduction`, `minimumPeckingDepth`,
  `accumulatedPeckingDepth`, `chipBreakDistance`, retract behavior, and dwell.
  Compare peck depth with diameter, flute space, hole depth, coolant, and the
  ability of chips to leave the hole.
- For tapping verify `pitch`, direction, spindle synchronization, and the
  machine/controller capability. Feed must equal RPM times thread pitch.
- On this shop's machine, choose a deliberately slower axial feed and staged
  prove-out. The checklist still has to show `f_rev`, peck behavior, and chip
  evacuation; "slower" without those values is not a completed review.

## Thread milling

- Apply the complete **Thread Offset (Pitch Diameter Offset)** checklist above.
- Confirm thread mill geometry, thread pitch, major/minor/pitch diameters,
  radial stock, `doMultiplePasses`, `numberOfStepovers`, `stepover`, direction,
  compensation, and lead radius.
- Verify programmed motion produces the specified pitch and that radial
  infeed per pass is compatible with the cutter and thread depth. Check the
  small orbit for chip crowding and deflection.

## Surface finishing

- Check the strategy's stepover control (`stepover`,
  `cuspHeightStepover`, projection stepover, steep stepover, or equivalent),
  stepdown control, tool effective cutting diameter, surface slope, tolerance,
  smoothing, stock to leave, cutting direction, and rest-material source.
- Calculate the expected scallop or maximum chip thickness when tool geometry
  and contact point permit it. A ball or barrel tool's effective diameter at
  contact can differ materially from its nominal diameter.
- Inspect transitions between steep, shallow, flat, pencil, and rest regions.
  A nominal finishing path can encounter roughing stock if its predecessor or
  boundary is wrong.
- Check reduced-feed or feed-optimization controls at inside corners and
  direction reversals, plus lead and linking moves that re-enter material.

## Chamfer, engraving, and deburr

- Derive effective cutting diameter and axial/radial engagement from chamfer
  width, tip offset, angle, selected edge, and heights. Nominal tool diameter
  alone is not the cutting diameter.
- Check depth per pass, multiple passes, stock or offset, feed, RPM, leads,
  compensation, and whether sharp corners force a speed reduction.
- For engraving, confirm the actual depth and tip geometry; small depth errors
  can multiply engagement on tapered tools.

## Multi-axis and rotary additions

Apply the routed milling checklist first, then also check tool-axis tilt,
lead/lean, rotary diameter, inverse-time or rotary feed behavior, singularity
handling, axis speed limits, smoothing, holder clearance, and whether machine
kinematics reduce the achievable feed. Parameter review cannot prove these
motions safe; require machine simulation and a controlled prove-out.

## Cutting profiles and non-cutting strategies

For `profile2d`, use the process-appropriate cutting-power model rather than
milling chip-load formulas; inspect kerf, quality, power or pressure, cutting
feed, pierce mode, pierce delay, heights, and material thickness.

For non-cutting/container strategies, mark cutting-intensity items not
applicable but still report program-integrity issues and any motion feed that
can affect probing or positioning safety.
