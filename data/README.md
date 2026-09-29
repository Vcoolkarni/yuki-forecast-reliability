# Data provenance

Raw meteorological files are intentionally excluded from Git. For every acquisition,
retain a manifest containing source URL/object key, retrieval UTC time, model cycle,
forecast step, variable, units, checksum, spatial subset, and processing version.
Never place generated or synthetic weather observations in the production data path.

