# Real-world extraction benchmark

The unit tests use invoices this project renders itself. This benchmark measures the text-layer
extractor on **115 invoices it did not create**, from two public corpora, so the accuracy claims in the
main README are reproducible.

```bash
cd backend
uv run python -m benchmarks.realworld.run            # download (cached, checksum-verified) and score
uv run python -m benchmarks.realworld.run --write    # refresh RESULTS.md and results.json
```

Latest results: [RESULTS.md](RESULTS.md).

## Sources

| Corpus | Commit | Licence | Documents | Ground truth |
|---|---|---|---|---|
| [invoice-x/invoice2data](https://github.com/invoice-x/invoice2data) `tests/compare` | `643eec7` | MIT | 11 | the project's own expected-output JSON |
| [ZUGFeRD/corpus](https://github.com/ZUGFeRD/corpus) `ZUGFeRDv2/correct`, `XML-Rechnung` | `82e886f` | Apache-2.0 | 104 | the CII XML embedded in each PDF |

invoice2data covers real vendor invoices (AWS, Flipkart, OYO, Coolblue, Free and others) in English,
Dutch, French and German. The ZUGFeRD corpus contains hybrid e-invoices produced by several
e-invoicing products, mostly in German. In those, the printed PDF and the embedded XML describe the
same invoice, which gives exact per-field ground truth. The documents are downloaded at pinned commits
and verified against the SHA-256 digests in [`datasets.lock.json`](datasets.lock.json); none are
committed here.

## Method

- **Scored extractor:** `PdfTextExtractor(read_embedded=False)`. In production, embedded e-invoice XML
  is read directly when present, but here the XML *is* the ground truth, so using it would be circular.
- **Matching:** amounts within 0.01; invoice and PO numbers after removing punctuation and case;
  dates exactly; tax IDs after removing spaces; vendor names by fuzzy match (token-set ratio ≥ 85 after
  dropping legal forms). Fields absent from the ground truth are not scored.
- **Core rate:** invoice number, invoice date and total all correct on the same document.
- **Splits.** The parser was developed against the **dev** split only (invoice2data, the FeRD
  XML-Rechnung examples and intarsys). The **test** split (Symtrax, FNFE, Mustang and PHP producers)
  was never opened while developing. Its scores were computed twice, once before and once after a
  final general change (reading column headings' values from the row below) that was judged on dev
  alone.
- **Baseline:** before this work the extractor, built against the project's own generated layouts,
  scored **0%** on the core rate for both splits.

## Known gaps

- The held-out invoice-number and date accuracy (~55%) is well below dev (~90%): some producers place
  them in layouts the rules don't recognise yet.
- invoice2data's "issuer" is a brand name (e.g. "OYO"), while invoices often print the legal entity
  ("Oravel Stays Pvt. Ltd."). These count as misses.
- No scanned documents: OCR is delegated to the Azure Document Intelligence extractor.
