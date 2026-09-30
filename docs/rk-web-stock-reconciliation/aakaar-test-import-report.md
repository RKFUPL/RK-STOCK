# Aakaar Test-Database Import Verification

**Final status: BLOCKED**

This report records the verification run against the disposable MongoDB database only. No production import was attempted.

## 1. Test database identification

- Configured database: `RK_TEST_DB`
- MongoDB configuration present: yes
- MongoDB ping: successful
- Production database match (`RKSTOCKDB`): no
- Connection strings and credentials: intentionally omitted

## 2. Pre-import counts

| Collection | Count |
|---|---:|
| Products | 0 |
| Product configurations | 0 |
| Inventory variants | 0 |
| Stock balances | 0 |
| Stock ledger entries | 0 |
| Collections | 0 |

The required Aakaar collection was not present in the test database.

## Collection-initialization attempt

The existing supported collection setup is `POST /api/collections`. It requires an authenticated user with effective `settings:write` permission and a current collection revision. The disposable database is empty, including its user collection, so there was no existing authorized application identity with which to invoke that route.

The application startup initializer was not used because it creates the standard collection set rather than only Aakaar, and startup/index/seed behavior would not satisfy the requested single-collection workflow. No direct MongoDB insert was used.

Result: **Aakaar collection setup was not performed.**

## Collection setup follow-up

The supported `create-admin` CLI invokes the normal application initialization path. On the test database, that path created the standard three active collections, including Aakaar. Direct read-only verification now shows:

- Database: `RK_TEST_DB`
- Aakaar ID: `6abd086468a0358cad9d179e`
- Name: `Aakaar`
- Slug: `aakaar`
- Code: `AAK`
- Active: `true`
- Position: `3`
- Collections revision: `0`
- Products/configurations/variants/stock balances/ledger entries: all `0`

Therefore no `POST /api/collections` request was sent: creating Aakaar again would be a duplicate and would violate the requirement to create exactly one Aakaar collection.

The test admin exists with role `admin` and is active. The role grants effective `*`, including `settings:write`. Authentication through `/api/auth/login` was not attempted because the password was entered privately during CLI setup and is not available to this investigation. No password or secret was printed.

## 3. Dry-run results

The corrected workbook was read without modification and passed the pure Aakaar projection:

| Check | Result |
|---|---:|
| Valid | `true` |
| Errors | 0 |
| Products | 19 |
| Configurations | 47 |
| Inventory variants | 47 |
| Physical stock records | 0 |
| Distinct source SKUs | 47 |
| Distinct vendor codes | 47 |
| Currency/tax | All INR and tax-inclusive |
| Physical/location/sellability | All zero, no location, not sellable |

## 4. CK-207 verification

- `CK-207-Red`: component count `2`
- `CK-207-Ivory`: component count `2`

## 5. Import result and post-import counts

No import was performed. The supported Aakaar commit path requires an existing active `Aakaar` collection document. Because the disposable database contains no collection records, proceeding would require manually seeding setup data or bypassing the established workflow. Neither was done.

Post-import counts are therefore unchanged from the pre-import counts: all inspected catalog, stock, and collection counts remain zero.

## 6. Ordered versus physical stock

The dry-run preserves source/order quantities separately. It creates no physical stock, reserved stock, available stock, stock balances, locations, or sellable inventory.

## 7. Idempotency test

Not run. No first import was possible because the required collection setup was absent.

## 8. Failure/rollback test

Not run against MongoDB. Existing automated tests cover the importer projection and compensation code path; no failure simulation was introduced for this verification.

## 9. Automated tests

- Focused Aakaar tests: **4 passed**.
- Full command `python -m pytest -q`: blocked during collection by pre-existing permission-denied `pytest-cache-files-*` directories.
- Full tests from `tests/`: **76 passed, 1 failed**.
- Failure: `tests/test_db.py::test_backend_loads_project_root_environment_configuration`, because that test hard-codes production database name `RKSTOCKDB` while this run intentionally uses `RK_TEST_DB`.

## 10. Safety confirmation

- Production `RKSTOCKDB`: not connected to or modified.
- Test database: no writes performed.
- RK-WEB: unchanged.
- WorkDrive: unchanged.
- LookbookMaker: unchanged.
- Preparation workbook: unchanged.
- VPS/deployment: untouched.
- Commit/push: not performed.

## Next action

Provision the existing active Aakaar collection in the disposable database through the approved Stock setup/import workflow, or provide an approved test-database initialization procedure. Then repeat pre-counts, dry-run, commit, post-counts, idempotency, and rollback verification. Do not change the root `.env` back to `RKSTOCKDB` for this test.
