# Tualatin Water bills

Downloads the monthly utility bills of your Tualatin Water account (water,
sewer, stormwater, parks and road fees) from CivicPay Online,
`tualatin.merchanttransact.com`, as PDFs, about two years of them. The
portal has no PDF of a bill, so each bill's print page is drawn as one.
This reads from a browser where you sign in yourself, with your password,
on the port named in `config.json` (see `config.example.json`, port 9302).
Passwords are never handled by the downloader.

Read-only, delete-safe, part of [PaperPull](../../README.md).

## Setup and use

1. Run `setup.command` (macOS) or `setup.bat` (Windows).
2. Copy `config.example.json` to `config.json` and set your local output folder.
3. Run `login.command` / `login.bat` and sign in yourself. Leave the window open.
4. Run `paperpull tualatin diagnose`, then `paperpull tualatin pilot` (one bill).
5. Check the downloaded bill before using `paperpull tualatin all`.

## How it works

Nothing is ever clicked. CivicPay Online keeps its session in a cookie, so
the app opens Activity, `/secure/Activity`, by its address, in your
CivicPay tab or, with none open, in a tab of its own. A tab of another
site is never used.

- **The list.** Activity draws one table, Transaction Date, Transaction
  Type, Description, Amount and Balance, a row per bill or payment. A
  Billing row links to its bill, `/secure/MyBill/<bill number>`, and a bill
  is known by that number.
- **Whole or stopped.** The table was seen with every transaction on one
  page. A pager, a count that is not the rows read, a date filter, a
  choice of accounts, or a table with no bills stops the list rather than
  being called whole. So does a row of a type other than Billing or
  Payment, named in what the run prints, a Billing row with no single bill
  link, a date that is not a calendar date, or one bill number twice.
- **The bill.** Each bill's print page, `/secure/MyBill/<bill
  number>/Print`, is fetched from inside the signed-in page, no redirect
  followed. Its own text, read before anything is written into it, must
  carry Bill Details, Billing Date and Total Amount Due, and its Billing
  Date must be the date its Activity row gives. Its stylesheets and images
  from the portal's own host are written into it: an `@import` is dropped
  and a `<` in a stylesheet is escaped. The page is then drawn as a PDF
  with every script, frame and form taken out, offline, so it loads
  nothing.
- **A budget.** The page, each stylesheet as written in and each image as
  its data address count against one 5 MB budget. Each answer is read
  through PaperPull's bounded reader, and one that does not fit is left
  out of the page and noted in the run's trace.
- **Signing out.** A redirect, a 401 or 403, or a print page asking for a
  password stops the run and keeps what it saved. Sign in again and run
  Resume. Any other answer that is not a printed bill fails that one bill.

## Validation status

Built from a signed-in survey of one account on 2026-10-29. Activity
listed 48 transactions, 24 of them bills, and a run saved all 24, each
bill's Billing Date matching its row. Not yet seen:

- An Activity with more transactions than that, so whether the portal
  pages or filters a longer one by date. Either stops the list.
- More than one account on one sign-in, which stops the list.
- An Activity with no bills, which stops the list.
- A row type other than Billing and Payment, which stops the list.

Never touched are payments, scheduled payments, autopay, the wallet, bank
accounts and cards, paperless, exports and account settings. Your account
number is kept out of every log and diagnostic file.

## Tests

```
python -m pytest tests -q
```

Run from this folder with PaperPull's bundled Python. They use invented
values only. The browser tests start PaperPull's bundled Chromium on made-up
host names, so nothing reaches Tualatin Water.
