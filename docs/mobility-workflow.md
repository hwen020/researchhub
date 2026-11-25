# Wearable mobility workflow

Upload [the synthetic sample](examples/mobility-synthetic.csv) as an immutable dataset version. In Workflows, select Wearable mobility, the dataset, its version and the study timezone. The pipeline validates the CSV, normalizes timestamps, groups observations by local day and participant, measures screened distance, then produces CSV and GeoJSON. Workers need the GEOSPATIAL capability. Open the final job under Jobs to download the exports.

CSV reports observed samples, steps, screened distance, gaps, speed outliers and repeated coordinates. GeoJSON uses WGS84 longitude/latitude order and splits routes at screened edges. The thresholds are 120 km/h and two hours. Cross-day edges are excluded. Results reflect sparse synthetic samples and are sensitive to cadence and GPS noise. Projected area and sampling coverage are outside this pipeline's scope.

## Source reuse

- Repository and exact commit [Wearable Mobility Research Pipeline at 82cd2f3](https://github.com/hwen020/wearable-mobility-research-pipeline/tree/82cd2f3b9f051c7a0c51fe803f592eae3f77e845).
- Source `app/pipeline.py` contributed participant ID, UTC timestamp, coordinate, step and synthetic-source validation. ResearchHub adapted the parser to a bounded immutable CSV snapshot with duplicate participant timestamp rejection.
- Source `app/analytics.py` contributed Haversine distance, screened edges, local-day aggregation and GeoJSON segmentation. ResearchHub adapted the routines from ORM objects to JSON stage results and added project-scoped CSV export.
- Target `backend/researchhub/mobility.py`. The [original MIT license](mobility-LICENSE.txt) is preserved.
