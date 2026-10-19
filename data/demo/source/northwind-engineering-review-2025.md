---
id: demo-northwind-review
title: Northwind Analytics: 2025 Annual Engineering Review (fictional)
author: DocuMind demo corpus
subject: A fictional company report written for the DocuMind demo
---
# Northwind Analytics: 2025 Annual Engineering Review

## Fictional sample document

Northwind Analytics is a fictional company. This review was written for the DocuMind demonstration corpus, and every name, number and event in it is invented. It does not describe any real organisation.

## 1. Company overview

Northwind Analytics sells a hosted analytics platform that lets mid-sized retailers explore sales, inventory and customer data through interactive dashboards. The company was founded in 2019 and is headquartered in Aarhus, Denmark, with a second engineering office in Copenhagen.

### Financial summary

Northwind's revenue for the 2025 financial year was DKK 48.2 million, an increase of 31 percent from DKK 36.8 million in 2024. Recurring subscription revenue accounted for 91 percent of the 2025 total; the remainder came from onboarding and consulting services. The company reached positive operating cash flow in the third quarter of 2025.

The board approved an operating budget for 2026 in December 2025. This review does not contain revenue forecasts or financial targets for any year after 2026.

### People

At the end of 2025 Northwind employed 112 people, of whom 47 worked in engineering. The engineering organisation is divided into four teams: Ingestion, Platform, Dashboards and Billing. Each team owns its services in production and participates in a shared on-call rotation.

### Customers and usage

The platform served 640 paying customer organisations at the end of 2025. Customers loaded an average of 2.1 billion events per day into the platform during the fourth quarter, compared with 1.3 billion events per day in the fourth quarter of 2024. Dashboard page views grew more slowly than event volume, by 22 percent over the year, because most new event volume came from automated integrations rather than from new users.

### Highlights of the year

- Migrated all customer databases to a new PostgreSQL cluster with synchronous replication.
- Introduced a Redis cache layer for dashboard queries.
- Moved feature flags and service configuration to an etcd cluster.
- Achieved 99.97 percent availability against a target of 99.95 percent.

<<<PAGEBREAK>>>

## 2. Platform architecture

### Event ingestion

Customer systems send events to a fleet of stateless ingestion services, which validate each event and write it to a partitioned message log. Stream processors read the log, aggregate events into hourly and daily summaries, and store the summaries in a columnar analytics store. Raw events are retained for 400 days.

### Transactional data

Account, subscription and billing data are stored in a PostgreSQL cluster with one primary server and two synchronous replicas. The Billing team runs all invoice and payment transactions at the SERIALIZABLE isolation level, which PostgreSQL implements with serializable snapshot isolation, and the billing service automatically retries any transaction that fails with a serialization error, up to three attempts. The Billing team chose this approach after an incident in 2024 in which two concurrent plan changes for the same customer produced an invoice with both the old and the new plan.

Other services use the default READ COMMITTED isolation level and protect individual rows that may be updated concurrently with a version column.

### Dashboard cache

Dashboard queries are expensive because they scan large ranges of aggregated data. In February 2025 the Dashboards team introduced a Redis cluster of six nodes that caches query results using the cache-aside pattern. Cache entries originally used a fixed time to live of 10 minutes. At the end of the year the dashboard cache served 87 percent of dashboard queries without touching the analytics store.

### Configuration and coordination

Feature flags, service discovery records and rate-limit settings are stored in an etcd cluster of five members, spread across three availability zones. Services read configuration from a local in-memory copy and watch etcd for changes, so they keep running with the last known configuration if etcd is unavailable. Changes to configuration, however, require etcd to accept writes.

<<<PAGEBREAK>>>

## 3. Reliability and incidents

Northwind measures availability as the fraction of one-minute intervals in which the dashboard and ingestion endpoints both respond successfully to synthetic checks. Availability in 2025 was 99.97 percent against a target of 99.95 percent. The team recorded 14 incidents, two of which were classified as major.

### Major incident 1: dashboard cache stampede

On 14 March 2025 the Redis dashboard cache cluster was restarted during a routine version upgrade. The restart emptied the cache. At the start of the European business day, thousands of dashboard requests missed the cache at the same time and sent their queries directly to the analytics store, whose CPU utilisation reached 100 percent. Dashboards were slow or unavailable for 23 minutes until engineers throttled traffic and the cache refilled.

The post-incident review identified the missing protection against concurrent cache misses as the root cause. The Dashboards team made two changes. First, they added request coalescing, so that only one request recomputes a missing cache entry while other requests for the same entry wait for its result. Second, they replaced the fixed 10-minute time to live with a random value between 8 and 12 minutes, so that entries created together no longer expire together. Cache restarts are now performed one node at a time.

### Major incident 2: configuration store unavailable

On 9 October 2025 two of the five etcd members were stopped for planned operating-system maintenance. While they were stopped, a disk failure took a third member offline. With only two of the five members running, the etcd cluster could not form a majority and stopped accepting writes. For 41 minutes no configuration changes or feature-flag updates could be made. Services continued to run with their last known configuration, so customers were not affected.

The Platform team changed the maintenance procedure so that at most one etcd member is taken offline at a time, and added an alert that fires when fewer than four members are healthy.

### Other reliability work

- Introduced automated failover drills for the PostgreSQL cluster every quarter.
- Reduced the median time to detect an incident from 6 minutes to 2 minutes.
- Wrote runbooks for every alert that can page an engineer.

<<<PAGEBREAK>>>

## 4. Engineering guidelines and 2026 priorities

### Engineering guidelines

The engineering handbook was revised in 2025. Two guidelines generated the most discussion.

The first guideline concerns concurrency. The handbook states that optimistic concurrency control is always faster than locking, and that new services should therefore use version columns instead of explicit row locks. The Billing team has an approved exception to this guideline, described in section 2.

The second guideline concerns caching. Every cache entry must have a time to live, and services must remain correct, if slower, when their caches are empty.

### Performance

In the fourth quarter of 2025, the 95th percentile latency of dashboard page loads was 180 milliseconds. The target for the end of 2026 is 120 milliseconds.

### Priorities for 2026

- Move read-only dashboard queries to PostgreSQL read replicas and a second analytics store region.
- Reduce the 95th percentile dashboard latency to 120 milliseconds.
- Add a local in-process cache in front of Redis for the most frequently requested dashboard tiles.
- Partition the ingestion message log by customer to support customers above 100 million events per day.
- Complete SOC 2 Type II certification.

### Open questions

The architecture group has not yet decided whether the analytics store should be replaced in 2027. A decision is expected after the 2026 capacity review. Headcount plans beyond 2026 have not been set.
