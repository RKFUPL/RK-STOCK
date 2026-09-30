# Aakaar Dry-Run Projection Report

**Repository:** `W:\RK Stocks and linesheets`  
**Mode:** read-only projection only  
**Database checked:** `RKSTOCKDB`  
**Dry-run status:** **PASS as a projection; BLOCKED for real import until importer changes are approved**

No application import route was called. The validated workbook remains the detailed row-level projection source: see its `Products`, `Configurations`, `Inventory Variants`, `Opening Stock`, and `Validation Issues` sheets.

## 1. Projection totals

| Entity | Projected | Validation |
|---|---:|---|
| Parent products | 19 | PASS |
| Colour configurations | 47 | PASS |
| Size-M inventory variants | 47 | PASS |
| Physical opening-stock records | 0 | PASS; intentionally unassigned |
| Source/order quantity records | 47 | PASS; M = 1 preserved as order quantity |

## 2. Products

Each product uses the base CK code as both product identity and display name. The existing Aakaar collection is reused.

| Product | Internal SKU | Category | Source rows / configuration count |
|---|---|---|---:|
| CK-201 | PRODUCT-AAK-CK-201 | Saree Set | 1, 4, 9, 14 / 4 |
| CK-204 | PRODUCT-AAK-CK-204 | Saree Set | 2, 21, 25 / 3 |
| CK-207 | PRODUCT-AAK-CK-207 | Saree Set | 3, 22 / 2 |
| CK-203 | PRODUCT-AAK-CK-203 | Saree Set | 5, 10, 20, 34 / 4 |
| CK-205 | PRODUCT-AAK-CK-205 | Saree Set | 6, 26, 32 / 3 |
| CK-211 | PRODUCT-AAK-CK-211 | Saree Set | 7, 12 / 2 |
| CK-212 | PRODUCT-AAK-CK-212 | Saree Set | 8, 15, 29 / 3 |
| CK-208 | PRODUCT-AAK-CK-208 | Saree Set | 11, 23, 27, 47 / 4 |
| CK-168 | PRODUCT-AAK-CK-168 | Skirt Set | 13 / 1 |
| CK-213 | PRODUCT-AAK-CK-213 | Saree Set | 16, 41, 42 / 3 |
| CK-90-A | PRODUCT-AAK-CK-90-A | Saree Set | 17, 38, 43 / 3 |
| CK-155-A | PRODUCT-AAK-CK-155-A | Saree Set | 18 / 1 |
| CK-202 | PRODUCT-AAK-CK-202 | Saree Set | 19, 31 / 2 |
| CK-210 | PRODUCT-AAK-CK-210 | Saree Set | 24, 35 / 2 |
| CK-97 | PRODUCT-AAK-CK-97 | Saree Set | 28, 40 / 2 |
| CK-191 | PRODUCT-AAK-CK-191 | Saree Set | 30, 39 / 2 |
| CK-88-A | PRODUCT-AAK-CK-88-A | Saree Set | 33, 37, 45 / 3 |
| CK-171 | PRODUCT-AAK-CK-171 | Saree Set | 36 / 1 |
| CK-209 | PRODUCT-AAK-CK-209 | Saree Set | 44, 46 / 2 |

The workbook `Configurations` sheet contains all 47 configuration rows with parent code, colour, full source/vendor code, RSKC source SKU, component count, MRP, source quantity, measurements, PO/reference, and delivery date. The workbook `Inventory Variants` sheet contains all 47 generated size-M variants.

## 3. Configuration projection

For each source row, the projection preserves:

- parent base CK code;
- colour configuration;
- full CK colour-specific source/vendor code;
- RSKC client/source SKU;
- component count;
- configuration-level MRP in INR;
- `tax_inclusive = true`;
- source/order quantity `M = 1`;
- measurements `waist 30`, `bust 36`, `hip 40`;
- PO/reference and delivery date;
- original import/linesheet provenance.

The proposed configuration SKU is `RK-AAK-{BASE_CK}-{COLOUR}-{SET}`. MRP remains independent per configuration and is not merged to the parent.

## 4. Inventory variant projection

Each configuration produces one size-M variant:

`{configuration_sku}-M`

Every projected variant has:

| Field | Dry-run value |
|---|---|
| Size | `M` |
| Physical quantity | `0` / unassigned |
| Reserved quantity | `0` |
| Available quantity | `0` |
| Source/order quantity | `1` |
| Location | Unassigned |
| Available for sale | False until physical stock is verified |

The source/order quantity is never converted into a stock balance.

