# Cosmic Credit Platform

An explainable credit-risk platform, starting with origination-time risk assessment for US residential mortgages.

**Status:** foundations and architecture planning. Data ingestion, models and dashboards are planned; no predictive results are claimed yet.

## Problem

Estimate the probability that a newly originated mortgage reaches 90+ days past due within a defined 12-month performance window. Help analysts assess discrimination, calibration, cohort stability and model limitations through reproducible experiments and visual reports.

The project treats transparency, governance and monitoring as architectural properties of a risk platform.

## First release scope

- Official Freddie Mac Single-Family Loan-Level Dataset samples.
- Validated origination records and monthly performance histories.
- Explicit target, maturity and early-exit rules.
- Training-prevalence benchmark and interpretable logistic regression.
- Chronological cohort evaluation, calibration analysis and explanations.
- Portfolio-level visual diagnostics and a documented model card.

Future stages include behavioral PD, monitoring, Lifetime PD, Forward Looking scenarios and evidence-grounded risk reporting. CCF requires a separate dataset suitable for revolving credit.

## Data and limitations

Source: [Freddie Mac Single-Family Loan-Level Dataset](https://www.freddiemac.com/research/datasets/sf-loanlevel-dataset).

Access requires registration and acceptance of source terms. Raw loan records will not be committed or redistributed with this repository. A future demo will use permitted aggregate outputs or clearly labeled synthetic fixtures.

These are US mortgage data. Results will not establish applicability to Brazilian credit portfolios, regulatory compliance or the causal effect of lending decisions. The proposed 90+ delinquency event is a research outcome, not an automatic regulatory default definition.

## Development setup

Python 3.11 and uv are required. From the repository root:

```bash
uv sync --locked
uv run --locked ruff check .
uv run --locked pytest
```

These commands validate the current engineering setup; they do not train a model. Modeling dependencies will be introduced when needed.

## Architecture

See [docs/architecture.md](docs/architecture.md) for data contracts, evaluation design, module responsibilities, open decisions and release criteria.
