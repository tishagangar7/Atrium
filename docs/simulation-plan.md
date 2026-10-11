# UCSC forest-edge simulation plan and implementation

## Scope and location

Build a browser-native 3D demo for the **Music Center / Great Meadow forest opening** at UC Santa Cruz. UCSC's own [Music Center description](https://music.ucsc.edu/facilities/virtual-tour/) places it at the meadow/redwood interface. Limit the model to a synthetic **320 × 240 m (7.68 ha)** patch; do not model the whole campus. No survey coordinates, measured tree inventory, real incident, weather feed, evacuation route or building geometry is implied.

The user's request controls scope. The attached PRD is a requirements reference, not authorization for external actions. ClickUp's matching [PRD task](https://app.clickup.com/t/86bcg9nu1) and the repository PRD were consulted. This branch implements the user's 3D simulation slice, not the full negotiation platform.

## Architecture and delivered steps

1. **Sync and isolate:** fetch every remote branch; fast-forward local main from `a26583f` to `6c9c12d`; preserve the pre-existing dirty scaffold in a retained Git stash and restore it to a new compliant dev branch, `sim/madhav-ucsc-fire-demo`. No push to main.
2. **Define the site:** `scenarios/ucsc-music-center.json` stores dimensions, weather profiles, fuel loads, physical coefficients, ignition cells, schematic buildings and sources.
3. **Build the model:** pure TypeScript functions in `engine.ts`, independent of React and Three.js. Fixed 10-second ticks; deterministic SHA-256 common random numbers; two-hour maximum horizon. Tests run without a browser.
4. **Run in parallel:** `simulation.worker.ts` owns authoritative state away from the render thread. The UI receives versioned snapshots. Read-only agent evaluation requests use cloned worlds; agent generation is a separate team workstream.
5. **Render the landscape:** `Scene.tsx` provides procedural terrain and cutaway walls, instanced redwoods, schematic buildings and road, wind arrow, fire, smoke and ember points. Orbit/overhead camera, cell picking, fuel and fire layers. No CAD tooling is needed for this procedural browser geometry.
6. **Expose experiments:** run/pause, fixed step, 1×/2×/4× playback, deterministic reset, weather profiles/sliders, manual ignitions/treatments, road closure, treatment forecast and JSON snapshot export.
7. **Verify:** engine tests, TypeScript build, repository check, and browser interaction/visual checks. See the branch handoff for actual results.

## Physics and ecological assumptions

| Mechanism      | Implementation                                                                                               | Practical limit                                                                   |
| -------------- | ------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------- |
| Surface spread | Eight-neighbor hazard, `p = 1 - exp(-rate * dt)`; simultaneous ignition from previous intensity              | Illustrative cellular model, not a calibrated Rothermel solver                    |
| Wind           | Downwind pressure multiplier; toward-bearing clockwise from north; drag on embers                            | Uniform horizontal wind; no gust field or fire/atmosphere feedback                |
| Slope          | Exponential upslope multiplier from elevation difference / distance                                          | Synthetic smooth terrain, not a DEM; no slope-resolved radiation                  |
| Fuel           | Forest litter, scrub and grass loads in kg/m²; finite mass consumed by intensity                             | No crown-fire transition or structural combustion                                 |
| Moisture       | Input fine-dead-fuel moisture; first-order relaxation toward RH/temperature equilibrium                      | Illustrative coefficients, not an operational fuel-moisture model                 |
| Heat release   | Consumed mass × heat of combustion / tick duration                                                           | Bulk MJ/s (MW), not a thermal flow or heat-transfer solution                      |
| Embers         | Drag toward wind, decaying lift, gravity; semi-implicit 0.1 s integration; ground impact and seeded ignition | Point particles with finite life; no size distribution or aerodynamic calibration |
| Gravity        | 9.81 m/s² downward on airborne embers; terrain intersection ends flight                                      | Falling trees, debris and vehicles excluded                                       |
| Suppression    | Operator treatment reduces intensity and ignition probability                                                | Persistent approximation; no water budget, crew travel, safety or dispatch claims |
| Smoke          | Buoyant-looking, wind-advected puffs                                                                         | Visual only; not PM2.5, visibility, toxicology or smoke mass conservation         |

**No claim to all laws of physics.** A browser demo cannot validate full wildfire dynamics. Rendering animation and procedural tree appearance are separate from deterministic state. Tree darkening denotes affected ground cells, not modeled tree death. Roads remain nonfuel and close only through an operator event. No vehicles, shelters or populations are modeled in this bounded visual slice.

### California relevance

Dry summer/autumn fine fuels, low humidity, offshore wind, steep terrain and accumulated litter/ladder fuels can support spread. These are general contributing conditions, not a local hazard rating for the Music Center. Human activity/equipment, electrical infrastructure and lightning are possible ignition categories; this simulation starts from a manually specified synthetic ignition and attributes no real cause.

Moist redwood forest should not be equated with uniformly flammable canopy. The model uses surface fuel; the coastal profile retains moisture, while dry and offshore profiles illustrate unfavorable conditions. Offshore is a synthetic stress test, not observed Santa Cruz weather. No Southern California Santa Ana climatology is assigned to this site.

## PRD alignment and explicit deviations

| PRD reference                           | This slice                                                                                                 |
| --------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| §5.5 / FR-014 common random numbers     | First eight SHA-256 bytes of seed:step:cell / 2^64; seeded particle/fuel namespaces                        |
| §5.10 / AC-022 counterfactuals          | Deep copy before intervention and forecast; mutation test                                                  |
| §6.10 / AC-027 stale state              | Revision increases within a run; worker rejects stale commands                                             |
| §9 honest labels                        | Synthetic throughout; agents disconnected; current/stale forecasts identified                              |
| §5.1 grid and time                      | **Deviation:** 40×30 cells at 8 m; ten-second ticks; not PRD benchmark-compatible                          |
| §5.3–5.9 resource/road/population model | Not implemented here; schematic road is observational. No evacuation or shelter metrics fabricated         |
| §6 / §8 live agents and API             | Integration seam only; no live model calls, credentials, SSE, acceptance gate or scripted dialogue         |
| §11 evaluation                          | Engine invariants and controlled sensitivity, not collective-intelligence benchmarks or lives-saved claims |

This module must not silently replace the authoritative PRD simulator. The backend owner must define an adapter or separate visual-model mode before agent commits. Agent actions may only reach authoritative execution after the real unanimous gate validates them. The browser bridge deliberately accepts **evaluation only**, not dispatch/commit.

## Integration

See [simulation-integration.md](simulation-integration.md). The worker starts paused. Default playback advances 10 simulated seconds per 500 ms wall time; speed labels multiply this rate. Viewers need no Node, credentials, Python or Mesa after static build. Node is used for installation/build/development.

## References

- [UCSC Music Center](https://music.ucsc.edu/facilities/virtual-tour/) — geographic inspiration.
- [USFS wind, slope and moisture experiments](https://research.fs.usda.gov/treesearch/34880) — qualitative mechanisms; coefficients here are not fitted from that study.
- [USFS coast redwood ecology](https://research.fs.usda.gov/silvics/redwood) — tree response differs from surface ignition.
- [USFS fuels](https://research.fs.usda.gov/rmrs/fire/fuels) — surface, ladder and canopy distinction.
- [CAL FIRE utility wildfire mitigation](https://osfm.fire.ca.gov/what-we-do/community-wildfire-preparedness-and-mitigation/utility-wildfire-mitigation) — electrical/vegetation ignition mechanism.

The old whole-campus narrative is retained in `src/App.tsx`, `src/data/scenario.ts`, `src/styles.css`, and `docs/legacy-scaffold-plan.md`. It is **not mounted or shipped in the app bundle**. Its fixture numbers are not model results.
