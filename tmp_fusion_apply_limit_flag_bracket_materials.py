import adsk.core
import adsk.fusion


def r(*codes):
    return ''.join(chr(x) for x in codes)


NAME_BRACKET = r(0x41A, 0x440, 0x43E, 0x43D, 0x448, 0x442, 0x435, 0x439, 0x43D, 0x20, 0x444, 0x43B, 0x430, 0x436, 0x43A, 0x430, 0x20, 0x43A, 0x43E, 0x43D, 0x446, 0x435, 0x432, 0x43E, 0x433, 0x43E)
NAME_WASHER = r(0x421, 0x442, 0x430, 0x43B, 0x44C, 0x43D, 0x430, 0x44F, 0x20, 0x448, 0x430, 0x439, 0x431, 0x430)
NAME_BODY = r(0x41A, 0x440, 0x43E, 0x43D, 0x448, 0x442, 0x435, 0x439, 0x43D, 0x20, 0x444, 0x43B, 0x430, 0x436, 0x43A, 0x430)


def mm(v):
    return round(v * 10.0, 3)


def dims_mm(body):
    box = body.boundingBox
    return [
        mm(box.maxPoint.x - box.minPoint.x),
        mm(box.maxPoint.y - box.minPoint.y),
        mm(box.maxPoint.z - box.minPoint.z),
    ]


def geom_counts(body):
    counts = {}
    for i in range(body.faces.count):
        geom = body.faces.item(i).geometry
        typ = getattr(geom, 'objectType', type(geom).__name__).split('::')[-1]
        counts[typ] = counts.get(typ, 0) + 1
    return counts


def is_washer_like(body):
    ds = sorted(dims_mm(body))
    if len(ds) != 3 or ds[1] <= 0 or ds[2] <= 0:
        return (False, 0.0, ds, {})
    counts = geom_counts(body)
    cylinders = counts.get('Cylinder', 0)
    torus = counts.get('Torus', 0)
    roundness = abs(ds[2] - ds[1]) / max(ds[2], 0.001)
    thinness = ds[0] / max(ds[1], 0.001)
    cylinder_signal = cylinders >= 2 or torus >= 1
    ok = roundness <= 0.08 and thinness <= 0.45 and cylinder_signal
    score = (1.0 - roundness) * 100.0 + (0.45 - min(thinness, 0.45)) * 50.0 + cylinders * 2.0 + torus
    return (ok, score, ds, counts)


def find_material_in_collection(coll, exact_names, contains_words):
    for name in exact_names:
        obj = coll.itemByName(name)
        if obj:
            return obj
    best = None
    for i in range(coll.count):
        obj = coll.item(i)
        lname = obj.name.lower()
        if all(word in lname for word in contains_words):
            best = obj
            break
    return best


def ensure_material(app, design, exact_names, contains_words):
    obj = find_material_in_collection(design.materials, exact_names, contains_words)
    if obj:
        return obj
    libs = app.materialLibraries
    src = None
    for i in range(libs.count):
        lib = libs.item(i)
        src = find_material_in_collection(lib.materials, exact_names, contains_words)
        if src:
            break
    if not src:
        raise RuntimeError('Material not found: ' + ','.join(exact_names))
    copied = design.materials.addByCopy(src, src.name)
    if not copied:
        raise RuntimeError('Failed to copy material: ' + src.name)
    return copied


def target_component_from_selection(ui):
    sels = ui.activeSelections
    if sels.count < 1:
        raise RuntimeError('No active selection')
    ent = sels.item(0).entity
    occ = adsk.fusion.Occurrence.cast(ent)
    comp = adsk.fusion.Component.cast(ent)
    body = adsk.fusion.BRepBody.cast(ent)
    face = adsk.fusion.BRepFace.cast(ent)
    if occ:
        return (occ.component, occ, 'occurrence:' + occ.fullPathName)
    if comp:
        return (comp, None, 'component:' + comp.name)
    if body:
        return (body.parentComponent, None, 'body:' + body.name)
    if face:
        return (face.body.parentComponent, None, 'face_body:' + face.body.name)
    raise RuntimeError('Unsupported selection type: ' + getattr(ent, 'objectType', type(ent).__name__))


def collect_bodies(comp):
    rows = []
    for i in range(comp.bRepBodies.count):
        rows.append((comp.bRepBodies.item(i), comp, None, 'direct'))
    for i in range(comp.allOccurrences.count):
        occ = comp.allOccurrences.item(i)
        for j in range(occ.bRepBodies.count):
            rows.append((occ.bRepBodies.item(j), occ.component, occ, occ.fullPathName))
    return rows


def set_body_material(body, mat):
    body.material = mat
    body.appearance = None


def mat_name(entity):
    mat = entity.material if entity else None
    return mat.name if mat else '<none>'


def run(_context=None):
    app = adsk.core.Application.get()
    ui = app.userInterface
    design = adsk.fusion.Design.cast(app.activeProduct)
    if not design:
        raise RuntimeError('No active Fusion design')

    aluminum = ensure_material(app, design, ['Aluminum 6061', 'Aluminum'], ['aluminum'])
    steel = ensure_material(app, design, ['Steel', 'Alloy Steel'], ['steel'])

    comp, selected_occ, selected_desc = target_component_from_selection(ui)
    old_name = comp.name
    rows = collect_bodies(comp)
    if not rows:
        raise RuntimeError('Selected component has no BRep bodies to classify')

    washer_rows = []
    best = None
    for body, owner_comp, owner_occ, path in rows:
        ok, score, ds, counts = is_washer_like(body)
        print('BODY_ANALYSIS|name=' + body.name + '|owner=' + owner_comp.name + '|path=' + path + '|dims=' + str(dims_mm(body)) + '|sdims=' + str(ds) + '|score=' + str(round(score, 3)) + '|washer=' + str(ok) + '|geom=' + str(counts))
        if ok:
            washer_rows.append((body, owner_comp, owner_occ, path, score))
        if best is None or score > best[4]:
            best = (body, owner_comp, owner_occ, path, score)

    if not washer_rows and best and best[4] >= 85.0:
        washer_rows.append(best)

    comp.name = NAME_BRACKET
    comp.material = aluminum
    try:
        comp.opacity = 1.0
    except Exception:
        pass

    for body, owner_comp, owner_occ, path in rows:
        owner_comp.material = aluminum
        set_body_material(body, aluminum)
        if body.name.startswith('Body'):
            body.name = NAME_BODY

    for body, owner_comp, owner_occ, path, score in washer_rows:
        owner_comp.material = steel
        set_body_material(body, steel)
        body.name = NAME_WASHER
        if owner_comp != comp and (owner_comp.name.startswith('Body') or owner_comp.name.startswith('Component')):
            owner_comp.name = NAME_WASHER

    design.computeAll()

    print('APPLY_DONE|doc=' + app.activeDocument.name)
    print('SELECTED=' + selected_desc)
    print('COMPONENT_RENAMED|' + old_name + '|to=' + comp.name)
    print('ALUMINUM_MATERIAL=' + aluminum.name)
    print('STEEL_MATERIAL=' + steel.name)
    print('BODIES_TOTAL=' + str(len(rows)) + '|WASHERS=' + str(len(washer_rows)))
    for body, owner_comp, owner_occ, path in rows:
        print('VERIFY_BODY|name=' + body.name + '|owner=' + owner_comp.name + '|path=' + path + '|material=' + mat_name(body) + '|dims=' + str(dims_mm(body)))


run(None)
