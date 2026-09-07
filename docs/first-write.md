# Controlled first write

An experimental profile may build configurations, but the GUI and `Remote.write_config()`
remain verified-only. The first hardware test uses a separate local workflow:

```bash
afterglow-first-write prepare candidate.ezhex \
  --recovery recovery.ezhex \
  --report first-write.json

# Review first-write.json, especially validation and changes.
afterglow-first-write apply first-write.json

# Wait until the remote has rebooted and reappeared on USB.
afterglow-first-write readback first-write.json --out readback.ezhex
```

`prepare` requires the artifact's profile to be `experimental`. It validates the EZHex
envelope and the backend-native payload, identifies the attached remote, reads its current
configuration, makes a second recovery copy, and records hashes plus a native change report.
It refuses to overwrite any of those files.

`apply` revalidates all three files and the connected identity, then requires the exact phrase
stored in the reviewed report. Before calling the transport it durably changes the report state
to `write-started`. If the process or USB connection fails, the state becomes
`write-outcome-unknown` and another apply is refused. Determine the actual state with readback;
never retry merely because the remote disappeared while rebooting.

`readback` accepts a completed or uncertain write, identifies the same physical target, saves a
new configuration without overwriting an existing file, validates it independently, and compares
its payload hash with the candidate. Only an exact match changes the report to
`readback-verified`.

The report is evidence for review, not an automatic promotion. Set a profile to `verified` only
after the remote also boots and the changed controls work on real equipment.
