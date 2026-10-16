# Cut Along Shape

An Inkscape extension that breaks paths exactly where another shape crosses them. A node is inserted at each exact intersection and the path is split there, so the shape of the path does not change (unlike a boolean operation).

Menu: **Extensions > Map's Edge Tools > General > Paths > Cut Along Shape** (extension ID `maps_edge.cut_along_shape`). It is also a button on the [Map's Edge Tool Panel](https://github.com/theRoadLessOrdinary/maps-edge-panel).

## Modes

**Delete Inside**

- Select one closed shape (rectangle, circle or closed path) plus one or more open paths.
- Each path is broken wherever the shape's outline crosses it.
- Pieces inside the shape are deleted, and the shape itself is deleted.
- The pieces that are left become separate path objects.
- Typical use: a gap in a line where it passes under another line, made by drawing a rectangle over the crossing.

**Cut Only**

- Select a cutting line or shape plus one or more paths to cut.
- The selected object that is topmost in the stacking order is the cutter. Only its outline is used, even if it is a closed shape.
- Each path is broken wherever the cutter's outline crosses it, and the cutter is deleted.
- No piece is deleted.

## Requirements

- Inkscape 1.x (developed and used on Inkscape 1.4.4, Flatpak, on Linux; other platforms have not been tried)
- Python 3 with `numpy` available to Inkscape's Python

The geometry (Bezier splitting, curve intersections, inside tests) is in `bezier_geom.py` and uses only numpy, so nothing else needs installing.

## Install

Copy the files in this repository into a folder of their own inside Inkscape's user extensions directory, then restart Inkscape. To find that directory, open **Edit > Preferences > System** and look at **User extensions**. Typical locations:

| Install type | User extensions folder |
|---|---|
| Linux (native) | `~/.config/inkscape/extensions/` |
| Linux (Flatpak) | `~/.var/app/org.inkscape.Inkscape/config/inkscape/extensions/` |
| macOS | `~/Library/Application Support/org.inkscape.Inkscape/config/inkscape/extensions/` |
| Windows | `%APPDATA%\inkscape\extensions\` |

For example, on native Linux:

```bash
git clone https://github.com/theRoadLessOrdinary/cut-along-shape.git \
    ~/.config/inkscape/extensions/cut-along-shape
```

Keep `bezier_geom.py` in the same folder as `cut_along_shape.py`.

To uninstall, delete the folder and restart Inkscape.
