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

- **Synthetic.** 41 SKUs in 10 categories. Dimensions, weights, inbound quantities and demand shares are plausible values chosen by hand. They do not come from any company's master data.
- With the 560 × 360 × 200 mm, 35 kg tote: 33 SKUs are volume-bound, 7 weight-bound and 1 (LED tube 1250 mm) does not fit. The non-fitting SKU is there to show the flag. It is assumed to go to long-goods storage.
- Inbound quantity per line: uniform integer between the min and max columns. Assumption.
- Spot-check against public manufacturer datasheets: **open**.
- Sanity check of categories by Albin: **open**.

## Simulation

Not started yet.
