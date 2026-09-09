"""Clone-and-repoint edits for Harmony One activity property assignments."""

from __future__ import annotations

from . import activity_index, command_index, gspm, relocation


def _hooks(payload: bytes, ordinal: int, include_refresh: bool) -> list[tuple]:
    contexts = activity_index.contexts(payload)
    if not 0 <= ordinal < len(contexts):
        raise ValueError(f"activity context {ordinal} does not exist")
    wanted = {activity_index.ENTER}
    if include_refresh:
        wanted.add(activity_index.REFRESH)
    out = []
    for row in contexts[ordinal]["rows"]:
        if row["key_code"] in wanted and row["category"] == activity_index.OBJECT:
            out.append(row["operand"])
    return list(dict.fromkeys(out))


def _locations(objects: list[dict], root: int, property_id: int) -> list[tuple[int, int]]:
    """Return top-level and one-hop SET atom locations as object/index pairs."""
    if not 0 <= root < len(objects):
        raise ValueError(f"activity hook object {root} falls outside section 11")
    tag = 0x80 | property_id
    found = [
        (root, index) for index, (_value, opcode) in enumerate(objects[root]["atoms"])
        if opcode == tag
    ]
    for operand, opcode in objects[root]["atoms"]:
        if opcode != activity_index.OBJECT or not 0 <= operand < len(objects):
            continue
        found.extend(
            (operand, index)
            for index, (_value, nested_opcode) in enumerate(objects[operand]["atoms"])
            if nested_opcode == tag
        )
    return found


def _property(payload: bytes, property_id: int) -> dict:
    records = activity_index.engine_records(payload)
    if not 0 <= property_id < len(records):
        raise ValueError(f"activity property {property_id} does not exist")
    return records[property_id]


def _validate_value(record: dict, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= record["limit"]:
        raise ValueError(
            f"activity property {record['property_id']} allows 0..{record['limit']}")
    transitions = record["transitions"]
    if not transitions:
        raise ValueError("activity property has no transition and cannot emit a command")
    if not any(item["to"] in (value, 0xFFFE) for item in transitions):
        raise ValueError(f"activity property has no transition to value {value}")


def edit_property(
        payload: bytes, activity_ordinal: int, property_id: int, *,
        operation: str, value: int | None = None, include_refresh: bool = True,
) -> tuple[bytes, dict]:
    """Add, change, or remove one activity SET from ENTER/REFRESH hooks."""
    if operation not in ("add", "change", "remove"):
        raise ValueError("activity property operation must be add, change, or remove")
    record = _property(payload, property_id)
    if operation != "remove":
        _validate_value(record, value)
    hooks = _hooks(payload, activity_ordinal, include_refresh)
    if not hooks:
        raise ValueError("activity context has no editable ENTER or REFRESH hook")
    objects = command_index.objects(payload)
    mutations: dict[int, list[tuple[int, int]]] = {}
    touched_hooks = []
    for hook in hooks:
        locations = _locations(objects, hook, property_id)
        if operation == "add":
            if locations:
                raise ValueError(f"activity hook {hook} already sets property {property_id}")
            atoms = mutations.setdefault(hook, list(objects[hook]["atoms"]))
            atoms.append((value, 0x80 | property_id))
            touched_hooks.append(hook)
            continue
        if not locations:
            continue
        if len(locations) != 1:
            raise ValueError(
                f"activity hook {hook} sets property {property_id} ambiguously")
        object_id, atom_index = locations[0]
        atoms = mutations.setdefault(object_id, list(objects[object_id]["atoms"]))
        if operation == "change":
            atoms[atom_index] = (value, atoms[atom_index][1])
        else:
            del atoms[atom_index]
            if not atoms:
                raise ValueError(f"removing the SET would empty object {object_id}")
        touched_hooks.append(hook)
    if not mutations:
        raise ValueError(f"activity does not currently set property {property_id}")

    start10, end10 = gspm.section_ranges(payload)[10]
    body10 = bytearray(payload[start10:end10])
    repoints = {}
    for object_id, atoms in mutations.items():
        if len(atoms) > 0xFF:
            raise ValueError(f"object {object_id} exceeds its atom-count field")
        repoints[object_id] = len(body10)
        body10 += bytes([len(atoms)])
        for operand, opcode in atoms:
            body10 += operand.to_bytes(2, "little") + bytes([opcode])
    result, relocation_report = relocation.relocate(
        payload, {10: bytes(body10)}, object_repoints=repoints)

    new_objects = command_index.objects(result)
    expected = None if operation == "remove" else value
    for hook in hooks:
        values = [
            new_objects[object_id]["atoms"][index][0]
            for object_id, index in _locations(new_objects, hook, property_id)
        ]
        if operation == "add" and values != [expected]:
            raise RuntimeError(f"activity hook {hook} did not acquire the requested SET")
        if operation == "change" and values and values != [expected]:
            raise RuntimeError(f"activity hook {hook} did not retain the requested SET value")
        if operation == "remove" and values:
            raise RuntimeError(f"activity hook {hook} retained the removed SET")
    return result, {
        "mode": "edit-activity-property", "operation": operation,
        "activity": activity_ordinal, "property_id": property_id, "value": value,
        "hooks": touched_hooks, "repointed_objects": sorted(repoints),
        "relocation": relocation_report,
    }
