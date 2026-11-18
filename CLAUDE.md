# CLAUDE.md - OXT Community Stacks

Stacks and script libraries that strangers share, the checker that
reads them, and the builder of the gallery that plays the stacks and
hands out the libraries. Read [README.md](README.md) and
[docs/MAINTAINING.md](docs/MAINTAINING.md) first.

The stacks here are other people's programs. Every rule below exists so
that a stack, or a pull request, can never do more than its box allows.

## Rules that are never traded away

1. **Nothing from a pull request is run by a workflow that holds a
   right or a secret.** `scan.yml` runs on `pull_request_target` with
   the main branch's tools and treats the pull request's files as data.
   Never check the pull request's branch out into its workspace, and
   never run anything from the folder its files are fetched into.
2. **A stack's script never runs outside a browser's box.** The scanner
   reads a stack with `lockMessages` on and the engine's permissions
   taken away, as the user "nobody" with no network
   (`tools/scan.py`, `tools/scan-dump.livecodescript`). No tool here
   opens a stack in a way that runs its handlers.
3. **A stack plays only in a frame without `allow-same-origin`.**
   `SANDBOX` and `GUARD` in `tools/build_site.py` are the whole wall:
   the frame's sandbox makes the stack a stranger to the site, and the
   guard keeps the player from playing anywhere else.
   `tools/tests/test_browser.py` plays a hostile stack against it; a
   change that weakens the wall must make that test fail.
4. **Nothing a stack brings is served as a page of the site.** Its
   files go into one `.zip`; a screenshot is served under a name made
   by the builder, and only when it starts as a picture does. Every
   word from a listing or a script is escaped (`esc` for HTML, `md` and
   `md_code` for the pull request comment).
5. **The signing key's secret half is never printed, logged or
   committed**, and only the `sign` job of `publish.yml` sees it. Do not
   move signing into a job that reads stacks or runs a browser.
6. **The gallery is never deployed to an address shared with anything
   else** (docs/MAINTAINING.md, "Where the gallery may live").
7. **The scanner fails closed.** What it cannot read (a password, a
   dump that does not parse, an engine that would not start) is a
   refusal or an error, never a pass.
8. **A library has no box, so it is never anything but text that was
   read.** A script library (`libraries/`) is installed into people's
   IDEs and runs as their own scripts do; nothing on the site runs one.
   It must be one script-only stack, with a name and handlers that are
   nobody else's, and the package people install is made by
   `tools/build_site.py` from the checked text (`scan.library_package`),
   never taken from the author. The list the IDE installs from,
   `libraries.json`, is signed like `index.json`, which itself must
   stay what released IDEs read. Compiled extensions (`.lcm`) and
   native code are refused: do not add a way to list them without
   asking first.

## Working here

- Python standard library only, in `tools/`. No packages.
- **Every rule has a test**, with a stack that breaks it and one that
  does not (`tools/tests/`, fixtures made by the real engine). A new
  rule, limit or page comes with its test. A security fix comes with
  the stack that got through before it.
- Run the tests with the engine and the browser, as CI does:

  ```sh
  export OXT_ENGINE=$(python3 tools/fetch.py engine ~/oxt-cache)
  export OXT_PLAYER=$(python3 tools/fetch.py player ~/oxt-cache)
  OXT_REQUIRE_ENGINE=1 OXT_REQUIRE_BROWSER=1 python3 -m unittest discover -s tools/tests
  ```

  Without `OXT_REQUIRE_*` the tests that need the engine or the browser
  skip themselves, which is not a pass.
- A published stack version is never changed. Rules that grow may
  refuse a stack that is already listed; Publish then leaves it out
  with a warning, and that is the intended result.
- Words that visitors read (the site, the checker's comment) are plain
  and short. Many readers are not programmers.
- Workflows pin every action to a commit, give each job only the
  permissions it uses, and say at the top why they are safe.
