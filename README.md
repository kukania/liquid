# Liquid consumption planner

Plan monthly spending, transfers and accumulated balances for January through December.

## Run

Use Python 3.11 or later:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

A portable Python runtime used for verification is also available locally in `.runtime`.
It is ignored by Git. Install dependencies in your normal environment for development.

## Finding your way around the code

Start with `main.py`, which builds the app and restores saved inputs. The main paths are:

- `timeline.py`, `box.py`, and `drag_to_connect.py`: monthly cards, layout and gestures.
- `money_object.py`: accounts and other planning objects, with their edit dialogs.
- `periodic_plan.py` and `periodic_plan_designer.py`: transfer models and the graph editor.
- `planner_state.py`: converts UI models to plain data, saves changes, and rebuilds results.
- `projection.py`: calculates monthly balances using integer cents, without UI or network calls.
- `storage.py`: SQLite tables, transactions and schema upgrades.
- `bank_panel.py`: bank-link controls; `banking.py`: Plaid requests and encrypted tokens.

A planning edit flows through `timeline._update_page()` to `planner_state.refresh()`.
Refresh takes a snapshot, calculates the results, saves the inputs, and rebuilds balance
cards. Bank refreshes use separate tables and do not enter this calculation path.

## GitHub workflow

The repository remote is `git@github.com:kukania/liquid.git` (SSH).
Run `git remote -v` to display it. SSH access requires a key registered with GitHub.

For future changes, create a branch with `git switch -c feature/your-change`, make and
test the changes, inspect `git diff`, then stage the intended files and commit them.
Use `git push -u origin feature/your-change` to publish that branch and open a pull
request on GitHub. Configuring a remote alone does not upload any code.

The local database, portable Python runtime, and `.env` files are ignored by Git.
Keep Plaid credentials out of source code and commits.

## Planning

- Create money objects with a January starting balance. For externally funded objects,
  enter monthly external income separately. Starting balances are not repeated as income.
- Add consumption by choosing its month, amount and paying object. Click a consumption
  card to edit it, click its trash button to delete it, or drag its body to a different
  month. Deletion is also available in the edit dialog and through a long press.
- Drag a Sources card onto a consumption card to change its paying object.
- Use the periodic-plan designer to add transfers, set active months, and order each
  source's transfers. Save periodic plans to apply the designer's transfer changes.
- Sources shows opening balance plus that month's external income. Savings shows the
  projected closing balance for every money object. Click or hover over a balance card
  for its breakdown. These cards are calculated, not independently editable balances.
- Timeline rows appear only for months containing consumption plans. Hidden months
  still contribute to accumulated balances. Removing a month's last consumption
  plan hides its row; no consumption plans means the timeline is hidden.
- Remainder transfers run after consumption and earlier-priority transfers. For example,
  $5,000 income minus $2,000 consumption and $500 to 401K sends $2,500 to Savings.
  With $2,000 already saved, the Savings card shows a $4,500 closing balance.
- Load example data is available in an empty planner: $5,000 monthly Paycheck income,
  $10,000 starting in 401K and $2,000 in Savings. Transfer $500 to 401K and then the
  remainder to Savings. No example is inserted automatically on restart.

## Calculation rules

1. Carry forward the previous closing balances (January uses starting balances).
2. Add recurring external income, once each month.
3. Deduct all consumption for that month from its paying object.
4. Apply active periodic transfers in ascending priority order. Equal priorities use
   the stored transfer order. Each transfer executes at most once per month, including
   when a graph contains a cycle.
5. Carry closing balances into the following month, including months with no spending.

Fixed transfers are all-or-nothing: an unaffordable transfer is skipped and later
transfers are still evaluated. A remainder transfer moves the nonnegative balance
remaining at its turn. Consumption may leave a negative balance; it is never silently
reduced. Failed periodic transfers mark both source and destination Savings cards in
red, with requested amount, available funds and shortfall in the breakdown. Consumption
shortfalls mark the paying object's Savings card red too. Warnings describe the affected
month even if a later incoming transfer restores funds.

