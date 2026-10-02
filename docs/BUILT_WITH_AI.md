# Built with AI

FermentOps was built with an AI coding assistant ([Claude Code](https://claude.com/claude-code)) as a personal project, not a work task. This page explains the method, because the interesting question about AI-assisted code isn't *whether* an assistant wrote it. It is *how you know it's right*.

## The principle: make the code checkable

An assistant can write plausible code very quickly. Plausible isn't correct, so the project is organised so that wrongness is hard to hide:

| Practice | How it shows up here |
|---|---|
| **Small, pure core** | All formulas live in one side-effect-free module ([`core_logic.py`](../core_logic.py)), so each can be checked in isolation against a hand calculation |
| **Validation at the boundary** | Pydantic models and explicit `FermentValueError`s reject impossible input instead of producing a confident wrong answer |
| **Tests as the contract** | 130+ tests, including worked examples computed independently and a headless run of the real UI. A change is only "done" when they pass |
| **Verify in the real runtime** | The deployed app is checked by actually loading it in a browser, not by assuming it works |
| **Humans own domain decisions** | Which formulas, which alert thresholds and what counts as safe are domain judgements that the person who ferments makes, not the tool |

## A concrete example of the loop

While preparing this repository for GitHub Pages, the assistant was asked to deploy and document the app. Reviewing and running it, rather than just writing the docs, surfaced three real problems that tests and documentation alone would have hidden:

1. **A wrong constant.** The hydrometer correction polynomial had `0.0000020441` where the published coefficient is `0.00000204052596`, a digit transcription slip. The effect is small (about 1e-5 SG at typical temperatures, up to about 1.6e-4 at extreme ones), but it is exactly the kind of quiet error that a confident-looking formula hides. It was found by comparing against the published form while writing the formula documentation, fixed, and pinned with a test that evaluates the published polynomial independently.
2. **A runtime assumption that didn't hold.** The app imported `sqlite3` at start-up. That works on a laptop but fails in the browser's Python (Pyodide), which doesn't ship it. It only showed up by *running the deployed build*, since unit tests on a laptop passed. The fix was to import it lazily, because the browser never uses it.
3. **An unverified claim.** `requirements.txt` declared `streamlit>=1.44`, but the app uses newer APIs (for example `width="stretch"` on dataframes) and nobody had tested that floor. It could not be bisected cleanly on the available toolchain, so the minimum was raised to a version that *was* verified (1.62, which the browser build runs; 1.64 was used locally) rather than leaving a number that looked authoritative and wasn't.

None of these needed cleverness. They needed running the thing and checking its claims, which is the habit that makes working with an AI assistant safe.

## What the assistant is good and bad at here

- **Good:** drafting boilerplate and tests quickly, wiring up CI, finding inconsistencies when asked to review, and explaining unfamiliar tooling (for example, getting a Python server app onto static hosting with WebAssembly).
- **Needs a check:** numeric constants, version numbers, and any claim about how an external system behaves. These are exactly the things that look right and aren't.
- **Not its call:** what the product should do, what's safe, and what to publish under someone's name.

## If you reuse this approach

1. Put the logic you can't afford to get wrong in a pure module with no I/O.
2. Write the test before you trust the formula, using a value you computed another way.
3. Run the real artefact in its real environment before calling it finished.
4. Treat every number, version and API claim the assistant produces as a hypothesis until something confirms it.
