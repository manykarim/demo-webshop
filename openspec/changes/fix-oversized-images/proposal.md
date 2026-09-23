## Why

The early load test of `workshop-rollout` task 3.4 moved **17.0 GB in ten minutes**, and **16.8 GB of it was product images**. Every file in `backend/app/static/img/` is 3.16 MB: fourteen assets, 44 MB in total, in a shop whose entire database fits in a few hundred kilobytes.

They are also not what they claim to be. All twelve `*.jpg` product photos are PNG data with a `.jpg` name, saved at 1024x1024 with no compression to speak of, and the pages announce them as `type="image/jpeg"` in a `<picture><source>`. Browsers sniff the bytes and render them anyway, so the mistake has stayed invisible.

Three costs follow from it:

- **The workshop day.** Forty participants on conference Wi-Fi pull these images on every product page. The run above needed 227 Mbit/s to serve forty simulated shoppers; the p95 of the HTML and API requests rose to 1700 ms purely from queueing behind that traffic, while the same shop answered an idle page in 0.11 s.
- **The order documents.** `invoice.html` embeds `barcode.png` and `flowline-logo.png`, and `order_summary.html` embeds the logo. WeasyPrint decodes two 3.16 MB images per document to place them at 200 px and 150 px. Invoices come out at 735 KB and the load test measured a 3300 ms p95 on `order-doc:own`.
- **The image.** 44 MB of the published container image is these files, in every layer pull, on every participant machine that runs the shop locally.

None of this is the shop's behaviour under test. It is weight that hides the numbers the gating test in `workshop-rollout` 4.3 is supposed to measure.

## What Changes

- The twelve product images become actual JPEG files at their current 1024x1024, quality 82, progressive. Names and URLs do not change, so seed data, stories and locators are untouched; the declared `image/jpeg` type becomes true.
- `flowline-logo.png` and `barcode.png` stay PNG, at twice the size they are ever rendered at: 300 px for the logo (`max-width: 150px`) and 400 px for the barcode (`max-width: 200px`).
- `backend/app/static/img/` drops from 44.3 MB to roughly 1.3 MB, a factor of about 30.
- A test holds the line: every file under `static/img/` stays within a per-file budget, and a file's format matches its extension, so the next asset dropped into the tree cannot quietly reintroduce the problem.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
None. `.openspec.yaml` sets `skip_specs: true`. No requirement changes: the shop serves the same products, at the same URLs, with the same pages, locators and documents. Only the bytes behind each image change.

## Impact

- **Assets**: the fourteen files in `backend/app/static/img/` are re-encoded in place.
- **Tests**: new `backend/tests/integration/test_static_asset_budget.py`.
- **Documents**: invoices and order summaries get smaller and render faster; their layout is unchanged, because both images were already scaled down by CSS.
- **Rollout**: the gating load test (`workshop-rollout` 4.3) can measure the shop rather than the link. The capacity record's `early` row keeps its warning; the gating row supersedes it.
- **Not in scope**: responsive sources, a CDN image pipeline or a build-time asset step. The shop is a teaching subject, and the point here is to stop measuring the network instead of the shop.
