# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.0.0] - 2026-10-02

First public release.

### Added
- Live demo on GitHub Pages: the Streamlit app runs in the browser via stlite
  (WebAssembly), served from the repository's own source files.
- Test suite (130+ tests): formulas, validation, alert rules, persistence, the
  Streamlit UI (headless `AppTest`), and the Pages build.
- CI (lint and tests on Python 3.11 and 3.13) and a deploy workflow that only
  publishes when lint and tests pass.
- Documentation: architecture, formulas with worked examples, deployment, and
  how the project was built with AI assistance.
- MIT license.

### Changed
- `storage.make_store()` uses the non-persistent store when running in the
  browser (Pyodide), where there is no disk to persist to.
- `sqlite3` is imported lazily, since the browser runtime does not ship it.
- Minimum Streamlit raised to 1.62 (the version verified with the browser build)
  from an untested 1.44.

### Fixed
- Hydrometer correction polynomial: the quadratic coefficient was
  `0.0000020441` instead of the published `0.00000204052596`, and the other
  coefficients are now given at full published precision. Corrected readings
  change by about 1e-5 SG at typical temperatures (up to about 1.6e-4 at the
  extremes of the 32-212 degF range).
