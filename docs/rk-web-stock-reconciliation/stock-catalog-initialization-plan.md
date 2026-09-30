# Stock & Linesheets catalog initialization plan

Read-only audit completed: 2026-09-30

## A. Current database state

Direct MongoDB reads confirmed database `RKSTOCKDB` contains:

| Collection | Count |
|---|---:|
| `products` | 0 |
| `product_configurations` | 0 |
| `inventory_variants` | 0 |
| `stock_balances` | 0 |
| `stock_ledger` | 0 |
| `collections` | 3 |
| `linesheets` | 1 |
| `imports` | 4 |

The three collections are `Aakaar`, `Inaara`, and `Hastakala`, with codes generated/configured as `AAK`, `INA`, and `HAS` by `backend/app/db.py` during application initialization. That initialization path is mutating and was not run during this audit.

## B. Actual Stock catalog creation workflow

The application has three relevant creation paths in `backend/app/routes.py`:

1. `POST /api/products` creates a product document directly. It requires `name` and `sku`, is admin-only, and stores optional `cost_price`, `selling_price`, `colors`, `sizes`, and `active`. It does not create a configuration or inventory variant.
2. `POST /api/linesheets` calls `_normalize_linesheet_items(..., persist_configurations=True)`. For each valid item it creates or reuses a product, creates or updates a `product_configurations` record, and embeds the item in a linesheet. It does not create `inventory_variants` or opening stock.
3. `POST /api/inventory/variants` creates or reuses inventory variants from an existing `product_configurations.linesheet_sku`. Positive quantities are passed to `mutate_stock(..., transaction_type="opening_stock")`.

The Excel workflow is split into:

- `POST /api/linesheets/import/inspect`: uploads and parses an `.xlsx`, stores an import preview, and returns mapped columns and validation errors.
- `POST /api/linesheets/import/<import_id>/commit`: validates client and active collection, creates a linesheet, and optionally creates products when `create_products` is true. This route is mutating and was not called.

## C. Existing Stock-side source data discovered

The database contains one shared linesheet with 47 items in collection `Aakaar`, type `mds_outright`, and four import records for the same workbook family. The stored items contain vendor codes, SKUs, colours, MRP values, and size quantities.

However, those 47 linesheet items have no `product_id`, `configuration_id`, or `linesheet_sku`. The database still has zero products and zero configurations.

The repository also contains uploaded workbook files under `backend/backend/uploads/imports/` and test fixture workbooks under `backend/tests/uploads/imports/`. These are linesheet/order-style workbooks, not a separate canonical Stock product seed or master catalog. No checked-in Stock product JSON/CSV/catalog seed was found.

## D. Required fields

### Product

The direct product route requires:

- `name`
- unique `sku`

The linesheet-derived product path additionally stores `product_code`, `description`, `collection`, `collection_id`, `images`, and `active`.

### Product configuration / colour

Each configuration requires or derives:

- parent `product_id`
- `collection_id`
- `product_code`
- `color`
- `set_of` from 1 through 5
- generated unique `linesheet_sku`
- `description`
- non-negative `mrp`
- at least one allowed size
- optional images

### Inventory variant

The inventory route requires:

- existing `linesheet_sku`
- a non-empty `sizes` list
- sizes limited by `inventory_sku()` to `XS`, `S`, `M`, `L`, or `XL`
- optional per-size `quantities`

## E. Required import format

The supported workbook importer recognizes an `.xlsx` workbook and searches headers using aliases in `_excel_mapping()`:

- serial number: `Sr No`, `Sr. No`, `Serial Number`
- vendor/product code: `Vendor Code`
- SKU: `SKU`, `Product SKU`
- colour: `Color`, `Colour`
- category: `Category`
- component count: `No of Components`, `Component Count`
- price: `MRP`
- remark: `Remark`, `Remarks`
- reference images: `Reference Image 1`, `Reference Image 2`
- delivery date: `Po DeliveryDate`, `PO Delivery Date`, `Delivery Date`
- size columns: headers beginning with an allowed size such as `XS`, `S`, `M`, `L`, or `XL`

Rows require a SKU, and quantity cells must parse as non-negative quantities. Duplicate SKUs and invalid quantities are rejected in preview. The current stored workbook used an `OutRight Order Details` sheet with vendor code, SKU, colour, category, component count, MRP, a size column, remarks, references, and delivery date.

