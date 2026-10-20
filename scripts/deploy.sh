#!/usr/bin/env bash
# Deploy famousdesks.com (Cloudflare Workers static assets) from a clean copy of a commit.
#
# Usage: scripts/deploy.sh [--dry-run] [--push] [--ref <commit>] [--force] [--check]
#
#   --dry-run    build and run `wrangler deploy --dry-run`; no upload, no checks, no push
#   --push       after a deploy that passes the live checks, `git push origin main`
#   --ref <rev>  deploy this commit instead of HEAD
#   --force      skip the "on main, nothing uncommitted" checks
#   --check      only run the live-site checks (against HEAD or --ref); no build, no deploy
#
# Why a clean copy: web/ serves ../content as its static assets, so building in the working
# folder ships whatever is on disk there (half-written renders, untracked spaces such as
# content/spaces/hallway/). Building from a temporary git worktree ships only what is committed.
set -euo pipefail

SITE="https://famousdesks.com"
NODE_PKG="node@22.23.3"   # wrangler 4 needs Node >= 22; npx fetches it without touching the system Node
SPACE="jobs-room"         # the space whose panorama the live check compares

DRY_RUN=0 PUSH=0 FORCE=0 CHECK_ONLY=0 REF=HEAD
while [ $# -gt 0 ]; do
	case "$1" in
		--dry-run) DRY_RUN=1 ;;
		--push) PUSH=1 ;;
		--force) FORCE=1 ;;
		--check) CHECK_ONLY=1 ;;
		--ref) [ $# -ge 2 ] || { echo "--ref needs a commit" >&2; exit 2; }; REF="$2"; shift ;;
		-h|--help) sed -n '2,14p' "$0" | cut -c3-; exit 0 ;;
		*) echo "Unknown option: $1 (try --help)" >&2; exit 2 ;;
	esac
	shift
done

step() { printf '\n==> %s\n' "$*"; }
die() { printf '\nError: %s\n' "$*" >&2; exit 1; }

ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
cd "$ROOT"
SHA="$(git rev-parse --verify --quiet "$REF^{commit}")" || die "'$REF' is not a commit."
SHORT="$(git rev-parse --short "$SHA")"

