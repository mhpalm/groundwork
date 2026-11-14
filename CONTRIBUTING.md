# Contributing to Groundwork

Thanks for helping. A few rules keep Groundwork safe to share between organizations.

## Sign your commits (DCO)

Every commit must carry a `Signed-off-by` line, which certifies the [Developer Certificate of Origin 1.1](https://developercertificate.org/):

```
git commit -s -m "Add Stripe system skill"
```

CI fails any pull request with an unsigned commit.

## What a pull request may contain

- No org-specific content: no overlays, real hostnames, customer names or email addresses. Use `example.com` and `example.org`. `tools/lint_no_org_data.py` enforces this.
- A system or tracker skill never restates a core rule. Refer to rules by id (for example, CR-01). `tools/lint_boundaries.py` enforces this.
- A new or changed system or tracker skill must state the contract version it meets in `groundwork.yaml`, include or update its golden test, and cite the platform's own documentation for every correctness rule.
- Bump the `version` of every skill you change, following semver. A breaking change to the contract or the overlay format ships with a migration in `skills/groundwork-core/migrations/`.

## Run the checks locally

Python 3.10 or later, standard library only:

```
python3 tools/run_checks.py
```

## Review

The maintainer reviews and merges every change (see `GOVERNANCE.md`).
