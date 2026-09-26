---
name: ui-mock
description: Draw UI mockups that look like the team's own system, from reference screenshots or the running app, rendered to PNG. Use when a PRD needs mockups, or when the user says "mock this up", "draw the screen", "wireframe", "what would this look like", or asks to capture the style of an app.
---

# Mock up screens in the style of the team's system

Mockups make a PRD concrete: reviewers react to a picture far faster than to
a table of fields. They are only useful if they look like the product the team
actually has, so the style comes from real screenshots, never from a generic
design system you know.

Mocks are drawn as HTML and rendered to PNG by a headless browser that is
already installed. Nothing is fetched from the internet, before or during
rendering.

## Steps

### 1. Load the style

Call `ui_style`. Then **Read every screenshot path it returns**, since the list
alone tells you nothing about the look, and read `notes` (the team's
hand-written `style.md`).

- `browser` is null → mockups cannot be rendered on this machine. Say so,
  point at `ui.browser` in `config.toml`, and stop.
- **No screenshots** → ask the user for one of:
  - the URL of the running app: `ui_capture` it (step 2), or
  - screenshots they drop into `<style_dir>/screens/`.

  If they have neither, say plainly that the mocks will use a neutral style,
  and use it.

### 2. Capture more of the app if needed (optional)

`ui_capture(url, name)` saves a screenshot of one page into the style folder.
Read it:

- **It shows a login form** → call `ui_login(url)` and ask the user to sign
  in, tick "Remember me" if offered, and close the window. Then capture again.
- Capture 2–4 pages that resemble what you need to draw: a list, a form, a
  detail page. More screenshots of the same layout add nothing.

### 3. Write down the style before drawing

From the screenshots and notes, list the concrete style in your message:

- colours as hex: background, surface, primary, text, muted text, borders,
  status colours;
- fonts (family, sizes for headings, body, labels), spacing rhythm, corner
  radius, shadows;
- page frame: header, side navigation, breadcrumbs, page title placement;
- how tables, buttons (primary / secondary), inputs, tabs and empty states
  look.

Estimate from the pixels. Where `style.md` gives a value, it wins over your
estimate.

### 4. Draw each screen as one self-contained HTML file

Write `<mocks_dir>/<prd-slug>/<screen-slug>.html` for each screen in the PRD's
Screens table, plus the important states (empty, error, no permission) as
their own files, e.g. `orders-list-empty.html`.

- One file, inline `<style>` only. **No external URL of any kind**: no CDN, no
  web font, no remote image. The renderer blocks the network, so anything
  external silently goes missing. Use the system font stack that matches the
  screenshots (e.g. `"Segoe UI", system-ui, sans-serif`).
- Reproduce the app's frame (header, navigation) so the screen reads as part
  of the product, but keep attention on the new content.
- Icons: simple inline SVG or Unicode, never an icon font.
- Data: realistic but invented. Plausible names, amounts and dates, never a
  real customer's or colleague's data, and nothing copied from the
  screenshots.
- Size to the default viewport (from config, usually 1440×900); for a longer
  page pass a larger `height` when rendering.

### 5. Render, look, fix

`ui_render_mock(html_path)`, then Read the PNG and compare it with the
reference screenshots side by side:

- Does it look like the same product (colours, density, type, frame)?
- Does it show exactly what the PRD says this screen shows and allows?
- Is anything clipped, overlapping or unstyled?

Fix and re-render. Stop after 3 rounds per screen; the goal is a
communicative mockup, not a pixel-perfect one.

### 6. Show the user

Show the rendered PNGs, with one line per screen on what it demonstrates, and
ask for changes before anything goes into a PRD.

### 7. Hand over

When called from `/prd-write`, return the PNG and HTML paths. The PRD embeds
each PNG as `![<Screen name>](attachment:<file>.png)` and publishes both files
as attachments, so the source travels with the page and can be regenerated.

## Notes

- A mockup is a proposal for review, not a design spec. Say so on the page if
  the team might read it as final.
- Screenshots of internal apps can contain real data. They stay in the
  git-ignored style folder; never attach reference screenshots to a
  published page.
- Everything is fixed-size PNG from one viewport. Interactions (hover,
  dropdowns open) need their own mockup file when they matter.

## If the donnyt tools are not available

Every tool has a CLI command (`python -m donnyt.cli tools`): `ui-style`,
`ui-login URL`, `ui-capture URL NAME`, `ui-render HTML_PATH`. Same steps, same
rules.
