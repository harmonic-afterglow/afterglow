# Activities and device state

## A device's power and inputs are state variables

As downstairs and upstairs build them (arch 12):

- **Sending a command** is an object `(command id, 0x7D) (device << 8 | tenths, 0x7C)`: on arch
  12 `0x7C`'s high byte is the device and its low byte a wait in tenths of a second.
- **`<Label>_Power_2`**, values 0 and 1: going 1 to 0 runs the device's off send, 0 to 1 a list
  of its on send and then the power-on delay as `0x7C` waits a hundred tenths at a time
  (downstairs' amplifier waits `0x264` then `0x214`, 12 s). A device with one power command
  sends it both ways.
- **`<Label>_Input_<n>`**, values 0 to n-1: inputs chosen directly get one transition each from
  "any value" to the input, running its send; inputs reached by stepping get one transition
  per ordered pair, stepping as many times as it takes. Every input variable in upstairs and
  in Kāt's configuration writes "any" as `0xFFFE`, and downstairs' amplifier does too; only
  downstairs' television uses `0xFFFD`. An activity's tag 5 writes its inputs again to re-send
  them, which only works if the transition fires on the value already held, so `0xFFFE` is
  read as "from any value, the same included" and is what a build writes.
- **Section 0 names them**: `Root` and `State` containers, then one leaf per state variable
  whose id is the variable's index - `TV_Power_2`, `TV_Input_11`, `CurrentLocation_1`,
  `CurrentActivityState_0_3`, `ButtonSoundVolume_2` (the Screen Sounds flag). No donor names
  a command. Generated images used to name every command there, whose ids collide with the
  variables'; they now name the variables, as the donors do.

A generated image builds them from the project's device fields - `power_on_cmd`,
`power_off_cmd` or a toggle `power_cmd`, `power_delay`, `inputs`, `input_cycle`,
`input_delay`, `online_inputs` and `app_power_delay` - after the Options screens'
variables, and activities set them by writing a device's power and input variables.

**The input delay and a smart TV's apps.** Logitech keeps a device's input delay (the
archive's `InputDelay`) in each input's own command object: Kāt's Hisense 50R6 has
InputDelay 1000 and its ten input sends carry `0x7C` low byte 10, which no other command of
it does (its power send has 1). That byte is how long the code is sent, in tenths, not a
wait after it: probe BO gave three copies of the Hisense's Volume Up the bytes 1, 10 and 30,
and each raised the volume one step - and 30 followed at once by 1 was one step too, where
a 3-second wait would have made two. A send held that long keeps its device busy as long,
so the input's 1 s is both: the code held, and the next command a second later. An import
reads it as the device's input delay, which a build writes as a press and a 1 s wait. Its apps' delay (`ConnectedAppPowerOnDelay`, 45 s) is a variable
`Kate_TV_OnlinePower_2`: power-on starts timer 2 (`1F EB02`), which after 45 s writes it 1;
power-off writes it 0; the Netflix input loads the byte register with 0 and, behind a test
of it, waits 45.2 s and writes it 1, then sends. A generated image has `<Label>_Online_2`
instead, with no timer: power-on clears it, and the first app after waits only what the
power-on wait has not, `app_power_delay - power_delay`, then sets it. An import reads both,
and the input delay either way (importing.py).

## Activities

An activity is a value of `CurrentActivityState`, a context in section 10, and four kinds of
screen; everything it does is a state write, as Danny Bloe's "how an activity is built"
found and the three household donors agree. Read from upstairs, downstairs and Kāt's
configuration with `one-tools/disasm.py` (contexts, modes and now switch tables), and
checked where it matters against the Harmony 800's firmware:

- **The counter.** `CurrentActivityState_0_<n+1>`: values 0 to n-1 are the activities and n
  is nothing running, its initial value. Every "go back to what is running" is a section-15
  switch on it: an activity's value enters its first page, the idle value the Activities
  menu.
- **Selecting.** `1F FFxx` selects context xx. The 800's handler (`FUN_0800b1b4`) runs the
  old context's tag 2 and the new one's tag 1, or the running one's tag 5 when it is picked
  again. A menu row is a click (`75 0FCA`) and the select; Off (`0xA5`, in the events
  context) selects Off's context. `07 FFFE` runs the running context's tag 5 again.
- **Enter (tag 1)**: enter the activity's starting screen, `07 FFFB` (stop every running
  timer: the 800's `07` handler with low byte `FB` calls its timer reset), write 1 to the
  power of each device it uses in order, its inputs, 0 to every other device's power, the
  counter, then enter its first page. A transition sends each command; an activity names
  none itself. **Leave (tag 2)**: `07 FFFB` and its leave steps. **Picked again (tag 5)**:
  `07 FFFB`, its inputs again, its first page.
- **Keys.** The context binds each key the activity routes - volume and mute to the volume
  device, the rest to the control device, by each command's hard slot - to that command's
  own object, as a device page binds it, and Help (`0xA6`) to its Help screen. A device page
  binds every key of the keypad in its own list (a command, or nothing), so device mode
  never falls through to the running activity; the stack is the donors': events (1), `0xFE`,
  the current mode, `0xFC`, the key light, and start-up selects Off's context last.
- **Off's context** has tags 1 and 5 and no tag 2, as every donor's has: the counter to
  idle, `07 FFFB`, the Activities menu, every device's power to 0.
- **Screens.** The starting screen draws the infrared waves (62x33 at 57,33), the
  activity's icon (62x42 at 57,67), "Starting ..." in attribute 11 and "Keep the remote
  pointed at your system." in attribute 0, and swallows every key. The activity's pages
  are its buttons, six to a page on blue frames, a Devices softkey, the side strips turning
  pages. **Each activity has its own device list**, as Logitech's compiles do (Danny Bloe's
  harmony-explorations, architectures/harmony-one/compiler.md, "the device lists"): every
  device once, those its start switches on first in that order, then the rest as the list
  with nothing running has them. An activity's pages open its own list; the Activities
  menu's Devices and every device page's Devices switch on the counter to the running
  activity's list, or the idle one. The lists come after the Tutorial's screens. Help draws its name, "Attempting to fix the problem...", the waves and the same
  reminder; entering it re-sends what the activity set and goes back. The device list's and
  device pages' left softkey reads "Current Activity" while one runs.

**Keys by scan code.** A row binds key `0x80 | scan`. Danny's key table gives 32 scans;
the rest are read here. Scan 34 (`0xA2`) opens the Activities menu from Kāt's events
context, 37 (`0xA5`) selects Off's context in all three, 38 (`0xA6`) enters Help in every
activity context, and 13 is the remaining keypad scan, `NumberEnter`. Danny left two pairs
undecided because every activity binds both members the same way; upstairs' Xbox One page
does not: scan 36 sends its `Chptr+` and 26 its `Chptr-`, while 27 and 29 send its
direction keys, so 27/29 are `DirectionUp`/`DirectionDown` and 36/26 `UpArrow`/`DownArrow`.

**Favourite channels.** Kāt's configuration opens a favourites activity on its favourites:
a page of buttons, "Commands" on the left softkey and Devices on the right. Logitech tunes
each one by writing a channel variable whose transition loads the number (`7A`) and runs
the firmware's number sender (`1F F3`) over a digit table in section 17. A build sends the
digits instead - the control device's digit commands, each followed by its key delay
(`press_interkey`), then the confirm key (`channel_confirm`) - which sends the same codes
without the table. An import reads Logitech's the way the firmware runs them: section
17 is the number sender, as Danny Bloe's harmony-explorations lays it out (config-format/
state.md, "Base slot 16", numbered from 0 there) - a record per device that takes a
number, its flags, a base added to the number, a minimum of digits, an instruction sent
first, one last (the confirm) and a prefix once the number is long enough, and three
tables of ten digit instructions, for the first place of several, the middle ones and the
last. A write of a variable whose transitions dial is read as what its transition sends,
the twin variable it writes silently after (`TV_+_AVR_DiscreteChannel_3` beside
`TV_+_AVR_Channel_3`) firing nothing; the digits it sends are one-block copies, read as
their keys' commands "(press)". Kāt's three favourites came back as channels 2, 3 and 4,
where before they were lost. A favourite's logo is composed onto the frame of the button place it is
drawn in; a favourite without one shows its name. An activity with favourites and buttons
opens on its favourites, the left softkey going between them ("Commands"/"Favorites"),
lighting zones 5 and 7 as the donors' screens with both softkeys do.

