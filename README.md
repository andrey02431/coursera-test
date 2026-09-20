# Blackboard Sync (University of Southampton)

A local tool that logs into University of Southampton's Blackboard **once**
(you complete 2FA yourself, in a real browser window it controls), saves
that authenticated session to disk, and then reuses it on a schedule to pull
down course content into a structured local folder — without you ever
having to log in by hand again, until the saved session eventually expires.

It runs entirely on **your own machine**. Your Southampton credentials and
session are never sent anywhere except blackboard.soton.ac.uk itself, and
nothing about your account is stored in this repository.

## How the 2FA problem is solved

Blackboard sits behind Southampton's SSO, which enforces 2FA on every
interactive login. There is no way to script around that safely or
reliably (and you shouldn't want to — 2FA is protecting your account).
Instead:

1. You run `bbsync login` once. This opens a real, visible Chromium window.
2. You log in and complete 2FA exactly as you always do.
3. Once you land on your Blackboard dashboard, you confirm in the terminal.
4. The tool saves the authenticated browser profile (cookies + local
   storage) to `.auth/profile/` on disk.
5. Every future `bbsync sync` run reuses that saved profile headlessly —
   no login prompt, no 2FA prompt, no browser window.

Southampton's SSO session will eventually expire (typically after some
number of days of inactivity, or on a fixed re-auth policy your IT sets).
When that happens `bbsync sync` will detect it, refuse to silently fail,
and tell you to run `bbsync login` again. This is a normal, expected part
of using the tool — not a bug.

**`.auth/profile/` is equivalent to a logged-in browser. Never commit it,
share it, or back it up to a public location.** It's already excluded via
`.gitignore`.

## What it downloads

Configurable in `config/config.yaml` (all on by default):

- **Files & materials** — everything under each course's Content /
  Learning Materials areas (PDFs, slides, docs, etc.), mirrored into
  folders that match Blackboard's own structure (e.g. `Week 3/Reading list/`).
  This is the highest-priority content type and is synced first.
- **Content item text** — the body/description text of content
  pages themselves (not just attachments), saved as `.html` next to a
  `.meta.json` with title/dates/links.
- **Announcements** — saved as dated HTML files per course.
- **Grades** — your own marks/feedback per course, saved as JSON.
- **Discussion boards** — thread text, saved as HTML per forum/thread.

Each sync is **incremental**: a manifest (`data/<course>/.manifest.json`)
tracks what's already been downloaded (by Blackboard's content ID + a
hash/size check), so re-runs only fetch what's new or changed instead of
re-downloading everything.

## Folder layout produced

```
data/
  BIOL1001 - Introduction to Biology/
    course.meta.json
    content/
      Week 1/
        lecture-slides.pptx
        Lecture overview.html
        Lecture overview.meta.json
      Week 2/
        ...
    announcements/
      2026-09-15__welcome-to-the-module.html
    grades/
      grades.json
    discussions/
      General discussion/
        thread-why-is-the-sky-blue.html
    .manifest.json
logs/
  sync-2026-09-20T10-00-00.log
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

cp config/config.example.yaml config/config.yaml
# edit config/config.yaml: set base_url to your Blackboard URL,
# e.g. https://blackboard.soton.ac.uk
```

### First-time login

```bash
python -m blackboard_sync login
```

A Chromium window opens. Log in, complete 2FA, wait until you see your
Blackboard dashboard, then press Enter in the terminal.

### Check the session is still valid (no download)

```bash
python -m blackboard_sync status
```

### See what courses/content would be found, without downloading

```bash
python -m blackboard_sync discover
```

Use this first. Blackboard's page structure is heavily customised per
institution, so the CSS selectors in `config/selectors.yaml` are a
best-effort starting point and will likely need small adjustments for
Southampton's actual theme. Run with `--debug-dump` to save the raw HTML
and a screenshot of every page visited into `debug/`, so you (or anyone
helping you) can see exactly what the tool sees and fix selectors quickly:

```bash
python -m blackboard_sync discover --debug-dump
```

### Run a full sync

```bash
python -m blackboard_sync sync
```

Run it for one course only:

```bash
python -m blackboard_sync sync --course <course-id-from-discover-output>
```

## Scheduling it so you never have to run it manually

`sync` exits non-zero and writes a clear message if the saved session has
expired, so it's safe to schedule — it will simply no-op/fail loudly
rather than doing anything destructive.

### Linux/macOS (cron)

```
# Sync every day at 07:00
0 7 * * * /path/to/coursera-test/scripts/run_sync.sh >> /path/to/coursera-test/logs/cron.log 2>&1
```

### Windows (Task Scheduler)

Create a task that runs:

```
C:\path\to\.venv\Scripts\python.exe -m blackboard_sync sync
```

with "Start in" set to the project folder.

If a scheduled run fails because the session expired, you'll see it in
`logs/` (and the run exits non-zero, so Task Scheduler/cron will flag it).
Just run `bbsync login` again when that happens.

## Adjusting selectors

All Blackboard DOM selectors live in `config/selectors.yaml`, not
hardcoded in the Python. If Blackboard changes its UI, or the defaults
here don't match Southampton's exact skin, edit that file — no code
changes needed for most breakage. Use `--debug-dump` (above) to inspect
the real markup and fix a selector.

## Ethics / acceptable use

This only ever acts as *you*, downloading content *you're* already
enrolled in and entitled to see, on *your own* machine. Even so:

- Check Southampton iSolutions' acceptable-use policy for any explicit
  restriction on automated access to Blackboard before scheduling this.
- The default request delay (`request_delay_seconds` in config) is set
  conservatively to avoid hammering the server — don't lower it.
- Don't share your `.auth/profile/` directory or downloaded course
  materials in ways that would violate module copyright/sharing rules.

## Related project

[`sanjacob/BlackboardSync`](https://github.com/sanjacob/BlackboardSync) is
a mature, actively maintained open-source app that does similar
file-syncing for many other UK universities via Blackboard's REST API. It
doesn't currently list Southampton and doesn't cover announcements,
grades, or discussions, which is why this tool exists — but it's worth
knowing about if you outgrow this one or want a GUI.

## Development

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

Only `storage`/`manifest` logic is unit-tested (pure, no network). The
Playwright scraping logic can't be meaningfully tested without a real
Blackboard session, so treat `discover --debug-dump` as your test loop
against the real site.
