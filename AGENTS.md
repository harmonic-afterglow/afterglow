# AGENTS.md

Operating rules for AI agents working on **Afterglow**. These are not suggestions.
They describe patterns that already exist in this codebase and that every change must
preserve. When in doubt, read the module you are about to touch and the format document
it cites in `docs/`.

Afterglow builds and flashes configuration files for Harmony remote controls whose
vendor service (Logitech) has shut down. A wrong config on a remote nobody has tested
can brick hardware that **cannot be re-flashed from a vendor server any more**. Treat
the format and the safety gates as load-bearing, because they are.

---

## 1. Tech stack - do not add to it

| Layer | What | Constraint |
|---|---|---|
| Language | Python `>=3.11` | Uses `X \| None`, `from __future__ import annotations`. Keep it. |
| Format / build layer | Pure standard library | **Zero third-party imports.** `pyproject.toml` `dependencies = []` is deliberate: unpacking, rebuilding and verifying a config must work on a bare Python. |
| GUI | `PyQt6>=6.5`, `Pillow>=10` | Optional extra `[gui]`. GUI code lives **only** under `src/afterglow/gui/`. |
| Tests | `pytest>=7` | Optional extra `[dev]`. |
| Lint | `ruff`, `line-length = 100` | Config lives in `pyproject.toml`. Not installed by default; respect the 100-col limit anyway. |

**Rules**

- Do **not** add a runtime dependency to the format/build layer. If you think you need
  one, you are solving the problem in the wrong layer.
- PyQt6 and Pillow may be imported **only** from `src/afterglow/gui/`. Nothing outside
  `gui/` may `import PyQt6` or `from PIL`. The build layer is headless so the CLI,
  the tools and the tests run without Qt or a display.
- Target 3.11. Do not use 3.12+-only syntax.

---

## 2. File structure - where things go

> ### The rule this section exists to serve
>
> **Every piece of code is remote-agnostic unless it lives inside that remote's
> `backends/<name>/` folder or a `payloads/<type>.py` module.** Removing support for a
> remote or a container format must be `rm -r` - never a refactor. No tight coupling in
> either direction.
>
> `tests/test_removability.py` enforces this by *doing* it: it builds the package with
> one backend, then one payload type, deleted, and imports everything that is left. It
> also fails any shared module that imports a concrete component or resolves one by a
> hardcoded name.
>
> Violations of this rule do not announce themselves. They look like: a static import of
> a concrete component in shared code, a `DEFAULT` that names one, a check for a path only
> one format has, a profile field defaulting to a component name, or a lookup by
> hardcoded id. Each one turns `rm -r` into a refactor, and one of them silently opens an
> unidentifiable config as a Harmony 900.
>
> The shapes that replaced them are the patterns to copy: **components are discovered,
> not listed**, and **they declare what they own** rather than shared code declaring it
> for them - `sniff()`/`claims()` for payload types, `claims_legacy()` for backends, and
> `LAST_RESORT` for a type that accepts anything so it can never win by default.

