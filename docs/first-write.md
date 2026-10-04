# Controlled first write

An experimental profile may build configurations, but the normal flash and
`Remote.write_config()` remain verified-only. A remote under test is written through this
separate workflow instead - from the command line below, or from the Flash tab, where an
experimental remote's button reads **Test Write…** and walks the same four steps (back up,
write, read back, restore). Each attempt keeps its files and report in its own folder under
`test-writes/`, and **Resume test write…** reopens one.

```bash
afterglow-first-write prepare candidate.ezhex \
  --recovery recovery.ezhex \
  --report first-write.json

# Review first-write.json, especially validation and changes.
afterglow-first-write apply first-write.json

# Wait until the remote has rebooted and reappeared on USB.
afterglow-first-write readback first-write.json --out readback.ezhex

# At any point after a write started: put the remote's own configuration back.
afterglow-first-write restore first-write.json
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

`restore` writes back only the recovery recorded in the report, after checking its digest and
the attached remote's identity again, and requires its own phrase. The normal write path
refuses an experimental profile, so without it a tester would hold a backup they could not
put back. Unlike `apply`, an uncertain restore may be repeated: writing the remote's own
configuration again is the recovery itself.

The report is evidence for review, not an automatic promotion. Set a profile to `verified` only
after the remote also boots and the changed controls work on real equipment.
