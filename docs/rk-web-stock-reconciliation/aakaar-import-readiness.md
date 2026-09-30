# Aakaar Linesheet Import Readiness

> **Business correction:** The earlier source value of component count `3` for `CK-207-Ivory` was confirmed erroneous. The authoritative initialization value is `2`, matching `CK-207-Red`. The erroneous value is not preserved as historical truth.

**Investigation mode:** read-only  
**Database:** `RKSTOCKDB`  
**Collection under review:** `Aakaar` (`AAK`, active)  
**Source:** existing Stock import records, stored linesheet, uploaded workbook metadata, and current import implementation

## Conclusion

**Not import-ready as an authoritative catalog.** The source is usable as a starting linesheet/order workbook, but it does not contain enough verified identity and inventory information to safely create the Stock catalog and opening balances without business corrections.

No import commit was executed. No product, configuration, inventory variant, stock, or WorkDrive write was performed.

## 1. Source linesheet and row count

Verified database state:

| Item | Verified value |
|---|---:|
| Stored Aakaar linesheets | 1 |
| Linesheet type | `mds_outright` |
| Linesheet status | `shared` |
| Stored item rows | 47 |
| Stored total quantity | 47 |
| Associated imported records | 4 |
| Products | 0 |
| Product configurations | 0 |
| Inventory variants | 0 |
| Stock balances | 0 |
| Stock ledger entries | 0 |

The stored linesheet is historical/source data, not a complete catalog. Its items contain vendor/source values, product names, colour, size quantities, and MRP-like values, but no Stock product or configuration IDs. The stored items also do not contain usable generated `linesheet_sku` values.

The source workbook is an `OutRight Order Details` worksheet with 19 mapped columns, including vendor code, SKU, colour, category, component count, MRP, remarks, references, delivery date, and a size/measurement column. The database projection shows 47 rows and no skipped rows or reported errors in the imported summary.

## 2. What the rows represent

The rows are best classified as **linesheet/order-detail rows with product candidates**, not complete inventory records.

They contain or may contain:

- product/vendor code and source SKU values;
- product description/name;
- colour;
- category text;
- component count/set information;
- MRP/unit-price text or numeric values;
- size quantities, with the observed size quantity being `M: 1` in the stored projection;
- source references and delivery-date fields.

They do not provide verified Stock-side:

- immutable product IDs;
- configuration IDs;
- inventory variant IDs;
- generated Stock linesheet SKUs;
- warehouse/location ownership;
- physical opening-stock provenance;
- reserved or available quantities;
- stock-ledger transaction IDs;
- an explicit authoritative tax/currency contract.

Therefore the rows are not safely interchangeable with product, colour-configuration, inventory-variant, or opening-stock records without an approved transformation and source-data decision.

## 3. Previous import trace

The relevant implementation is `backend/app/routes.py`, `commit_linesheet_import` at `POST /api/linesheets/import/<import_id>/commit`.

The route:

1. Reads the import preview.
2. Builds linesheet items from each valid preview row.
3. Looks up a product by the source row SKU.
4. Creates a product only when the request includes `create_products: true`.
5. Inserts the linesheet document.
6. Marks the import as `imported` and writes a summary.

The summary is calculated as:

```text
existing_products_matched = len(items) - created_products
```

That calculation treats every row that did not create a product as an existing match, even when the lookup returned no product and `create_products` was false. This explains the historical `existing_products_matched: 47` alongside `products: 0`: it is a summary-labeling defect, not evidence that 47 products existed.

The commit route also does not create `product_configurations` or `inventory_variants`. Those are created by the separate linesheet normalization and inventory-variant workflows. The import route can create a linesheet and may invoke the existing WorkDrive path for MDS linesheets, so it must not be called merely as a validation step.

## 4. Read-only validation findings

