---
name: ship-site
description: Put Famous Desks live on famousdesks.com (Cloudflare Workers static assets) and push to GitHub safely, then confirm it's really live. Use this whenever the user says "deploy", "push", "ship it", "put it live", "update production", asks why the live site looks old, wants link previews/metadata/share image updated, or a change is committed and ready, even if they only say "push to github".
---

# Shipping the site

`scripts/deploy.sh` does the whole job: it refuses to run off `main` or with uncommitted tracked changes under `web/` or `content/spaces/`, builds from a clean temporary git worktree of the commit (so half-written renders, draft previews and the untracked `content/spaces/hallway/` never ship), runs wrangler under Node 22 via npx (the Mac has Node 20; don't change the system Node), checks the live site and only then pushes.

```sh
scripts/deploy.sh --push      # usual: deploy HEAD of main, verify, push to GitHub
scripts/deploy.sh --dry-run   # build + wrangler --dry-run, nothing uploaded
scripts/deploy.sh --check     # just the live checks
```
The user asks before each deploy ("deploy and push", "deploy first then..."); don't deploy unprompted. Commit first, with a message that says what visitors will notice.

## After deploying
- The script's live checks: `/` with og:image and twitter:card, index.json, space.json, favicon, and a panorama whose live bytes match the commit.
- Then a browser smoke test: `node tools/check/check.mjs smoke --base https://famousdesks.com --size all` (tour-check skill), plus whatever the change was about (e.g. `closeup "The display" --base https://famousdesks.com`).
- Report: what went live (commit), checks passed, anything still pending.

## Caching (why people may still see the old site)
- Images and models are addressed with `?v=<hash>` by the export, and cached for a year (`web/public/_headers`): a re-render changes the addresses, so nobody needs a hard refresh. Tour data (`space.json`, `index.json`) caches 5 minutes; favicons and the share image a day.
- If a user sees old content: compare live bytes with local (`curl -s <url> | shasum`); if they match, it's their browser or space.json's 5 minutes. Hard refresh doesn't reload lazily-loaded tiles, which is why versioned URLs exist.
- Cloudflare's single-page fallback answers a missing file with the app's HTML and status 200, so "200" doesn't prove a JSON file exists. Never load hidden or undeployed spaces (`site.hiddenSpaces`).

## Metadata and share image
- Link previews don't run JavaScript, so title, description, canonical, theme colour, favicons and `og:`/`twitter:` tags are written into `web/src/app.html`, not added by the app.
- The share image is `web/public/og-image.jpg` (1200×630): a clean shot of the room with the UI hidden and the wordmark bottom-left. Regenerate it after a re-render changes the main view. Link-preview services cache old previews; LinkedIn Post Inspector / Facebook Sharing Debugger refresh them.
- Static site files live in `web/public/` (copied into the build with `_headers`). `_headers` allows one `*` per rule; use `:placeholder` names for the rest.

## Setup facts
Worker `famous-desks` in the user's own Cloudflare account (`web/wrangler.jsonc`: assets `./build`, single-page-application, custom domains famousdesks.com and www). GitHub: `garphillips/famous-desks` (public). This is a personal project: keep work accounts and tools out of it.
