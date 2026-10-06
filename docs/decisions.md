# Project decisions

## Mortgage origination risk as the first release

Date: 2026-10-06
Status: accepted

The initial source is the official Freddie Mac Single-Family Loan-Level Dataset, beginning with samples. The first model predicts a proposed 90+ delinquency event over a defined 12-month horizon from origination, using only available origination attributes.

Monthly histories support target construction, temporal analysis and later monitoring. Exact month alignment and terminal-event treatment remain pending source inspection.

This scope enables interpretable PD research and later lifetime analysis. It does not support CCF estimation from mortgage data; revolving-credit data are required for that extension. Forecasting and agent components remain later milestones.
