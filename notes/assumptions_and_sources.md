# Assumptions and sources

Every number in the model is listed here. "Assumption" means no source backs it. Albin's confirmations from the warehouse are marked "Albin's recollection". No company data is used anywhere.

Status column: **open** = still to be confirmed or checked.

## Tote

| Parameter | Value | Why | Source | Varied in sensitivity? | Status |
|---|---|---|---|---|---|
| Max load | 35 kg | Upper limit of what Cuby shuttles carry | SSI Schäfer Cuby product page: https://www.ssi-schaefer.com/da-dk/produkter/lagerloesninger-optimering/fuldautomatiserede-lagerloesninger/storage-shuttle-systems/ssi-cuby-1229028 | Yes: 25 / 30 / 35 kg | |
| Inner dimensions | 560 × 360 × 200 mm | Common 600 × 400 mm footprint tote | Assumption | Yes: two heights (value of second height open) | open |
| Fill-height margin | 0 mm | Goods may fill up to the rim | Assumption | Not yet decided | open |

## Packing rule

| Item | Value | Why | Source |
|---|---|---|---|
| Layout | One SKU per tote, one orientation per tote, regular grid | Simple rule a screen could show a worker | Assumption. A simplified heuristic, not full 3D bin packing |
| Rounding tolerance | 1e-9 | Stops floating point from turning 100.0 into 99 | Implementation detail |
| Items treated as boxes | Bounding box of the package | Round coils and bags are approximated by their bounding box | Assumption |

## SKU catalogue (`data/sku_catalogue.csv`)

- **Synthetic.** 35 SKUs in 10 categories. Dimensions, weights, inbound quantities and demand shares are plausible values chosen by hand. They do not come from any company's master data.
- With the 560 × 360 × 200 mm, 35 kg tote: 28 SKUs are volume-bound and 7 weight-bound. (The step-1 note said 33 / 7 / 1. It miscounted, the correct split before the removal below was 32 / 8 / 1.)
- Removed on 2026-11-01 after Albin's check. **Albin's recollection:** these products did not go into the Cuby system.
  - LMP-06 LED tube T8 1250 mm: too long for a Cuby tote.
  - CR-02 installation cable 3x2.5, 50 m coil (9.0 kg): too heavy.
  - CR-04 telecom cable, 100 m reel (4.5 kg): too heavy.
  - The packing rule alone would have accepted both coils (35 kg limit). So the real limit for single items, or the site's own rule, is stricter than the tote's load limit. The model does not try to capture that rule. It only uses SKUs that go into Cuby.
