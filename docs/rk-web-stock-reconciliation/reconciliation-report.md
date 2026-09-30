# RK-WEB ? Stock & Linesheets Read-Only Catalog Reconciliation

Generated: 2026-09-30T06:57:19.251801+00:00

## Result

- RK-WEB products inspected: **56**
- RK-WEB colour variants inspected: **64**
- RK-WEB size entries inspected: **320**
- Stock products/configurations/inventory variants/stock balances: **0 / 0 / 0 / 0**
- Collections: RK-WEB **7**, Stock **3**
- Automatic product matches: **0**
- Automatic collection matches by normalized slug: **1**
- Ambiguous: **0**
- Unmatched RK-WEB products: **56**
- Unmatched Stock products: **0**
- Duplicate candidates: **0**
- Conflicts: **0**
- Inventory and price mismatches: **not comparable because Stock has no product/configuration/variant records**

## Matching rules

Native IDs are preserved separately. Exact shared IDs and exact SKUs were checked conceptually but no Stock product/configuration records exist. No title-only or collection-name-only product mappings were created. All RK-WEB products, colour variants, and size entries are `UNMATCHED` with `NO_STOCK_CANDIDATE`.

Collections were compared independently. Exact normalized slug matches are marked `AUTO_MATCHED` as collection candidates only; this does not map products or authorize synchronization.

## Evidence and safety

- Source: direct MongoDB read-only projections from `RKSTOCKDB` and `RKFUPL`.
- No application routes were called.
- No writes, inserts, updates, deletes, upserts, indexes, stock adjustments, reservations, checkout, orders, or WorkDrive operations were performed.
- Product-level, variant-level, and size-level stock remain separate.
- RK-WEB quantities are reported as source values only and are not treated as Stock physical opening stock.

## Files

- `rk-web-stock-reconciliation.xlsx` with Summary, Collections, Products, Colour Variants, Size Mappings, Inventory Comparison, Price Comparison, Auto Matched, Ambiguous, Unmatched, Duplicates, and Conflicts sheets.
- `summary.json`
- `source_projections.json`
- `products.csv`
- `colour_variants.csv`
- `size_mappings.csv`
- `collections.csv`
- `catalog_mappings_candidates.json`
- `unmatched.csv`
- Empty category CSVs for inventory, price, automatic matches, ambiguity, duplicates, and conflicts.
