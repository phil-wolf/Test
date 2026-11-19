# Bud Bar Business Playbook: SCORM 1.2 test course

Two SCORM 1.2 packages, built from editable content files:

| Package | Zip to upload | Status reported to the LMS |
|---|---|---|
| **Free:** "Is a bud bar business right for you?" (4 modules + 5-question quiz, ~20 min) | `bud-bar-free_scorm12.zip` | `passed` / `failed` (80% to pass) + score |
| **Paid sample:** "Staffing & the Certified Service Standard" (~10 min, intake form, 3-question check) | `bud-bar-paid-sample_scorm12.zip` | `completed` (on reaching the last screen) + knowledge-check score |

Everything is plain HTML/CSS/JavaScript with no external CDNs: fonts, logo and code are all inside each zip.

---

## 1. Preview locally (no LMS needed)

Open either of these in a browser (double-click works):

- `bud-bar-free/index.html`
- `bud-bar-paid-sample/index.html`

With no LMS present, the course uses a **mock LMS**. A dark strip in the bottom-right corner shows what would be sent: `status · score · bookmark`. Click it to open the full **debug panel**:

- **Current LMS values:** lesson_status, score.raw, lesson_location (the bookmark), exit, session_time, suspend_data
- **Call log:** every `LMSInitialize`, `LMSGetValue`, `LMSSetValue`, `LMSCommit`, `LMSFinish` call, with errors highlighted
- **Simulate exit (LMSFinish):** does what happens when a learner closes the course
- **Reset preview data:** starts over as a brand-new learner

The mock saves to your browser, so you can test **resume**: go to a few screens in, reload the page, and the course reopens where you were, with a "Welcome back" message.

> Inside a real LMS the debug panel is hidden. If your LMS lets you edit the launch URL, adding `?debug=1` shows it.

---

## 2. Edit content and rebuild

All wording lives in `content/`. You never need to touch HTML or JavaScript.

```
content/
  free/
    course.json               title, version, passing score, module order
    01-what-is-a-bud-bar.md   one Markdown file per module
    02-business-models.md
    03-costs-and-revenue.md
    calculator.json           calculator labels + example dollar figures
    04-state-landscape.md
    state-table.json          the state list and statuses
    05-quiz.md
    quiz.json                 quiz questions, answers, feedback
    06-next-steps.md          end screen, paid-playbook link
  paid-sample/
    course.json
    01-staffing-and-certified-service.md
    intake-form.json          the Client Event Intake Form fields
    02-knowledge-check.md
    knowledge-check.json
    03-sample-complete.md
```

### How the Markdown files work

```markdown
# Module title              <- first line: the module name (shown in the menu)

## Screen title             <- every "## " starts a new screen

Normal paragraph text. **bold**, *italic*, [link text](https://example.com)

- bullet list
1. numbered list
> A callout box
| Table | Header |
|---|---|
| cell | cell |

[[calculator:calculator.json]]          <- interactive pieces ("embeds")
[[quiz:quiz.json]]
[[state-table:state-table.json]]
[[download:intake-form.json|Button text]]
```

Anything written as `[PHILIP TO VERIFY]` (or `[PHILIP TO VERIFY — note]`) shows as a yellow highlight in the course.

### Quiz files

`"answer"` is the **number of the correct option, counting from 1**. Add or remove questions freely; the build checks that every answer number is valid.

### Rebuild

From this folder:

```bash
python build.py
```

