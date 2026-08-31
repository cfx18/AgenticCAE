# Human Geometry Reviews

Store one append-only JSONL ledger per frozen campaign in this directory. Each
line conforms to `human-geometry-review.schema.json` and binds an adjudication
to immutable evidence hashes. Never hand-edit a ledger; submit corrections as
new records that set `supersedes_review_id`, then run
`cad-evoloop geometry-review-verify` before committing it.

Reviewer identifiers should be stable pseudonyms, not personal data. Do not
commit generated review bundles or upstream dataset images.