Money calculations and database amounts use integer cents. User amounts are rounded to
cents using decimal half-up rounding. Transfers preserve total money; external income
increases it and consumption decreases it. No interest, investment returns or taxes are
inferred. The current projection is a single January?December year, with external income
repeating every month; periodic transfers have inclusive start/end months.

## Storage

`planner.sqlite3`, beside `main.py`, stores money objects, periodic transfers, consumption
plans and display settings. Validated edits save automatically in a SQLite transaction.
Only inputs are stored; monthly results are recalculated on load and after edits. Close
the app before copying this file for a backup. Deleting a money object also deletes its
transfers and consumption plans, after the existing deletion confirmation.

## Verification

```powershell
python -m unittest test_projection test_planner_integration test_banking
```

Tests cover calculation order, carry-forward, remainder transfers, shortfalls, exact-cent
rounding, SQLite reload/rollback, object edits/deletion, payer assignment and responsive
control construction. They do not replace a visual desktop interaction check.

## Plaid Sandbox bank linking (Windows desktop)

The Linked bank accounts section connects **test accounts only** through Plaid Hosted
Link. Real bank linking and Production are not enabled in this build.

Create a Plaid developer account and obtain your Sandbox client ID and secret from
[the Plaid Dashboard](https://dashboard.plaid.com/). Set these environment variables
in the PowerShell session that launches the app (replace the placeholders locally):

```powershell
$env:PLAID_ENV = "sandbox"
$env:PLAID_CLIENT_ID = "your-client-id"
$env:PLAID_SECRET = "your-sandbox-secret"
.\.runtime\python.exe main.py
```

The app reads environment variables directly; it does not load `.env` files. Never put
keys in source code. No additional Python dependencies are needed for this integration.

1. Click **Connect bank (Sandbox)** and complete Link in the browser. Use the test
   credentials provided by Plaid, usually `user_good` / `pass_good`.
2. Return to Liquid and click **Check connection**. If data is still being prepared,
   use **Refresh** after a short wait.
3. Map an account to an existing money object if useful. This records an ID-based
   relationship only; it does not overwrite January balances or create spending plans.
4. Use **Disconnect** to revoke a connection and remove its local bank records.
   A failed revocation retains the connection so you can retry.

Current and available balances, currency, account mask and fetch time are stored
separately from projections. Unknown balances remain unavailable, not zero.
`/accounts/get` returns the latest available cached balances; the displayed fetch time
is not a guarantee that the bank balance is current at that instant. Account mappings
survive ordinary planner saves and become unmapped if their money object is deleted.
Only the latest observation per account is retained in this milestone.

Access tokens are protected using Windows DPAPI and saved as encrypted blobs in SQLite.
They can be decrypted by the same Windows user; database backups alone are not portable
bank credentials. API secrets remain in the launching process environment. This is a
personal desktop integration, not a backend suitable for distributing API credentials.

The Link session stays in memory while the app is running. Complete it before closing
the app. Cancel closes the local session; close its browser tab too. Avoid linking the
same institution twice: duplicate-institution reconciliation is not implemented.
Expired bank authorization currently requires disconnecting and linking again.

This uses the Transactions product to initialize Sandbox Link, but does not import
transactions or initiate payments. Future work includes Production setup, reconnect
mode, transaction reconciliation, and dated forecast starting balances.
See [Plaid Hosted Link](https://plaid.com/docs/link/hosted-link/) and
[Accounts API](https://plaid.com/docs/api/accounts/) for the underlying flow.

Banking tests use mocked Plaid responses plus a real Windows DPAPI round trip; no bank
credentials are needed. DPAPI requires the normal Windows user context and may fail in
a restricted sandbox. Browser interaction and live Sandbox API calls need separate
verification with configured keys.
