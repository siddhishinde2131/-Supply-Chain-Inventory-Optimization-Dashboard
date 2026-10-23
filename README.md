# Supply Chain & Inventory Optimization Dashboard

An inventory analytics and business-intelligence application built with **Python, Pandas, NumPy,
PostgreSQL, SQL, Streamlit and Plotly**. It helps retail and supply-chain teams reduce excess
inventory, spot potential stock-outs, calculate safety stock and reorder points, classify products
with ABC/XYZ analysis and plan replenishment, using either a reproducible synthetic dataset or
their own CSV files.

> Every number, chart, alert and recommendation is calculated from the loaded dataset. Nothing is
> hard-coded, and no machine learning is used.

---

## 1. Business problem

Inventory ties up working capital. Too much stock means holding cost, obsolescence and cash locked in
warehouses. Too little means stock-outs and lost sales. Planners need to know:

* Which products drive most of the value? (**ABC**)
* Which products have predictable demand, and which are erratic? (**XYZ**)
* How much **safety stock** does each product need for a target service level, and when should it be
  reordered? (**reorder point**)
* What should be ordered now, and at what cost? (**replenishment plan**)
* What does a higher service level cost? (**scenario analysis**)

## 2. Key features

| Area | What you get |
|---|---|
| Data input | Synthetic sample dataset (2,400 SKUs) **or** CSV upload with templates, preview and validation |
| Validation | Missing columns/values, types, invalid dates, negatives, zero prices, invalid lead times, duplicate keys, orphan references, empty/incompatible files. Every excluded row is listed with the reason and how to fix it |
| Storage | **CSV mode** (no database) and **PostgreSQL mode** (relational tables, keys, indexes, SQL analytics) |
| Analytics | Demand statistics, trends, weekday/monthly seasonality, outlier flags, ABC, XYZ, 9-group matrix |
| Inventory | Safety stock (demand + lead-time variability, or fixed lead time), reorder point, stock position, alerts, potential stock-out risk |
| Planning | Order-up-to replenishment respecting MOQ and order multiples, cost estimate, CSV export |
| Scenarios | 90% / 95% / 99% (and others) service levels, plus what-if demand and lead-time changes |
| Reports | Cleaned inventory, ABC/XYZ classification, reorder recommendations, stock-out risk, scenarios, supplier review and data quality, all as CSV |
| Login | Accounts with salted PBKDF2 password hashes, admin/analyst roles, lockout after failed attempts, idle timeout, user management |
| Tests | 116 Pytest tests: formulas, classification, validation, planning, reports, login, database and every UI page |

## 3. Technology stack

Python 3.11 · Pandas · NumPy · PostgreSQL (psycopg2) · SQL (CTEs, window functions) · Streamlit ·
Plotly · Pytest · python-dotenv · Git/GitHub.

## 4. Project structure

```
app.py                         Entry point: login gate, navigation, sidebar (user, data badge, service level)
app_pages/                     (not named pages/ on purpose - see the note below)
  1_Data_Management.py         Home: mode, sample/upload, templates, validation report, settings, PostgreSQL
  2_Executive_Overview.py      KPIs and distribution charts
  3_Inventory_Analysis.py      Product table, stock levels, demand trends, excess, SQL analytics
  4_ABC_XYZ_Analysis.py        ABC, XYZ, Pareto curve, 3x3 matrix, recommendations
  5_Replenishment_Planning.py  Alerts, safety stock / ROP, suggested orders, export
  6_Scenario_Analysis.py       Service-level comparison and what-if analysis
  7_Business_Insights.py       Findings, supplier review, all downloads
  8_Account.py                 Change password; administrators manage users
assets/                        Logo (SVG)
.streamlit/config.toml         Theme colours and toolbar settings
src/
  auth/        passwords.py (hashing, password rules), user_store.py (accounts, lockout, roles)
  config.py                    Paths, default settings (single place for all assumptions)
  data/        schema.py (file definitions), sample_generator.py, loader.py, cleaning.py, quality.py
  validation/  validator.py    File, row and cross-file validation
  analytics/   demand.py, classification.py, kpis.py, suppliers.py, pipeline.py
  inventory/   formulas.py (all inventory formulas), stock.py, planning.py, scenarios.py
  database/    connection.py, repository.py, queries.py
  reporting/   exports.py      CSV report builders
  ui/          state.py, components.py, charts.py, theme.py, auth.py (Streamlit-only helpers)
sql/
  schema.sql                   Tables, keys, constraints, indexes
  analytics/*.sql              9 documented analysis queries used in PostgreSQL mode
tests/                         Pytest suite
data/sample/                   Generated synthetic CSVs (not committed; recreated on first run)
```