```
afterglow.py              launcher; puts src/ on the path FIRST, then imports the package
pyproject.toml            src-layout, package data (library/icons/scaffolds), ruff, pytest
src/afterglow/
  paths.py                the ONE answer to "where does shipped data live" - see §4
  ezhex.py                the .ezhex container: unpack / pack_standalone / rehash
  project_devices.py      canonical portable device shape stored in projects
  remotes.py              remote profiles + the writable/untested safety gate
  importer.py             profile-selected backend import dispatcher
  library.py              private portable device/protocol library + learn()
  build_service.py        headless build orchestration (ConfigBuildService)
  vocabulary.py           device types, activity types and hard keys - read from the
                          remote's own profile, not held here (button glyphs are
                          files under icons/buttons/, found via paths.icons())
  remote_shell.py         a shell on the remote over USB: its own system log
  ir_signal.py            PORTABLE signal envelope - no backend may be imported here
  ir_protocol.py          PORTABLE protocol grammar - likewise
  device_json.py          portable database record -> portable project device
  rf.py, hao.py, concord.py, flipper.py ...
  backends/               ONE ARCHITECTURE'S ENCODING. Selected by the remote profile.
    __init__.py           dynamic registry + required backend contract
    harmony_pk/           PK\x03\x04 payload import, lowering and build: builder/, importer,
                          states, irproto, ssir, protocol_json, ir_emit, ir_vm and the
                          generated-native registry
  payloads/               container formats, selected by profile.payload: pk, blob
  gui/                    PyQt6 authoring app ONLY
    app.py                MainWindow + main() entry point
    tabs.py               the four tabs: Devices / Activities / Remote Settings / Flash
    device_wizard.py activity_wizard.py macro.py properties_editor.py ...
    constants.py          re-exports paths/vocabulary so windows import from one place
  library/                SHAREABLE data - portable protocols and remote profiles (JSON)
  icons/                  Logitech artwork from app-main.swf - NOT under this repo's GPL
  scaffolds/              per-remote platform state each build starts from - Logitech's
tests/                    regression-first pytest suite; conftest.py holds fixtures
tools/                    standalone CLI utilities (compare_configs, learn_ir, rf_pair...)
linux/                    udev rules + harmony_net.sh to bring the USB link up
```

**Rules**

- **Architecture-specific encoding goes in `backends/<arch>/`, never at the package
  root.** This is the rule the codebase learned the hard way. `irproto`, `ssir`,
  `protocol_json` and `ir_compile` were written when there was one remote, so "the
  format" and "*this remote's* format" were the same thing and the root was the obvious
  home. Twenty-six modules then imported them by bare name, because they looked like
  core - and a tool whose whole premise is a portable device library had become a
  Harmony-900 tool that could not be extended without a fork.

  Ask of any new module: *would this mean anything to a remote that does not use this
  exact payload/IR runtime?* If
  no, it is a backend. `tests/test_backend_boundary.py` enforces that **no shared
  module imports a concrete backend**. Selection goes through `afterglow.backends`.
- New portable logic → a module in `src/afterglow/`. New backend build logic → that
  backend's package. New GUI → a module in `src/afterglow/gui/`. Do not
  create top-level modules that mix layers.
- Project devices use only `afterglow-project-device/1`: command names plus portable
  `protocol`/`waveform` signals. `protocol`, `codec`, `raw_codes`, `raw_ir` and native
  block definitions are forbidden as top-level project fields. A backend may create
  them only in its transient lowering copy. `project_devices.validate()` enforces this.
- Shareable portable data (protocol semantics and remote profiles) goes in `library/`
  as JSON. Native protocol programs are ephemeral backend build products generated from
  those semantics. An unknown imported program may survive only inside backend-opaque
  signal evidence; there is no shipped native catalogue. User device maps and captures go
  under `paths.user_library()`, never here.
  Code addresses `library/`, `icons/`, `scaffolds/` **by filename**
  via `paths.py` - never hardcode a relative path to them.
- `icons/` and `scaffolds/` are Logitech-authored and carry their own `NOTICE.md`. Do
  not relicense, publish, or synthesise substitutes for them silently.

---

## 2b. Adding a remote - the path that should stay boring

Supporting another remote must be *data plus a backend*, never edits scattered through
the root. The order below is also the order the tests will stop you in.

**If evidence shows it uses the same `PK\x03\x04` payload and IR runtime:**

1. Add `library/remotes/<model>.json`: `identity` (skin id), `payload`, `infrared`,
   `capabilities`, `vocabulary`, `properties`. Copy `harmony-900.json` and edit.
2. Add `scaffolds/<model>/` - a sanitised real configuration from that remote. It cannot
   be synthesised, and one from a *different* model must never be substituted: it carries
   that remote's calibration and persisted settings.
3. Leave `status: untested`. `require_writable()` refuses to build for it, on purpose.
4. Flash it, boot it, and only then set `verified`. **No exceptions** - there is no vendor
   server to recover from.

That is the whole job. No Python.

A tree-like internal layout is not sufficient evidence. Harmony One uses a different
indexed tree beginning `GSPM`; it does not belong to the `harmony_pk` backend.

**If it is a new architecture:**

