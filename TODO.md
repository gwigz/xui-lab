# XUI Lab work

These tasks remove friction found while reviewing the production Inventory
Explorer. The changes belong in XUI Lab or its Alchemy adapter.

## Make fixture requirements explicit

- [x] Let a subject declare its default fixture or its fixture requirements in
  the adapter manifest.
- [x] Include fixture availability in `preflight` so an openable result means
  that the requested session can start.
- [x] Make `session start` and `interactive` use a declared default fixture
  when the caller omits `--fixture`.
- [x] Show the fixture used by the active process in the browser inspector.
- [x] Add regression coverage for the inspector's active-fixture state.

## Turn layout diagnostics into a reliable gate

- [x] Report a visible control whose local or clipped rectangle has a negative
  width or height.
- [x] Report a visible control that lies outside its intended parent clipping
  rectangle.
- [x] Suppress clipping reports for descendants that are intentionally
  offscreen inside a scroll container.
- [x] Suppress expected host-root overlaps such as Menu Holder against Floater
  View.
- [x] Preserve the control path, source location, rectangles, and ancestor
  chain in every actionable diagnostic.
- [x] Add `Window.expect_no_layout_diagnostics()` for scenario assertions.
- [x] Add a scenario or CLI option that fails on actionable layout diagnostics.
- [x] Let captures collect the diagnostics for the captured frame and fail when
  the strict option is active.
- [x] Add layout assertions to the Inventory Explorer width scenarios.

## Improve selectors and inspection

- [ ] Expose button tooltips or explicit LLUI accessibility metadata as the
  accessible name used by role selectors.
- [ ] Verify that icon-only buttons can be selected by role and name without a
  control ID or XUI path.
- [ ] Default the browser tree to the visible subject subtree.
- [ ] Add toggles for hidden controls, menus, and lab-owned root views.
- [ ] Keep the selected control visible when the tree filter changes.

## Add useful visual test data

- [ ] Expand the Inventory Explorer fixture with nested folders, long names,
  several item types, folder counts, worn items, favorites, and enough entries
  to exercise scrolling.
- [ ] Provide deterministic local thumbnails through the texture-fetch system
  boundary.
- [ ] Keep all fixture identifiers stable for scenario selectors.
- [ ] Add scenarios that cover real thumbnails, fallback artwork, count badges,
  long labels, and scroll boundaries.

## Speed up visual comparison

- [ ] Add named subject-size presets for common narrow, reference, and wide
  layouts.
- [ ] Add UI-scale presets for 1.0 and 1.25.
- [ ] Label filmstrip entries with subject size, UI scale, fixture, and view
  state.
- [ ] Allow the inspector to display a reference image beside a capture or as
  an adjustable overlay.
- [ ] Keep reference images outside scenario pass criteria. Structural
  assertions remain the primary proof.
