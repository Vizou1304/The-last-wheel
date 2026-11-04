# The Last Wheel

A frozen low-poly colony kept alive by a real hamster. Live: https://thelastwheel.app

Squeektoshi's wheel (Squeekchain) is the city's only heat source. A heat reserve fills when the wheel turns and
drains with the cold; at zero the colony hibernates and frost sets in. Nobody plays: everyone watches the town hold on.

## How it uses Squeekchain

Read-only. No wallet, no keys, nothing to sign. The server polls the public Squeekchain API (Sepolia testnet):

| Endpoint | Used for |
|---|---|
| `/v1/status` | work units, rpm, counter status (ACTIVE / IDLE), freshness, provenance, distance today |
| `/v1/settlements?range=24h` | recent settlements, linked to their Sepolia transactions ("Verify on Sepolia") |
| `/v1/measurement/stats` | pace statistics (`tools/fetch_pace.py`, to calibrate the game's content length) |

Safety rules: an unknown or unavailable value is never treated as zero; if the signal is lost, the counter faults,
or the data does not come from real hardware, the colony pauses instead of inventing numbers; catch-up work after
an outage is released progressively, never in one burst. In `--sim` mode the page says "Simulation".

## Run it

Python 3.9+ standard library only (no dependencies). The 3D scene runs in the visitor's browser (three.js, bundled in `web/vendor/`).

```bash
python server/main.py --sim --speed 60   # test city with a fake hamster (1 simulated hour per minute)
python server/main.py                    # the real city, following the real hamster
```

Open http://localhost:8080. Saved state goes to `data/` (not versioned). Useful environment variables:
`TLW_HOST`, `TLW_PORT`, `TLW_DATA`, `SQUEEK_API`, `SQUEEK_SETTLEMENTS`.

## Layout

- `server/` simulation, live feed, chronicle, small HTTP server (read-only, GET only)
- `content/` buildings, phrases and balance (`config.json`, including `wu_scale`)
- `web/` the page (`city3d.js`, `hud.js`) and the exported scene `web/assets/city.glb`
- `tools/blender_city.py` Blender script that builds the 3D city (the 3D source); `audit_scene.py` checks overlaps;
  `check_balance.py`, `fetch_pace.py`, `checkup.py` are balance and health tools
- `PI_SETUP.md` step-by-step guide to run it 24/7 on a Raspberry Pi (written in French)

## Notes

The scene is exported from Blender as glTF without vertex colors. Everything the visitor sees about the chain is
read-only and links to a public explorer.

MIT license (see `LICENSE`).
