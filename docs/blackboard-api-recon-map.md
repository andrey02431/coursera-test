# Blackboard API recon map

Quick-reference briefing for Claude (or anyone) picking this project up
cold. For the narrative of *how* each of these was found - debugging
dead ends, screenshots, what broke and why - see
`docs/blackboard-api-notes.md` instead. This file is the map, not the
journey: what's confirmed, what's still guesswork, and where to look for
more.

Institution: University of Southampton, `blackboard.soton.ac.uk`,
Blackboard Learn Ultra (SaaS), version `4001.2.0-rel.68` at time of
writing. Endpoint shapes are almost certainly similar at other Blackboard
Ultra SaaS institutions but **unverified** anywhere but this one tenant.

## Auth model (read this first)

- No OAuth, no API keys. Every endpoint below is same-origin,
  cookie-authenticated - the exact session cookies a normal logged-in
  browser has. If you have a Playwright `page`/`context` that's already
  logged in (via this repo's `blackboard_sync login`), call
  `page.context.request.get(url)` and the cookies ride along automatically.
- Blackboard's officially documented public API
  (`/learn/api/public/v1/...`, OAuth2, `developer.blackboard.com`) is a
  **different, mostly-unused path** here - it needs an institution admin
  to register a REST Integration, not available to a student account. A
  couple of `/learn/api/public/v1/...` calls were seen in capture (LTI
  placements, upload settings) but they're also just cookie-authenticated
  in this context, not the OAuth flow.
- Some requests also carry a `x-blackboard-xsrf` header (value matches a
  cookie, Angular's standard XSRF double-submit pattern). Not yet
  confirmed whether GETs actually enforce it server-side - every endpoint
  used so far has worked via plain `page.context.request.get()` without
  manually setting it. If a write (POST/PUT/DELETE) ever 403s, this header
  is the first thing to add (read the matching cookie's value, set the
  header explicitly).
- This project only ever does reads (GET). No endpoint below has been
  exercised for writes, and the project's scope (personal content sync)
  shouldn't need to.

## Status legend

- ✅ **CONFIRMED** - real response body inspected, field names verified, a
  scraper module calls it.
- 🟡 **URL confirmed, body not inspected** - seen succeed (200, JSON
  content-type) in a capture, but nobody has read the response shape yet.
- ❓ **Speculative** - inferred from a URL pattern or an unrelated field
  (e.g. a `contentDetailUrl` value), never actually called.

## Core endpoints (what the scraper uses)

| Purpose | Status | Endpoint |
|---|---|---|
| Current user | ✅ | `GET /learn/api/v1/users/me` → `.id` is the Blackboard user id used everywhere else (`_1168594_1`-shaped) |
| Enrolled courses | ✅ | `GET /learn/api/v1/users/{userId}/memberships?expand=course.effectiveAvailability,course.permissions,courseRole&includeCount=true&limit=10000` |
| Announcements | ✅ | `GET /learn/api/v1/courses/{courseId}/announcements?limit=100&sort=startDateRestriction(desc)` |
| Grades (+ column defs via expand) | ✅ | `GET /learn/api/v1/courses/{courseId}/gradebook/grades?userId={userId}&limit=200&expand=column&includeNoGradeItems=true` |
| Content tree, one level | ✅ | `GET /learn/api/v1/courses/{courseId}/contents/{parentId}/children?@view=Summary&limit=200` - `parentId` starts at the literal string `ROOT`; recurse into any folder by its own `id` |
| Content tree, single item | 🟡 | `GET /learn/api/v1/courses/{courseId}/contents/{contentId}` (singular, no `/children`) - URL pattern inferred from the `/children` sibling, not itself captured |
| Discussion topics, one level | ✅ | `GET /learn/api/v1/courses/{courseId}/contents/INTERACTIVE/children?limit=200` - same shape as the content tree, `INTERACTIVE` is a virtual parent id (not a real content id) that groups forum-link items |
| Discussion forum detail (posts) | 🟡 | `GET /learn/api/v1/courses/{courseId}/discussionboards/{conferenceId}/forums/{forumId}` - path seen as a `contentDetailUrl` field on a `resource/x-bb-forumlink` content item, itself never fetched. `conferenceId`/`forumId` come from that item's `contentDetail["resource/x-bb-forumlink"]` |
| File download | ✅ (HTML, not API) | No API endpoint found for this - still done by visiting the item's Ultra detail page and reading a hidden `<a data-ally-file-preview-url="https://.../bbcswebdav/...">`, then fetching that URL directly. See "File download" in `blackboard-api-notes.md`. |

### Content tree item shape (confirmed)

Each entry in a `/contents/.../children` response:

```json
{
  "id": "_8184141_1",
  "parentId": "_8049735_1",
  "title": "Module Overview and Assessment",
  "description": "<p>...</p>",
  "contentHandler": "resource/x-bb-lesson",
  "contentDetail": { "resource/x-bb-lesson": { "isFolder": true, "...": "..." } },
  "body": {
    "rawText": "", "displayText": "",
    "webLocation": "https://blackboard.soton.ac.uk/courses/1/{courseDisplayId}/content/{id}/embedded/"
  },
  "position": 0,
  "modifiedDate": 1790073154373
}
```

- **Folder vs leaf**: check `contentDetail[contentHandler].isFolder`
  (lessons/modules) - not a universal field name across all
  `contentHandler` values, inspect the matching sub-object.
- **`contentHandler` values seen**: `resource/x-bb-lesson` (folder),
  `resource/x-bb-forumlink` (discussion link), `resource/x-bb-bltiplacement-*`
  (LTI tool launch, e.g. Teams). Document/file content handlers (e.g.
  `resource/x-bb-document`, `resource/x-bb-file`) **not yet seen** in a
  captured tree response - only inferred from the Ultra UI's document
  viewer page, not this API. Next capture should drill into a folder with
  an actual file reading to confirm.
- **`body.webLocation`** (`https://.../courses/1/{courseDisplayId}/content/{id}/embedded/`)
  is present and type-agnostic on every item seen, but **confirmed NOT
  directly navigable** as a top-level page: visiting it lands on a plain
  "The specified resource was not found or you do not have permission to
  access it" page (checked live). It's presumably meant to be loaded
  inside an iframe with some parent-frame context, not opened standalone.
  Use the type-specific URL instead, keyed off `contentHandler`:
  `/ultra/courses/{id}/document/{contentId}?view=content&state=view` for
  ordinary content (reverse-engineered from the DOM, confirmed working for
  at least document-type items), `/ultra/courses/{id}/discussion/{contentId}?view=discussions`
  for `resource/x-bb-forumlink`, and nothing at all (skip) for
  `resource/x-bb-bltiplacement-*` (an LTI tool launch, e.g. a Teams
  meeting link - there's no document to fetch).
- **Pagination**: every list endpoint (announcements, grades, content
  children) shares one shape - `{"results": [...], "paging": {"limit",
  "count", "offset", "nextPage", "previousPage"}, "permissions": {...}}`.
  `nextPage` is a relative path, empty string when there's no more.
  `blackboard_sync/scraper/api.py`'s `paginated_results()` follows it
  generically.

### Grade record shape (confirmed)

```json
{
  "id": "_5908647_1",
  "columnId": "_571876_1",
  "status": "GRADED",
  "pointsPossible": 100.0,
  "effectiveScore": 0.0,
  "displayGrade": { "grade": "Complete", "score": 0.0 },
  "submissionStatus": { "status": "GRADED" },
  "column": {
    "id": "_571876_1",
    "columnName": "1.1.2 How difficult is your week's learning goal?",
    "effectiveColumnName": "1.1.2 How difficult is your week's learning goal?",
    "dueDate": "2026-11-09T15:00:00.000Z",
    "possible": 100.0,
    "gradebookCategory": { "title": "Survey.name" }
  }
}
```

`column.dueDate` only appears on items that actually have one (absent, not
null, on most). A separate `GET .../gradebook/columns` endpoint exists but
is redundant once `expand=column` is used on the grades call.

### Announcement shape (confirmed)

```json
{
  "id": "_534924_1",
  "title": "Diego's Introduction & Weekly Webinar",
  "body": { "rawText": "<p>...</p>", "displayText": "<div class=\"vtbegenerated\">...</div>" },
  "createdDate": "2026-09-25T12:30:06.276Z",
  "modifiedDate": "2026-09-25T12:30:06.341Z",
  "startDateRestriction": "2026-09-25T12:30:06.339Z",
  "creatorUserId": "_1168736_1",
  "isDraft": false
}
```

`body.rawText` is the full announcement HTML, including any embedded
attachment links (`<a data-bbtype="attachment" data-bbfile="{...}">`) -
worth parsing further if announcement attachments matter, not done yet.

## Broader catalog - URL only, not inspected (🟡 / ❓)

From a sweep of 333 captured calls across 8 course pages (course outline,
announcements, grades, engagement, calendar, messages, achievements,
groups), deduped to 66 unique endpoints by
`scripts/summarize_api_captures.py`. Everything above was pulled out of
this set and verified; the rest is listed here as-is, URL pattern only.
Re-run the summarizer against `debug/api/` (gitignored, regenerate with
`python -m blackboard_sync discover-api`) for the full list with example
files.

| Area | Endpoint (course-scoped unless noted) |
|---|---|
| Course metadata | `GET /learn/api/v1/courses/{courseId}?expand=instructorsMembership,instructorsMembership.courseRole,effectiveAvailability,isChild` |
| Course roster | `GET /learn/api/v1/courses/{courseId}/memberships?expand=user,courseRole,user.hasEmailAddress` |
| Current user's role in a course | `GET /learn/api/v1/courses/{courseId}/users/{userId}?expand=courseRole` |
| Course entitlements/permissions | `GET /learn/api/v1/courses/{courseId}/entitlements` |
| Course tools enabled | `GET /learn/api/v1/courses/{courseId}/tools` and `/tools/{toolName}` (seen: `announcements`, `messages`, `groups`, `discussion_board`, `bb-achievements-ultra`, `bb-attendance`, `bb-course-automations`, `ai-messages`) |
| Calendar events in a range | `GET /learn/api/v1/courses/{courseId}/calendars/calendarItems?since={ISO}&until={ISO}` |
| Course messages/conversations | `GET /learn/api/v1/courses/{courseId}/conversations?limit=25&offset=0`, `/conversations/counts`, `/conversations/options` |
| Groups | `GET /learn/api/v1/courses/{courseId}/groups?expand=studentCount,memberships,permissions,signUpSheet,hasSubmittedGroupAttempt,hasGrades`, `/groupsets` |
| Discussion board settings/counts | `GET /learn/api/v1/courses/{courseId}/discussionboards/count`, `/discussionboards/settings` |
| Content review/completion indicators | `GET /learn/api/v1/courses/{courseId}/contents/indicators` |
| Course schedule | `GET /learn/api/v1/courses/{courseId}/schedule?sort=location(desc)` |
| Gradebook settings/schemas | `GET /learn/api/v1/courses/{courseId}/gradebook/settings`, `/gradebook/schemas`, `/gradebook/schemas/{schemaId}` |
| Due-date exceptions for one enrollment | `GET /learn/api/v1/courses/{courseId}/gradebook/memberships/{membershipId}/exceptions` |
| Unread grades count | `GET /learn/api/v1/courses/{courseId}/gradebook/unreadGradesCount` |
| Progress tracking config | `GET /learn/api/v1/courses/{courseId}/progress/configuration` |
| Achievements (note: different host entirely) | `GET https://blackboard.soton.ac.uk/foundations/eu.prod/prod/lms-achievements/api/v1/tenants/{tenantId}/courses/{foundationsCourseId}/achievements` and `.../memberships/{foundationsMembershipId}/achievements`, `.../achievements/unread` - uses `foundationsId` values (UUIDs) from the course/membership objects, not the `_NNN_1` Blackboard ids |
| Cross-course activity feed | `POST /learn/api/v1/streams/ultra` - body not captured; **high value to check** - plausibly one call for "what's new across every course" instead of polling each course individually |
| Global nav pages (Activity, Marks, etc.) | Not yet captured - `discover-api`'s global-nav sweep pulls these from the page's own sidebar links at runtime rather than hardcoding URLs; check `debug/course_list_requests.log` or a fresh `discover-api` run for what it found |

## Known unknowns / good next captures

1. A content tree leaf item that's an actual file/reading (not a lesson
   folder or forum link) - needed to confirm whether file attachment info
   is directly in the API response (would let file download skip the HTML
   page-visit step entirely) or whether the current `data-ally-file-preview-url`
   HTML approach stays necessary. Capture: `discover-api` would need
   extending to recurse one level into a folder, or manually hit
   `/contents/{leafContentId}` for a content id found by hand.
2. `GET /learn/api/v1/courses/{courseId}/discussionboards/{conferenceId}/forums/{forumId}`
   full body - would tell us whether individual posts/replies are
   available via API (likely yes, probably needs a further
   `/forums/{forumId}/posts` or similar call this hasn't surfaced yet).
3. `POST /learn/api/v1/streams/ultra` request body - if this is a genuine
   cross-course "what's new" feed, it could replace per-course polling of
   announcements/grades/discussions with one call.
4. Whether `x-blackboard-xsrf` is actually enforced - untested since
   nothing here has needed a write.

## Where the raw data lives

- `debug/api/*.json` - one file per captured call (method, URL, request/response
  headers, parsed JSON body). Gitignored - regenerate with
  `python -m blackboard_sync discover-api [--course <id>]`, which clears
  and repopulates this directory each run.
- `debug/course_list_requests.log` - a flat log of *every* request/response
  the course list page made (not just ones matching the `/api/` + JSON
  filter `discover-api`'s main capture uses) - useful when a page's real
  data call doesn't match that filter, as happened with the course list
  itself originally.
- `scripts/summarize_api_captures.py` - dedupes a `debug/api/` directory
  down to unique `(method, path)` endpoints with call counts and an
  example file per endpoint; run it after any `discover-api` sweep before
  trying to review files one by one.
