# Remote profile reference

A remote is a folder, `src/afterglow/library/remotes/<id>/`. Delete the folder and the remote
is gone. Nothing about a remote belongs anywhere else in the code. The folder holds:

| File | What it is |
|---|---|
| `profile.json` | who the remote is, what it can do, and what the interface offers for it |
| `art.json` | where each key is in the remote's drawing (optional) |
| `art.svg` | the drawing, cut from Logitech's guide; see `NOTICE.md` (optional) |

A profile is checked when it loads (`remotes._check_interface`). A profile that does not say
what its remote has is refused. It never inherits the Harmony 900's answer.

## `profile.json`

| Key | Meaning |
|---|---|
| `id` | the folder's name, `harmony-650` |
| `model` | what the remote is called; shared by all its skins: `Harmony 600 / 650 / 665` |
| `identity` | `arch`, `skin`, `other_skins`, `flash`, `board`, `software_type`: what a configuration's `<INTENDEDVERSION>` must say. Leave out a field the remote does not state. |
| `payload` | the container format, `pk` or `blob` (`payloads/`) |
| `backend` | the backend that builds and imports it (`backends/<name>/`) |
| `status` | `read-only`, `experimental` or `verified`. This is a safety gate, not a label. **Anyone** can write an experimental remote from the Flash tab. See AGENTS.md §2b and `docs/first-write.md`. |
| `default` | `true` on the one remote a project that names none is for: the Harmony 900, whose projects came before remotes were named. Not a status: several remotes can be verified. |
| `capabilities` | what the remote has: `hard_keys`, `touchscreen`, `keyboard`, `ir_learning`, `rf_blaster`, `first_time_setup` |
| `infrared` | what the backend can send natively |
| `looks` | `{skin: scaffold}`: a model with a look of its own, such as `{"71": "harmony-600"}`, the 600's grey pictures and light levels |
| `vocabulary` | device types, activity types, hard keys, their aliases, layout and labels |
| `properties` | the `<Property>` entries a device or activity can carry (the 900 / 1100) |
| `preferences` | the remote's own settings files, offered on Remote Settings |

### Skins: one profile, several models

Some remotes were sold under several names. The 650's profile covers the Harmony 600 (skins
71 and 73), the 650 (72) and the 665 (75). A project records the model it is for in
`settings.skin`. The skin is what the status bar shows (`remotes.model_name`). It is a
separate entry in the remote chooser, and it is kept through a move to another remote when
the target has it. A model can also look different. The profile's `looks` names the
scaffold whose `look.json` gives it its own pictures and light levels:
`scaffolds/harmony-600/look.json` for the 600's skins 71 and 73.

### `interface`: what the editors offer

| Key | Type | Meaning |
|---|---|---|
| `tabs` | list | which of `devices`, `activities`, `settings` and `flash` are shown. `devices` and `flash` are required. |
| `device_pages` | list | the device editor's pages: `search`, `identity`, `commands`, `screen`, `inputs`, `timing`, `advanced` |
| `activity_pages` | list | the activity editor's pages: `identity`, `roles`, `favourites`, `screen_buttons`, `hard_buttons`, `startup`, `power`, `advanced`. A move to another remote keeps screen buttons and favourites only where the target lists them (`migrate.py`). |
| `settings` | list | the Remote Settings rows: `output_file`, `owner`, `language`, `rf_blasters`, `theme`, `assistant`, `welcome`, `preferences` |
| `timing` | list | the Timing page's fields, by the project key each one sets |
| `languages` | list | `[label, LocaleId]` pairs the remote can be set to |
| `type_icons` | object or `false` | `{"folder", "fallback"}` gives the remote's own device and activity icons (the One, the 800). `false` means the remote draws none (the 650, the 700). Left out, the icons are the 900's (`icons/`). |
| `favourite_logos` | bool | whether a favourite can have a logo. The 650 and 700 have none. |
| `favourites_button` | string | the label of the button an activity's screen opens its favourites with |
| `screen_icons` | bool | whether a screen button can have an icon. Only the 900 and 1100 draw them. |
| `activity_layouts` | bool | whether an activity has Sound and Picture layouts (the 550, 555 and 688). The Activities tab lists them under each activity, each edited in its own window. |
| `skins_without_layouts` | list | skin numbers of this profile whose remote has no Sound and Picture keys, so no layouts (the 688 profile's 675) |
| `screen_grid` | object | `{"device": [columns, rows], "activity": [...]}`: the screen's grid of buttons, so the editor previews pages as the remote lays them out |
| `activity_buttons` | list | `[label, value]` for each key that starts an activity (Watch TV, Watch a Movie, Listen to Music). An activity stores the value in `activity_button`. |
| `activity_screens` | object | the 1100's touchscreen tabs: each `{group, flag}` |

A key starting with `_` (`_comment`) is a note for the reader and is ignored.

## `art.json`

Coordinates are the guide page's points, the same as `art.svg`'s.

| Key | Meaning |
|---|---|
| `svg` | the drawing's file name, `art.svg` |
| `view` | `[x, y, width, height]`: the part of the drawing shown. This is the whole case. |
| `keys` | `{key: [x, y, width, height]}`: where each hard key sits, by the profile's key names. Each key is lit in the shape of the outline drawn around it. Keys that share an outline (a rocker, the d-pad) are cut into their parts. |
| `unassignable` | keys the remote keeps for itself (activity keys, Help, the screen's keys), shown dark |
| `cut` | `[top, bottom, widen]`: a band left out of the editors' picture and closed up over, so the keys fit a smaller window. `widen` scales what is above it to meet the case below (the 650's screen). |
| `source` | the recipe `tools/remote_art.py` redraws `art.svg` from: `guide`, `page`, `region`, `drop` (callout colours to leave out), `erase` (rectangles), `recolour`, `screen` (a mock-up screen to empty), and `marks`. Marks are paths printed on the keys, such as the colour keys' colours and labels as letter outlines, so the drawing needs no font. |

Run `python3 tools/remote_art.py --help` for how to redraw one.
