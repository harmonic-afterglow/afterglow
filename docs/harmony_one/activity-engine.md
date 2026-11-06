# Contexts, state variables and the activity engine

## Activities and state contexts

Section 10 begins with a one-byte context count and absolute `u24` pointers indexed by activity
ordinal. A short context is a count followed by four-byte `{key code, object u16, class}` rows. A
zero first count selects the long form: a second count followed by five-byte rows that add a flags
byte before the short-form fields. Codes `01`, `02`, and `05` are the observed ENTER, LEAVE, and
REFRESH hooks. Afterglow retains every context row and resolves only class `7f` object references.

Section 14's complete section body is `8 + 3*n` bytes: a `u16` property count, six header bytes,
then one absolute `u24` pointer per property. A property record contains `u16 initial`, `u16 limit`,
`u16 transition count`, one preserved padding byte, and eight-byte transitions. Each transition is
`{flags u8, from u16, to u16, operand u16, class u8}`. Class `7f` operands enter the section-11
object graph and may ultimately reach indexed command IDs.

An activity row is a touch/key object containing `{0xff00 | ordinal, 1f}`. Its label is retained as
one or more raw glyph lines using the same geometry-based association as device menus. Activity
attribution starts at the context's ENTER and REFRESH objects. Object atoms with a class at least
`80` set property `class & 7f` to the atom's operand; section 14 then supplies the transitions and
commands for that value. An activity that reaches no indexed command is marked undetermined, not
as using no devices, because the separate All Off/default-state mechanism remains unexplained.

The downstairs donor has 10 contexts, 45 properties, 73 transitions, and three ENTER activities;
two can be attributed to indexed commands. The upstairs donor has 16 contexts, 48 properties, 47
transitions, and nine ENTER activities; eight can be attributed. These differing populations
confirm that neither RE-HARMONY's ten-context observation nor one factory activity count is a
format constant.

Section 0 owns the names of state properties used by this engine. It begins with `ed fe`, a `u24`
length equal to the section size minus two, then a contiguous chain of A7 records and a final
little-endian `beef`. An A7 record is `{a7, length u16, type u16, id u16, name}`; `length` counts
the four bytes occupied by type and ID plus the name. Type zero records are containers and type
one records are leaves. Ownership depends on the enclosing section and contiguous close, not an
unbounded A7 byte scan. Names are decoded as UTF-8 when possible and always retained as raw bytes.
The broader upstairs donor contains a valid name with parentheses that RE-HARMONY's restricted
name regular expression omitted.

Section-10 rows also provide the physical-key mapping for active activity contexts. A binding is
complete evidence only when its class-`7f` object is either a direct `{command,7d}/{device,7c}`
shape or has exactly one `7f` jump to that shape, the command is owned by section 5, and command
and runtime-device high bytes agree. All other rows remain visible with their rejection reason.
The downstairs and upstairs donors contain 62 and 138 such complete rows respectively.

The button inventory begins at header offset `67`: a one-byte count followed by four-byte
`{code, sequential index u16, tag}` rows. Both broader donors contain 55 rows with sequential
indexes. This is a vocabulary, not a dispatch table. Comparing its codes to all section-19 zones
classifies 43 as physical candidates, two as lifecycle hooks, two as established touch controls,
two as paging strips, and six as physically/touch ambiguous. English silkscreen names are not in
the image and are therefore not assigned from this table.

Drawing inventory follows calls, jumps, every switch target, and class-`73` atoms through the
section-12 subprogram index. Referenced bitmap resources have either a four-byte mode-0 header and
flat RGB565 pixels or a five-byte mode-1 header and the row-run encoding used by sprites. Every
referenced resource must decode to its declared width and height. The downstairs donor reaches 64
distinct valid bitmaps; the upstairs donor reaches 75, with no invalid referenced resource.

## Section 14, the activity engine

Section 14 is a counted index - `u16` count, the count less one, a one, the count less one
again, then a pointer per record - over records that are state machines. A record is a
`u16` initial value, a `u16` limit, a `u16` transition count and a padding byte, then that
many eight-byte transitions of `{u8 flags, u16 from, u16 to, u16 operand, u8 category}`.
`0xfffe` appears as `from` throughout and behaves as "whatever the current state is".