| Check | Result | Classification |
|---|---|---|
| Required source rows present | 47 stored rows | Verified |
| Stored row errors | 0 in historical import summary | Verified, but not a fresh preview |
| Product IDs | Missing | Needs correction / identity decision |
| Configuration IDs | Missing | Needs correction / identity decision |
| Inventory variant IDs | Missing | Needs correction |
| Generated Stock SKU | Missing from stored linesheet items | Needs correction |
| Collection reference | Aakaar name is present; collection exists and is active | Verified |
| Colour values | Present in stored items | Requires row-level normalization review |
| Size values | Size quantity data present; observed `M` | Requires row-level validation |
| Prices | MRP-like values present as source values | Requires currency/tax/business validation |
| Quantities | Stored total quantity 47 | Not opening-stock proof |
| Location/warehouse | Not present in the inspected projection | Missing |
| Reserved stock | Not present | Missing |
| Available stock | Not present | Missing |
| Duplicate product codes/SKUs | Not proven by the stored aggregate projection | Requires fresh preview/report |

The historical import summary is not sufficient to prove current validation because the original preview rows were not re-committed and the supported inspect endpoint itself writes a preview/import record. A fresh inspect operation should only be run if its file-write and database-write side effects are explicitly approved.

## 5. Row classification

The available stored evidence supports the following conservative classification:

| Classification | Rows | Reason |
|---|---:|---|
| READY | 0 | No row has a verified Stock product/configuration/inventory identity and opening-stock provenance |
| NEEDS_CORRECTION | 47 | Missing Stock identity, generated SKU, and warehouse/location/stock semantics |
| DUPLICATE | 0 proven | No duplicate result was established from the stored projection |
| INVALID | 0 proven | Historical import reported no row errors, but this is not a current full validation |
| AMBIGUOUS | 47 | Source rows could represent order lines, product candidates, configurations, or size quantities |

These classifications deliberately do not auto-correct names, codes, colours, prices, sizes, or quantities.

## 6. Candidate creation counts if approved and corrected

Exact post-commit counts cannot be guaranteed from the stored records. The safe expected shape is:

- **Products:** up to 47 product candidates, reduced if approved product-code deduplication identifies multiple rows for one product.
- **Configurations:** one per approved product/colour/set combination after running the existing linesheet normalization workflow; exact count is not verified.
- **Inventory variants:** one per approved configuration/size combination after calling the existing inventory-variant workflow; exact count is not verified.
- **Opening stock:** not approved or determinable. The stored quantity of 47 is linesheet quantity, not proof of physical opening stock and must not be posted to `stock_balances`.

The import route alone would create a linesheet and, only with `create_products: true`, product documents. It would not complete configuration, variant, or stock initialization.

## 7. Risks

- The source SKU may be a vendor/order identifier rather than the authoritative Stock product SKU.
- The historical `existing_products_matched` number is misleading.
- A linesheet quantity must not be interpreted as physical warehouse stock.
- No location/warehouse contract was verified.
- Price currency, tax-inclusive status, and price ownership were not established.
- Colour and size normalization may change business identity if applied without approval.
- Directly committing the old import could create a linesheet and possibly products without the configurations and inventory records required for stock management.
- The import commit path can invoke WorkDrive processing for MDS data; it was not called during this audit.
- No authoritative relationship to RK-WEB should be created at this stage.

## 8. Exact next action

1. Obtain business approval for whether the 47 rows are intended to become Stock products, or remain historical linesheet/order rows.
2. Produce a corrected, controlled source workbook containing one explicit product identity per product, approved colour/configuration identity, allowed size values, currency/tax semantics, and a separate decision for opening stock and location.
3. Run the existing inspect/preview workflow in an approved disposable or staging database, because the current inspect route persists an import preview.
4. Review duplicate and validation results row by row.
5. Only after approval, commit through the existing import workflow with an explicit `create_products` decision, then create configurations, inventory variants, and opening stock through their existing supported workflows.

No commit endpoint, product route, configuration route, inventory route, or stock-adjustment route was called for this report.
