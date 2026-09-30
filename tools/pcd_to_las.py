#!/usr/bin/env python3
"""Convert an Autoware pointcloud_map.pcd to LAS 1.2 so PotreeConverter can index it.

PotreeConverter 2.x reads LAS/LAZ only (it chunks via laszip). LAS point format 3
carries xyz + intensity + RGB, which is what gives the Potree viewer its three
colour modes: surface (the RGB baked here), intensity, and elevation.

Adapted from hudsonMap's ~/hudson/present/pcd_to_las.py with two dependencies
removed, deliberately:

  * laspy  -- replaced by a hand-rolled LAS 1.2 writer below. laspy was not
              installed on either machine and the format is 227 header bytes
              plus a packed 34-byte record; adding a dependency to write that
              is a worse trade than writing it.
  * mapio  -- replaced by parsing the PCD header directly. It is ASCII up to
              the DATA line, so this works on any binary xyzi PCD.

    python3 pcd_to_las.py --pcd <in.pcd> --out out/bc.las
"""
import argparse
import os
import sys

import numpy as np

LAS_HEADER_SIZE = 227
LAS_POINT_SIZE = 34          # point data record format 3


def read_pcd_xyzi(path):
    """Parse a binary PCD with FIELDS x y z intensity, all float32."""
    with open(path, 'rb') as f:
        fields = sizes = types = counts = None
        n = None
        while True:
            line = f.readline()
            if not line:
                raise ValueError('hit EOF before DATA line')
            tok = line.decode('ascii', 'replace').split()
            if not tok:
                continue
            key = tok[0].upper()
            if key == 'FIELDS':
                fields = tok[1:]
            elif key == 'SIZE':
                sizes = [int(v) for v in tok[1:]]
            elif key == 'TYPE':
                types = tok[1:]
            elif key == 'COUNT':
                counts = [int(v) for v in tok[1:]]
            elif key == 'POINTS':
                n = int(tok[1])
            elif key == 'DATA':
                if tok[1].lower() != 'binary':
                    raise ValueError(f'only DATA binary is supported, got {tok[1]}')
                offset = f.tell()
                break

    if fields != ['x', 'y', 'z', 'intensity']:
        raise ValueError(f'expected FIELDS x y z intensity, got {fields}')
    if sizes != [4, 4, 4, 4] or types != ['F'] * 4 or (counts and counts != [1] * 4):
        raise ValueError(f'expected 4x float32, got SIZE={sizes} TYPE={types}')

    a = np.memmap(path, dtype=np.float32, mode='r', offset=offset, shape=(n, 4))
    return np.array(a[:, :3]), np.array(a[:, 3])


def write_las12_fmt3(path, xyz, intensity_u16, rgb_u16, scale=0.001):
    """Write LAS 1.2, point data record format 3. Packed, little-endian."""
    n = len(xyz)
    offsets = np.floor(xyz.min(axis=0)).astype(np.float64)
    mins = xyz.min(axis=0).astype(np.float64)
    maxs = xyz.max(axis=0).astype(np.float64)

    # Quantised coordinates must fit int32: at 1 mm that is +/-2147 km. Fine.
    q = np.rint((xyz.astype(np.float64) - offsets) / scale).astype(np.int32)

    rec = np.zeros(n, dtype=np.dtype({
        'names':   ['X', 'Y', 'Z', 'intensity', 'flags', 'classification',
                    'scan_angle', 'user_data', 'point_source_id', 'gps_time',
                    'red', 'green', 'blue'],
        'formats': ['<i4', '<i4', '<i4', '<u2', 'u1', 'u1',
                    'i1', 'u1', '<u2', '<f8', '<u2', '<u2', '<u2'],
        'offsets': [0, 4, 8, 12, 14, 15, 16, 17, 18, 20, 28, 30, 32],
        'itemsize': LAS_POINT_SIZE,
    }))
    rec['X'], rec['Y'], rec['Z'] = q[:, 0], q[:, 1], q[:, 2]
    rec['intensity'] = intensity_u16
    rec['flags'] = 0b00001001          # return 1 of 1
    rec['classification'] = 1          # unclassified
    rec['red'], rec['green'], rec['blue'] = rgb_u16[:, 0], rgb_u16[:, 1], rgb_u16[:, 2]

    hdr = bytearray(LAS_HEADER_SIZE)
    def put(off, fmt, *vals):
        hdr[off:off + np.dtype(fmt).itemsize * len(vals)] = \
            np.array(vals, dtype=fmt).tobytes()

    hdr[0:4] = b'LASF'
    put(24, 'u1', 1)                   # version major
    put(25, 'u1', 2)                   # version minor
    hdr[58:58 + 32] = b'pcd_to_las.py (gokart)'.ljust(32, b'\0')
    put(94, '<u2', LAS_HEADER_SIZE)
    put(96, '<u4', LAS_HEADER_SIZE)    # offset to point data
    put(100, '<u4', 0)                 # number of VLRs
    put(104, 'u1', 3)                  # point data format
    put(105, '<u2', LAS_POINT_SIZE)
    put(107, '<u4', n)
    put(111, '<u4', n, 0, 0, 0, 0)     # points by return
    put(131, '<f8', scale, scale, scale)
    put(155, '<f8', *offsets)
    put(179, '<f8', maxs[0], mins[0], maxs[1], mins[1], maxs[2], mins[2])

    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'wb') as f:
        f.write(bytes(hdr))
        rec.tofile(f)
    return os.path.getsize(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pcd', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()

    xyz, inten = read_pcd_xyzi(a.pcd)
    n = len(xyz)
    print(f'  {n:,} points', flush=True)

    # Bake RGB exactly as hudsonMap did: REFLECTIVITY drives luminance, because
    # that is what carries paving joints, kerbs and markings; ELEVATION only
    # tints. A full rainbow ramp on Z photographs well and buries the detail the
    # scan actually measured. The viewer still offers pure elevation as a mode.
    z = xyz[:, 2].astype(np.float32)
    lo, hi = np.percentile(z, [2, 97])
    r = inten.astype(np.float32)
    rl, rh = np.percentile(r, [4, 96])
    print(f'  z    p2..p97   {lo:7.2f} .. {hi:7.2f} m')
    print(f'  int  p4..p96   {rl:7.1f} .. {rh:7.1f}')

    from matplotlib import cm
    lum = np.clip((r - rl) / max(rh - rl, 1e-6), 0, 1) ** 0.7 * 0.78 + 0.22
    h = np.clip((z - lo) / max(hi - lo, 1e-6), 0, 1)
    tint = cm.cividis(h)[:, :3] * 0.55 + 0.45
    rgb = np.clip(tint * lum[:, None] * 1.25, 0, 1)
    del tint, h

    iu16 = (np.clip((r - rl) / max(rh - rl, 1e-6), 0, 1) * 65535).astype(np.uint16)
    rgb16 = (rgb * 65535).astype(np.uint16)
    del rgb

    sz = write_las12_fmt3(a.out, xyz, iu16, rgb16)
    print(f'  wrote {a.out}  ({sz/1e6:.1f} MB)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