The importer is a linesheet/order importer. It is not a standalone product master import and it does not create configurations or inventory variants automatically.

## F. SKU generation rules

`backend/app/sku.py` defines the rules:

- Collection codes: `INA`, `HAS`, `AAK`, `ANA`, `NAQ`, and `SAN`, with a configured two- or three-letter code accepted.
- Configuration SKU: `RK-{COLLECTION_CODE}-{NORMALIZED_PRODUCT_CODE}-{NORMALIZED_COLOR}-{SET_OF}`.
- Product code and colour are uppercased and non-alphanumeric runs become hyphens.
- `set_of` must be an integer from 1 through 5.
- Inventory SKU: `{linesheet_sku}-{SIZE}`.
- Inventory sizes are limited to `XS`, `S`, `M`, `L`, and `XL`.

The direct product route uses the supplied product SKU and enforces a unique MongoDB index on `products.sku`. The linesheet-derived product path uses an internal key shaped like `PRODUCT-{COLLECTION_CODE}-{PRODUCT_CODE}`.

## G. Collection requirements

Linesheets require an active collection found by exact name. Existing collections must not be renamed or assumed to represent RK-WEB collections solely by name.

The current three Stock collections are Stock-side operational collections. They are not proof that all seven RK-WEB collections should be copied into Stock. Any new collection requires an explicit business decision and should use the existing collection configuration route and validation.

## H. Configuration, colour, and size relationship

The intended relationship is:

`product` → `product_configuration` for one product code/colour/set → `inventory_variant` for one size → `stock_balance` keyed by SKU, colour, size, location, and client.

The linesheet normalization path creates the first two levels. The inventory variant route creates the third level. Stock balances are created by the stock mutation service when an opening-stock transaction is applied.

## I. Inventory opening-stock workflow

`POST /api/inventory/variants` creates/reuses variants. For each positive quantity it calls `mutate_stock` with `opening_stock`.

`mutate_stock`:

- creates a balance if absent;
- increments `physical`;
- derives `available = physical - reserved`;
- creates a stock ledger entry;
- uses an idempotency key when provided;
- uses optimistic `revision` checks for concurrent changes.

The generic `POST /api/stock` route also supports stock mutations, including `opening_stock`, but is restricted to admin or production/inventory users. No opening-stock route was called in this audit.

## J. Information still missing

Before initialization, Stock needs a controlled Stock-side source or approved workbook containing, at minimum:

- authoritative Stock product code and product name;
- collection name and approved collection code;
- colour and, where used, colour code;
- set/component count;
- allowed sizes for each configuration;
- MRP and currency/tax interpretation;
- product/configuration status;
- opening physical quantities by SKU, colour, size, location, and client ownership;
- a decision on whether the existing 47-item Aakaar linesheet is an operational source, a historical order artifact, or incomplete catalog input.

The existing linesheet does not supply stable Stock product/configuration IDs and its stored items lack generated configuration SKUs, so it cannot by itself be treated as a complete initialized catalog.

## K. Recommended next action

Do not copy RK-WEB data and do not import yet. First obtain or approve a Stock-owned catalog workbook using the existing import shape, then run the existing preview/validation workflow against a disposable or explicitly approved local database.

The safest implementation sequence is:

1. Confirm whether the existing Aakaar linesheet is valid Stock-owned source data.
2. Produce a clean Stock catalog workbook with one row per product configuration/colour and explicit size columns or size quantities.
3. Preview it through the existing importer and review validation errors.
4. Decide explicitly whether `create_products` should be true.
5. Commit the linesheet/catalog through the existing workflow.
6. Create inventory variants from the resulting configuration SKUs.
7. Enter opening stock only after physical quantities and ownership are approved.
8. Re-run read-only reconciliation against the newly populated Stock catalog before any integration synchronization design.

## L. Safety considerations

- The current importer has a write-capable commit route. Preview and commit must be treated separately.
- `create_products: true` creates Stock product documents; it must not be enabled without approved Stock source data.
- Linesheet import does not create inventory variants or stock balances automatically.
- Opening stock changes physical inventory and creates ledger entries; it must be a separately approved step.
- Do not use RK-WEB as the initial source until Stock ownership and identity rules are approved.
- Do not rename collections, alter existing linesheets, modify orders, call checkout/reservation routes, or touch WorkDrive as part of initialization planning.
- Existing uncommitted application changes and the Phase 1 worksheet remain preserved.