- Also removed on 2026-11-01, as near-duplicates in packing terms (Albin's decision): LMP-02 (twin of LMP-01), PNL-03 (twin of PNL-01, both 4 per tote), GL-03 (twin of GL-02, same box, both weight-bound). Each removed share was added to its kept twin (LMP-01 0.05 → 0.10, PNL-01 0.02 → 0.04, GL-02 0.02 → 0.03), so the category mix stays the same.
- Demand shares now sum to 0.97, because the three non-Cuby SKUs' shares (0.03) were dropped. The simulation normalises them to sum to 1 when it samples SKUs.
- Inbound quantity per line: uniform integer between the min and max columns. Assumption.
- Spot-check against public manufacturer datasheets: **open**.
- Sanity check of categories by Albin: **in progress** (checklist doc, 2026-11-01). Removals above confirmed.

## Albin's answers to the open questions (2026-11-01)

| Q | Answer | How it is used |
|---|---|---|
| 2 Tote limit | Does not remember. Albin chose 15 kg as the base value. | Base max load 15 kg. **Assumption, not a recollection.** The 35 kg Cuby figure stays as the upper end of the sensitivity range. At 15 kg, 17 of 35 SKUs are weight-bound (7 at 35 kg). |
| 3 Mixed totes | **Albin's recollection (corrected the same day):** a tote always held one product. Sometimes a divider went in the middle, and the system was told which side held which product. (His first answer, "products could be mixed", was withdrawn.) | Divided-tote design (brief decision D10). Each half holds one SKU. |
| 4 Overweight totes | **Albin's recollection:** the conveyor did not accept an overweight tote. The worker had to redo the tote before pushing it onto the conveyor again. | Overweight check at induction. A rejected tote returns to the worker, who removes units (time `t_rework`) and resubmits. Removed units go into the next tote. |
| 5 Handling time | **Albin's recollection:** about 3-5 minutes per tote, depending a lot on how complex the delivery is. | Mean total time per tote calibrated to about 4 min. The split into fetch, decide and per-unit time is an assumption. |
| 5b Stations and staff | **Albin's recollection:** about 4 stations, one worker in each. | The model simulates one station with one worker. Arrival rate is per station. An extra worker means a second station. |
| - Lifter | **Albin's recollection:** never a bottleneck, except during rare technical faults. | Lifter modelled with a fixed service time from the 400 cycles/h figure. Faults are not modelled. |
| - Rework | **Albin's recollection:** an overweight tote had to be redone before the conveyor accepted it. | Rework time per rejected tote is timed and shown separately in the worker breakdown. Its value is an assumption and is varied. |
| 6 Judgement bias | **Albin's recollection:** workers underfilled, because an overfilled tote was not accepted by the conveyor. | Judgement fill factor F has its mode below 1. The sweep covers 0.6-1.05. |

## Simulation (`src/simulation.py`, class `Params`)

All handling times are means. Each draw is gamma-distributed with CV 0.3 (assumption). Times were chosen so that one tote takes about 4 min on average, in line with Albin's 3-5 min. At a 15 kg limit an average tote holds about 24 units and a line needs about 2.4 totes (rule, no mixing).

| Parameter | Value | Why | Source | Varied? |
|---|---|---|---|---|
| Base max load | 15 kg | Albin's chosen site value (D9) | Assumption | Yes: 15 / 25 / 35 kg |
| Shift | 480 min, starts empty | One shift per replication, so no warm-up. Lines that arrive before the end are finished in overtime | Assumption | No |
| Arrival rate, normal | 4 lines/h per station | Gives worker utilisation of about 50-60 % | Assumption (calibrated) | Yes |
| Arrival rate, peak | 6 lines/h (1.5 × normal) | Brief: 1.5-2 × normal | Assumption | Yes |
| Stations | 1 modelled, 1 worker | Albin's recollection: about 4 stations, one worker each (D11) | Albin's recollection | S5: 2 workers |
| Line setup | 1.5 min per line | Read the delivery note, unpack, scan | Assumption | No |
| Tote handling | 1.0 min per tote | Fetch an empty tote, label, push onto the conveyor | Assumption | No |
| Decision, rule | 0.1 min per tote | Read the number from a screen | Assumption | No |
| Decision, judgement | 0.5 min per tote | Look, estimate, maybe lift to feel the weight | Assumption | No |
| Place one unit | 5 s | | Assumption | No |
| Rework | 1.5 min + 5 s per removed unit | Tote comes back from the conveyor check, units come out, push again (D12) | Assumption, mechanism from Albin's recollection | Not yet |
| Judgement fill factor F | triangular(0.65, 0.85, 1.10) per tote | Albin's recollection: workers underfilled. The upper tail lets about 9 % of totes be filled above capacity, so overweight happens sometimes | Assumption | **Yes, headline sweep of the mode** |
| How F works | Worker puts round(F × n_max) units in a tote, at most what physically fits | A worker can see volume but cannot see weight. So only weight-bound SKUs can be overweight | Modelling choice | No |
| Overweight rework | Units removed until the tote is under the limit | Simplification: after rework the tote is exactly at the weight bound | Modelling choice | No |
| Dividers | Three layouts: half across the length (2 × 280 × 360 × 200 mm), half along the length (2 × 560 × 180 × 200 mm), quarters (4 × 280 × 180 × 200 mm). Divider thickness ignored | **Albin's recollection (2026-11-01, when asked):** both dividers were used "if the circumstances were right" | Albin's recollection, sizes are assumptions | Yes: none / halves / all |
| Compartment capacity | Packing rule on the compartment. The weight limit stays the whole tote's (15 kg) | Same grid rule as a full tote | Modelling choice | With max load |
| Which layout | A leftover goes into the smallest compartment it fits: a quarter, then the bigger half. A leftover that fits no compartment gets its own tote | Greedy, easy to show on a screen | Modelling choice | Not yet |
| Waiting tote | A partly filled divided tote waits at the desk for the next leftover that fits a free compartment and keeps the weight OK (exact for the rule, F × limit for judgement). Only one can wait at a time. If a leftover does not fit, the waiting tote is sent with its empty compartments | **Albin's recollection (when asked):** a partly filled divided tote could wait at the desk. One at a time is Albin's simplification | Albin's recollection + assumption | Not yet |
| How often dividers are used | Whenever a leftover fits in a half, in both scenarios | Albin said "sometimes". Using the same policy in both scenarios keeps the rule-vs-judgement difference about filling only | Assumption | On / off |
| Lifter | 9 s per tote (400 cycles/h), buffer 10 totes | 2016 press figure, indicative only. Albin's recollection: never a bottleneck | Public figure + Albin's recollection | No |
| Lead time | Arrival until the worker has put all units of the line in totes | With dividers, the last units may wait in an open half-filled tote, so "until inducted" is not defined | Modelling choice | No |
| Random numbers | Separate streams for arrivals, fill factors and handling times. Fill and time streams are per order line | Common random numbers: the same line gets the same draws in every scenario | Method | No |

