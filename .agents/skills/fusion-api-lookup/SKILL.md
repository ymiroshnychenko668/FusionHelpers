---
name: fusion-api-lookup
description: Look up exact Fusion 360 API symbols — class names, method/property signatures, parameter types, return types, enum values — from the local FusionAPIReference submodule. Use this BEFORE writing or reviewing any adsk.* / Fusion API code, or whenever unsure of an API shape, instead of guessing or fetching the web.
---

# Fusion 360 API lookup (offline, version-pinned)

This project targets exactly one API: the Fusion 360 API. The full
reference is vendored locally in the `FusionAPIReference/` git submodule
plus the scraped index at the repo root. Never invent API names — look
them up here first. All paths below are relative to the repo root
(`/Users/yuriymiroshnichenko/Projects/FusionHelpers`).

## Which source to use

1. **Signatures, parameter types, return types → Python stubs**
   `FusionAPIReference/Fusion_API_Python_Reference/defs/adsk/*.py`
   Type-hinted stubs, one module per namespace:
   `core.py`, `fusion.py`, `cam.py`, `drawing.py`, `sim.py`, `volume.py`.
   These mirror `import adsk.core, adsk.fusion, …`. This is the
   authoritative source for *how to call* something.

2. **Descriptions, behavior, examples → HTML docs**
   `FusionAPIReference/Fusion_API_Documentation/files/<Class>.htm`
   and `<Class>_<member>.htm` (16k+ pages). Use when the stub signature
   isn't enough and you need semantics, edge cases, or sample code.

3. **"Does class/member X exist? what's its URL?" → scraped index**
   `fusion_api_reference.md` (object-level) / `fusion_api_reference.json`
   (every member + autodesk.com detail URL). Good for breadth/discovery
   and for giving the user a clickable link.

## Recipes

Find a class and its members (signatures):
```
grep -n "^class CombineFeatures\b" FusionAPIReference/Fusion_API_Python_Reference/defs/adsk/fusion.py
# then read that line range to see methods/properties with type hints
```

Find a method/property across all namespaces:
```
grep -rn "def createInput\|def add\b" FusionAPIReference/Fusion_API_Python_Reference/defs/adsk/
```

Read the human docs / examples for a symbol:
```
# class page
open/Read  FusionAPIReference/Fusion_API_Documentation/files/CombineFeatures.htm
# member page  (Class_member.htm)
open/Read  FusionAPIReference/Fusion_API_Documentation/files/CombineFeatures_createInput.htm
```
Strip HTML when reading docs in-tool (keep it lightweight), e.g.
`python3 -c "import re,sys;print(re.sub('<[^>]+>',' ',open(sys.argv[1]).read()))" <file>.htm`.

Enum values:
```
grep -n "class FeatureOperations\b" FusionAPIReference/Fusion_API_Python_Reference/defs/adsk/fusion.py
```

Discovery / get the user a link:
```
grep -i "combinefeatures" fusion_api_reference.md
```

## Rules

- Prefer the **stubs** for anything you'll write in code (exact param
  order, optional args, return type). Confirm semantics in the **.htm**
  only when needed — don't bulk-read HTML.
- The submodule is **version-pinned**; it is the source of truth over
  training memory. If a symbol isn't there, say so rather than guessing —
  verify via `fusion_mcp_read` or a live `fusion_mcp_execute` snippet.
- This is reference, not project code: never edit anything under
  `FusionAPIReference/`. Update it only via `git submodule update
  --remote` when explicitly asked.
- Cite findings as `FusionAPIReference/…:line` so they're clickable.
- Respect the submodule's license (CC BY-NC-SA 3.0): use it to inform
  code, don't wholesale copy doc prose into the repo.
