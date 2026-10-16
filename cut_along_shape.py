#!/usr/bin/env python3
"""
Cut Along Shape

Two modes, picked via the Mode dropdown:

- Delete Inside: select one closed shape (rectangle, circle, or any closed
  path) plus one or more open paths. Every place the shape's boundary
  crosses a selected path gets a node inserted at the EXACT intersection
  (no shape distortion, unlike a boolean op), the path is broken there,
  whichever resulting piece(s) fall inside the shape are discarded, and the
  shape itself is deleted. Surviving pieces become separate path objects.
  Typical use: showing one line passing "under" another in a diagram (e.g.
  a zig-zag stitch crossing under another line) by cutting a gap where a
  covering rectangle sits over the crossing.

- Cut Only: select a cutting line or object plus one or more paths to cut.
  Whichever selected object is TOPMOST in the document's z-order is the
  cutter (it can be an open line or a closed shape - either way, only its
  outline is used, never a fill/inside test). Every place the cutter's
  outline crosses a selected path gets a node inserted at the exact
  intersection and the path is broken there, and the cutter itself is
  deleted afterward. Unlike Delete Inside, no cut piece is discarded - this
  just segments the path(s), it doesn't reroute anything the way a boolean
  op would.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import inkex
from inkex import EffectExtension, ShapeElement, PathElement
from inkex.paths import CubicSuperPath

import bezier_geom as bg

CLOSE_TOL = 1e-6


def make_csp(subpaths):
    """Build a CubicSuperPath directly from raw subpath node lists, bypassing
    the command-parsing append() logic (which we don't need since we already
    have the exact [in, pt, out] triples)."""
    obj = CubicSuperPath.__new__(CubicSuperPath)
    list.__init__(obj, subpaths)
    return obj


def subpath_closed(subpath, tol=CLOSE_TOL):
    if len(subpath) < 2:
        return False
    p0, p1 = subpath[0][1], subpath[-1][1]
    return abs(p0[0] - p1[0]) < tol and abs(p0[1] - p1[1]) < tol


def is_closed(csp):
    return len(csp) > 0 and all(subpath_closed(sp) for sp in csp)


def world_superpath(el):
    """This element's geometry, transformed into document/root coordinates."""
    path = el.path.to_absolute()
    path = path.transform(el.composed_transform())
    return path.to_superpath()


def local_superpath(el):
    """This element's geometry in its own (untransformed) coordinate space,
    i.e. what its 'd' attribute actually encodes."""
    return el.path.to_absolute().to_superpath()


def segment_points(subpath, i):
    """4 bezier control points for the segment from node i to node i+1."""
    p0 = subpath[i][1]
    p1 = subpath[i][2]
    p2 = subpath[i + 1][0]
    p3 = subpath[i + 1][1]
    return (tuple(p0), tuple(p1), tuple(p2), tuple(p3))


def flatten_shape_rings(shape_csp):
    rings = []
    for subpath in shape_csp:
        pts = []
        for i in range(len(subpath) - 1):
            p0, p1, p2, p3 = segment_points(subpath, i)
            pts.extend(bg.flatten_cubic(p0, p1, p2, p3, n=16)[:-1])
        if pts:
            rings.append(pts)
    return rings


def point_inside_shape(pt, rings):
    inside = False
    for ring in rings:
        if bg.point_in_polygon(pt, ring):
            inside = not inside
    return inside


def find_cuts_for_segment(world_seg, shape_csp):
    """t-values (0..1, along world_seg) where the shape boundary crosses it."""
    hits = []
    for shape_subpath in shape_csp:
        for j in range(len(shape_subpath) - 1):
            shape_seg = segment_points(shape_subpath, j)
            hits.extend(bg.cubic_intersect(world_seg, shape_seg))
    merged = bg.dedup_intersections(hits)
    ts = sorted(t1 for t1, _t2, _pt in merged if 1e-7 < t1 < 1 - 1e-7)
    # also keep near-0/near-1 hits (crossing right at a node) but avoid
    # duplicating a cut that coincides with an existing node
    for t1, _t2, _pt in merged:
        if t1 <= 1e-7 or t1 >= 1 - 1e-7:
            pass  # crossing exactly at an existing node: no new node needed
    return ts


def rebuild_subpath_with_cuts(local_subpath, cuts_by_seg):
    """Returns (new_nodes, break_after_indices)."""
    first = local_subpath[0]
    new_nodes = [[list(first[0]), list(first[1]), list(first[2])]]
    break_after = []

    for i in range(len(local_subpath) - 1):
        p0, p1, p2, p3 = segment_points(local_subpath, i)
        cur = (p0, p1, p2, p3)
        t_offset = 0.0
        for t in cuts_by_seg.get(i, []):
            t_local = (t - t_offset) / (1 - t_offset) if (1 - t_offset) > 1e-12 else 0.0
            t_local = min(max(t_local, 0.0), 1.0)
            left, right = bg.split_cubic(*cur, t_local)
            new_nodes[-1][2] = list(left[1])
            new_nodes.append([list(left[2]), list(left[3]), list(right[1])])
            break_after.append(len(new_nodes) - 1)
            cur = right
            t_offset = t
        new_nodes[-1][2] = list(cur[1])
        nxt = local_subpath[i + 1]
        new_nodes.append([list(cur[2]), list(nxt[1]), list(nxt[2])])

    return new_nodes, break_after


