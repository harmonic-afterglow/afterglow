#!/usr/bin/env python3
"""RF blaster routing: where each device's IR actually comes out.

`platformconfig/XmlUserRfSetting.xml` decides whether a device is blasted from the
remote's own front IR LED or from a wireless RF blaster base station. It is the
single most consequential file outside `userconfig/`: point a device at a base the
remote is not paired with and it emits NOTHING, and the activity's power-on hangs
waiting for that base.

THE FORMAT (firmware `RFService.lua`, and byte-verified against real dumps):

    <Controllers>              every emitter, keyed by <Guid>
                               "0"  = the remote's own front IR LED
                               MAC  = a wireless RF blaster base (up to 5, labelled 1-5)
    <Controller2UserDeviceMap> device -> controller + <PortNumber>

`PortNumber` per `ASSERT_NUM_PORTS=4` ("-1->all, 0->base and 1-2->ports"):

    -1  all outputs (the default)      Logitech's UI calls the base "1"
     0  the base's built-in blaster    and its two wired mini-emitters
     1  wired mini-emitter A           "1-A" and "1-B"
     2  wired mini-emitter B

A device that is NOT in the map emits from the remote's front IR.

This module both READS an existing config (`extract`) and WRITES one (`apply`), so
the two directions of the same format stay in one place; `extract` -> `apply` is a
byte-exact round-trip on every available dump.
"""
import glob
import os
import re

def _read_text(path):
    """One RF settings file. `errors="replace"` because a corrupt byte in somebody's
    settings must not stop the config being read."""
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def _crc8(data, poly=0x21):
    """The 1-byte sidecar checksum the remote stores next to each platformconfig file
    (CRC-8, poly 0x21, init 0 -- reversed from the donor dumps' *.crc files)."""
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xff if crc & 0x80 else (crc << 1) & 0xff
    return crc


# RF IR-output ports, per the firmware (RFService.lua: ASSERT_NUM_PORTS=4,
# "-1->all, 0->base and 1-2->ports"). A base station has its own built-in blaster
# plus two wired mini-emitter ("spider cable") jacks. Logitech's software shows a
# base as "1"/"2" and its mini ports as "1-A"/"1-B" -- A/B map to ports 1/2.
_RF_PORTS = {"all": -1, "-1": -1, "base": 0, "0": 0, "a": 1, "1": 1, "b": 2, "2": 2}


def _rf_export_xml(receivers, mapping, remote_date):
    """Reproduce RFService.lua's rfsExportDbAsXML() byte-for-byte (verified against
    the donor/home dumps). `receivers` = ordered list of dicts
    {mac,label,firmware,date,status}; `mapping` = ordered list of (device_id, mac, port).
    Devices absent from `mapping` are omitted -> they emit from the remote's front IR."""
    x = ["<RemoteInfo>", "<Controllers>",
         "<Controller>", "<Guid>0</Guid>", "<Label>0</Label>",
         f"<ConfigurationUpdateDate>{remote_date}</ConfigurationUpdateDate>",
         "<ControllerStatus>1</ControllerStatus>", "</Controller>"]
    for r in receivers:
        x += ["<Controller>", f"<Guid>{r['mac']}</Guid>", f"<Label>{r['label']}</Label>",
              f"<Firmware>{r.get('firmware', '3.4')}</Firmware>",
              f"<ConfigurationUpdateDate>{r.get('date', remote_date)}</ConfigurationUpdateDate>",
              f"<ControllerStatus>{r.get('status', 1)}</ControllerStatus>", "</Controller>"]
    x += ["</Controllers>", "<Controller2UserDeviceMap>"]
    for r in receivers:
        x.append(f'<Controller guid="{r["mac"]}">')
        for did, mac, port in mapping:
            if mac == r["mac"]:
                x += ["<Device>", f"<UserDeviceId>{did}</UserDeviceId>",
                      f"<PortNumber>{port}</PortNumber>", "</Device>"]
        x.append("</Controller>")
    x += ["</Controller2UserDeviceMap>", "</RemoteInfo>"]
    return "\n".join(x).encode("utf-8")


def _rf_parse_assign(token, label2mac):
    """Friendly blaster token -> (mac, port), or None for the remote's front IR.
    "remote"/"front"/"0"/None -> front IR;  "1" -> base 1, all ports;
    "1-A"/"1-B" -> base 1 mini port A/B;  "1-base" -> base 1 built-in blaster only.
    A dict {"receiver": mac-or-label, "port": -1|0|1|2} is taken verbatim."""
    if token in (None, "", "remote", "front", "0", 0):
        return None
    if isinstance(token, dict):
        rcv = str(token["receiver"])
        mac = label2mac.get(rcv, rcv)
        return (mac, int(token.get("port", -1)))
    label, _, port = str(token).strip().lower().partition("-")
    mac = label2mac.get(label)
    if mac is None:
        raise ValueError(f"rf: no receiver labeled {label!r} (have {sorted(label2mac)})")
    if port == "":
        return (mac, -1)                       # bare "1" = All ports (firmware default)
    if port not in _RF_PORTS:
        raise ValueError(f"rf: bad port {port!r} (use A/B/base/all)")
    return (mac, _RF_PORTS[port])


