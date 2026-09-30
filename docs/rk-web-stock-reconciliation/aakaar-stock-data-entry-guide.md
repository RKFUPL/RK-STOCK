# Aakaar Stock Data Entry Guide

This workbook is an approved preparation package. It remains non-mutating and must not be submitted to the production import endpoint.

## Approved structure

- **19 Products:** one parent product for each base CK code. The product code and display name are the base CK code, such as `CK-207`.
- **47 Configurations:** one colour/set configuration per source row. Preserve the full source/vendor code, client/source SKU, category, MRP, component count, measurements, PO/reference, delivery date, and source order quantity.
- **47 Inventory Variants:** one size-`M` variant for each configuration.
- **Opening Stock:** separate from source/order quantity. Physical quantity and location remain blank until verified.

## Source and identity fields

The `RSKC...` value is client/source SKU metadata. It is not the Stock product identity.

The full CK colour-specific value, for example `CK-207-Red`, is preserved as the configuration source/vendor code. The parent product identity is the base code `CK-207`; the colour is stored separately as `Red`.

The source category is preserved exactly. Existing rows are `Saree Set` or `Skirt Set`; no category is invented.

The existing collection is reused: `Aakaar`, code `AAK`, slug `aakaar`. No duplicate collection is created.

## Pricing

MRP is authoritative in INR and is tax-inclusive. MRP remains configuration-level data, so different colours may retain different values if the source differs.

INR remains the source-of-truth price. Future USD, EUR, GBP, AED, or other display currencies must be derived through a configurable live FX provider. No provider is hard-coded and no converted price is persisted as authoritative data in this preparation package.

## SKU generation

The package follows the existing normalization conventions with the approved base-code grouping:

- Product: `PRODUCT-AAK-{BASE_CK_CODE}`
- Configuration: `RK-AAK-{BASE_CK_CODE}-{COLOUR}-{SET}`
- Inventory variant: `{CONFIGURATION_SKU}-M`

The source application allows sizes `XS`, `S`, `M`, `L`, and `XL`. The source data establishes only size `M` for these 47 rows.

The component count is configuration data. `CK-207-Red` and `CK-207-Ivory` both use authoritative set count `2`. An earlier source value of `3` for CK-207-Ivory was confirmed as erroneous and was corrected during initialization; it must not be preserved or treated as historical truth.

## Quantity, locations, and stock

The source `M: 1` value is an ordered/linesheet quantity. It is preserved in the configuration and opening-stock sheets as source quantity metadata. It must not be copied into physical stock, available stock, or the stock ledger.

Approved physical holders are represented as explicit choices:

- Kolkata Flagship Store
- Mumbai Store
- MDS Client
- PR Team

No row is assigned to a holder. MDS Client and PR Team quantities must not be treated as automatically available for sale. Physical stock requires a separate verification and opening-stock process.

## Provenance

Keep the source/client SKU, full CK colour code, source/order quantity, MRP, PO/reference, delivery date, component count, measurements, import ID, workbook hash, and linesheet number. These fields support audit traceability and do not prove physical possession.

## Safe next step

Review the generated package and approve the four physical-stock/location decisions separately. Then run the existing inspect/preview workflow only against an approved disposable or staging database. Do not call `/api/linesheets/import/<import_id>/commit` against the current production/live database.
