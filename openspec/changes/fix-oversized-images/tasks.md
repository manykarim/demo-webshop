## 1. Re-encode the assets

- [x] 1.1 Re-encode the twelve product images in `backend/app/static/img/` as JPEG, keeping 1024x1024, at quality 82 with `optimize` and `progressive`. Verify: each `*.jpg` file starts with the JPEG signature, each is under 400 KB, the directory's twelve product files total under 1.2 MB, and the pixel dimensions are unchanged at 1024x1024.
- [x] 1.2 Downscale `flowline-logo.png` to 300 px and `barcode.png` to 400 px on their longest edge, saved as optimized full-colour PNG. Verify: both start with the PNG signature, the logo is under 60 KB, the barcode is under 200 KB, and both still render in an invoice and an order summary without layout change.
- [x] 1.3 Confirm the whole directory. Verify: `backend/app/static/img/` is under 1.5 MB in total, contains the same fourteen file names as before, and `git status` shows fourteen modified files and no additions or deletions.

## 2. Hold the line

- [x] 2.1 Add `backend/tests/integration/test_static_asset_budget.py`. Verify: it fails a file above 400 KB and a file whose magic bytes contradict its extension, it walks the directory rather than a fixed list, and it passes on the re-encoded tree.
- [x] 2.2 Run the suite. Verify: `uv run pytest` is green, including the PDF tests that embed the logo and barcode, and the browser smoke tests that load product pages.

## 3. Measure the result

- [x] 3.1 Record the before and after in the PR: directory size, per-file range, invoice byte size and the container image size. Verify: an invoice generated from the re-encoded tree is materially smaller than the 735 KB the load test measured, and the numbers in the PR body are taken from commands run against this branch, not estimated.
