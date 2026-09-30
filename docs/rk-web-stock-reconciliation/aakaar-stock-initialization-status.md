# Aakaar Stock Initialization Status

**Status:** `PREPARATION COMPLETE — VALIDATED, NOT IMPORTED`  
**Database:** `RKSTOCKDB`  
**Source rows:** 47

## Generated preparation structure

| Level | Count | Result |
|---|---:|---|
| Parent products | 19 | Base CK codes, unique |
| Colour configurations | 47 | One per source row, unique configuration SKU |
| Size-M inventory variants | 47 | One per configuration, unique inventory SKU |
| Opening-stock records | 0 | Deliberately unconfirmed and unassigned |

## Approved decisions applied

- Product identity/name is the base CK code.
- Full colour-specific CK code remains configuration source/vendor metadata.
- `RSKC...` remains client/source SKU metadata.
- Collection is existing `Aakaar` / `AAK` / `aakaar`.
- Source categories are preserved.
- MRP is INR and tax-inclusive.
- MRP remains independent at configuration level.
- `M:1` remains source/order quantity and is not stock.
- Physical stock remains blank.
- No generic `main` location was assigned.
- Approved holder choices are Kolkata Flagship Store, Mumbai Store, MDS Client, and PR Team.
- MDS Client and PR Team are not assumed saleable.
- CK-207 component counts are corrected to Red `2` and Ivory `2`. The earlier Ivory value `3` was confirmed erroneous and is not retained as authoritative data.

## Validation results

- 47 source rows represented: PASS.
- 19 parent CK products: PASS.
- 47 colour configurations: PASS.
- 47 size-M inventory variants: PASS.
- Parent product codes unique: PASS.
- Configuration identities unique: PASS.
- Inventory variant identities unique: PASS.
- All 47 RSKC values preserved: PASS.
- All 47 full CK colour-specific codes preserved: PASS.
- CK-207 Red set count `2`: PASS.
- CK-207 Ivory set count `2`: PASS.
- All MRP values preserved and marked INR: PASS.
- All MRP values marked tax-inclusive: PASS.
- Source order quantity converted to opening stock: PASS, zero conversions.
- Physical stock assigned without verification: PASS, zero assignments.
- Existing Aakaar collection reused: PASS.
- Location choices represented without assignment: PASS.

## Existing implementation compatibility

The current Stock implementation normally uses `product_code` as supplied, then derives configuration and inventory SKUs from product code, colour, set count, and size. The package therefore supplies the approved base CK code as product code while preserving the original full code separately.

The application’s existing product normalization can generate internal product SKUs, configuration SKUs, and inventory SKUs. No database IDs are fabricated in this workbook; IDs remain application-generated at a future approved creation step.

Currency conversion is not implemented or configured in the current package. INR remains authoritative. A future FX provider should be introduced through a server-side abstraction and configuration, without persisting stale converted prices as source prices.

## Safety result

- No MongoDB writes.
- No products, configurations, inventory variants, stock balances, or ledger entries created.
- No import endpoint called.
- No Aakaar linesheet modified.
- No RK-WEB, WorkDrive, or Lookbook project modified.
- No application started.
- No commit, push, or deployment performed.

## Remaining operational decision

The preparation package is ready for business review. A separate physical-stock verification is still required before any opening balance can be recorded. Any future import must use an approved staging/disposable database first and continue through the existing Stock workflow.
