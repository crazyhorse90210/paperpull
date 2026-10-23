# Bank of America statement downloader

Will download your own **Bank of America statements** as PDFs, for your
records. Read-only, delete-safe, and part of [PaperPull](../../README.md).

**NOT BUILT YET.** This is a first shell, made for
[issue #121](https://github.com/rheeloaded/paperpull/issues/121). It opens
Bank of America's site in a browser profile of its own so you can sign in,
and it lets Record and Diagnose watch the page you leave open. That is all
it does. Discover, Pilot, Run All and Resume say it is not built yet and
stop, and nothing is listed or downloaded. Which page lists statements and
how a statement's PDF arrives cannot be seen without an account, so the
real app is built from a recording of one trip to a statement, made by
someone who banks there.

## Help test it, no programming needed

1. Install PaperPull from the [latest release](https://github.com/rheeloaded/paperpull/releases/latest)
   and open the control panel.
2. Click **add a provider** and tick **Bank of America**. Pick it in the
   App list.
3. Click **Login**. Your own Edge or Chrome opens on bankofamerica.com,
   with a separate profile. Sign in yourself, answer any code it sends,
   and leave the window open.
4. In that window, open the page with your statements on it, the way you
   normally would.
5. Click **more** under the buttons, then **Record**. Go back to the
   browser and click your way to one statement PDF, at your normal pace,
   then come back and click **Stop recording**. It writes
   `Diagnostics\recording.json`, records nothing you type and reads no
   cookies. The whole walkthrough is
   [Testing a provider](../../docs/testing-a-provider.md).
6. Open `recording.json` in Notepad and read it through. If anything in it
   looks personal, delete that line.
7. Attach it to [issue #121](https://github.com/rheeloaded/paperpull/issues/121),
   with a sentence or two about anything the recording cannot show, such
   as how far back the statements go or whether a card's statements sit
   apart from checking's.

**If a run stops early, send the file it wrote.** Every failed run leaves a
`failure-*.json` in the `Diagnostics` folder and prints where it put it. It
says which step broke and what the page looked like at the time, as counts
and states, with no text from your account in it. Attach it to the issue
the same way. A Discover or Pilot that says this app is not built yet is
not a failure and writes none.

## Sign-in

Sign-in uses your own installed Edge or Chrome, in a separate profile. You
sign in yourself, answer your own code, and leave the window open. The app
never sees your password. Login says what the window shows, a sign-in form
or a check, and since this first build does not read your accounts it
never says you are signed in.

## Safety

Bank of America moves money, through transfers, Zelle and bill pay. This
first build presses nothing on the bank's pages at all. Login opens the
home page in a tab of its own only when no tab of yours is on the site,
and Diagnose reads the page you left open and follows nothing. Every
address it will act on is on `bankofamerica.com`.

## Commands

```
paperpull bofa setup
paperpull bofa login        sign in yourself, leave the window open
paperpull bofa record       record one trip to a statement, press Enter to stop
paperpull bofa diagnose     survey the page you left open, download nothing
```

Discover, Pilot, All and Resume say this app is not built yet and stop.

## Tests

```
python -m pytest tests -q
```
