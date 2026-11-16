# About the remote pictures

Each remote's `art.svg` is **Logitech's drawing of that remote**, cut out of its user guide
or getting-started guide. `art.json` says where from: `source.guide`, `source.page` and
`source.region`. `tools/remote_art.py` redraws it from that recipe, and it is what the
interface shows when you choose a remote or pick a key. The drawings include Logitech's
wordmark.

They are **not covered by this project's GPL-3.0 licence**. No permission to use them has
been granted by Logitech. If you are redistributing this project, or if Logitech asks,
these are the files to remove.

## Removing or replacing them

The rest of each folder - `profile.json`, and the key outlines and marks in `art.json` -
is this project's own work. Without `art.svg` the interface shows the remote's keys as a
plain grid instead of the picture. A drawing of your own can go in its place as long as the
keys sit where `art.json`'s outlines say they are.
