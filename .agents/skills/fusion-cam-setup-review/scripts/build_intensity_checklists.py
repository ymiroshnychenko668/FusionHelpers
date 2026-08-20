"""Build one cutting-intensity checklist skeleton per exported CAM operation."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


_GROUPS = (
    (
        "Feeds and spindle",
        re.compile(
            r"(^tool_(spindlespeed|rampspindlespeed|surfacespeed|feed))"
            r"|(finishfeed|reducedfeed|otherwayfeed|highfeed|noengagementfeed)"
            r"|(breakthroughfeed|positioningfeed)",
            re.IGNORECASE,
        ),
        "Calculate vc and the applicable fz or feed per revolution; compare cutting, ramp, plunge, entry, transition, and reduced feeds.",
    ),
    (
        "Entry, drilling, and chip evacuation",
        re.compile(
            r"ramp|plungeangle|(^|_)pitch$|threadpitch|peck|dwell|chipbreak|"
            r"lead(in|out)?|entry|helix|predrill|startingdepth|breakthrough|"
            r"cycletype|drillingcycle|coolant",
            re.IGNORECASE,
        ),
        "Verify entry kinematics, axial feed, chip space, peck/retract behavior, and coolant or air delivery.",
    ),
    (
        "Engagement and passes",
        re.compile(
            r"stepover|stepdown|optimalload|loaddeviation|multipledepth|"
            r"multiplepass|roughingpass|finishingpass|cuttingradius|cuspheight|"
            r"chipthinning|direction|compensation|repeatpass|fine(step|stepdown)",
            re.IGNORECASE,
        ),
        "Establish worst credible ae and ap, including full-slot segments, then calculate ae/D, ap/D, and MRR where possible.",
    ),
    (
        "TABS and part retention",
        re.compile(
            r"(^|_)(group_tabs|use_?tabs?|tabs?_enabled)\b|"
            r"tab(shape|width|height|positioning|approach|spercontour|distance|positions)|"
            r"notabzones",
            re.IGNORECASE,
        ),
        "Decide whether the operation can release or destabilize the part. If tabs are enabled, verify their shape, width, height, count/spacing, positions, no-tab zones, and survival through later operations; if disabled, require another positive retention method.",
    ),
    (
        "Thread Offset (Pitch Diameter Offset)",
        re.compile(
            r"pitch[\s_-]*diameter[\s_-]*offset|thread[\s_-]*offset|"
            r"(^|_)threaddepth\b",
            re.IGNORECASE,
        ),
        "For a Thread strategy, verify the positive diametral difference D_major - D_minor and reconcile it with internal/external geometry, definition method, modeled diameter, nominal thread, pitch, starts, and fit. Do not confuse it with tool tip/diameter compensation or height offsets; mark not applicable for non-Thread strategies.",
    ),
    (
        "Stock, finish, and path accuracy",
        re.compile(
            r"stocktoleave|verticalstock|restmaterial|tolerance|smoothing|"
            r"boundary|stockcontour|finish(ing)?overlap|allowstepovercusps",
            re.IGNORECASE,
        ),
        "Confirm the real incoming stock, allowances, rest source, and whether a later operation removes every allowance.",
    ),
    (
        "Tool and contact geometry",
        re.compile(
            r"^tool_(diameter|numberofflutes|flutelength|bodylength|"
            r"shaftdiameter|cornerradius|tipangle|taperangle|type|material)",
            re.IGNORECASE,
        ),
        "Reconcile these values with the physical cutter and derive the effective cutting diameter at contact.",
    ),
    (
        "Depth and height limits",
        re.compile(
            r"((top|bottom|feed|retract|clearance)height)|(^|_)depth($|_)|"
            r"maximumdepth|minimumdepth|fulldepth",
            re.IGNORECASE,
        ),
        "Confirm actual cutting depth, flute engagement, breakthrough, and that height choices do not create an unintended heavy first move.",
    ),
)


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object: %s" % path)
    return value


def _markdown(value: object) -> str:
    text = str(value if value is not None else "")
    return text.replace("|", "\\|").replace("\n", " ")


def _parameter_row(name: str, parameter: dict) -> str:
    return "| `%s` | %s | %s | %s |" % (
        _markdown(name),
        _markdown(parameter.get("expression", "")),
        "yes" if parameter.get("enabled") else "no",
        "yes" if parameter.get("visible") else "no",
    )


def _parameter_groups(parameters: dict) -> tuple[list[tuple[str, str, list]], set[str]]:
    grouped = []
    used = set()
    for title, pattern, guidance in _GROUPS:
        matches = []
        for name, value in parameters.items():
            if not isinstance(value, dict):
                continue
            if not (value.get("enabled") or value.get("visible")):
                continue
            searchable = "%s %s" % (name, value.get("title", ""))
            if pattern.search(searchable):
                matches.append((name, value))
                used.add(name)
        grouped.append((title, guidance, sorted(matches)))
    return grouped, used


def _required_calculations(strategy: str) -> list[str]:
    if strategy == "drill":
        return [
            "feed per revolution f_rev = axial feed / RPM",
            "depth/D and each enabled peck depth/D",
            "tapping synchronization feed = RPM * pitch when applicable",
            "chip evacuation and breakthrough-load assessment",
        ]
    if strategy == "bore":
        return [
            "surface speed vc and programmed chip load fz",
            "tool-center orbit radius = (hole diameter - cutter diameter) / 2",
            "pitch/orbit, axial feed component, and approximate orbit count",
            "radial clearance and chip-volume assessment",
        ]
    if strategy == "thread":
        return [
            "surface speed vc and programmed chip load fz",
            "pitch advance per orbit and lead for the programmed number of starts",
            "Pitch Diameter Offset = major diameter - minor diameter, positive and diametral",
            "one-side radial thread depth = Pitch Diameter Offset / 2",
            "final thread size/fit, compensation, radial infeed per pass, and chip-clearance assessment",
        ]
    if strategy == "profile2d":
        return [
            "process-specific kerf, power or pressure, cutting feed, and pierce-load assessment"
        ]
    return [
        "surface speed vc = pi * D * RPM / 1000",
        "programmed chip load fz = cutting feed / (RPM * flute count)",
        "worst credible ae/D and ap/D, explicitly testing for full slot",
        "MRR proxy = ae * ap * cutting feed",
        "ramp/plunge/entry feed ratios and helix axial component when present",
        "chip-thinning-adjusted maximum chip thickness only when ae/D warrants it",
    ]


def render_checklists(setup_document: dict, operation_documents: list[tuple[str, dict]]) -> str:
    if not operation_documents:
        raise ValueError("Setup contains no operations; cutting-intensity review cannot be completed")

    setup = setup_document.get("setup", {})
    context = setup_document.get("review_context", {})
    lines = [
        "# Cutting-intensity review checklists",
        "",
        "Setup: **%s**  " % _markdown(setup.get("name", "")),
        "Document: **%s**" % _markdown(setup_document.get("document", {}).get("name", "")),
        "",
        "Each section is an evidence skeleton. The reviewer must select exactly one result for every checklist group and add the calculated verdict; generation of this file is not a safety approval.",
        "",
        "## External review context",
        "",
        "```json",
        json.dumps(context, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Mandatory user-supplied inputs",
        "",
        "- [ ] Workpiece: exact user-supplied material designation; temper, condition, or hardness when relevant.",
        "- [ ] Physical cutter for every used tool: type, diameter, flute/tooth count, cutter material, coating, usable cutting length, and actual stickout; maker/product limits and center-cutting/ramp capability when available or relevant.",
        "- [ ] Spindle: rated power, maximum and usable RPM range, plus motor/pole/VFD or known low-speed torque behavior; model and torque/power curve when available.",
        "- [ ] Ask one bundled question for every missing fact. Fusion library, preset, stock-material, and machine-definition values do not count as user confirmation. Keep affected cutting-data verdicts pending until the user answers; if a fact is unknown, record the limitation and lower confidence.",
        "",
    ]

    for index, (relative_path, document) in enumerate(operation_documents, 1):
        operation = document.get("operation", {})
        parameters = operation.get("parameters", {})
        strategy = str(operation.get("strategy", ""))
        tool = operation.get("tool")
        groups, used = _parameter_groups(parameters)
        eligible = {
            name
            for name, value in parameters.items()
            if isinstance(value, dict) and (value.get("enabled") or value.get("visible"))
        }

        lines.extend(
            [
                "## %d. %s" % (index, _markdown(operation.get("name", ""))),
                "",
                "- Strategy: `%s`" % _markdown(strategy),
                "- Source: [%s](%s)" % (_markdown(relative_path), _markdown(relative_path)),
                "- Tool: %s" % _markdown(tool.get("description", "") if isinstance(tool, dict) else "MISSING"),
                "- Toolpath: present=%s, valid=%s, generating=%s" % (
                    bool(operation.get("has_toolpath")),
                    bool(operation.get("is_toolpath_valid")),
                    bool(operation.get("is_generating")),
                ),
                "",
                "### Tool reality and shop facts",
                "",
                "- [ ] Result: pass / change required / unknown / not applicable",
                "- [ ] Confirm user-supplied physical tool type, diameter, flute count, carbide/HSS state, cutting length, stickout, holder, center-cutting capability, and coolant delivery.",
                "- [ ] Reconcile every discrepancy with the exported tool before calculating load.",
                "",
            ]
        )

        for title, guidance, matches in groups:
            lines.extend(
                [
                    "### %s" % title,
                    "",
                    "- [ ] Result: pass / change required / unknown / not applicable",
                    "- [ ] %s" % guidance,
                    "",
                ]
            )
            if matches:
                lines.extend(
                    [
                        "| Internal parameter | Expression | Enabled | Visible |",
                        "| --- | --- | --- | --- |",
                    ]
                )
                lines.extend(_parameter_row(name, value) for name, value in matches)
            else:
                lines.append("No matching parameter was exported; mark unknown unless the item is physically not applicable.")
            lines.append("")

        lines.extend(
            [
                "### Required calculations and verdict",
                "",
                "- [ ] Result: pass / change required / unknown / not applicable",
            ]
        )
        lines.extend("- [ ] %s" % item for item in _required_calculations(strategy))
        lines.extend(
            [
                "- [ ] Check the exact strategy-specific section in `references/strategy-intensity-checklists.md`.",
                "- [ ] State severity, evidence, impact, correction, confidence, and the controlled prove-out required.",
                "- Unclassified enabled/visible parameters remaining for review: **%d**" % len(eligible - used),
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def build_from_export(export_dir: Path, output_path: Path | None = None) -> Path:
    export_dir = export_dir.resolve()
    setup_path = export_dir / "setup.json"
    setup_document = _read_json(setup_path)
    manifest = setup_document.get("operation_files", [])
    operation_documents = []
    for item in manifest:
        relative_path = item.get("file")
        if not relative_path:
            raise ValueError("operation manifest item has no file")
        operation_documents.append((relative_path, _read_json(export_dir / relative_path)))

    rendered = render_checklists(setup_document, operation_documents)
    destination = (output_path or export_dir / "intensity-checklists.md").resolve()
    destination.write_text(rendered, encoding="utf-8")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build one cutting-intensity checklist per exported Fusion CAM operation."
    )
    parser.add_argument("export_dir", type=Path, help="Directory containing setup.json")
    parser.add_argument("--output", type=Path, help="Output Markdown path")
    args = parser.parse_args()
    destination = build_from_export(args.export_dir, args.output)
    print(destination)


if __name__ == "__main__":
    main()
