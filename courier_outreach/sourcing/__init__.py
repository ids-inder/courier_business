"""Lead sourcing — pluggable discovery of companies that dispatch goods in
Tricity and Baddi / BBN, plus extraction of the email they publish on their own
website.

Sources implement the `Source` protocol (see base.py). Shipped sources:
  - OverpassSource  (OpenStreetMap; free, no API key)
  - CsvImportSource (a seed list you provide, or an official seller-account export)

`ingest.ingest()` runs a source, enriches candidates with a published email,
and upserts them into the DB (de-duplicated).
"""
