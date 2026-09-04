"""Synthetic device definitions shared by protocol tests.

Regression tests need a stable protocol consumer, not a record of hardware in a
contributor's home. These values describe no product and deliberately contain only the
single NEC command needed to exercise protocol assembly.
"""

NEC_DEVICE = {
    "id": "40000002",
    "type": "Receiver",
    "mfr": "Test",
    "model": "Synthetic NEC receiver",
    "label": "Test Receiver",
    "codec": "nec",
    "protocol": "a7b8a0e6c639",
    "power_cmd": "PowerToggle",
    "commands": [("PowerToggle", "Power", "01", "02", None)],
    "inputs": [],
}