**Help.** Upstairs' Help, read with `one-tools/flow.py` (which follows a screen's keys,
touches and handlers to every screen they enter), re-sends the activity's power and inputs
under "Attempting to fix the problem... Keep the remote pointed to your system.", then asks
"Did that fix the problem? If not, the remote will ask you questions to help correct the
problem." No asks after each device's power and then each input in turn - "Is the AV
Receiver on?", "Is the TV set to the TV input?" - over the activity's icon, Yes and No the
softkeys. Yes moves on to the next; No sends it again and asks "Now is ...?", whose Yes asks
"Did that fix the problem?" (Yes: the activity; No: the next question) and whose No sends it
again and asks the first question once more. After the last, the activity. Help on any of
these screens goes back to the activity. Off's Help is the same about each device being off.
A build generates exactly that: Help's screen, the first question, and four screens per
question (`ordinals.QUESTION`), the words Logitech's.

**The Remote Assistant.** Upstairs keeps one state for the whole remote (its variable 19,
0-3, unnamed): 0 never shown, 1 welcomed, 2 shown before, 3 hidden. After an activity
starts - or is picked again - a switch on it opens a note titled with the activity's name
and a colon, under "Remote Assistant:": at 0, "If any devices are not set up correctly,
press "Help" now." (entering it sets 2), OK to the activity; at 1, "The remote has now set
up your system for this Activity." (also sets 2), OK to that note; at 2, that note, OK to "Do
you want to hide the Remote Assistant?", whose Yes sets 3 and says "To hide the remote
assistant, use the software to update the display settings for your remote."; at 3,
nothing. Off has its own: at 0 or 1, "Welcome to your remote." (OK sets 1), then "Ensure all
your devices are off. If any devices are still on, press "Help" now."; at 2, that and the
offer to hide it. Start-up runs Off, so a new remote opens on the welcome. Options' first row
is a switch on the same state: at 3 it reads "Turn Remote Assistant On" and sets 1, else
"Turn Remote Assistant Off" and sets 3. A build generates all of it, its state
`RemoteAssistant_4` (activity_screens.Flow._notes).

