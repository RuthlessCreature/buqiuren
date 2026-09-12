# Third-party components and provenance

## china-testing/bazi

- Upstream: `https://github.com/china-testing/bazi`
- Pinned revision: `33b18354d5407727640e545c3aaec0efb4bf5282`
- Purpose: authoritative Bazi chart calculation for this application
- Integration: `scripts/vendor_bazi.sh` fetches the exact revision during build; `src/bazi_adapter.py` executes the upstream `bazi.py` with its documented CLI arguments and captures its output. The application does not reimplement the Bazi chart algorithm.

### Licensing note

At the time this project was prepared, the upstream GitHub repository did not declare a repository license. No upstream source files are committed into this repository by this project; they are fetched from the pinned upstream revision during build. This technical arrangement is **not** a substitute for copyright permission. Before commercial/public operation, the operator should obtain appropriate permission from the upstream author or otherwise confirm a lawful basis for use and redistribution in the deployed bundle.

### Update policy

Do not silently track `master`. Any upstream update must be deliberate:

1. review the upstream diff;
2. update the pinned commit in both `scripts/vendor_bazi.sh` and `src/bazi_adapter.py`;
3. run the regression fixture from the upstream README;
4. compare representative solar/lunar, male/female, leap-month and boundary-hour charts;
5. document the change in the commit message.

This prevents an upstream change from silently altering production chart results.

## Python packages

Runtime dependencies are declared in `pyproject.toml` and resolved at build time. Their individual licenses remain governed by their upstream package metadata.
