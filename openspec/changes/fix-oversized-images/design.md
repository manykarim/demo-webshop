## D1. Re-encode in place, keep every name

The alternative was a build step that generates web assets from originals kept elsewhere. Rejected: the shop is the subject of a workshop, and a participant who opens `backend/app/static/img/` should find the files the pages serve. Re-encoding in place keeps `image_url` values in `seed_data.py`, the `<picture>` sources, the PDF templates, the stories and every lab locator exactly as they are. The change is invisible to everything except the byte count.

## D2. Product images: JPEG at 1024x1024, quality 82, progressive

The files are already 1024x1024 and the largest place any of them renders is the home hero at 720 px, so the pixels are sufficient and are left alone: downscaling would be a visual change to a shop whose screenshots appear in the workshop material.

Quality 82 is the usual break-even for photographic content; measured across the twelve files it lands between 41 KB and 167 KB, average 90 KB. Progressive encoding costs nothing and renders the hero earlier on a slow link, which is the workshop-day case.

The extension stops lying: `Image.save(..., "JPEG")` writes JPEG bytes to a `.jpg` name, which is what `type="image/jpeg"` in `products.html`, `home.html` and `product_detail.html` already promises.

## D3. PDF assets: PNG, downscaled to twice their rendered size

`barcode.png` and `flowline-logo.png` are decorative gradient art, not scannable or vector. They keep PNG (their extension, and the invoice's `<img src>`) and lose the pixels nobody sees: the logo renders at `max-width: 150px` and the barcode at `max-width: 200px`, so 300 px and 400 px leave a 2x reserve for print DPI.

Full-colour PNG is kept over a 256-colour palette. The palette saves another 75 KB across the two files and risks banding in the gradients; at 211 KB together, against 6.2 MB today, the saving is not worth a fidelity question in a document participants will read on screen.

## D4. A budget test, not a review habit

The problem arrived because nobody weighed a file before committing it, and it survived because nothing failed. `test_static_asset_budget.py` fails on two things:

- any file under `static/img/` above **400 KB**, comfortably clear of the 167 KB largest product image and far below the 3.16 MB that caused this;
- any file whose actual format contradicts its extension, read from the file's own magic bytes, which is the specific mistake made here. Pillow would also answer this, but it reaches the test only as a transitive dependency of WeasyPrint; four signatures in the test file owe nothing to that.

The budget covers the whole directory rather than a list of known names, so a new product photo is caught on the commit that adds it.

## D5. What this does not claim

The `early` capacity row stays a warning, not a pass. This change removes the dominant term from that measurement; it does not turn a run made over a saturated client link into capacity evidence. The gating test of `workshop-rollout` 4.3 remains the one that decides, and it is run from a host with real bandwidth.
