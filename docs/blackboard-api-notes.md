# Blackboard API / endpoint notes (University of Southampton)

Working notes on how to talk to `blackboard.soton.ac.uk` programmatically.
Everything below was reverse-engineered against a real logged-in session
during development of this tool - nothing here is from Blackboard's own
documentation unless explicitly marked as such.

**Status: no true JSON API endpoints captured yet.** Everything in this
document so far comes from parsing Blackboard's rendered HTML (the
approach `blackboard_sync/scraper/*.py` currently uses), not from
Blackboard's own internal JSON calls. The `discover-api` command
(`blackboard_sync/scraper/api_capture.py`) exists to capture those and has
not been run against a real account yet - see "Next step" at the bottom.

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

## Course identification

The course list page (`/ultra/course`) does **not** expose course IDs via
a normal `href`. Each course tile is:

```html
<a class="course-title" id="course-link-_240080_1" href="javascript:void(0);"
   ng-click="baseCourses.handleCourseLinkClick(membership.course, $event)">
  <h4 id="course-name-_240080_1">SSPC2002 Techno Harms: ...</h4>
</a>
```

The real course ID (`_240080_1`) has to be parsed out of the tile's own
`id` attribute (`course-link-(.+)`) - the `href` is a no-op Angular click
handler. There's also a sibling `<span id="course-id-_240080_1">` carrying
the human-readable module code (`SSPC2002-44138-26-27`), separate from the
internal ID.

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

## Not yet done: real JSON API capture

All of the above is HTML-page scraping, not API calls. Ultra's React
frontend is necessarily calling *something* JSON-shaped, same-origin,
cookie-authenticated, to render all of this without a full page reload
when you click around normally - those calls have not been captured yet.

To capture them: run `python -m blackboard_sync discover-api` (optionally
`--course <id>`) against a real, logged-in session. It attaches a
Playwright response listener while navigating the same five pages
documented above, and writes every JSON response whose URL contains
`/api/` to `debug/api/<section>_NNN.json` (method, URL, request/response
headers, JSON body). Once that's run and the output reviewed, this
document and the scraper modules under `blackboard_sync/scraper/` should
be updated to use the real endpoints instead of (or alongside) the HTML
routes above.