Not one field in a record is an address. States are numbers, and a transition's operand is
an index into section 11 rather than a pointer, so a record moves without anything being
repaired: all 45, 48, 51 and 44 records in the four donors re-encode byte for byte from
their fields alone. That is what lets composition model section 14 instead of carrying it,
and a generated image emit whatever records it is given.

An operand whose high byte is `0xf8` or above is not a value but an expression. The
application firmware dispatches on it from 0x23042: `0xfb` loads the low byte into an
accumulator, `0xfa` adds to it, `0xf9` loads through the table pointer, and each of
`0xf8` to `0xff` has its own handler. That is what the `0xf202` and `0xfb01` operands seen
with category `0x1f` are. See `tools/harmony_one_firmware.py`.

The table has three parts. Records 0 to 6 are the real-time clock. Records 7 to 17 are
platform properties, byte-identical in the factory configuration and all four donors -
limits 2, 3, 7, 7, 32, 1, 1, 4, 3, 1, 3, initial values 0, 0, 5, 0, 0, 0, 1, 2, 0, 0, 0,
no transitions - except record 14, which is identical across the donors and differs from
the factory. The last record is a terminator: limit `0xfefd`, initial zero, no
transitions, in every image. What lies between record 17 and the terminator is what a
household configuration adds.

### What a household property is

A household property is one device's discrete state. Its limit is the highest state it
reaches, and each transition names a section-11 object holding the commands that get
there. One donor's record is an input selector, and the objects say so plainly: limit 4,
and five transitions whose objects send a setup command, then the input command as many
times as the state number, then a confirm. That is how a device whose input is cycled by a
single button is driven.

Every household property that sends anything sends it to exactly one device - 5, 8, 11 and
5 records across the four donors, and never two devices in one record. The rest send
nothing at all: 21, 21, 21 and 20 properties the remote tracks but cannot drive.

One property counts the activities. Its limit is one less than how many the configuration
has - 2 against 3, 8 against 9, 10 against 11, 1 against 2 - and its initial value is the
activity that was running when the configuration was saved: 2, 8, 9 and 1, each a valid
index. Where a configuration has few activities that limit is shared with the boolean
properties, so a non-zero initial is what singles it out, which means an image saved in
activity zero cannot be told from one naming no activity at all.

An earlier hypothesis was tested and refused. The records with a limit of 1 number 17, 20,
21 and 19 against 3, 6, 7 and 4 devices - devices plus fourteen in three of the four -
which looked like a power flag per device. It is not: none of them drives a device. The
first attempt to check this also looked only at transitions whose category is `7f` and
read the device out of the atom directly, missing both the transitions whose category is
zero - whose operand is always zero, a null action - and the fact that a device is named
in the high byte of a nested object's atom rather than by the atom itself.

### How an activity reaches its commands, and where All Off does not

A context's rows carry hooks by key code: `01` on entering, `02` on leaving, `05` on
refresh. A hook names an object, that object writes `(property, value)` pairs, and each
write is resolved by finding the property's transition whose `to` matches the value and
following its object to the commands it sends. That path is what makes an activity
determined, and it works: 2 of 3, 8 of 9, 10 of 11 and 1 of 2 activities in the four
donors resolve to between 5 and 9 indexed commands across 4 to 6 devices.

The one context per donor that resolves to nothing is All Off, and it is not unresolved.
It writes exactly eight properties in every image, **none of them a property that drives
a device**, and its set is always a subset of what a real activity writes - a real
activity writes those eight and adds the driving ones, 5, 7, 8 and 5 of them.

All Off stores no commands because it does not need to. **Every property that drives a
device has exactly one transition to state zero, and that transition carries a command** -
5, 8, 11 and 5 properties across the four donors, without a single exception - so turning
everything off is driving every property to zero, using the transitions the activities
themselves installed. `all_off` returns those commands: 6, 9, 11 and 5 of them, covering
every device that has a driving property at all.

A property whose limit is 1 and which drives a device is a power toggle, state 1 on and
state 0 off, and most devices have one: 3 of 3, 5 of 6, 7 of 7 and 4 of 4. Where a device
has none its power sits inside a property with more states, which is why counting limit-1
records alone never gave the device count - and why the earlier attempt at that failed. It
counted every limit-1 record, and the silent ones outnumber the driving ones four to one.