# --- Live-site checks (after a deploy, or alone with --check) -------------------------------
# Sets FAILS to the number of failed checks.
check_live() {
	step "Checking $SITE against $SHORT"
	FAILS=0
	pass() { printf '  PASS  %s\n' "$*"; }
	fail() { printf '  FAIL  %s\n' "$*"; FAILS=$((FAILS + 1)); }
	# Retries cover the few seconds before a new version is serving everywhere.
	fetch() { curl -sS --retry 3 --retry-delay 2 --retry-all-errors "$@"; }
	status() { fetch -o /dev/null -w '%{http_code}' "$1" 2>/dev/null || echo 000; }

	# The shell HTML, with the share tags link previews depend on.
	local index tag path code pano file want got
	index="$(fetch -f "$SITE/" 2>/dev/null || true)"
	if [ -n "$index" ]; then pass "/ loads"; else fail "/ did not load"; fi
	for tag in 'og:image' 'twitter:card'; do
		if printf '%s' "$index" | grep -q "\"$tag\""; then pass "/ has $tag"; else fail "/ is missing $tag"; fi
	done

	for path in /spaces/index.json "/spaces/$SPACE/space.json" /favicon.svg; do
		code="$(status "$SITE$path")"
		if [ "$code" = 200 ]; then pass "$path $code"; else fail "$path returned $code"; fi
	done

	# A panorama is the heaviest, most cache-sensitive asset: confirm the live bytes are the
	# committed ones (space.json addresses it with ?v=<first 10 of its sha1>).
	pano="$(git show "$SHA:content/spaces/$SPACE/space.json" \
		| grep -o '"panos/[^"/?]*\.webp?v=[0-9a-f]*"' | head -n 1 | tr -d '"' || true)"
	if [ -z "$pano" ]; then
		fail "no panorama found in content/spaces/$SPACE/space.json"
		return
	fi
	file="content/spaces/$SPACE/${pano%%\?*}"
	want="$(git show "$SHA:$file" | shasum | cut -d' ' -f1)"
	got="$(fetch -f "$SITE/spaces/$SPACE/$pano" 2>/dev/null | shasum | cut -d' ' -f1)"
	if [ "$want" = "$got" ]; then pass "/spaces/$SPACE/$pano matches the committed file"
	else fail "/spaces/$SPACE/$pano differs from $file (want $want, got $got)"; fi
	if [ "${pano##*v=}" != "$(printf '%s' "$want" | cut -c1-10)" ]; then
		fail "$pano: ?v= is not the file's sha1 (re-export space.json?)"
	fi
}

if [ "$CHECK_ONLY" -eq 1 ]; then
	check_live
	[ "$FAILS" -eq 0 ] || { step "$FAILS live check(s) FAILED."; exit 1; }
	step "All live checks passed."
	exit 0
fi

# --- Safety checks -------------------------------------------------------------------------
step "Checking the repo"
if [ "$FORCE" -eq 0 ]; then
	# The live site should always be a commit on main, so what's live can be found in history.
	BRANCH="$(git symbolic-ref --quiet --short HEAD || echo '(detached)')"
	[ "$BRANCH" = main ] || die "HEAD is on '$BRANCH', not main.
  Switch with 'git checkout main' (merge your branch first), or pass --force to deploy anyway."
	# Uncommitted edits would not be deployed (we build from the commit), which is confusing:
	# commit or discard them first. Untracked files (e.g. content/spaces/hallway/) are fine.
	DIRTY="$(git status --porcelain --untracked-files=no -- web content/spaces)"
	[ -z "$DIRTY" ] || die "uncommitted changes to tracked files under web/ or content/spaces/:
$DIRTY
  Commit or discard them ('git status'), or pass --force to deploy the commit without them."
	echo "On main, no uncommitted changes under web/ or content/spaces/."
else
	echo "--force: skipping the branch and uncommitted-changes checks."
fi
echo "Deploying $SHORT: $(git log -1 --format=%s "$SHA")"

# --- Build from a clean worktree -----------------------------------------------------------
TMP="$(mktemp -d "${TMPDIR:-/tmp}/famous-desks-deploy.XXXXXX")"
BUILD_DIR="$TMP/repo"
cleanup() {
	# Always remove the temporary worktree, even on failure or Ctrl-C, so none pile up.
	git -C "$ROOT" worktree remove --force "$BUILD_DIR" >/dev/null 2>&1 || true
	rm -rf "$TMP"
}
trap cleanup EXIT

step "Creating a clean worktree of $SHORT"
git worktree add --quiet --detach "$BUILD_DIR" "$SHA"

cd "$BUILD_DIR/web"
step "Installing dependencies (npm ci)"
npm ci --no-audit --no-fund --loglevel=error

step "Building (npm run build)"
npm run build --silent >"$TMP/build.log" 2>&1 || { cat "$TMP/build.log"; die "build failed."; }
tail -n 3 "$TMP/build.log"

WRANGLER=(npx --yes -p "$NODE_PKG" -- node node_modules/wrangler/bin/wrangler.js deploy)
if [ "$DRY_RUN" -eq 1 ]; then
	step "wrangler deploy --dry-run (Node 22 via npx)"
	"${WRANGLER[@]}" --dry-run
	step "Dry run OK: $SHORT built and validated; nothing uploaded, nothing pushed."
	exit 0
fi

step "wrangler deploy (Node 22 via npx)"
"${WRANGLER[@]}"

cd "$ROOT"
check_live
if [ "$FAILS" -gt 0 ]; then
	step "Deployed $SHORT, but $FAILS live check(s) FAILED. Not pushing."
	exit 1
fi
step "Deployed $SHORT; all live checks passed."

if [ "$PUSH" -eq 1 ]; then
	step "Pushing main to origin"
	git push origin main
else
	echo "Not pushed (pass --push to push main after a verified deploy)."
fi
