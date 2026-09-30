# Brooklyn Commons — point cloud map viewer

The prior map an autonomous go-kart localises against at Brooklyn Commons, and
the lanelet route it is allowed to drive, published as a browser-based 3D viewer.

* `index.html` — landing page
* `viewer.html` — the Potree viewer
* `pointclouds/brooklyn_commons/` — Potree 2.0 octree, BROTLI encoded
* `route.json` — lanelet bounds and centrelines, extracted from `lanelet2_map_split.osm`
* `tools/pcd_to_las.py` — the conversion step, so this is reproducible

## The map

| | |
|---|---|
| points | 7,497,016 |
| extent | 241.6 × 175.9 m, z −29.2 → 33.9 m |
| median point spacing | 4.1 cm (exact NN in a 20 × 20 m box on the route) |
| frame | local metres (`map_projector_info.yaml`: `projector_type: Local`) |
| route | 4 lanelets, 277.4 m of centreline, 10 km/h limit |

## Rebuilding the octree

`PotreeConverter` reads LAS/LAZ, not PCD, so there are two steps. The converter
here needs only `numpy` and `matplotlib` — it writes LAS 1.2 point format 3
directly rather than pulling in `laspy`.

```bash
python3 tools/pcd_to_las.py \
  --pcd /path/to/pointcloud_map.pcd \
  --out work/brooklyn_commons.las

PotreeConverter work/brooklyn_commons.las \
  -o pointclouds/brooklyn_commons --encoding BROTLI -m poisson
```

7.5 M points indexes in about 2 s and produces a 66 MB `octree.bin.png` — under
GitHub's 100 MB per-file limit, so no chunking is needed.

## Testing locally

Potree streams the octree with HTTP range requests. **Python's stock
`http.server` does not serve 206 responses**, and the failure is silent — the
viewer just never fills in. Use a range-capable server:

```bash
pip install rangehttpserver
python3 -m RangeHTTPServer 8101
```

## Notes for anyone forking this

* `.nojekyll` at the root is required, or Jekyll mangles the octree paths.
* Do not put the cloud in Git LFS. GitHub Pages does not serve LFS content and
  the viewer breaks.
* Potree vendors a Cesium build containing a live Mapbox token, which GitHub
  push protection rejects outright. `libs/Cesium` is not included here; Potree
  only references it from a comment in its glTF loader.

Point cloud and lanelet map © ASAS Labs. Rendered with
[Potree](https://github.com/potree/potree).
