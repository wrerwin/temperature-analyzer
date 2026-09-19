#!/usr/bin/env python3
"""Build data/conus-states.json: simplified state boundaries (lon/lat GeoJSON) for the Map tab.

Source: us-atlas states-10m.json (TopoJSON of US Census cartographic boundaries, public domain).
Decodes the TopoJSON, keeps the contiguous states + DC, simplifies each arc (Douglas–Peucker) and
rounds to 2 decimals so the whole file is < 100 KB. Also emits a merged national outline is not needed:
the page draws each state and the union reads as the country.

    python3 analysis/make_outline.py
"""
import json, os, sys
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), 'data', 'conus-states.json')
URL = 'https://cdn.jsdelivr.net/npm/us-atlas@3/states-10m.json'
SKIP = {'02': 'AK', '15': 'HI', '72': 'PR', '78': 'VI', '66': 'GU', '60': 'AS', '69': 'MP'}


def dp(points, tol):
    """Douglas–Peucker on a list of (x, y)."""
    if len(points) < 3:
        return points
    (x0, y0), (x1, y1) = points[0], points[-1]
    dx, dy = x1 - x0, y1 - y0
    L2 = dx * dx + dy * dy
    best, bi = -1.0, 0
    for i in range(1, len(points) - 1):
        px, py = points[i]
        if L2 == 0:
            d2 = (px - x0) ** 2 + (py - y0) ** 2
        else:
            t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / L2))
            d2 = (px - (x0 + t * dx)) ** 2 + (py - (y0 + t * dy)) ** 2
        if d2 > best:
            best, bi = d2, i
    if best > tol * tol:
        return dp(points[:bi + 1], tol)[:-1] + dp(points[bi:], tol)
    return [points[0], points[-1]]


def main():
    tol = float(sys.argv[1]) if len(sys.argv) > 1 else 0.02
    topo = requests.get(URL, timeout=60).json()
    sx, sy = topo['transform']['scale']; tx, ty = topo['transform']['translate']
    arcs = []
    for arc in topo['arcs']:
        x = y = 0; pts = []
        for dx, dy in arc:
            x += dx; y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append([(round(a, 2), round(b, 2)) for a, b in dp(pts, tol)])

    def ring(idx_list):
        out = []
        for i in idx_list:
            a = arcs[i] if i >= 0 else arcs[~i][::-1]
            out += a if not out else a[1:]
        return out

    feats = []
    for g in topo['objects']['states']['geometries']:
        if g['id'] in SKIP:
            continue
        polys = [g['arcs']] if g['type'] == 'Polygon' else g['arcs']
        coords = [[ring(r) for r in p] for p in polys]
        feats.append({'type': 'Feature', 'id': g['id'], 'properties': {'name': g['properties']['name']},
                      'geometry': {'type': 'MultiPolygon', 'coordinates': coords}})
    fc = {'type': 'FeatureCollection', 'source': 'us-atlas states-10m (US Census, public domain), simplified', 'features': feats}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(fc, open(OUT, 'w'), separators=(',', ':'))
    print(f'{len(feats)} states, {os.path.getsize(OUT)/1e3:.0f} KB', file=sys.stderr)


if __name__ == '__main__':
    main()