1. `backends/<arch>/backend.py` implementing every callable in
   `backends.REQUIRED`, plus that family's private modules/data. Nothing goes at root.
2. Name it in the profile's `infrared.backend`;
   the backend contract test checks the package and callable surface really exist.
3. A `payloads/<format>.py` if the container differs, named in `payload` - which every
   profile must state; there is deliberately no default format.
   Give it `sniff(payload)` and `claims(src_dir)` so the container can identify it from
   the bytes or the tree without anyone naming it, and `ALIASES` for any former name.
4. Do **not** import your concrete backend outside `backends/`, and do not let shared
   code name it in a string either. Shared import/build/source code calls
   `backends.for_profile(profile)`; anything that must recognise your own older files
   declares `claims_legacy()` so `backends.for_legacy_device()` can find you.
5. Run `pytest tests/test_removability.py`. It deletes your component and asserts the
   rest of the package still stands - and does the same for everyone else's, so your
   addition cannot make an existing one undeletable.

---

## 2c. Documentation - where the format is written down

`docs/` describes the **configuration format**, independently of the code that reads it:
the `.ezhex` container, the unpacked tree, `IrProto.bin`, `SsIr.bin`, and how a remote is
identified. It is not a general documentation folder - architecture goes in
`CONTRIBUTING.md`, and user instructions in `README.md`.

- Explaining a format detail? It goes in `docs/`, and the module cites it with
  `Format reference: docs/<file>.md`. Do not restate a format in a docstring.
- Adding a document? Link it from `docs/README.md`.
- `tests/test_docs.py` fails on a citation that does not resolve and on a document the
  index does not link.
- Where a field's meaning is unknown, say it is preserved verbatim. Inventing meaning for
  bytes that cannot be regenerated is worse than admitting the gap.

**Do not write down a number that changes when the code changes.** A test count, a module
count, a file count: they are wrong by the next commit, and a stale number reads as
authoritative. Say "the suite passes", not how many tests there are.

Measurements of things *outside* this repository are different and worth recording,
because they are evidence and they do not drift: how many archive commands a remote
refuses, how many donor devices agreed with a reading, what a firmware image contains.
Give those with what produced them.

---

## 3. Naming conventions - match what exists

- **Modules**: `snake_case.py`, single lower-case word or two (`build_service.py`,
  `device_json.py`).
- **Library JSON files**: `kebab-case` derived from the real product/protocol name
  (`yamaha-rx-v3067.json`, `samsung32-38-0-khz.json`, `harmony-900.json`).
- **Classes**: `PascalCase` (`ConfigBuildService`, `RemoteProfile`, `MainWindow`).
- **Functions / variables**: `snake_case`.
- **Tests**: the test name is a **sentence describing the behaviour**, not the function
  under test:
  `test_editing_a_device_changes_nothing_it_was_not_asked_to_change`,
  `test_roundtrip_is_byte_identical`, `test_a_device_never_claims_two_power_modes`.
  Keep this. A test name is documentation of the invariant.
- **Docstrings**: every module opens with prose explaining *why the module exists* and
  what constraint it is under. Keep it short and impersonal - state the rule, not its
  history. **The format itself belongs in `docs/`**, not in a docstring; cite it with a
  `Format reference: docs/<file>.md` line. `tests/test_docs.py` fails on a citation that
  does not resolve.

---

## 4. State & data patterns - the rules that keep configs valid

**The project is a plain `dict`.** There is no ORM, no central store, no framework
state. `gui/project.py::DEFAULT_PROJECT` is the shape. It is passed by reference to the
tabs, mutated in place, and serialized to `project.json` with `json.dumps(..., indent=2)`.
GUI change notification is done with Qt signals (`changed` → `refresh` / `_mark_dirty`),
not a store. Do not introduce a state-management library.

**The three inviolable data rules:**

