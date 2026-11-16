# Contributing to Afterglow

Afterglow builds, reads and writes configurations for Logitech Harmony remotes whose
service has shut down. This page covers how the code is arranged and how a build and an
import flow through it. The rules a change must keep, and why each one exists, are in
[AGENTS.md](AGENTS.md). Read its section 1 before changing anything.

## Getting started

```bash
python3 -m pip install -e '.[dev,gui]'
```

```bash
python3 afterglow.py
```

```bash
python3 -m pytest -q
```

```bash
python3 -m pytest -q -m "not slow"
```

```bash
ruff check src tests tools
```

The last `pytest` command is the quick run, about a minute: it leaves out the files that
build whole images for the One, the 800 and the arch-14 remotes. The full suite takes about
five minutes. Neither goes online; `AFTERGLOW_TESTS_ONLINE=1` lets a test reach the
network. Tests that need real configurations look for them under `configs/`, and
skip when they are not there. Real configurations, dumps and firmware images are never
committed. `tests/test_synthetic_roundtrip.py` keeps the byte-identity gate running without
them, so it runs in CI too.

## The layers

```
gui/            PyQt6 (or PyQt5, through qt/) - the only place Qt or Pillow may be imported
build_service   ConfigBuildService: project -> backend -> .ezhex, with a log
importer        .ezhex -> its remote's backend -> project
migrate         a project moved to another remote, every change reported
remotes         the profiles in library/remotes/<id>/ and the build/write gates
backends/<id>   one architecture's encoding: build_project, import_project
payloads/       container formats inside an .ezhex: pk (a ZIP tree), blob (one image)
ezhex           the envelope: an XML header, then the payload
ir_signal       portable signals and protocols; no backend is imported here
ir_protocol
```

Everything below `gui/` uses only the standard library. A backend is removable: deleting
`backends/<id>/` and its remote's folder removes that remote, and needs no change anywhere
else (AGENTS.md, rule 1). Modules the One, the 800 and the arch-14 backend read and write
alike live once, in `backends/_gspm/shared/`. Each of those backends keeps a short module
of the same name that runs the shared source in its own package, so a fix there reaches
all three.

## Registries, not lists

Nothing is listed centrally. Each kind of thing is found where it lives:

- **Remotes.** Every folder in `src/afterglow/library/remotes/` with a `profile.json` is
  one remote. [docs/profile-reference.md](docs/profile-reference.md) describes what a
  profile and its `art.json` say. A profile names its backend and its payload type.
- **Backends.** `backends.get(name)` imports `backends/<name>/` and checks that it has
  `build_project` and `import_project`. A backend can also offer optional hooks, such as
  `capability`, `migrate_legacy_device`, `name_activity_keys` and `SCREEN_GAPS`. Callers
  look these up with `getattr` and do without them if they are missing.
- **Payload types.** Each module in `payloads/` recognises its own bytes
  (`payloads.identify`). There is no default: a payload nothing recognises is refused.

## How a build flows

1. The interface hands `ConfigBuildService.build(project)` the project: devices, activities
   and settings. The project is the only input. A build never edits a template
   configuration.
2. `remotes.for_project(project)` names the profile, and `require_buildable()` refuses a
   `read-only` one.
3. The profile's backend builds from the project and the remote's scaffold
   (`scaffolds/<id>/`, the platform state a real remote carries). The 900 and 1100 build a
   ZIP tree of XML. The One, 650, 700 and 800 build a single image.
4. `ezhex` puts a header on the payload. The header states the remote it is for. The write
   checks compare it against the attached remote before anything is written
   (`concord.Remote._verify_intended_for`).

## How an import flows

1. `ezhex.unpack` splits the header from the payload, and the payload type unpacks it.
   Unpacking records everything needed to repack it byte for byte.
2. `remotes.identify(header)` finds the profile by the skin the header states. A header
   that states none is no remote.
3. The backend reads the payload into a project, as close to what the owner set up as the
   format allows.

## Tools

`tools/` holds one-off and maintenance scripts. Each script's docstring says what it does,
and `--help` prints it without doing anything. Scripts that regenerate shipped files say
which files, for example `arch14_pot.py` for the 650's and 700's translation templates and
`remote_art.py` for a remote's drawing. Run the test that checks a generated file after
regenerating it.

## Commits

Make one change per commit, with a message that says what changed for the person using
Afterglow. Add a regression test with each bug fix, and check that the test fails without
the fix.
