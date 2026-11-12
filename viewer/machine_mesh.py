#!/usr/bin/env python3
"""Open5x-Maschinenmodell für gcode_viewer.html: STLs aus open5x_machine_stl/ -> open5x_machine_stl/machine_mesh.js.

Der Viewer wird per Doppelklick (file://) geöffnet, dort darf er keine Dateien nachladen; ein klassisches
<script src> geht aber. Deshalb stehen die Netze hier fertig platziert, verschweißt, auf 16 bit quantisiert und
gzip-komprimiert als base64 in einer JS-Datei. Nach geänderten STLs einfach neu laufen lassen:

    python machine_mesh.py

Maschinen-KS (wie der Viewer): Ursprung = Plattenmitte auf der Oberfläche = Schnitt von B- und C-Achse,
X rechts, Y hinten, Z oben, B um Y, C um Z, Düse senkrecht.

* aussen3 / innen3 / z-steg liegen im Baugruppen-KS des Tisches: Ursprung wie oben, B-Achse = STL-X, Flanschlager
  (Schwenkantrieb) bei STL-X < 0. Rz(-90°) legt die B-Achse auf Maschinen-Y, Flansch hinten (+Y), Wellenlager vorn
  (passt zum Screenshot und zur Kinematik des Viewers).
* Extruder.stl (Prusa-Kopf) ist Y-oben exportiert (Düse -Y, Front +Z, X-Schlitten -Z). Rx(+90°) stellt ihn auf,
  danach liegt die Düsenspitze (tiefster Punkt) im Ursprung der Kopf-Gruppe.
Das Lager zwischen z-steg und innen ist kein STL, der Viewer zeichnet es selbst (MACH.bearing).
"""
import base64
import gzip
import json
import struct
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SRC = HERE / 'open5x_machine_stl'
OUT = SRC / 'machine_mesh.js'

R_TABLE = np.array([[0, 1, 0], [-1, 0, 0], [0, 0, 1]], float)    # Rz(-90°): (x, y, z) -> (y, -x, z)
R_HEAD = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float)     # Rx(+90°): (x, y, z) -> (x, -z, y)

# Name, Datei, Glied der Kette im Viewer (carY = Y-Schlitten, cradleB = Schwenk B, tableC = Drehung C, head = Kopf)
PARTS = [
    ('aussen', 'aussen3.stl', 'carY', R_TABLE),
    ('innen', 'innen3.stl', 'cradleB', R_TABLE),
    ('zsteg', 'z-steg.stl', 'tableC', R_TABLE),
    ('extruder', 'Extruder.stl', 'head', R_HEAD),
]


def read_stl(path):
    b = path.read_bytes()
    n = struct.unpack('<I', b[80:84])[0] if len(b) >= 84 else 0
    if n and 84 + 50 * n == len(b):
        a = np.frombuffer(b, dtype=np.dtype([('n', '<f4', 3), ('v', '<f4', (3, 3)), ('a', '<u2')]), count=n, offset=84)
        return a['v'].astype(np.float64)
    import re
    v = np.array(re.findall(rb'vertex\s+(\S+)\s+(\S+)\s+(\S+)', b), dtype=np.float64)
    return v[:len(v) - len(v) % 3].reshape(-1, 3, 3)


def pack(tri):
    """Dreiecke -> verschweißte, quantisierte Netze (Positionen uint16 je Achse getrennt, Indizes uint16/uint32)."""
    P = tri.reshape(-1, 3)
    lo, hi = P.min(0), P.max(0)
    span = np.maximum(hi - lo, 1e-9)
    q = np.rint((P - lo) / span * 65535).astype(np.uint16)
    uq, inv = np.unique(q, axis=0, return_inverse=True)
    idx = inv.reshape(-1, 3)
    idx = idx[(idx[:, 0] != idx[:, 1]) & (idx[:, 1] != idx[:, 2]) & (idx[:, 0] != idx[:, 2])]  # entartete raus
    it = np.uint16 if len(uq) <= 65535 else np.uint32
    raw = np.ascontiguousarray(uq.T).tobytes() + idx.astype(it).tobytes()
    return {
        'nv': int(len(uq)), 'nt': int(len(idx)), 'i32': it is np.uint32,
        'min': [round(float(x), 4) for x in lo], 'span': [round(float(x), 4) for x in span],
        'b64': base64.b64encode(gzip.compress(raw, 9, mtime=0)).decode('ascii'),
    }


def main():
    parts = []
    for name, fn, link, R in PARTS:
        tri = read_stl(SRC / fn) @ R.T
        info = ''
        if link == 'head':
            P = tri.reshape(-1, 3)
            tip = P[P[:, 2] < P[:, 2].min() + 0.05].mean(0)              # Düsenspitze = tiefster Punkt
            tri = tri - tip
            info = f'  Düsenspitze (STL) {np.round(tip @ R, 2).tolist()}'
        p = pack(tri)
        p.update(name=name, file=fn, link=link)
        parts.append(p)
        P = tri.reshape(-1, 3)
        print(f'{name:9s} {link:8s} {len(tri):6d} Dreiecke -> {p["nv"]:6d} Punkte, {len(p["b64"]) / 1e6:.2f} MB base64, '
              f'x {P[:, 0].min():.1f}..{P[:, 0].max():.1f}  y {P[:, 1].min():.1f}..{P[:, 1].max():.1f}  '
              f'z {P[:, 2].min():.1f}..{P[:, 2].max():.1f}{info}')
    OUT.write_text('// erzeugt von tools/machine_mesh.py aus den STLs in diesem Ordner - nicht von Hand ändern\n'
                   'window.OPEN5X_MACHINE = ' + json.dumps({'v': 1, 'parts': parts}, separators=(',', ':')) + ';\n',
                   encoding='utf-8')
    print(f'{OUT} ({OUT.stat().st_size / 1e6:.2f} MB)')


if __name__ == '__main__':
    sys.exit(main())