The calculation modules (`src/analytics`, `src/inventory`) have no Streamlit code, so they are
reusable and testable. Pages only call them and display results.

**Why `app_pages/` and not `pages/`:** Streamlit treats a folder called `pages/` as an automatic
multipage app and can then run a page script without `app.py`, which would skip the login gate and
the sidebar. Pages are registered explicitly with `st.navigation` in `app.py` instead.

## 5. Dataset schema

Mandatory columns must exist and be filled in. Optional columns may be missing entirely or blank.
Dates use `YYYY-MM-DD`. Common alternative names (`sku`, `qty`, `date`, `lead_time` ...) are mapped
automatically. Templates can be downloaded on the Home page.

**Products & Inventory** (required, one row per SKU)

| Column | Type | Mandatory | Rule / meaning |
|---|---|---|---|
| sku_id | text | Yes | Unique product ID |
| product_name | text | Yes | |
| category | text | Yes | |
| unit_cost | number | Yes | > 0 |
| selling_price | number | Yes | > 0 (warning if below cost) |
| on_hand_qty | number | Yes | >= 0 physical stock |
| reserved_qty | number | Optional | >= 0, blank = 0 |
| min_order_qty | number | Optional | > 0, blank = no minimum |
| order_multiple | number | Optional | > 0 pack size, blank = 1 |
| supplier_id | text | Yes | Should exist in the suppliers file |
| snapshot_date | date | Yes | Date of the stock count |

**Sales History** (required): `sale_date` (date, Yes), `sku_id` (Yes, must exist in products),
`quantity_sold` (>= 0, Yes), `revenue` (>= 0, Optional). Several rows for the same SKU and day are summed.

**Suppliers & Lead Times** (required): `supplier_id` (Yes, unique), `supplier_name` (Yes),
`avg_lead_time_days` (> 0 and <= 365, Yes), `lead_time_std_days` (>= 0, Optional).

**Purchase Orders** (optional): `po_id`, `sku_id`, `order_qty` (> 0), `order_date`,
`expected_delivery_date` (>= order date), `actual_delivery_date` (Optional), `status`
(`open`, `in_transit`, `received`, `cancelled`). `po_id + sku_id` must be unique.

### Validation and cleaning rules

* **File-level errors** (empty file, header only, missing required columns, `;` separator, duplicate
  column names, required file missing) **block** the analysis.
* **Row errors** (bad number/date, missing mandatory value, negative or zero where not allowed,
  invalid status, impossible PO dates, conflicting duplicate IDs, SKU not in products) **exclude the
  row**. For uploads you must tick a confirmation before analysing with exclusions.
* **Exact duplicate rows**: the first is kept, the copies are excluded and reported.
* **Warnings** keep the row (price below cost, reserved > on-hand, supplier not found, received order
  without delivery date, open order that already has a delivery date).
