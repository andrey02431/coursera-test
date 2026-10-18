# Blackboard API / endpoint notes (University of Southampton)

Working notes on how to talk to `blackboard.soton.ac.uk` programmatically.
Everything below was reverse-engineered against a real logged-in session
during development of this tool - nothing here is from Blackboard's own
documentation unless explicitly marked as such.

**Status: course discovery is now a real API call** (see below) -
`blackboard_sync/scraper/courses.py` no longer renders or scrapes any
page for the course list. Content/announcements/grades/discussions are
still HTML-page scraping (the sections further down); capturing their real
API equivalents is the next step - see "Not yet done" at the bottom.

## Confirmed: course list via the real API (no page rendering needed)

```
GET /learn/api/v1/users/{userId}/memberships
    ?expand=course.effectiveAvailability,course.permissions,courseRole
    &includeCount=true&limit=10000
```

Cookie-authenticated like everything else; `{userId}` comes from
`GET /learn/api/v1/users/me` (just needs the `id` field from that
response). Both implemented in `blackboard_sync/scraper/courses.py` via
`page.context.request.get(...)` - no page navigation, no waiting for
Angular to render, no selector tuning. This fully replaced the old
`/ultra/course` DOM-scraping approach (see "Deprecated" below), which was
the single largest source of flakiness in the whole tool (skeleton-loading
races the settle-selector retry logic couldn't reliably outlast). It also
returned a course the DOM scraper's course list never surfaced at all (a
Classic/Original-view one), so it's strictly more complete, not just more
reliable.

Response shape - one entry per `results[]`:

```json
{
  "courseId": "_240080_1",
  "course": {
    "id": "_240080_1",
    "name": "SSPC2002 Techno Harms: Discrimination, Conspiracy Theories and Extremism (44138-26-27)",
    "displayName": "SSPC2002 Techno Harms: Discrimination, Conspiracy Theories and Extremism (44138-26-27)",
    "displayId": "SSPC2002-44138-26-27",
    "externalAccessUrl": "https://blackboard.soton.ac.uk/ultra/courses/_240080_1/outline",
    "ultraStatus": "ULTRA",
    "courseViewOption": "CHOOSE_ULTRA",
    "isClosed": false,
    "isAvailable": true,
    "effectiveAvailability": true,
    "term": { "id": "_465_1", "name": "2026-27 Modules", "startDate": "...", "endDate": "..." }
  },
  "courseRole": { "identifier": "S", "roleBucket": "TAKING" }
}
```

Key fields the scraper relies on: `course.id`, `course.displayName`,
`course.externalAccessUrl` (ready-to-use outline URL for Ultra courses),
`course.ultraStatus` (`"ULTRA"` vs `"CLASSIC"` - only Ultra is supported;
Classic ones use `course.homePageUrl` instead, something like
`/webapps/blackboard/execute/courseMain?course_id=_184556_1`, and need an
entirely different - unimplemented - Original-view scraper), and
`course.isClosed`.

## Deprecated: the old DOM-based course list

Kept here for context on what broke, not as something to fix further.
`/ultra/course` renders Blackboard's older Angular "Base Navigation" course
list (not the Ultra React app). Each course tile was:

```html
<a class="course-title" id="course-link-_240080_1" href="javascript:void(0);"
   ng-click="baseCourses.handleCourseLinkClick(membership.course, $event)">
  <h4 id="course-name-_240080_1">SSPC2002 Techno Harms: ...</h4>
</a>
```

getting the course ID required parsing it out of the tile's own `id`
attribute (`course-link-(.+)`) since the `href` was a no-op Angular click
handler - and even then, the page's course rows were Angular-rendered
skeleton placeholders that didn't reliably populate within any timeout we
tried, confirmed repeatedly on live runs. The API call above has none of
these problems.

## Why not the officially documented Blackboard REST API

Blackboard Learn has a real, documented public REST API at
`/learn/api/public/v1/...` (OAuth2, `developer.blackboard.com`). It's not
usable here: authenticating against it requires an institution admin to
register a "REST Integration" (an OAuth application ID/secret) in
Southampton's Blackboard admin panel. A student account cannot self-serve
this, so it's out of reach unless Southampton iSolutions sponsors it.

## Confirmed: page-level routes (Ultra course view)

These are real URLs that return fully-formed HTML pages when requested
with an authenticated session's cookies. All relative to
`https://blackboard.soton.ac.uk`.

| Purpose | URL template | Notes |
|---|---|---|
| Course list | `/ultra/course` | Renders Blackboard's older Angular "Base Navigation" UI, not the Ultra React app. See "Course identification" below. |
| Course content outline | `/ultra/courses/{course_id}/outline` | Ultra React SPA. |
| Announcements | `/ultra/courses/{course_id}/announcements` | |
| Grades | `/ultra/courses/{course_id}/grades` | |
| Discussions | `/ultra/courses/{course_id}/engagement` | **Not** `/discussions` - the nav bar's "Discussions" tab actually links here (Blackboard's combined engagement/discussion hub). Using `/discussions` 404s. |
| Content item detail | `/ultra/courses/{course_id}/document/{content_id}?view=content&state=view` | One per leaf content item; the item's actual title link in the outline points here. Other content types use different path segments, e.g. `/discussion/{content_id}?view=discussions` for a discussion-board link embedded in content. |

`{course_id}` and `{content_id}` both look like `_240080_1` - an
underscore-prefixed numeric Blackboard primary key plus a trailing `_1`.

