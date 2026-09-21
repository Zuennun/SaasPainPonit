---
name: pi-release
description: Pre-merge and release-quality checklist for the Global Problem Intelligence repository.
---

# PI Release and Review

Before considering a change complete:

- Review the final git diff.
- Confirm acceptance criteria.
- Run relevant automated tests.
- Run configured lint/type checks.
- Check migrations and schema changes when applicable.
- Check secrets and credentials are not committed.
- Verify new external dependencies are intentional.
- Verify source/evidence semantics were not weakened.
- Verify provenance remains intact.
- Update docs or ADRs when architecture or policy changed.
- Explicitly report anything that was not tested.

For important changes, prefer independent review by pi-review.

Reviewers must look for:
- unsupported claims,
- evidence inflation,
- source-specific architectural coupling,
- silent fallback behavior,
- destructive migrations,
- missing error handling,
- regression risk,
- insufficient tests.

Passing tests is necessary but not by itself sufficient for approval.
