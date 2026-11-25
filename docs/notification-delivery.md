# Project notification delivery

A source transaction records job failure, workflow completion, funding approval activity or a project announcement with its notification intent. The kind and source ID deduplicate repeated source actions. The scheduler assigns replay sequence numbers to committed intents in a serialized publication transaction. A late commit receives a later sequence even when its event was created first.

Clients request the project feed with `after` set to the last confirmed sequence. The workbench polls while Notifications is open and retries after a connection failure. It rebuilds from the durable feed after reload. Read receipts are independent per account. Researchers receive funding notices only for their own requests. PIs, finance and platform administrators see project funding activity. Every read and update rechecks project authorization.
