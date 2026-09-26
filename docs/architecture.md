# System architecture

## Core collections

`users`, `clients`, `products`, `linesheets`, `orders`, `production_batches`, `production_movements`, `stock_balances`, `stock_ledger`, `dispatches`, `consignment_transactions`, `documents`, `activity_log`, `counters`, and `settings`.

Documents refer to business records by immutable MongoDB IDs. Human identifiers (`client_code`, `sku`, `linesheet_number`, and `po_number`) have unique indexes. Uploaded PO versions are immutable; a document family points to all versions.

## Quantity rules

- Product variants are uniquely identified by SKU, color, and size.
- Physical, reserved, production, and consignment quantities are separate.
- Available quantity is derived as physical minus reserved; it is never edited directly.
- Every stock mutation creates one ledger entry in the same MongoDB transaction where transactions are available.
- Idempotency keys prevent a dispatch or adjustment being applied twice.
- Production movements transfer a quantity from one stage bucket to another; the sum of stage buckets, completed, rejected, and rework quantities cannot exceed the ordered production quantity.
- Commercial order status and production status are stored separately.

## API

All application routes are under `/api`. Authentication uses short-lived signed JWT bearer tokens and bcrypt password hashes. Mutating routes enforce Admin, Sales, or Production/Inventory permissions and add activity entries.

Implemented functional APIs cover authentication, dashboard aggregation, clients, products, linesheets, orders/PO lookup, PO document versioning, production queues and stage movement, stock balances/ledger/adjustments/reservations, consignment movements, users, settings, and CSV/Excel-ready report exports.