## Confirmed: content outline structure

`/ultra/courses/{course_id}/outline` renders each item as:

```html
<div class="content-list-item" data-content-id="_8073724_1">
  ...
  <!-- folder ("Learning Module"): -->
  <button id="learning-module-title-_8073724_1" aria-expanded="false"
          aria-controls="learning-module-contents-_8073724_1">Lecture 12: ...</button>
  <!-- once expanded, children render inside: -->
  <div id="learning-module-contents-_8073724_1"> ... nested .content-list-item divs ... </div>

  <!-- OR leaf item: -->
  <a href="https://blackboard.soton.ac.uk/ultra/courses/_240080_1/document/_8199560_1?view=content&state=view"
     data-analytics-id="content.item.coures.outline.document.link">Module Guide</a>
</div>
```

- Folder vs. leaf: a folder owns a title control at
  `#learning-module-title-<its-own-data-content-id>`; a leaf has a real
  `<a href>` instead.
- Folder path for any leaf is reconstructed by walking up the DOM for an
  ancestor `#learning-module-contents-<id>`, then reading
  `#learning-module-title-<id>` for that folder's display name.
- `data-analytics-id` values seen so far (Blackboard's own internal
  telemetry attribute, one of the more stable things to key off):
  `content.item.coures.outline.document.link` (yes, "coures" - a typo in
  Blackboard's own code), `content.item.course.outline.courseContent.link`,
  `course.link.item.forumLink.link` (a discussion embedded in content),
  `course.learning.module.base.item.toggleLm.button` (folder toggle).

## Confirmed: the actual file-download mechanism

A content item's own detail page (e.g.
`/ultra/courses/{course_id}/document/{content_id}?view=content&state=view`)
embeds the real downloadable file URL in a **hidden**, non-clickable anchor:

```html
<a data-ally-content-id="_8199560_1:r7:"
   data-ally-file-eid="_40609472_1"
   data-ally-file-preview-url="https://blackboard.soton.ac.uk/bbcswebdav/pid-8199561-dt-content-rid-40609472_1/xid-40609472_1"
   style="display: none;"></a>
```

`data-ally-file-preview-url` is a direct, authenticated (session-cookie)
GET URL that returns the raw file bytes - this is what
`blackboard_sync/scraper/content.py` fetches via
`page.context.request.get(...)` rather than trying to click anything. The
real filename (with extension) comes from a sibling element's
`aria-label="Preview File <filename>"`, not from the outline item's own
title text (which is often a shortened display name like "Module Guide").

The `bbcswebdav` path shape itself -
`/bbcswebdav/pid-<pid>-dt-content-rid-<rid>-xid-<rid>` - looks like
Blackboard's long-standing WebDAV content-collection URL scheme (predates
Ultra), just surfaced here via the Ultra UI.

## Confirmed: announcements markup

```html
<tr class="announcement-item-row">
  <a id="list-item-title-_532610_1" class="list-item-title" href="#">Hidden Hate Podcast</a>
  <p class="list-item-body three-lines">Dear All, ...</p>  <!-- full text in the DOM despite the "three-lines" CSS clamp -->
  <span class="list-item-date-sent">14/09/2026, 10:19</span>
</tr>
```

## Confirmed: grades markup

```html
<tr data-grade-id="_567028_1" data-testid="course-student-grades-table-row-Assessment 1: Meme Analysis">
  <td aria-describedby="course-student-grades-header-itemName">...</td>
  <td aria-describedby="course-student-grades-header-dueDate">23/10/2026</td>
  <td aria-describedby="course-student-grades-header-status">Unopened</td>
  <td aria-describedby="course-student-grades-header-grade">Not marked</td>
  <td aria-describedby="course-student-grades-header-results"></td>
</tr>
```

## Confirmed: discussions/engagement hub

`/ultra/courses/{course_id}/engagement` reuses the exact same
`content-list-item`/`data-content-id` component as the outline (see
above) - each discussion topic is one of those, with a real `<a href>`
pointing at `/ultra/courses/{course_id}/discussion/{content_id}?view=discussions`.
What an actual post/reply looks like on that page is **not** confirmed -
the only topic tested had zero posts.

## Not yet done: content/announcements/grades/discussions as real API calls

Course discovery is now API-based (above); everything else -
`blackboard_sync/scraper/content.py`, `announcements.py`, `grades.py`,
`discussions.py` - still renders and scrapes HTML pages. Ultra's React
frontend is necessarily calling *something* JSON-shaped, same-origin,
cookie-authenticated, to render those too; those calls haven't been
captured yet, but the same technique that found the memberships endpoint
should work the same way for each of them.

To capture them: run `python -m blackboard_sync discover-api` (optionally
`--course <id>`) against a real, logged-in session. It attaches a
Playwright response listener while navigating the outline/announcements/
grades/engagement pages for one course, and writes every JSON response
whose URL contains `/api/` to `debug/api/<section>_NNN.json` (method, URL,
request/response headers, JSON body) - `debug/api/` is cleared at the
start of each run so files don't mix across runs, and a companion
`debug/course_list_requests.log` / `log_all_requests()` is available if a
page's relevant call doesn't match the `/api/` + JSON filter (not
guaranteed for every page - the course list's own data call turned out to
live under `/learn/api/v1/...`, found this way after the filtered capture
alone wasn't enough). Once captured, update the relevant scraper module to
call the real endpoint directly, the same way courses.py now does.
