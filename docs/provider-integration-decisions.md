# External provider decisions

Checked against official provider information on 2026-10-01. Do not add credentials or a production adapter until the corresponding commercial account, licence, sandbox, and operating entity are confirmed.

## Market data

Start with licensed end-of-day data because the current product evaluates completed daily bars. The [Casablanca Stock Exchange market-data offer](https://www.casablanca-bourse.com/en/market-data/offre-market-data) includes end-of-day, historical, reference, dividend, and corporate-action data, and the exchange publishes a list of [certified redistributors](https://www.casablanca-bourse.com/en/market-data/rediffuseurs). Request a sample and written terms from its Market Data department before implementing the transport.

The agreement must state display and redistribution rights, permitted retention, user/device limits, delayed versus real-time labeling, environments, instrument identifiers, corrections, calendars, corporate actions, backfill depth, rate limits, support, and termination behavior. The first adapter should populate the existing catalog, sessions, adjusted daily bars, FX rates, and provenance fields. It must never relabel a delayed or derived value as real-time.

[Twelve Data documents](https://twelvedata.com/docs) a broad REST/WebSocket API, exchange/MIC metadata, daily bars, adjustments, and FX. Treat it as an international-market candidate only after its sales team confirms the exact exchanges, instruments, business plan, and redistribution rights needed by this SaaS. Its general country coverage is not evidence that a particular Casablanca instrument is licensed.

## Broker

Interactive Brokers is a reasonable first sandbox candidate. Its official country list currently includes [Morocco](https://portal.interactivebrokers.com/en/accounts/open-account-country-list.php), and its [paper-account documentation](https://ibkrcampus.com/campus/glossary-terms/paper-trading-account/) supports the Web and TWS APIs. The [Web API documentation](https://ibkrcampus.com/campus/ibkr-api-page/webapi-doc/) says individual paper API use requires a fully open, funded IBKR Pro live account; third-party products require compliance approval, and sessions and rate limits constrain the integration.

Therefore the next broker step is an onboarding/approval decision, not live order code. Once approved, implement sandbox-only authentication, contract-ID mapping, order preview, an explicit state machine, idempotent submission, confirmations, polling/webhook reconciliation, account/currency checks, a kill switch, and an immutable audit trail. Keep the current `501` live boundary until those tests pass.

## Billing

Stripe's current [global availability list](https://stripe.com/global) does not include Morocco. Do not build a Stripe-specific subscription core for a Morocco-only legal entity. Stripe remains possible if the operating company and bank account satisfy its rules in a supported country.

For a Moroccan entity, begin commercial onboarding with CMI or one of its payment-establishment partners. CMI describes [online card acceptance](https://www.cmi.co.ma/fr/solutions-paiement-ecommerce), saved cards for repeat customers, refunds, and merchant reporting, but a public subscription/webhook contract was not identified. Obtain sandbox documentation for recurring authorization, mandates, webhook signatures, retries, refunds, chargebacks, reconciliation, and test cards before selecting it for SaaS subscriptions.

The application billing domain should stay provider-neutral: plans, entitlements, quotas, provider customer/subscription IDs, an idempotent webhook inbox, effective periods, grace/cancel states, and an append-only billing audit. Card data must remain on the provider's hosted flow.

## Decisions required

Before provider code begins, record:

1. Legal entity and billing country.
2. Launch audience, exchanges, delayed/real-time requirement, and expected users.
3. Market-data display/redistribution and retention rights.
4. First broker and whether the product acts as a third-party trading interface.
5. Identity provider and allowed organization/account model.
6. Transactional email provider and sending domain.
7. Monthly provider budget and target launch date.

Until these are settled, continue provider-independent work: durable jobs/alerts, entitlements, the TypeScript web shell, operational infrastructure, and measured performance benchmarks. The bounded portfolio CSV import is implemented; files above its synchronous limit will use the durable job framework.
