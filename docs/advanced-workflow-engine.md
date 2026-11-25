# Advanced workflow engine

The scheduler locks active workflow rows while it reconciles states and enqueues jobs. A node waits until its dependencies are terminal. The default condition requires success. Failed or cancelled inputs block default descendants. Unmet explicit conditions mark nodes skipped. Finalizers run after their dependencies settle. Conditions are limited to success, any dependency failure, always, or exact scalar equality with a successful dependency's top-level result field.

A rerun creates a descendant run from the saved snapshot. The selected failed or cancelled node and its descendants are recomputed. Whole-run retry recomputes failed, cancelled and blocked nodes and their descendants. Unaffected completed nodes retain references to their original job and attempts. Changed input or parameter values require a new run. Cancel waits for previously issued leases to settle. Provenance links the run, parent, version, input digests, attempts and output digests.
