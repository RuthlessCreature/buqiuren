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

## 6tail/lunar-python

- Upstream: `https://github.com/6tail/lunar-python`
- Runtime package: `lunar-python==1.4.8`
- License: MIT
- Purpose: deterministic calendar/date facts for current-turn expressions such as today, yesterday, tomorrow and explicit solar/lunar dates; in particular, Gregorian/lunar conversion and the day's GanZhi.
- Integration: `src/calendar_context.py` resolves date expressions before the LLM is called. The model receives the calculated date fact and only interprets it; it does not calculate the day pillar itself.

### Update policy

The runtime version is pinned. Before changing it:

1. review upstream changes;
2. run the public README fixture (`1986-05-29` = `癸酉日`);
3. run relative-date, explicit-solar and explicit-lunar regression tests;
4. verify the Worker bundle under Pyodide/Cloudflare;
5. document the version change.

## Python packages

Runtime dependencies are declared in `pyproject.toml` and resolved at build time. Their individual licenses remain governed by their upstream package metadata.