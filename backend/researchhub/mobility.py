"""Adapted MIT-licensed Wearable Mobility routines; see docs/mobility-workflow.md."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from math import atan2, cos, isfinite, radians, sin, sqrt
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

EARTH_RADIUS_KM = 6371.0088
MAX_SPEED_KMH = 120.0
MAX_GAP_HOURS = 2.0
REQUIRED = {"participant_id", "timestamp_utc", "latitude", "longitude", "steps"}
OPTIONAL = {"heart_rate_bpm", "source"}
PARTICIPANT_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
MAX_ROWS = 1024


def parse_row(row):
    participant = row["participant_id"].strip()
    if not PARTICIPANT_PATTERN.fullmatch(participant):
        raise ValueError("Invalid synthetic participant identifier")
    timestamp = datetime.fromisoformat(row["timestamp_utc"])
    if timestamp.utcoffset() is None:
        raise ValueError("Mobility timestamps require UTC offsets")
    latitude, longitude = float(row["latitude"]), float(row["longitude"])
    if not (isfinite(latitude) and isfinite(longitude) and -90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("Coordinates are outside valid WGS84 ranges")
    steps = int(row["steps"])
    heart_rate = row.get("heart_rate_bpm", "").strip()
    source = row.get("source", "synthetic").strip().lower() or "synthetic"
    if not 0 <= steps <= 100000 or (heart_rate and not 30 <= int(heart_rate) <= 240):
        raise ValueError("Steps or heart rate are outside fixture bounds")
    if source not in {"synthetic", "demo", "simulated"}:
        raise ValueError("Mobility fixtures must be labeled synthetic, demo or simulated")
    return dict(participant_id=participant, timestamp_utc=timestamp.astimezone(timezone.utc).isoformat(),
                latitude=latitude, longitude=longitude, steps=steps)


def validate_observations(payload):
    rows = payload["rows"]
    if not 2 <= len(rows) <= MAX_ROWS:
        raise ValueError(f"Mobility datasets require 2 to {MAX_ROWS} observations")
    if any(not REQUIRED <= row.keys() or row.keys() - REQUIRED - OPTIONAL for row in rows):
        raise ValueError("Mobility CSV columns do not match the schema")
    normalized = [parse_row(row) for row in rows]
    keys = {(row["participant_id"], row["timestamp_utc"]) for row in normalized}
    if len(keys) != len(normalized):
        raise ValueError("Duplicate participant and timestamp")
    try:
        ZoneInfo(payload["timezone"])
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Unknown study timezone") from exc
    return {"rows": normalized, "timezone": payload["timezone"]}


def temporal_processing(payload):
    zone = ZoneInfo(payload["timezone"])
    groups = defaultdict(list)
    for row in payload["rows"]:
        local_date = datetime.fromisoformat(row["timestamp_utc"]).astimezone(zone).date().isoformat()
        groups[(row["participant_id"], local_date)].append(row)
    return {"groups": [
        {"participant_id": participant, "date": date,
         "observations": sorted(rows, key=lambda row: datetime.fromisoformat(row["timestamp_utc"]))}
        for (participant, date), rows in sorted(groups.items())
    ], "timezone": payload["timezone"]}


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
    return 2 * EARTH_RADIUS_KM * atan2(sqrt(a), sqrt(max(0, 1 - a)))


def edge_quality(previous, current):
    hours = (datetime.fromisoformat(current["timestamp_utc"])
             - datetime.fromisoformat(previous["timestamp_utc"])).total_seconds() / 3600
    if hours <= 0:
        return 0.0, "nonpositive_interval"
    if hours > MAX_GAP_HOURS:
        return 0.0, "sampling_gap"
    length = haversine_km(previous["latitude"], previous["longitude"], current["latitude"], current["longitude"])
    if length / hours > MAX_SPEED_KMH:
        return 0.0, "speed_outlier"
    return length, "repeated_coordinate" if length == 0 else None


def analyze(payload):
    metrics = []
    for group in payload["groups"]:
        points = group["observations"]
        edges = [edge_quality(previous, current) for previous, current in zip(points, points[1:])]
        flags = Counter(flag for _, flag in edges if flag)
        metrics.append({
            "participant_id": group["participant_id"], "date": group["date"], "samples": len(points),
            "steps": sum(point["steps"] for point in points), "distance_km": round(sum(length for length, _ in edges), 3),
            "speed_outliers": flags["speed_outlier"], "sampling_gaps": flags["sampling_gap"],
            "repeated_coordinates": flags["repeated_coordinate"],
        })
    return {**payload, "records": metrics}


def spatial_aggregation(payload):
    features = []
    for group in payload["groups"]:
        points = group["observations"]
        segments = [[points[0]]]
        for previous, point in zip(points, points[1:]):
            _, flag = edge_quality(previous, point)
            if flag not in (None, "repeated_coordinate"):
                segments.append([])
            segments[-1].append(point)
        for segment in segments:
            if len(segment) > 1:
                features.append({
                    "type": "Feature", "properties": {"participant_id": group["participant_id"], "date": group["date"]},
                    "geometry": {"type": "LineString",
                                 "coordinates": [[point["longitude"], point["latitude"]] for point in segment]},
                })
    return {"records": payload["records"], "geojson": {"type": "FeatureCollection", "features": features},
            "timezone": payload["timezone"]}


def report(payload):
    return dict(payload, method="Screened WGS84 Haversine distance", source="synthetic",
                limits={"max_gap_hours": MAX_GAP_HOURS, "max_speed_kmh": MAX_SPEED_KMH})