def split_into_pieces(new_nodes, break_after):
    bounds = [0] + break_after + [len(new_nodes) - 1]
    pieces = []
    for k in range(len(bounds) - 1):
        a, b = bounds[k], bounds[k + 1]
        if b - a >= 1:
            piece = [[list(n[0]), list(n[1]), list(n[2])] for n in new_nodes[a:b + 1]]
            pieces.append(piece)
    return pieces


class CutAlongShape(EffectExtension):
    def add_arguments(self, pars):
        pars.add_argument("--mode", type=str, default="delete_inside")

    def effect(self):
        sel = list(self.svg.selection.get(ShapeElement))
        if len(sel) < 2:
            raise inkex.AbortExtension(
                "Select the shape/line to cut with and at least one path to cut, then run again."
            )

        if self.options.mode == "cut_only":
            self.effect_cut_only(sel)
        else:
            self.effect_delete_inside(sel)

    def effect_delete_inside(self, sel):
        shapes = []
        targets = []
        for el in sel:
            csp = world_superpath(el)
            if is_closed(csp):
                shapes.append((el, csp))
            else:
                targets.append(el)

        if len(shapes) != 1:
            raise inkex.AbortExtension(
                f"Expected exactly one closed shape in the selection, found {len(shapes)}."
            )
        if not targets:
            raise inkex.AbortExtension(
                "Select at least one open path to cut, in addition to the closed shape."
            )

        shape_el, shape_csp = shapes[0]
        shape_rings = flatten_shape_rings(shape_csp)

        any_cut = False
        for target_el in targets:
            if self.process_target(target_el, shape_csp, shape_rings):
                any_cut = True

        shape_el.delete()

        if not any_cut:
            inkex.utils.errormsg(
                "No intersections found between the shape and the selected path(s) "
                "- nothing was cut. The shape was still deleted."
            )

    def effect_cut_only(self, sel):
        # Topmost-in-z-order selected element is the cutter; everything else
        # selected is a target to be cut. Document order == paint order, so
        # the last selected element encountered while walking the tree is on
        # top, regardless of grouping/nesting.
        order = {id(el): i for i, el in enumerate(self.svg.iter())}
        cutter_el = max(sel, key=lambda el: order.get(id(el), -1))
        targets = [el for el in sel if el is not cutter_el]

        if not targets:
            raise inkex.AbortExtension(
                "Select the cutting line/object plus at least one path to cut, then run again."
            )

        cutter_csp = world_superpath(cutter_el)

        any_cut = False
        for target_el in targets:
            if self.process_target(target_el, cutter_csp, None, keep_all=True):
                any_cut = True

        cutter_el.delete()

        if not any_cut:
            inkex.utils.errormsg(
                "No intersections found between the cutting object and the selected path(s) "
                "- nothing was cut. The cutter was still deleted."
            )

    def process_target(self, target_el, shape_csp, shape_rings, keep_all=False):
        w_csp = world_superpath(target_el)
        l_csp = local_superpath(target_el)
        transform = target_el.composed_transform()

        any_cut = False
        kept_pieces = []

        for si, l_subpath in enumerate(l_csp):
            w_subpath = w_csp[si]
            cuts_by_seg = {}
            for i in range(len(w_subpath) - 1):
                w_seg = segment_points(w_subpath, i)
                ts = find_cuts_for_segment(w_seg, shape_csp)
                if ts:
                    cuts_by_seg[i] = ts

            if not cuts_by_seg:
                kept_pieces.append(l_subpath)
                continue

            any_cut = True
            new_nodes, break_after = rebuild_subpath_with_cuts(l_subpath, cuts_by_seg)
            pieces = split_into_pieces(new_nodes, break_after)

            for piece in pieces:
                if keep_all:
                    kept_pieces.append(piece)
                    continue
                p0, p1, p2, p3 = segment_points(piece, 0)
                mid_local = bg.split_point(p0, p1, p2, p3, 0.5)
                mid_world = transform.apply_to_point((mid_local[0], mid_local[1]))
                if not point_inside_shape((mid_world.x, mid_world.y), shape_rings):
                    kept_pieces.append(piece)

        if not any_cut:
            return False

        parent = target_el.getparent()
        index = list(parent).index(target_el)
        style = target_el.get("style")
        base_id = target_el.get_id()

        for n, piece in enumerate(kept_pieces):
            new_el = PathElement()
            new_el.path = make_csp([piece]).to_path()
            if style is not None:
                new_el.set("style", style)
            if target_el.get("transform") is not None:
                new_el.set("transform", target_el.get("transform"))
            new_el.set_id(f"{base_id}-{n + 1}")
            parent.insert(index, new_el)
            index += 1

        target_el.delete()
        return True


if __name__ == "__main__":
    CutAlongShape().run()
