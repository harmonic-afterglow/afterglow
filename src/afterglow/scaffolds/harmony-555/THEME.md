# A Harmony 5xx theme

What a 5xx build draws that you can change, as files you can edit. A theme is a folder
of them beside `assets.json`; copy `Example`, give the copy a name, change what you like
and pick it under Remote Settings, Theme. A file a theme leaves out is drawn as the
default draws it.

    images/backdrop.png          96x64  behind the remote's notices, Devices, the
                                        Activities menu and a page with no bottom row
    images/backdrop-more.png     96x64  behind the Remote Assistant, the welcome and the
                                        "devices should be off" screens: the arrow at the
                                        bottom right says there is more
    images/backdrop-ok.png       96x64  behind "Nothing to do": the frame of its OK key
    images/backdrop-yes-no.png   96x64  behind the question that hides the Assistant: the
                                        frames of its Yes and No keys
    images/page.png              96x64  behind a device's or activity's page with keys
                                        at the bottom: the line between the top corners
                                        and the bottom ones
    images/underline.png         96x1   the line under a title: Devices, the Activities
                                        menu and every page of a device or activity
    fonts/galmuri/GalmuriAfterglow7.bdf.gz   the typeface every word is drawn from

A picture can be any PNG. A build turns it grey (transparent counts as white), shrinks it
to fit if it is too big, and dithers it to black and white; a picture drawn black on
white at its size comes through pixel for pixel. A smaller picture is drawn in the middle
of its box. The screen has one colour and no shades, so a photo comes through as a dot
pattern; line art works best.

The words are drawn over the pictures where Logitech's software drew them: a title on the
top row, a key's label in its corner. Keep those places clear, or draw round them.

The typeface is a BDF font drawn on the remote's eleven-row grid: two rows above the
capitals for accents, the capitals on the seven rows above the baseline, and two below it
for descenders. A taller font is cut off. Read from Remote reads a name by what its
letters look like, so a remote written with another typeface reads back its names as "?"
wherever a letter looks like neither Galmuri's nor Logitech's.

A 5xx's configuration holds no Harmony logo and no pictures besides these - in
Logitech's configurations as in ours - so a theme has nothing else to change. What else
the remote shows, its firmware draws.