def apply_rf_setting(work, rf):
    """Route IR emission by regenerating platformconfig/XmlUserRfSetting*.xml.

    THE FORMAT (RFService.lua): <Controllers> registers each emitter by Guid -- "0"
    is the remote's OWN front IR LED; a MAC is a wireless RF blaster base station
    (up to 5, labelled 1-5). <Controller2UserDeviceMap> assigns each device to a
    controller + PortNumber. A device NOT in the map emits from the remote's front
    IR. A device mapped to a base the remote isn't paired with emits NOTHING and the
    activity/OOBE power-on hangs reaching for it.

    settings["rf"] accepts:
      "front"                      -- every device on the remote's front IR (no base).
      {"receivers": [{"mac","label","firmware","date","status"}, ...],
       "assign": {device_id: "1" | "1-A" | "1-B" | "2" | "remote" | {...}}}
                                   -- multi-blaster: register bases and route devices
                                      to them by the software's 1 / 1-A / 1-B naming.
    Rewrites the file, its .backup, and the Rollback pair, each with a fresh CRC-8.
    """
    if not rf:
        return
    pc = os.path.join(work, "platformconfig")
    main = os.path.join(pc, "XmlUserRfSetting.xml")

    # Preserve the remote's ConfigurationUpdateDate from the base tree if present.
    remote_date = "20140101 000000"
    if os.path.exists(main):
        m = re.search(r"<Guid>0</Guid>\s*<Label>0</Label>\s*"
                      r"<ConfigurationUpdateDate>([^<]*)</ConfigurationUpdateDate>",
                      _read_text(main))
        if m:
            remote_date = m.group(1)

    files = [p for p in glob.glob(os.path.join(pc, "XmlUserRfSetting*")) if not p.endswith(".crc")]

    def _write(path, data):
        with open(path, "wb") as f:
            f.write(data)
        crc_path = path + ".crc"
        if os.path.exists(crc_path):
            with open(crc_path, "wb") as f:
                f.write(bytes([_crc8(data)]))

    if rf == "front":
        # Keep each file's <Controllers> registry byte-for-byte (so the RF file still
        # matches one this remote already accepts) and only empty the device->base map;
        # unmapped devices fall back to the remote's front IR (proven by the donor's own
        # Apple TV). Do NOT drop the registered base -- removing the remote's known base
        # produces a zero-receiver file with no accepted sample.
        for path in files:
            s = _read_text(path)
            s = re.sub(r"(<Controller2UserDeviceMap>).*?(</Controller2UserDeviceMap>)",
                       r"\1\2", s, flags=re.S)
            _write(path, s.encode("utf-8"))
        return

    if not isinstance(rf, dict):
        raise ValueError(f"unsupported rf setting {rf!r}")
    receivers = [dict(r) for r in rf.get("receivers", [])]
    label2mac = {str(r["label"]): r["mac"] for r in receivers}
    label2mac.update({r["mac"]: r["mac"] for r in receivers})
    mapping = []
    for did, token in (rf.get("assign") or {}).items():
        res = _rf_parse_assign(token, label2mac)
        if res is not None:
            mapping.append((str(did), res[0], res[1]))
    data = _rf_export_xml(receivers, mapping, remote_date)
    for path in files:
        _write(path, data)

def extract_rf(extracted_dir):
    """The RF block of a configuration directory, or None if it has no receivers."""
    path = os.path.join(extracted_dir, "platformconfig", "XmlUserRfSetting.xml")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as handle:
        return parse_rf_xml(handle.read())


def parse_rf_xml(s):
    """Parse XmlUserRfSetting.xml into a settings["rf"] block:
    {"receivers":[{mac,label,firmware,date,status}], "assign":{device_id: token}} where
    token is the software's blaster name ("1", "1-A", "1-B", "1-base", ...). Returns None
    if there are no RF receivers (everything already emits from the remote's front IR).
    Importing a user's own .ezhex is how the GUI learns their base station's MAC."""
    port_tok = {-1: "", 0: "-base", 1: "-A", 2: "-B"}   # inverse of build_config._RF_PORTS
    receivers, label_by_mac = [], {}
    for m in re.finditer(r"<Controller>(.*?)</Controller>", s, re.S):   # registry (no guid attr)
        body = m.group(1)
        guid = re.search(r"<Guid>([^<]*)</Guid>", body)
        if not guid or guid.group(1) == "0":                            # skip the remote itself
            continue
        lbl = re.search(r"<Label>([^<]*)</Label>", body)
        fw = re.search(r"<Firmware>([^<]*)</Firmware>", body)
        date = re.search(r"<ConfigurationUpdateDate>([^<]*)</ConfigurationUpdateDate>", body)
        st = re.search(r"<ControllerStatus>([^<]*)</ControllerStatus>", body)
        label = lbl.group(1) if lbl else str(len(receivers) + 1)
        rec = {"mac": guid.group(1), "label": int(label) if label.isdigit() else label}
        if fw: rec["firmware"] = fw.group(1)
        if date: rec["date"] = date.group(1)
        if st and st.group(1).lstrip("-").isdigit(): rec["status"] = int(st.group(1))
        receivers.append(rec)
        label_by_mac[guid.group(1)] = rec["label"]
    if not receivers:
        return None
    assign = {}
    for m in re.finditer(r'<Controller\s+guid="([^"]*)">(.*?)</Controller>', s, re.S):  # device map
        mac = m.group(1)
        if mac not in label_by_mac:
            continue
        for dm in re.finditer(r"<UserDeviceId>(\d+)</UserDeviceId>\s*"
                              r"<PortNumber>(-?\d+)</PortNumber>", m.group(2)):
            did, port = dm.group(1), int(dm.group(2))
            assign[did] = f"{label_by_mac[mac]}{port_tok.get(port, '-' + str(port))}"
    return {"receivers": receivers, "assign": assign}
