# Stock catalog import template description

This is a description of the existing Stock linesheet import format. No template was populated or imported.

## Workbook

- File type: `.xlsx`
- The importer accepts a workbook sheet selected during preview.
- A practical current sheet name is `Outright Order Details` or `OutRight Order Details`.
- The importer enforces a 25 MB limit.

## Columns

Required or useful columns recognized by the existing importer:

| Column | Purpose | Required behavior |
|---|---|---|
| `Sr No` | source row number | optional identifier |
| `Vendor Code` | product/style code | preferred product-code input |
| `Sku` or `Product SKU` | row SKU | required and unique within the workbook |
| `Color` or `Colour` | colour | required for configuration-quality data |
| `Category` | category label | retained on linesheet items |
| `No of Components` | set/component count | normalized to `set_of`, valid values 1–5 |
| `MRP` | price | non-negative numeric value |
| `XS`, `S`, `M`, `L`, `XL` | size quantity/measurement columns | at least one valid size quantity is required per row |
| `Remark` | row note | optional |
| `Reference Image 1/2` | source references | optional |
| `Po DeliveryDate` or `Delivery Date` | delivery date | optional |

The actual importer identifies columns by aliases and size-like headers. It stores a preview before commit and reports invalid rows, duplicate SKUs, and quantity errors.

## Important limitation

This is a linesheet/order import format, not a complete product/configuration/inventory master template. The commit route can optionally create product documents with `create_products: true`, but it does not create product configurations or inventory variants as part of the import.

After a successful catalog/linesheet commit, configurations are created through the normal linesheet normalization path and inventory variants are created separately through:

`POST /api/inventory/variants`

That route requires an existing `linesheet_sku`, a size list, and optional quantities. Positive quantities create `opening_stock` ledger transactions through the existing stock mutation service.

## Required approval before use

Before preparing a real workbook, confirm:

1. The rows represent Stock-owned products rather than only historical order lines.
2. Product codes, colours, set counts, sizes, prices, and opening quantities are authoritative.
3. The target active Stock collection is correct.
4. Product creation is explicitly enabled only for approved rows.
5. Opening-stock quantities are approved separately from catalog creation.
