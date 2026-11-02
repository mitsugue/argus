# Parsed restore and retired report residency

The artifact loader creates a private JSON parse. During verified-view
restore, that temporary parse can otherwise coexist with a growing store
of independently serialized destination snapshots.

`_consume_parsed_restore_snapshots` validates the entire lookup with the
existing shared normalizer, consumes only that private parse's current
mapping, and yields snapshots in the original order. Each yielded snapshot
must still pass through the existing `publish_atomic`, including its
serialized read-back, age and quality checks, limits and independently
owned destination. Caller-owned restore inputs keep the existing path.
The iterator grants no normalized provenance or verification shortcut.
Only artifact-loader call sites may select consumption; JSON data cannot.

Bulk generation attachment also has to respect the existing individual
chart retirement switch. When generation is disabled, its unchanged report
archive and item files remain detached. The checkpoint carries the existing
sealed state hash. Explicit attachment and enabled generation keep their
existing behavior. Stored reports, public retired responses, market-view
production, restoration authority and generation settings are preserved.

The Product preparation adds the consuming iterator and its compatibility
coverage. Runtime wiring selects it only for private artifact parses; default
bulk attachment respects the existing generation switch, while explicit
attachment retains its existing behavior. Neither preparation nor an
isolated comparison accepts production resources;
the deployed build must satisfy the existing actual 2 GiB criteria.
