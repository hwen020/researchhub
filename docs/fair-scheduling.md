# Fair scheduling

The queue ranks eligible projects by their persisted last-dispatch sequence. A successful claim moves its project to the end of the rotation. Eligibility requires backoff to have elapsed, a matching worker and sufficient project resources. Projects with no eligible job leave room for other work.

Within a project, priority is an integer from 0 through 10. A job gains one effective priority point every 30 seconds up to 10. Older jobs win equal-priority ties. Conditional eligibility and capacity still apply after aging. The database preserves the dispatch order across process restarts.

A schema-scoped PostgreSQL lock serializes decisions. Fenced job state is the reservation ledger. Transitions that occur outside the scheduling lock can reduce active usage or move an active job back to retry without increasing outstanding demand. Serialized decisions can limit throughput at high dispatch rates. Measure that cost separately from plugin execution time.
