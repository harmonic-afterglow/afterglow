"""Assign devices to RF blaster ports."""


from PyQt6.QtWidgets import (
    QMessageBox
)



def rf_receivers(project):
    rf = project.get("settings", {}).get("rf")
    return rf.get("receivers", []) if isinstance(rf, dict) else []
def rf_options(project):
    """[(display, token)] for the per-device IR-output combo, given known receivers."""
    opts = [("Remote (front IR)", "remote")]
    for rec in rf_receivers(project):
        lbl = rec["label"]
        opts += [(f"Base {lbl} - all ports", f"{lbl}"),
                 (f"Base {lbl} - port A", f"{lbl}-A"),
                 (f"Base {lbl} - port B", f"{lbl}-B"),
                 (f"Base {lbl} - base blaster", f"{lbl}-base")]
    return opts
def rf_get(project, device_id):
    rf = project.get("settings", {}).get("rf")
    if isinstance(rf, dict):
        return rf.get("assign", {}).get(str(device_id), "remote")
    return "remote"
def assignments_by_mac(receivers, assign) -> dict:
    """`{device_id: (mac, port_suffix)}` - routing tied to the physical base.

    `assign` stores a label token ("1", "1-A"), and labels are slots, not identities:
    `rfsGetAvailableLabel` hands out the first free number 1-5, so a blaster re-paired
    after a reset can come back as a different number. Carrying the tokens across a
    reset unchanged would leave devices pointing at whichever base happened to take
    that slot. Anchoring to the MAC is what survives.
    """
    label_to_mac = {str(r.get("label")): r.get("mac") for r in receivers or []}
    out = {}
    for device_id, token in (assign or {}).items():
        label, _, port = str(token).partition("-")
        mac = label_to_mac.get(label)
        if mac:
            out[device_id] = (mac, port)
    return out


def assignments_for(by_mac: dict, receivers) -> tuple[dict, list]:
    """Rebuild `assign` against the labels the blasters have *now*.

    Returns the routing that could be restored, and the device ids whose base did not
    come back - those cannot be routed anywhere and are reported rather than dropped
    silently.
    """
    mac_to_label = {r.get("mac"): str(r.get("label")) for r in receivers or []}
    assign, orphaned = {}, []
    for device_id, (mac, port) in by_mac.items():
        label = mac_to_label.get(mac)
        if label is None:
            orphaned.append(device_id)
            continue
        assign[device_id] = f"{label}-{port}" if port else label
    return assign, orphaned


def add_receiver(project, parent=None) -> bool:
    """Find blasters and add the chosen ones to the project.

    The host cannot discover a blaster's address - the link is Z-Wave and the PC has no
    radio, so a blaster only appears by being included, which needs its button pressed.
    What the host can do is open the remote's inclusion window, watch the remote's own
    list, and let the user pick. See `blaster_scan`.
    """
    from .blaster_scan import BlasterScanDialog


    settings = project.setdefault("settings", {})
    existing = settings.get("rf") if isinstance(settings.get("rf"), dict) else {}
    previous = list(existing.get("receivers", []))
    known = {r.get("mac"): r for r in previous}
    # Routing anchored to the physical base, so a reset-and-re-pair can restore it
    # even when the labels come back in a different order.
    routing = assignments_by_mac(previous, existing.get("assign"))

    dialog = BlasterScanDialog(set(known), parent)
    if not dialog.exec():
        return False

    for receiver in dialog.chosen:
        known[receiver.get("mac")] = receiver
    if not known:
        return False

    # Routing is re-expressed against the labels the blasters have now: labels are
    # slots, not identities, so a blaster can come back as a different number.
    assign, orphaned = assignments_for(routing, list(known.values()))
    settings["rf"] = {"receivers": list(known.values()), "assign": assign}

    restored = len(assign)
    if orphaned:
        QMessageBox.warning(
            parent, "Some devices lost their blaster",
            f"{len(orphaned)} device(s) were routed through a blaster that is no "
            "longer paired, so they are back on the remote's front emitter.\n\n"
            "Set their IR output again on each device's Edit page.")
    elif restored:
        QMessageBox.information(
            parent, "Routing kept",
            f"{restored} device routing(s) were carried over, matched by blaster "
            "address rather than by number - so they still point at the same "
            "physical base even if it came back as a different one.")
    return True


def rf_label(project, device_id):
    """How a device's routing reads on the device list - the combo's own wording."""
    token = rf_get(project, device_id)
    for display, value in rf_options(project):
        if value == token:
            return display
    return token or "Remote (front IR)"


def rf_set(project, device_id, token):
    """Persist a device's routing into settings["rf"]; collapse to the plain "front"
    string when nothing is routed to a base so simple projects stay simple."""
    settings = project.setdefault("settings", {})
    rf = settings.get("rf")
    receivers = rf.get("receivers", []) if isinstance(rf, dict) else []
    assign = dict(rf.get("assign", {})) if isinstance(rf, dict) else {}
    if token in (None, "remote"):
        assign.pop(str(device_id), None)
    else:
        assign[str(device_id)] = token
    settings["rf"] = {"receivers": receivers, "assign": assign} if (receivers or assign) else "front"