1. **A carrier must never silently drop what it does not understand.** Import, parse,
   and rebuild are round-trips. The backend state parser and `ezhex.py` carry unknown blocks *verbatim*
   (`extra`, `order`, `name_first`) rather than normalising them away. If you cannot
   model something, carry it whole. Reordering, re-casing, or "correcting" what you read
   produces a config that differs from every real one and the remote rejects it.

   **Count your rejects.** When you filter catalogue or dumped data, keep a count and a
   reason for every item you drop, and surface them - a `Counter` in the audit report, a
   warning, or a printed error. Never `except: pass` on a conversion failure.

   The failure shape to watch for is a strict match on one item discarding a whole
   collection: one unusable block aborting a configuration, one null model name hiding a
   manufacturer's entire catalogue, exact-case matching dropping inputs because Logitech
   writes `InputAux` in one file and `InputAUX` in another. Silent filtering passes
   review; a count does not.

2. **`unpack → pack must be BYTE-IDENTICAL.**` This is the regression gate
   (`test_ezhex_roundtrip.py`). The remote rejects any container that differs from
   Logitech's, down to `\r\n` vs `\r\r\n`, Unix modes, and Info-ZIP extra fields. Never
   change `ezhex.py` without keeping this test green against a real config.

3. **Every build starts from the bundled `scaffolds/<remote-id>/`, never from a donor
   config.** A donor config carries the other remote's platform state (RF assignments,
   statetracker, calibration) that would ride along unnoticed. Import takes only devices
   and activities; the config is rebuilt on the scaffold. See
   `build_service.py::ConfigBuildService.build`.

4. **A gate must not be stricter than the runtime it protects, and never looser.** When
   a checker and the thing it models disagree, the model is wrong - say so, don't tune
   the threshold. A structural check written from the shape of the bytes rather than from
   execution will both refuse blocks that run cleanly and accept blocks that do not: an
   element with `symbols=0` never dereferences its alphabet, so a zero-size pointer there
   is vestigial, not broken. `ir_vm` is the arbiter for anything about native execution; if you add a
   structural check, add the corpus test that asserts it agrees with the VM.

**Say what you measured, not what it implies.** "Portable" describes the interchange
model; "reproducible" describes one remote's backend. They differ by half the corpus -
99.99% of the Logitech archive is representable and the Harmony 900 refuses about 52% of
it, so quoting the first alone is a false claim. Both numbers come out of one `tools/logitech_archive.py … audit --reproduce <remote>` run; report them
together.

**The safety gate:** `remotes.py` profiles have `status: verified | untested`.
`profile.require_writable()` refuses to build for an `untested` remote. Only
`harmony-900` is verified. **Never** downgrade this gate or mark a profile `verified`
that has not actually had a config flashed and booted on it. Adding support for a remote
of an already-implemented architecture is **adding a JSON file to `library/remotes/`,
not editing code.**

**Paths:** ask `paths.py`, never count directories from `__file__`.
- `paths.root()` - where *shipped* data (`library/icons/scaffolds`) lives (found by
  markers, works in a checkout or installed).
- `paths.app_dir()` - where the *user's own* files live (dumps, projects, output).
- These are distinct on purpose. Never offer to write user files under `paths.root()`;
  that writes a user's own devices into the application.

---

## 5. Privacy - never commit someone's living room

A configuration is a list of what is in somebody's home; a donor dump belongs to
someone else; a project file carries the MAC of any paired RF base. `.gitignore` blocks
`*.ezhex`, `configs/`, `channel_logos/`, firmware (`*.hfw`), decompiled firmware
(`lua_src/`, `ffdec_out/`), and the private device library.

**JSON at the repository root is denied by default (`/*.json`).** A list of names -
`project.json`, `*_dump.json` and so on - cannot hold, because a private file only has to
be named something nobody predicted. The deny-by-default rule is what works: every private
artifact this project writes lands in the working directory, and nothing shareable does.
Every tracked `.json` lives under `src/afterglow/library/`.

So adding a genuinely shareable `.json` at the root needs `git add -f`, which is the
moment to ask what is in it. Prefer putting it under `library/` instead.

Still check `git status --porcelain` **before** `git add`, not after. **Never** commit any
of these, never weaken these ignores, and never publish a config, a firmware image, or
anything recovered by decompiling one.

Publishing pushes **all history and every commit's author metadata**, not just the current
tree. Before a first push, audit the history itself, not the checkout.