## 5. Required CK-207 check

**PASS**

```text
CK-207
- Red
  - RSKC052641
  - CK-207-Red
  - components = 2

- Ivory
  - RSKC052640
  - CK-207-Ivory
  - components = 2
```

The previously reported Ivory value of `3` is treated as an erroneous source value and is not authoritative.

## 6. Identifier checks

| Check | Result |
|---|---|
| Parent product identities | 19 unique / PASS |
| Configuration identities | 47 unique / PASS |
| Inventory variant identities | 47 unique / PASS |
| RSKC source SKUs | 47 unique and preserved / PASS |
| Full CK source/vendor codes | 47 unique and preserved / PASS |
| Source rows represented | 47 / 47 / PASS |

## 7. Pricing checks

- All 47 MRP values are preserved.
- All are marked `INR`.
- All are marked tax-inclusive.
- Pricing remains configuration-level.
- Different colour configurations are not merged into one price.
- INR remains authoritative.
- No converted currency value is stored as an authoritative price.
- No live FX call was required for this dry run.

## 8. Inventory checks

- No physical opening stock inferred: PASS.
- No stock balance generated: PASS.
- No ledger entry generated: PASS.
- No location assigned: PASS.
- Ordered quantity did not become physical quantity: PASS.
- Approved holders are represented as choices only: Kolkata Flagship Store, Mumbai Store, MDS Client, and PR Team.
- MDS Client and PR Team are not treated as sellable: PASS.

## 9. Current database collision check

Read-only query results from `RKSTOCKDB`:

| Collection | Count | Proposed identity collisions |
|---|---:|---:|
| `products` | 0 | 0 |
| `product_configurations` | 0 | 0 |
| `inventory_variants` | 0 | 0 |
| `stock_balances` | 0 | 0 |
| `stock_ledger` | 0 | 0 |

The existing collection was found and reused:

```text
Aakaar / AAK / aakaar / active
```

No product-code, configuration-SKU, inventory-SKU, RSKC, or full CK vendor-code collisions were found.

## 10. Existing importer compatibility

The generic legacy `POST /api/linesheets/import/<import_id>/commit` workflow is not safe for this model by itself. A dedicated `model: "aakaar"` validation/projection path has now been implemented, and the commit branch consumes the validated projection rather than the legacy row-by-row product logic. It was not called during this dry run.

The legacy path still has these gaps and must not be used for Aakaar:

- It processes rows independently and does not group 47 rows by base CK code.
- It looks up products by the row SKU, which would treat the RSKC/source SKU as the product lookup key.
- Product creation is optional through `create_products`; it does not enforce the approved 19-product grouping.
- It does not create product configurations.
- It does not create inventory variants.
- It does not preserve the new source/client SKU, full vendor code, tax-inclusive flag, measurements, or source order quantities in its committed item shape.
- It does not create or validate explicit physical locations.
- It does not create stock balances in the commit route, but it also does not create the separate inventory-variant records needed for later stock management.
- Its historical `existing_products_matched` summary can report rows as matched when no product exists.
- MDS import commit can invoke WorkDrive processing, which is outside this dry-run boundary.

The Aakaar-specific path now validates all rows and identity collisions before writes, groups by base CK code, creates one product per base, creates configuration and variant records, preserves source metadata, and creates zero stock balances. Its write helper compensates by deleting records it created if a later write fails; no MongoDB transaction is introduced.

The newer `/api/linesheets` normalization path can represent many of the approved fields and creates configurations when invoked, but it is still a mutating workflow and was not called. A real import requires a separately approved importer change or a controlled sequence using the supported APIs in a staging database.

## 11. Blockers before real import

1. Implement or approve a dry-run-capable importer that groups rows by base CK code.
2. Ensure the importer creates exactly 19 products, 47 configurations, and 47 variants.
3. Preserve all source metadata in the committed model.
4. Keep source/order quantity separate from physical stock.
5. Require explicit location and physical verification before any stock balance.
6. Run the importer first against an approved disposable/staging database.
7. Re-run collision checks immediately before any production import.

## 12. Safety and test result

- MongoDB access was read-only.
- No import endpoint was called.
- No product/configuration/inventory records were created.
- No stock balances were created.
- No ledger entries were created.
- No production changes occurred.
- No RK-WEB, WorkDrive, or Lookbook changes occurred.
- No commit, push, or deployment occurred.
- The existing worksheet was preserved.

The focused Aakaar importer suite passes at `10 passed`. The complete backend suite passes at `77 passed` after the final implementation changes.
