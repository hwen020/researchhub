# Research reproducibility

An immutable CSV version can supply inputs for the summary or age-association plugin. The summary accepts a `value` column. Age association accepts an `age` column and finite, named expression features. The job snapshots normalized inputs and, where applicable, the dataset ID, version and SHA-256. Successful jobs record the plugin version, execution attempt, code identifier, runtime details, completion time and a checksum of canonical output JSON. A configured build identifier takes precedence over the package source SHA-256. Both plugins are deterministic and require no random seed.

The genomics plugin uses exploratory Spearman correlations and Benjamini–Hochberg adjustment. The fixture demonstrates expected output for monotonic and constant features. It contains no clinical or participant data. Read the [reuse matrix](reuse-matrix.md) for upstream attribution.