* **Outliers** (a day above the SKU's mean + 4 standard deviations) are flagged, never removed.
* Uploaded files are only read in memory; the originals are never modified.

## 6. Sample data

`src/data/sample_generator.py` creates a **synthetic** dataset with a fixed random seed (42), so it is
identical on every run. It is written once to `data/sample/` and re-used; the app never regenerates it
on rerun. Contents: 2,400 SKUs in 10 categories, 40 suppliers (6 without a lead-time standard
deviation), 365 days of daily sales (551k rows) with stable, seasonal, trending, intermittent and
zero-demand products, ~7,400 purchase orders (received, cancelled, open, in transit), 8 suppliers that
deliver ~30% later than stated, stock-outs and excess stock. **30 duplicate and 6 negative sales rows
are injected on purpose** to demonstrate validation. Supplier names carry "(Synthetic)". All screens
show a "SYNTHETIC data" badge.

Regenerate manually: `python -m src.data.sample_generator`

## 7. Installation (Windows, PowerShell)

```powershell
cd "E:\DA Projects\Supply Chain & Inventory Optimization Dashboard"
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
streamlit run app.py
```

The browser opens at <http://localhost:8501>.

1. **Register:** open the *Register* tab and create an account (password: at least 8 characters with a
   letter and a number). The **first account registered becomes the administrator**; later ones are
   analysts. Save the **recovery code** shown after registering.
2. **Sign in** with your username and password on later visits.
3. **Forgot password:** open the *Forgot password* tab, enter username + recovery code + new password.
4. On the Home page choose **CSV mode -> Use Sample Dataset -> Load sample dataset**, then use the
   pages in the sidebar. If PowerShell blocks `activate`, run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or call `.venv\Scripts\python.exe -m streamlit run app.py`.

### Using your own CSV files

1. Home page -> CSV mode -> **Upload My Own Data**.
2. Download the templates, put your data in the same columns and save as **CSV UTF-8 (comma
   delimited)**.
3. Upload products, sales and suppliers (and optionally purchase orders), check the preview and click
   **Validate files**.
4. Read the validation report. Fix blocking errors. If some rows will be excluded, tick the
   confirmation and click **Use this data for analysis**.

## 8. Login and user accounts

| Feature | How it works |
|---|---|
| Storage | `data/users.json` (change with `AUTH_USERS_FILE`). Excluded from Git. Works without PostgreSQL |
| Passwords | Never stored. Salted **PBKDF2-HMAC-SHA256** hash (310,000 iterations), constant-time comparison |
| Password rules | At least 8 characters, a letter and a number, not equal to the username |
| Roles | **admin**: everything, plus user management and writing to PostgreSQL. **analyst**: load data and use all analysis pages |
| Brute force | 5 wrong passwords lock the account for 5 minutes. The message never reveals whether a username exists |
| Session | Signed-in user kept in server-side session state; signs out after 30 idle minutes (`AUTH_SESSION_MINUTES`). Sign out clears all loaded data |
| Registration | Anyone can register on the sign-in screen. First account = admin, all later accounts = analyst |
| Forgot password | Uses a one-time **recovery code** (e.g. `K7QM-2XPA-9RTD-HV4C`) shown at registration and stored only as a hash. After a reset the old code stops working and a new one is shown. Wrong codes count towards the lockout. No e-mail server is needed |
| New recovery code | *Account* page -> *Create new recovery code* (needs the current password). Accounts created by an admin start without a code |
| Admin tools | *Account & Users* page: add users, reset passwords (also unlocks), change roles, delete users. The last administrator cannot be removed |

Lost both the admin password and the recovery code? Stop the app, delete `data/users.json` and start
again; the next account registered becomes the administrator (other accounts in that file are lost).

## 9. PostgreSQL setup (optional)

1. Create a database, e.g. in psql: `CREATE DATABASE inventory_dashboard;`
2. Copy `.env.example` to `.env` and fill in host, port, database, user and password
   (`.env` is excluded from Git). You can also type the values into the connection form; the
   password is then kept in memory only.
3. Home page -> **PostgreSQL mode** -> *Test connection* -> *Create / update tables* (creating tables and storing data are **admin-only**; analysts can analyse stored data).
4. *Store the sample dataset* (or load/upload data in CSV mode first and *Store the currently loaded
   dataset*). Storing **replaces** the data in the tables, in one transaction.
5. *Analyse data stored in PostgreSQL*. The data read back goes through the same validation as CSV
   files. The **SQL analytics** tab on *Inventory Analysis* then runs the queries in `sql/analytics`,
   with reconciliation checks against the Python results.

If the connection fails, the app shows the reason and stays in PostgreSQL mode. It never switches data
source silently; select CSV mode yourself to continue without a database.

Tables: `suppliers`, `products`, `inventory_snapshots`, `sales_history`, `purchase_orders`,
`inventory_metrics` (Python-calculated safety stock/ROP, so SQL uses the same formulas),
`dataset_metadata`. These have primary and foreign keys, CHECK constraints and indexes on category,
supplier, sale date and PO status.

SQL queries (parameterised, `%(name)s`): inventory value by category · highest-value products ·
sales by SKU and date (zero-filled, 7-day moving average) · demand summary · supplier lead-time
analysis · products below reorder point · ABC support (window functions) · inventory rankings
(RANK, DENSE_RANK, PERCENT_RANK, NTILE) · CTE inventory health.

## 10. Formulas and assumptions

All inventory formulas live in `src/inventory/formulas.py` and are covered by tests.

| Metric | Formula |
|---|---|
| Average daily demand d | units in window / days in window |
| Demand variability sigma_d | **sample** standard deviation (n-1) of the daily series |
| Safety stock (combined) | Z x sqrt(L x sigma_d^2 + d^2 x sigma_L^2) |
| Safety stock (fixed lead time) | Z x sigma_d x sqrt(L) |
| Reorder point | d x L + safety stock |
| Stock position | on-hand - reserved + open and in-transit POs |
| Target stock level | ROP + d x target coverage days (default 30) |
| Suggested order | if stock position <= ROP: target - stock position, raised to MOQ, rounded up to order multiple |
| Inventory value | on-hand x unit cost |
| Annual holding cost (est.) | average inventory value x holding-cost rate (default 25%) |
| Inventory turnover | COGS / average inventory value (annualised when the window < 1 year) |
| Days of inventory on hand | days in period / period turnover |
| Excess units | available - (target level + d x excess buffer days (default 60)), min 0 |
| Annual consumption value | annual demand x unit cost |
| CV | sigma_d / d |

* **Service levels**: 90% -> Z 1.282, 95% -> 1.645, 99% -> 2.326 (others use the inverse normal).
* **Independence**: demand and lead time are assumed independent; lead-time demand is assumed roughly
  normal. Alerts are *potential* risks under these assumptions, never certainties.
* **Lead-time variability source** per supplier: (1) `lead_time_std_days` in the suppliers file;
  (2) otherwise the sample std of observed lead times from at least 3 received POs;
  (3) otherwise the fixed-lead-time model is used. The average lead time always comes from the
  suppliers file.
* **Incoming stock** = POs with status `open`/`in_transit` and no actual delivery date. Received and
  cancelled orders never count.
* **Missing sales days**: by default a day without a record is zero demand (the sales file is treated
  as a complete log). Days on which no SKU sold anything are reported as possible data gaps. This can
  be switched off in the settings.
* **ABC**: products are ranked by value; a product is A while the cumulative share *before* it is
  < 80%, B while < 95%, otherwise C. Zero-value products are always C. With less than a year of
  history, annual values are labelled as annualised estimates.
* **XYZ**: X if CV <= 0.50, Y if CV <= 1.00, Z above. Zero mean -> "No Demand"; fewer than 28 days of
  history -> "Insufficient Data".
* **Alert statuses**: Insufficient Data -> Reorder Required (position <= ROP) -> Low Stock (available
  <= safety stock but incoming keeps position above ROP) -> Excess Inventory Review -> No Recent Demand
  -> Above Reorder Point.
* **Average inventory**: only one snapshot per SKU exists, so current inventory value is used as the
  estimate of average inventory.

All thresholds are configurable on the Home page (Analysis settings).

## 11. Calculated findings (synthetic sample dataset, default settings, 95% service level)

These come from running the app on the synthetic data. They describe that data, not a real business.

* **Inventory value $33.09M** across 2,400 SKUs (1.35M units). Electronics holds 36% of it.
* **ABC**: 512 A products (21% of SKUs) make up 80.0% of annual consumption value; 1,207 C products
  (50%) make up 5.0%.
* **XYZ**: 461 X, 900 Y, 934 Z and 105 No-Demand products. The matrix has 211 AX (predictable, high
  value) and 159 AZ (high value, erratic) products.
* **Turnover** 3.67 per year, **about 99 days of inventory on hand**. Estimated annual holding cost:
  $8.27M at 25%.
* **591 products require reorder**, 85 are Low Stock waiting for incoming orders, and 150 with demand
  are out of stock. Suggested replenishment is about $4.34M.
* **125 class-A products have a potential stock-out risk**, with about $0.89M revenue exposure over one
  lead time.
* **Excess stock estimate: $12.56M in 597 products**, led by Electronics ($4.22M). 104 products
  without any sales still hold $0.38M of stock.
* **Scenarios**: safety-stock investment is $3.55M at 90%, $4.55M at 95% (+$1.00M) and $6.43M at 99%
  (+$2.89M vs 90%). Going from 95% to 99% costs almost twice as much as going from 90% to 95%.
* **8 suppliers need a lead-time review** (actual lead times about 30% above stated, low on-time
  rates), affecting 487 SKUs. 348 SKUs use a lead-time std estimated from PO history.
* Validation found and excluded the 30 injected duplicate and 6 negative sales rows.

## 12. Screenshots

Add your own screenshots after running the app, for example:

```
docs/screenshots/home.png          Home & data validation
docs/screenshots/overview.png      Executive Overview
docs/screenshots/abc_xyz.png       ABC/XYZ matrix
docs/screenshots/replenishment.png Replenishment plan
docs/screenshots/scenarios.png     Scenario comparison
```

## 13. Testing

```powershell
.venv\Scripts\activate
python -m pytest
```

116 tests cover formulas (hand-checked examples such as 1.645 x sqrt(9x4 + 10^2x4) = 34.35), ABC
thresholds and ties, XYZ boundaries, zero demand, zero variance, zero lead-time variability, service
level changes, stock position and incoming POs, password hashing, lockout, roles, registration, recovery-code password reset, the sign-in / sign-out / timeout flow, MOQ and multiples, insufficient data, validation of
invalid/missing/duplicate/orphan data, empty files, reports, database error handling, and every
Streamlit page (via `streamlit.testing`).

PostgreSQL integration tests (round trip, SQL vs Python reconciliation, full UI workflow) are skipped
unless a **disposable** test database is configured:

```powershell
$env:TEST_PGHOST="localhost"; $env:TEST_PGPORT="5432"; $env:TEST_PGDATABASE="inventory_dashboard_test"
$env:TEST_PGUSER="postgres"; $env:TEST_PGPASSWORD="your_password"
python -m pytest
```

## 14. Limitations

* One stock snapshot per SKU: no stock-level trend, and average inventory = current inventory.
* **Inventory aging is not calculated**, because receipt dates per stock lot are not part of the inputs.
* Sales are used as demand. Days when a product was out of stock record lower sales than real demand
  (censored demand), which can understate demand.
* Demand is described by historical mean and variance. There is no forecasting, trend or seasonality
  adjustment in the safety-stock formula (seasonality is shown separately for review).
* Normality and independence assumptions can understate the safety stock needed for very
  intermittent (Z) items.
* Each product has one supplier; costs exclude freight, discounts and taxes.
* PostgreSQL mode stores one dataset at a time (storing replaces the tables).
* Login is designed for a local or small-team deployment. Reloading the browser tab starts a new
  session (sign in again). For internet-facing use, run behind HTTPS and consider a central identity
  provider (Streamlit `st.login` with OpenID Connect).
* Estimates are not proven savings. Measuring savings needs before-and-after data.

## 15. Future improvements

* Multiple stock snapshots for stock trends and true average inventory.
* Lot-level receipts for inventory aging.
* Seasonal / trend-adjusted demand rates in safety stock.
* Multi-supplier and multi-location inventory.
* Excel/PDF report export.

## 16. Publishing to GitHub

Review the repository first, then:

```powershell
git init
git add .
git status            # check that .env, .venv, data/users.json and data/sample/*.csv are NOT listed
git commit -m "Supply Chain & Inventory Optimization Dashboard"
git branch -M main
git remote add origin https://github.com/<your-username>/supply-chain-inventory-optimization.git
git push -u origin main
```