The leave hook was checked for it and does not hold it either. Every activity but All Off
carries one, each writing eight properties, and in all four donors not one of those writes
reaches an indexed command. `inspect` follows it anyway rather than reading it and dropping
it, and reports an activity that reaches no command as `state_only` rather than
undetermined, so that determined and state-only together account for every context.

### The clock, and section 3's unexplained byte

Records 0 to 6 have limits 59, 59, 23, 30, 6, 11 and a year, and their initial values are
section 3's timestamp fields: second, minute, hour, day, weekday, month, year. All 35
fields agree across the factory configuration and all four donors.

Those limits settle how the fields count. A day whose limit is 30 counts from zero, and so
does a month whose limit is 11. Read that way the fifth byte of section 3 - the one nothing
had accounted for - is the weekday with Sunday as zero, and every image agrees:

| image | date | weekday | stored |
| --- | --- | --- | --- |
| factory | 2007-10-25 | Thursday | 4 |
| downstairs | 2023-08-23 | Wednesday | 3 |
| upstairs | 2024-12-28 | Saturday | 6 |
| backup-One | 2015-08-02 | Sunday | 0 |
| HarmonyONE | 2026-05-06 | Wednesday | 3 |

Read one-based instead, two of those dates fall on the same weekday and carry different
values, which is exactly why the byte stayed unexplained. `stamp` now derives the weekday
from the date, refuses one that disagrees with it, and takes the day and month from zero -
so it accepts a zeroth day and month, which it used to reject, and refuses month twelve,
which it used to accept and no remote could hold.

## The Activities menu

Both donors draw a second menu of the same shape - equally sized touch zones in reading order,
paired band for band with labels at x=63 - but its rows start an activity instead of opening a
screen: the row's object carries opcode `0x1f` with `0xff` in the operand's high byte and the
activity ordinal in the low one. That is also what keeps the two menus apart, because a device-menu
row containing it is refused.

Neither donor replicates its Activities menu: one screen holds all of it, two rows downstairs and
eight across three pages upstairs, each activity on exactly one row and every ordinal matching one
the activity index already owns. Its labels come from the same restricted menu font as the device
rows.

### What an activity ordinal is

An activity ordinal is a position in the section-10 context table, so removing a context would
renumber every one above it. Section 10 opens with 7 contexts that hold no activity in all four
images measured, and activities occupy 7 upwards. Those seven are not otherwise constant: they were
byte-identical at identical offsets in the first two images compared, but across four only one of
them - a seven-byte context 5 - is identical, and one image places them 12 bytes further along.
Their count is a format property; their contents are not. Exactly one context row starts an
activity directly - the Off key (`a5`) in context 1 - and it names the one activity each donor keeps
off its menu: a long-form five-row context, referenced by a single object where menu activities have
two. That is the All Off path, and a row for it is refused.

The references to an activity ordinal that this backend can find are few: 5 object atoms downstairs
and 17 upstairs, carrying opcode `0x1f` with `0xff` in the operand's high byte, plus that one
context row. Opcode `0x1f` is not only this action - the donors use fifteen other high-byte values
with it - and section-14 transitions name no activity at all.

Following every reference this backend owns leaves 45% and 50% of the object table reachable from
nothing, and each activity's second object sits in that set. Four measurements show it is emitted
slack rather than a structure something else indexes. The drawing graph walks to completion with no
rejects, so nothing hides behind unfollowed control flow. Of the unreferenced objects, 149 and 463
are entirely zero atoms and 671 and 1,597 are byte-identical to an object that is referenced,
leaving 223 and 327 distinct bodies. Three-byte values equal to an object body address number 3,210
and 5,884, of which section 11's own table is 3,015 and 5,647; the excess is at or below the 209 and
934 measured for random addresses in the same region. Outside the bytes this backend parses, a `u16`
below the object count followed by `0x7f` occurs 116 and 139 times, against 104 and 219 for `0x73`
and a mean of 2,219 and 2,423 over all 256 possible following bytes. Finally, every section with no
model totals 1,520 and 2,419 bytes, where a bare `u16` index over the objects would need 6,030 and
11,294.

That is evidence and not proof - firmware computing an index rather than reading one would
overturn it - which is one more reason a build generates every ordinal afresh rather than
renumbering somebody else's.