---

## 6. Testing philosophy

- **Regression-first.** Almost every test guards something that once built cleanly,
  verified cleanly, and was wrong anyway. When you fix a bug, add the test that would
  have caught it, named as the invariant.
- **Real configs are never committed.** Tests that need one ask the `configs` /
  `a_config` fixtures and **skip** when absent (`conftest.py`, `CONFIGS` list). The
  suite must stay useful without a Harmony and thorough with one. Do not hardcode a real
  config into a test; add it to the fixture list.
- GUI tests use the `qapp_or_skip` fixture (`QT_QPA_PLATFORM=offscreen`) and skip if
  PyQt6 is not installed.

---

## 7. Exact terminal commands

**Set up (from `afterglow/`):**
```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev,gui]'
```

**Test:**
```bash
.venv/bin/python -m pytest              # full suite
.venv/bin/python -m pytest -q           # quiet
.venv/bin/python -m pytest tests/test_ezhex_roundtrip.py   # the byte-identical gate
```
Skips vary with the private real-config fixtures; everything else must pass.

**Test as a runner would**, when you touch anything that looks for a host program
(`shutil.which`, `subprocess`):
```bash
env -i PATH=/var/empty HOME="$HOME" QT_QPA_PLATFORM=offscreen python3 -m pytest -q
```
A developer machine has `pkexec`, `pgrep`, `dnsmasq`; a CI runner has none of them. A test
that stubs the wrong function still passes locally, because the real lookup succeeds, and
fails on every runner.

**Lint:**
```bash
.venv/bin/ruff check .                  # config in pyproject.toml; must stay clean
```
The gate is `select = ["E4","E7","E9","F"]`. **`F` (pyflakes) is load-bearing, not
cosmetic** - its first run found a shipped CLI that raised `NameError` before reaching
the remote, and a module that imported only on Python 3.14 because PEP 649 made
annotations lazy. Do not silence an `F` finding; fix it. The E-series style rules this
codebase deliberately uses (`E402`, `E701`, `E702`, `E741`, `E731`) are off on purpose
and the reasons are written out in `[tool.ruff]`.

CI (`.github/workflows/ci.yml`) runs the suite on **3.11, 3.12 and 3.13**. 3.11 is the
declared floor and testing it is not optional - see the annotation bug above.

**Run the app:**
```bash
python3 afterglow.py                    # or ./afterglow.py - everything else is in the GUI
```
On Linux the app offers to set the USB link up on first run, and again from
Settings ▸ Set up the USB link. Do not tell a user to run `harmony_net.sh` by hand.

**Install** is `pip install -e '.[gui]'`; the console entry point is `afterglow`
(`afterglow.gui:main`). Package data (`library/**`, `icons/**`, `branding/*`,
`linux/*`, `scaffolds/**` including its required dotfiles) ships via
`[tool.setuptools.package-data]`. If you add a data folder, declare it there **and** in
`packaging/afterglow.spec`, or it will be missing from the bundle only;
`tests/test_package_stays_code.py` fails on an undeclared one.

**Bundle** (a standalone executable) is `pyinstaller --noconfirm packaging/afterglow.spec`,
run by `.github/workflows/bundle.yml`. `--self-check`, `--concord-check` and
`--import-check` verify a built bundle without opening a window.

**Compare two configs by behaviour (not bytes):**
```bash
python3 tools/compare_configs.py reference.ezhex mine.ezhex   # exit 1 if behaviour differs
```

---

## 8. Before you open a PR / hand off

1. `.venv/bin/python -m pytest` is green (or only real-config skips remain).
2. `unpack → pack` byte-identical test still passes against any real config present.
3. No third-party import leaked into the format/build layer; no `PyQt6`/`PIL` outside
   `gui/`.
3b. If you touched code that probes for host programs, the suite passes with a scrubbed
   `PATH` too - see section 7.
4. No config, project, dump, or firmware got committed.
5. New/changed modules carry a short docstring saying why they exist; any format detail
   is in `docs/` and cited, not restated.
6. If you changed device/config shape, a regression test named as the invariant guards
   it.
