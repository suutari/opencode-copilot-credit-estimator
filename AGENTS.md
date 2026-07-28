# AGENTS.md

Instructions for agents working in this repository.

## Cutting a release

This project has an associated Homebrew formula at
`springernature/homebrew-opensource` (`Formula/opencode-copilot-credit-estimator.rb`).
It currently tracks `head` (the `main` branch) because there is no tagged
release yet — that must change as part of every release going forward.

When cutting a new release (see `CONTRIBUTING.md` for the version-bump/tag
steps), you must also update the Homebrew formula in the same pass:

1. Clone `springernature/homebrew-opensource` and open
   `Formula/opencode-copilot-credit-estimator.rb`.
2. Point the formula at the tagged release instead of `head`:
   - Replace the `head "ssh://git@github.com/springernature/opencode-copilot-credit-estimator.git", branch: "main"`
     line (and its accompanying "no tags/releases yet" comment) with a
     versioned `url` + `sha256` pointing at the release tarball, e.g.:
     ```ruby
     url "https://github.com/springernature/opencode-copilot-credit-estimator/archive/refs/tags/vX.Y.Z.tar.gz"
     sha256 "<sha256 of that tarball>"
     ```
     Compute the sha256 with `curl -L <tarball-url> | shasum -a 256`.
   - Bump the formula's version to match the new tag (Homebrew infers this
     from the `url` for GitHub tag tarballs, but double check with
     `brew audit`/`brew style` if available).
3. Update the `license` field — it currently reads
   `license :cannot_represent # no LICENSE file is present upstream yet`.
   Since a `LICENSE` file (MIT) now exists upstream, this should be
   `license "MIT"`.
4. Re-check the `resource` blocks (dependency name/version/sha256 for
   `textual`, `textual-plotext`, and their transitive deps) against the
   `uv.lock` in this repo at the tagged commit — regenerate any resources
   whose pinned versions have moved since the formula was last updated.
5. Sanity check the `install`/`test` blocks still match this repo's layout
   (currently: no `[project.scripts]` entry point, so the formula builds a
   venv and hand-writes a wrapper script for `estimator.py` — see
   `Formula/opencode-copilot-credit-estimator.rb` for the exact approach).
   If packaging changes in this repo (e.g. a console-script entry point is
   added later), the formula's `install` block must be updated to match.
6. Commit and push the formula change to `homebrew-opensource` (or open a PR,
   per that repo's contribution norms), referencing the release tag in the
   commit message.
7. Verify locally if possible:
   ```sh
   brew install --build-from-source springernature/opensource/opencode-copilot-credit-estimator
   brew test springernature/opensource/opencode-copilot-credit-estimator
   ```

Do not consider a release finished until the formula update has been made —
a tagged GitHub release with no corresponding formula update leaves the tap
silently stale (still serving `head`, or an outdated pinned version).
