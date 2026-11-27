# v3.3 approved coverage objectives

Scope: original fixed 300-security universe as of 2026-11-24 for regression.
The new recommendation universe remains 300 securities. External issuers are
comparison-only. No change to production or dashboard until user review.

## Release criteria
- Actual statement source collection >=99%; separately report original-security
  and eligible-issuer denominators, never silently remove source failures.
- Weighted full-factor coverage >=95%, each of the eight factors >=95%,
  industry-relative factor >=95%, financial specialized/alternative slots >=95%.
- Official complete eight-factor scores >=95% of eligible targets; the same
  issuer must satisfy all eight factors, not just an average across issuers.
- Independent source reconciliation >=99%; tests 100%; no duplicated source
  metrics or invented values. Unverified measures block release.
- Track 97–98% as a stretch objective rather than an achieved result.

## Experiment and adoption
Preserve weights 20/15/10/10/10/15/10/10. The five industrial economic slots
remain 2 points each. Test ROA as an alternative to ROIC, liabilities/equity
as an alternative to net debt/EBITDA, net margin and operating cash flow/sales
as alternatives to their primary measures. Compare like with like, never mix
different ratios within a percentile distribution. Examine rank changes and
overlap before adoption. Exact code and broader three-digit code groups are
separate scenarios, and business comparability must be reviewed.

For forward-looking evidence, distinguish independent broker research,
explicit issuer forward guidance and historical earnings trends. Historical
growth is not a forecast and must not be counted as one. A renamed 10-point
outlook model needs an independently validated common scoring rubric. Missing
analyst reports must not be represented as analyst consensus.

For financials, keep the five existing models, review the unclassified 40
issuers, and separately define investment holding, REIT and infrastructure
models. Regulatory capital, liquidity, profitability and solvency alternatives
must be appropriate to the specific business model. Do not substitute ROE for
regulatory capital or reuse an existing factor's input under another name
without explicit overlap review.

All current results and experiments remain candidate-only. Record both
full-coverage and partial-coverage rates, not just one headline percentage.