This takes a few seconds and:
1. Increases both version numbers by one (1.0.3 → 1.0.4). The version shows on each course's last screen, on the intake form, and in the LMS course title.
2. Regenerates `bud-bar-free/` and `bud-bar-paid-sample/` (don't edit those folders by hand; they get overwritten).
3. Rebuilds both zips and checks each manifest (structure, IDs, every file present).
4. Regenerates `VERIFY_LIST.md`.

Other options:

```bash
python build.py free
```

```bash
python build.py --no-bump
```

The first rebuilds only one course (`free` or `paid-sample`). The second rebuilds without changing version numbers.

If you make a typo, such as broken JSON or an answer number that doesn't exist, the build stops with a plain message naming the file and line. **Nothing is changed**: the previous zips and version numbers stay in place.

Needs Python 3.8 or newer. No extra packages.

### Branding

Colors, fonts and logo are all in **`brand/brand.css`** (the CashoM palette is already set). To swap the logo, replace `brand/logo.svg`. It sits on the dark top bar, so use a light version. Rebuild after any change.

---

## 3. Test on SCORM Cloud (free tier)

1. Sign up for a free account at **cloud.scorm.com** (Rustici Software). The free tier limits how many learners and registrations you can have, which is plenty for testing.
2. In the left menu, go to **Library** (or **Content Library**), then **Add Content** / **Import**.
3. Upload `bud-bar-free_scorm12.zip`. SCORM Cloud reads `imsmanifest.xml` and should list the course as **SCORM 1.2** with the title ending in the version, e.g. "(v1.0.3)".
4. Open the course and click **Launch**, which runs it as a test learner.
5. Repeat for `bud-bar-paid-sample_scorm12.zip`.

SCORM Cloud's menus get renamed from time to time. If a label above doesn't match, look for "Library", "Add Content" and "Launch".

### What to check

| Check | How | Expected |
|---|---|---|
| **Completion: free** | Finish the quiz with 4 or 5 right | Registration shows **Passed** |
| **Fail path: free** | New registration; get 3 or fewer right | **Failed**, score 60 or lower; "Try again" appears |
| **Score** | After the quiz | Score matches the % shown in the course |
| **Completion: paid** | Reach the last screen | **Completed**, with the knowledge-check score |
| **Resume** | Go to screen 5, close the course window, launch again | Opens on screen 5 with "Welcome back" |
| **Version** | Last screen of each course | Matches the version in `content/*/course.json` |
| **Mobile** | Launch on your phone | No sideways scrolling; buttons easy to tap |

To see exactly what the course sent, open the registration's details or launch history in SCORM Cloud. It has a debug log that lists every SCORM call, the same as the preview debug panel.

### ⚠ Re-uploading a new version

- In SCORM Cloud, use the course's **"New Version" / update** option instead of importing it as a new course, so the course keeps the same ID.
- **Some LMSs reset learner progress when a course is re-uploaded or replaced.** Others keep old learners on the old version. Test with a fresh registration after each upload.
- The bookmark is a screen number. If you **add or remove screens**, learners resuming an older attempt may land on a different screen than they left. Quiz answers and calculator values are kept.

---

## 4. Technical notes

- **SCORM wrapper:** `engine/scorm-api.js`. It finds the LMS `API` object (parent frames or the opener window), calls `LMSInitialize`, sets `lesson_status` to `incomplete` on the first launch, and saves `lesson_location` (bookmark) and `suspend_data` (quiz answers, calculator values, furthest screen) after every screen. It reports `score.raw/min/max`, and on exit it sets `session_time` and `exit` (`suspend` if not finished), then calls `LMSCommit` and `LMSFinish`. If no LMS is found, it uses a built-in mock that enforces the same SCORM 1.2 rules: read-only fields, valid statuses, and the 4,096-character `suspend_data` limit.
- **Mastery score:** the free course's manifest includes `adlcp:masteryscore` = 80, so the LMS uses the same pass mark as the course.
- **Quiz answers are in the course files.** That's normal for simple SCORM courses, but a determined learner could find them. Fine for this test; use LMS-side quizzing if that ever matters.
- **Schema files:** the official SCORM 1.2 `.xsd` files aren't bundled. SCORM Cloud and most LMSs don't need them. If a strict LMS asks for them, they can be added to `engine/` and listed by the build.
- **Accessibility:** works by keyboard (Tab / Enter / Space; Esc closes the mobile menu); there's a skip link; focus moves to each new screen's heading; quiz results are announced to screen readers; quiz options use fieldsets and legends; text contrast meets WCAG AA.
- **Fonts:** Playfair Display (headlines) and Source Sans 3 (body), bundled in `brand/fonts/`, both under the SIL Open Font License (license files included).

## 5. Before real learners see this

Go through **`VERIFY_LIST.md`**. It lists every `[PHILIP TO VERIFY]` item with file, line and screen. Fix each in the content file, delete the marker, and rebuild; the list updates itself. Also replace the placeholder link `https://example.com/bud-bar-playbook` in `content/free/06-next-steps.md` and `content/paid-sample/03-sample-complete.md`.