**Options and the Tutorial.** Both household donors' Options have two pages: the Remote
Assistant, the Tutorial and Date and Time, then Screen Sounds and Screen Sensitivity. A
build with activities lays them out the same; without activities, Options is one page of
Date and Time, Screen Sounds and Screen Sensitivity. Every donor's Tutorial is the same
eleven pages (upstairs' screens 218, 219, 215, 216, 208, 209, 206, 207, 211, 222, 223): a
black screen - its fragment a filled rectangle, not the backdrop - one of Logitech's pictures
of the remote, the words from the left at x 10 in attribute 14, eleven pixels a line, and
Exit bottom right. Each is moved on by the key it teaches (the right arrow, Activities,
Help, Off) or by touching the page, the left arrow back, Exit back to what is running. A
build generates the same from a page table (options_screens.TUTORIAL: the picture and
where, where the words start, the keys and touch zones that move on, the labels drawn over
the picture) with the scaffold's `tutorial/<n>` pictures, which the extractor finds as the
black-screen pages and orders by their own left arrows, and Logitech's words from the
catalogue; it adds a small page counter, top right.

**Held steps.** A sequence step held for a duration becomes a record of its own: the
command's press, then its repeat frame (or the press again) until the hold has lasted that
long, then its release - the One holds a code only while a key is down, so this is how a
sequence can give a television its two-second power-off. The record is in its device's
section-4 run but on no screen.

**Where a build improves on the donors.** Help re-sends a device's power only where it has
a separate on and off command, since sending a toggle again turns a device off that Help
was asked to fix; Logitech's Help resent toggles too. Off's Help likewise sends only
discrete offs.

**The pictures.** Activities are drawn in blue where devices are orange and Options green:
the Activities menu's row frame and the six button frames, found from the menu screen and
from the screens the counter's switches enter, and the waves, the one picture every
starting screen shares, are extracted by `tools/harmony_one_extract_assets.py` as
`activity/*`. An activity's icon is composed from its type's icon onto the patch of the
frame or backdrop it is drawn over (`row_icons.py`).
