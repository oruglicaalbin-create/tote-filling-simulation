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

## Simulation

Not started yet.
