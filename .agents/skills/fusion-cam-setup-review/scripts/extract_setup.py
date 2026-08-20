"""Read-only Fusion CAM setup snapshot exporter.

This module is imported and executed inside Fusion's Python interpreter.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import os

import adsk.cam
import adsk.core


SCHEMA_ID = "fusion-cam-ai-export/v6"

_TOOL_LIBRARY_CONTEXT_PARAMETER_NAMES = (
    "tool_coolantSupport",
    "tool_presetMaterialCategory",
    "tool_presetMaterialQuery",
    "tool_presetMaterialUseHardness",
    "tool_presetMaterialMinimumHardness",
    "tool_presetMaterialMaximumHardness",
)

_PRESET_MATERIAL_PARAMETER_PREFIX = "tool_presetMaterial"

_SNAPSHOT_COVERAGE = {
    "included": [
        "all accessible setup, container, and operation CAMParameters",
        "normalized Tool.toJson definition and selected tool-library context",
        "selected preset material applicability",
        "toolpath existence, validity, generation state, warnings, and errors",
        "setup stock, material, fixture, machine, and WCS context exposed by Fusion",
    ],
    "not_available_without_external_context": [
        "completed simulation or verification collision results",
        "individual toolpath motion coordinates",
        "real cutter dimensions, stickout, holder, material, or workholding facts not stored in Fusion",
    ],
}


def _safe_get(obj, name, default=None):
    try:
        value = getattr(obj, name)
        return default if value is None else value
    except Exception as exc:
        return {"read_error": "%s: %s" % (type(exc).__name__, str(exc))}


def _enum_name(enum_type, value):
    if value is None:
        return None
    for name in dir(enum_type):
        if name.startswith("_"):
            continue
        try:
            if getattr(enum_type, name) == value:
                return name
        except Exception:
            continue
    return str(value)


def _entity_summary(entity):
    result = {"object_type": _safe_get(entity, "objectType", type(entity).__name__)}
    for prop in ("name", "operationId"):
        value = _safe_get(entity, prop, None)
        if value is not None and not isinstance(value, dict):
            result[prop] = value
    return result


def _json_value(value, depth=0):
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return value
    if depth >= 4:
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_json_value(item, depth + 1) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item, depth + 1) for key, item in value.items()}
    try:
        object_type = value.objectType
    except Exception:
        return str(value)
    if object_type:
        return _entity_summary(value)
    return str(value)


def _parameter_value_type(object_type):
    known_types = {
        adsk.cam.BooleanParameterValue.classType(): "boolean",
        adsk.cam.ChoiceParameterValue.classType(): "choice",
        adsk.cam.FloatParameterValue.classType(): "float",
        adsk.cam.IntegerParameterValue.classType(): "integer",
        adsk.cam.StringParameterValue.classType(): "string",
        adsk.cam.CadContours2dParameterValue.classType(): "cad_contours_2d",
        adsk.cam.CadMachineAvoidGroupsParameterValue.classType(): "machine_avoid_groups",
        adsk.cam.CadObjectParameterValue.classType(): "cad_objects",
        adsk.cam.CAMArrangeParameterValue.classType(): "arrange_selections",
    }
    return known_types.get(object_type, str(object_type).split("::")[-1])


def _parameter_value(parameter):
    try:
        value_obj = parameter.value
    except Exception as exc:
        return {"read_error": "%s: %s" % (type(exc).__name__, str(exc))}
    if value_obj is None:
        return None

    object_type = _safe_get(value_obj, "objectType", type(value_obj).__name__)
    result = {"value_type": _parameter_value_type(object_type)}
    try:
        raw_value = value_obj.value
    except Exception:
        raw_value = None
    if raw_value is not None:
        result["resolved"] = _json_value(raw_value)

    try:
        if object_type == adsk.cam.FloatParameterValue.classType():
            result["unit_type"] = _enum_name(
                adsk.cam.FloatParameterValueTypes,
                adsk.cam.FloatParameterValue.cast(value_obj).type,
            )
        elif object_type == adsk.cam.CadContours2dParameterValue.classType():
            selections = adsk.cam.CadContours2dParameterValue.cast(value_obj).getCurveSelections()
            result["selection_count"] = selections.count if selections else 0
        elif object_type == adsk.cam.CadMachineAvoidGroupsParameterValue.classType():
            groups = adsk.cam.CadMachineAvoidGroupsParameterValue.cast(value_obj).getMachineAvoidGroups()
            result["group_count"] = groups.count if groups else 0
        elif object_type == adsk.cam.CadObjectParameterValue.classType():
            cad_value = adsk.cam.CadObjectParameterValue.cast(value_obj)
            result["resolved"] = [_entity_summary(entity) for entity in cad_value.value]
        elif object_type == adsk.cam.CAMArrangeParameterValue.classType():
            selections = adsk.cam.CAMArrangeParameterValue.cast(value_obj).getArrangeSelections()
            result["selection_count"] = selections.count if selections else 0
    except Exception as exc:
        result["detail_read_error"] = "%s: %s" % (type(exc).__name__, str(exc))
    return result


def _parameters(parameters):
    if not parameters or isinstance(parameters, dict):
        return {}
    result = {}
    for index in range(parameters.count):
        parameter = parameters.item(index)
        name = _safe_get(parameter, "name", "")
        if not name or isinstance(name, dict):
            raise RuntimeError("CAM parameter at index %d has no readable internal name" % index)
        if name in result:
            raise RuntimeError("Duplicate CAM parameter internal name: %s" % name)
        item = {
            "expression": _safe_get(parameter, "expression", ""),
            "enabled": _safe_get(parameter, "isEnabled", None),
            "visible": _safe_get(parameter, "isVisible", None),
        }
        item.update(_parameter_value(parameter) or {})
        warning = _safe_get(parameter, "warning", "")
        error = _safe_get(parameter, "error", "")
        if warning:
            item["warning"] = warning
        if error:
            item["error"] = error
        result[name] = item
    return result


def _base_record(obj):
    parameters = _parameters(_safe_get(obj, "parameters", None))
    return {
        "object_type": _safe_get(obj, "objectType", type(obj).__name__),
        "name": _safe_get(obj, "name", ""),
        "operation_id": _safe_get(obj, "operationId", None),
        "strategy": _safe_get(obj, "strategy", ""),
        "notes": _safe_get(obj, "notes", ""),
        "is_selected": _safe_get(obj, "isSelected", False),
        "is_suppressed": _safe_get(obj, "isSuppressed", False),
        "is_optional": _safe_get(obj, "isOptional", False),
        "is_protected": _safe_get(obj, "isProtected", False),
        "has_warning": _safe_get(obj, "hasWarning", False),
        "has_error": _safe_get(obj, "hasError", False),
        "warning": _safe_get(obj, "warning", ""),
        "error": _safe_get(obj, "error", ""),
        "parameter_count": len(parameters),
        "parameters": parameters,
    }


def _selected_parameters(parameters, names=None, prefix=None):
    exported = _parameters(parameters)
    return {
        name: value
        for name, value in exported.items()
        if (names and name in names) or (prefix and name.startswith(prefix))
    }


def _tool_record(tool):
    try:
        raw_json = tool.toJson()
        try:
            parsed_json = json.loads(raw_json)
        except Exception:
            parsed_json = raw_json
    except Exception as exc:
        parsed_json = {"read_error": "%s: %s" % (type(exc).__name__, str(exc))}
    if isinstance(parsed_json, dict) and "read_error" not in parsed_json:
        definition = dict(parsed_json)
        definition.pop("guid", None)
        definition.pop("start-values", None)
    else:
        definition = parsed_json
    library_context = _selected_parameters(
        _safe_get(tool, "parameters", None),
        names=set(_TOOL_LIBRARY_CONTEXT_PARAMETER_NAMES),
    )
    canonical_tool = {
        "definition": definition,
        "library_context": library_context,
    }
    canonical_definition = json.dumps(
        canonical_tool,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    key = hashlib.sha256(canonical_definition.encode("utf-8")).hexdigest()[:16]
    return key, {
        "key": key,
        "description": _safe_get(tool, "description", ""),
        "definition": definition,
        "library_context": library_context,
    }


def _preset_record(preset):
    if not preset or isinstance(preset, dict):
        return None
    return {
        "name": _safe_get(preset, "name", ""),
        "id": _safe_get(preset, "id", ""),
        "material_context": _selected_parameters(
            _safe_get(preset, "parameters", None),
            prefix=_PRESET_MATERIAL_PARAMETER_PREFIX,
        ),
    }


def _machining_time(cam, target, assumptions):
    try:
        result = cam.getMachiningTime(
            target,
            assumptions["feed_scale_percent"],
            assumptions["rapid_feed_cm_s"],
            assumptions["tool_change_seconds"],
        )
        return {
            "source": "Fusion CAM.getMachiningTime",
            "feed_distance_cm": result.feedDistance,
            "feed_time_seconds": result.totalFeedTime,
            "rapid_distance_cm": result.rapidDistance,
            "rapid_time_seconds": result.totalRapidTime,
            "tool_change_count": result.toolChangeCount,
            "tool_change_time_seconds": result.totalToolChangeTime,
            "machining_time_seconds": result.machiningTime,
            "note": "Fusion may apply document machine/controller data; treat this as an estimate.",
        }
    except Exception as exc:
        return {"read_error": "%s: %s" % (type(exc).__name__, str(exc))}


def _operation_record(operation, tree_path, sequence, cam, assumptions, tools):
    record = _base_record(operation)
    record.update(
        {
            "sequence": sequence,
            "tree_path": tree_path,
            "is_generating": _safe_get(operation, "isGenerating", False),
            "generating_progress": _safe_get(operation, "generatingProgress", ""),
            "has_toolpath": _safe_get(operation, "hasToolpath", False),
            "is_toolpath_valid": _safe_get(operation, "isToolpathValid", False),
            "operation_state": _enum_name(
                adsk.cam.OperationStates,
                _safe_get(operation, "operationState", None),
            ),
        }
    )

    tool = _safe_get(operation, "tool", None)
    if tool and not isinstance(tool, dict):
        key, tool_data = _tool_record(tool)
        tools.setdefault(key, tool_data)
        record["tool_ref"] = key
    else:
        record["tool_ref"] = None

    record["tool_preset"] = _preset_record(_safe_get(operation, "toolPreset", None))

    if record["has_toolpath"]:
        record["machining_time"] = _machining_time(cam, operation, assumptions)
    else:
        record["machining_time"] = None
    return record


def _container_kind(obj):
    object_type = _safe_get(obj, "objectType", "")
    if object_type == adsk.cam.CAMPattern.classType():
        return "pattern"
    if object_type == adsk.cam.CAMFolder.classType():
        return "folder"
    if object_type == adsk.cam.Setup.classType():
        return "setup"
    return "container"


def _walk_children(parent, parent_path, cam, assumptions, tools, containers, operations):
    children = _safe_get(parent, "children", None)
    if not children or isinstance(children, dict):
        return []
    tree = []
    for index in range(children.count):
        child = children.item(index)
        child_path = parent_path + [_safe_get(child, "name", "")]
        if child.objectType == adsk.cam.Operation.classType():
            operation = adsk.cam.Operation.cast(child)
            record = _operation_record(
                operation,
                child_path,
                len(operations) + 1,
                cam,
                assumptions,
                tools,
            )
            operations.append(record)
            tree.append(
                {
                    "kind": "operation",
                    "operation_id": record["operation_id"],
                    "sequence": record["sequence"],
                    "name": record["name"],
                }
            )
            continue

        container = _base_record(child)
        container["kind"] = _container_kind(child)
        container["tree_path"] = child_path
        containers.append(container)
        tree.append(
            {
                "kind": container["kind"],
                "operation_id": container["operation_id"],
                "name": container["name"],
                "children": _walk_children(
                    child,
                    child_path,
                    cam,
                    assumptions,
                    tools,
                    containers,
                    operations,
                ),
            }
        )
    return tree


def _setup_catalog(cam):
    result = []
    for index in range(cam.setups.count):
        setup = cam.setups.item(index)
        result.append(
            {
                "index": index,
                "name": setup.name,
                "operation_id": setup.operationId,
                "is_active": setup.isActive,
                "is_selected": setup.isSelected,
                "operation_count": setup.allOperations.count,
            }
        )
    return result


def _select_setup(cam, selector):
    setups = cam.setups
    available = _setup_catalog(cam)
    if setups.count == 0:
        raise RuntimeError("The active document has no CAM setups")

    selector = selector or {}
    if "name" in selector:
        requested = str(selector["name"])
        exact = setups.itemByName(requested)
        if exact:
            return exact, available, "name"
        matches = [
            setups.item(index)
            for index in range(setups.count)
            if setups.item(index).name.casefold() == requested.casefold()
        ]
        if len(matches) == 1:
            return matches[0], available, "name_casefold"
        raise RuntimeError("Setup name not found: %s; available=%s" % (requested, json.dumps(available, ensure_ascii=False)))

    if "operation_id" in selector:
        requested_id = int(selector["operation_id"])
        setup = setups.itemByOperationId(requested_id)
        if setup:
            return setup, available, "operation_id"
        raise RuntimeError("Setup operation id not found: %d; available=%s" % (requested_id, json.dumps(available, ensure_ascii=False)))

    if "index" in selector:
        requested_index = int(selector["index"])
        if 0 <= requested_index < setups.count:
            return setups.item(requested_index), available, "index"
        raise RuntimeError("Setup index out of range: %d; available=%s" % (requested_index, json.dumps(available, ensure_ascii=False)))

    mode = selector.get("mode", "default")
    if mode in ("selected", "default"):
        selected = [setups.item(index) for index in range(setups.count) if setups.item(index).isSelected]
        if len(selected) == 1:
            return selected[0], available, "selected"
        if mode == "selected":
            raise RuntimeError("Expected exactly one selected setup; available=%s" % json.dumps(available, ensure_ascii=False))

    if mode in ("active", "default"):
        active = [setups.item(index) for index in range(setups.count) if setups.item(index).isActive]
        if len(active) == 1:
            return active[0], available, "active"
        if mode == "active":
            raise RuntimeError("Expected exactly one active setup; available=%s" % json.dumps(available, ensure_ascii=False))

    if mode == "default" and setups.count == 1:
        return setups.item(0), available, "only_setup"
    raise RuntimeError("Setup selection is ambiguous; available=%s" % json.dumps(available, ensure_ascii=False))


def _document_record(document):
    data_file = _safe_get(document, "dataFile", None)
    record = {
        "name": document.name,
        "is_modified": _safe_get(document, "isModified", None),
    }
    if data_file and not isinstance(data_file, dict):
        record["data_file"] = {
            "name": _safe_get(data_file, "name", ""),
            "id": _safe_get(data_file, "id", ""),
            "version_number": _safe_get(data_file, "versionNumber", None),
        }
    else:
        record["data_file"] = None
    return record


def _collection_entities(collection):
    if not collection or isinstance(collection, dict):
        return []
    result = []
    for index in range(collection.count):
        result.append(_entity_summary(collection.item(index)))
    return result


def _machine_record(machine):
    if not machine or isinstance(machine, dict):
        return machine
    capabilities = _safe_get(machine, "capabilities", None)
    capabilities_record = None
    if capabilities and not isinstance(capabilities, dict):
        capabilities_record = {
            "milling": _safe_get(capabilities, "isMillingSupported", False),
            "turning": _safe_get(capabilities, "isTurningSupported", False),
            "cutting": _safe_get(capabilities, "isCuttingSupported", False),
            "additive": _safe_get(capabilities, "isAdditiveSupported", False),
        }
    post_url = _safe_get(machine, "postURL", None)
    if post_url and not isinstance(post_url, dict):
        post_url = post_url.toString()
    return {
        "id": _safe_get(machine, "id", ""),
        "vendor": _safe_get(machine, "vendor", ""),
        "model": _safe_get(machine, "model", ""),
        "description": _safe_get(machine, "description", ""),
        "capabilities": capabilities_record,
        "has_post": _safe_get(machine, "hasPost", False),
        "post_url": post_url,
        "has_simulation_model": _safe_get(machine, "hasSimulationModel", False),
    }


def _stock_material_record(material):
    if not material or isinstance(material, dict):
        return material
    result = {
        "name": _safe_get(material, "name", ""),
        "category": _safe_get(material, "category", ""),
        "designators": _json_value(_safe_get(material, "designators", [])),
        "hardness": _json_value(_safe_get(material, "hardness", None)),
    }
    try:
        raw_json = material.toJson()
        try:
            result["json"] = json.loads(raw_json)
        except Exception:
            result["json"] = raw_json
    except Exception as exc:
        result["json"] = {"read_error": "%s: %s" % (type(exc).__name__, str(exc))}
    return result


def _setup_context(setup):
    stock_mode = _safe_get(setup, "stockMode", None)
    stock_solids = []
    if stock_mode == adsk.cam.SetupStockModes.SolidStock:
        stock_solids = _collection_entities(_safe_get(setup, "stockSolids", None))
    matrix = _safe_get(setup, "workCoordinateSystem", None)
    matrix_values = None
    coordinate_system = None
    if matrix and not isinstance(matrix, dict):
        matrix_values = matrix.asArray()
        origin, x_axis, y_axis, z_axis = matrix.getAsCoordinateSystem()
        coordinate_system = {
            "origin_cm": origin.asArray(),
            "x_axis": x_axis.asArray(),
            "y_axis": y_axis.asArray(),
            "z_axis": z_axis.asArray(),
        }
    return {
        "models": _collection_entities(_safe_get(setup, "models", None)),
        "fixture_enabled": _safe_get(setup, "fixtureEnabled", False),
        "fixtures": _collection_entities(_safe_get(setup, "fixtures", None)),
        "stock_mode": _enum_name(adsk.cam.SetupStockModes, stock_mode),
        "stock_solids": stock_solids,
        "stock_material": _stock_material_record(_safe_get(setup, "stockMaterial", None)),
        "machine": _machine_record(_safe_get(setup, "machine", None)),
        "work_coordinate_system": {
            "matrix": matrix_values,
            "coordinate_system": coordinate_system,
        },
    }


def extract(config=None):
    config = config or {}
    app = adsk.core.Application.get()
    document = app.activeDocument
    if not document:
        raise RuntimeError("Fusion has no active document")
    product = document.products.itemByProductType("CAMProductType")
    cam = adsk.cam.CAM.cast(product) if product else None
    if not cam:
        raise RuntimeError("The active document has no CAM product")

    assumptions_input = config.get("time_assumptions") or {}
    assumptions = {
        "feed_scale_percent": float(assumptions_input.get("feed_scale_percent", 100.0)),
        "rapid_feed_cm_s": float(assumptions_input.get("rapid_feed_cm_s", 100.0)),
        "tool_change_seconds": float(assumptions_input.get("tool_change_seconds", 0.0)),
    }
    review_context = _json_value(config.get("review_context") or {})
    setup, catalog, selection_mode = _select_setup(cam, config.get("setup"))

    tools = {}
    containers = []
    operations = []
    tree = _walk_children(
        setup,
        [setup.name],
        cam,
        assumptions,
        tools,
        containers,
        operations,
    )

    setup_record = _base_record(setup)
    setup_record.update(
        {
            "is_active": setup.isActive,
            "operation_type": _enum_name(adsk.cam.OperationTypes, setup.operationType),
            "operation_count": setup.allOperations.count,
            "machining_time": _machining_time(cam, setup, assumptions),
            "context": _setup_context(setup),
        }
    )

    return {
        "schema": SCHEMA_ID,
        "extracted_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "read_only": True,
        "document": _document_record(document),
        "setup_catalog": catalog,
        "selection": {
            "mode": selection_mode,
            "requested": config.get("setup"),
        },
        "time_assumptions": assumptions,
        "review_context": review_context,
        "snapshot_coverage": _SNAPSHOT_COVERAGE,
        "setup": setup_record,
        "tree": tree,
        "containers": containers,
        "operations": operations,
        "tools": list(tools.values()),
        "counts": {
            "containers": len(containers),
            "operations": len(operations),
            "unique_tools": len(tools),
            "warnings": sum(1 for item in operations if item.get("has_warning")),
            "errors": sum(1 for item in operations if item.get("has_error")),
            "suppressed": sum(1 for item in operations if item.get("is_suppressed")),
            "missing_toolpaths": sum(1 for item in operations if not item.get("has_toolpath")),
            "invalid_toolpaths": sum(
                1
                for item in operations
                if item.get("has_toolpath") and not item.get("is_toolpath_valid")
            ),
        },
    }


def _filename_slug(value):
    result = []
    previous_dash = False
    for character in str(value).lower():
        if character.isascii() and character.isalnum():
            result.append(character)
            previous_dash = False
        elif not previous_dash:
            result.append("-")
            previous_dash = True
    slug = "".join(result).strip("-")
    return slug or "operation"


def _operation_filename(operation):
    operation_id = operation.get("operation_id")
    if not isinstance(operation_id, int):
        operation_id = "unknown"
    return "%03d-op-%s-%s.json" % (
        operation["sequence"],
        operation_id,
        _filename_slug(operation.get("name", "")),
    )


def _tree_with_operation_files(nodes, files_by_sequence):
    result = []
    for node in nodes:
        item = dict(node)
        if item.get("kind") == "operation":
            item["file"] = files_by_sequence.get(item.get("sequence"))
        else:
            item["children"] = _tree_with_operation_files(
                item.get("children", []),
                files_by_sequence,
            )
        result.append(item)
    return result


def _write_json(path, value):
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def _write_split_export(result, output_dir):
    output_dir = os.path.abspath(output_dir)
    if os.path.exists(output_dir):
        if not os.path.isdir(output_dir):
            raise RuntimeError("output_dir exists and is not a directory: %s" % output_dir)
        if os.listdir(output_dir):
            raise RuntimeError("output_dir must be empty: %s" % output_dir)
    else:
        os.makedirs(output_dir)

    operations_dir = os.path.join(output_dir, "operations")
    os.makedirs(operations_dir)

    tools_by_key = {tool["key"]: tool for tool in result["tools"]}
    operation_files = []
    files_by_sequence = {}

    for operation in result["operations"]:
        filename = _operation_filename(operation)
        relative_path = os.path.join("operations", filename)
        files_by_sequence[operation["sequence"]] = relative_path
        tool = tools_by_key.get(operation.get("tool_ref"))
        operation_with_tool = dict(operation)
        operation_with_tool.pop("tool_ref", None)
        operation_with_tool["tool"] = tool
        operation_document = {
            "schema": result["schema"],
            "kind": "fusion_cam_operation",
            "extracted_at_utc": result["extracted_at_utc"],
            "read_only": result["read_only"],
            "document": result["document"],
            "setup_ref": {
                "name": result["setup"]["name"],
                "operation_id": result["setup"]["operation_id"],
                "file": "../setup.json",
            },
            "time_assumptions": result["time_assumptions"],
            "review_context": result["review_context"],
            "snapshot_coverage": result["snapshot_coverage"],
            "operation": operation_with_tool,
        }
        _write_json(os.path.join(output_dir, relative_path), operation_document)
        operation_files.append(
            {
                "sequence": operation["sequence"],
                "name": operation["name"],
                "operation_id": operation["operation_id"],
                "strategy": operation["strategy"],
                "tool_description": tool.get("description", "") if tool else None,
                "has_toolpath": operation["has_toolpath"],
                "is_toolpath_valid": operation["is_toolpath_valid"],
                "file": relative_path,
            }
        )

    setup_document = {
        "schema": result["schema"],
        "kind": "fusion_cam_setup",
        "extracted_at_utc": result["extracted_at_utc"],
        "read_only": result["read_only"],
        "document": result["document"],
        "setup_catalog": result["setup_catalog"],
        "selection": result["selection"],
        "time_assumptions": result["time_assumptions"],
        "review_context": result["review_context"],
        "snapshot_coverage": result["snapshot_coverage"],
        "setup": result["setup"],
        "tree": _tree_with_operation_files(result["tree"], files_by_sequence),
        "containers": result["containers"],
        "operation_files": operation_files,
        "counts": result["counts"],
    }
    setup_path = os.path.join(output_dir, "setup.json")
    _write_json(setup_path, setup_document)
    return setup_path, operation_files


def run(context: str):
    config = json.loads(context) if context else {}
    result = extract(config)
    output_dir = config.get("output_dir")
    if not output_dir:
        raise RuntimeError("output_dir is required for split JSON export")
    setup_path, operation_files = _write_split_export(result, output_dir)
    print(
        "CAM_SETUP_REVIEW_EXPORTED setup_path=%s setup=%s operation_files=%d"
        % (
            setup_path,
            result["setup"]["name"],
            len(operation_files),
        )
    )
