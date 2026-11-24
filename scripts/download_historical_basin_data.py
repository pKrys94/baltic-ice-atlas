"""Retrieve historical basin SIC and thickness in resumable five-winter chunks.

The default mode performs size-only requests. Pass ``--download`` to retrieve.
Copernicus credentials are read from the local Toolbox configuration.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import copernicusmarine
import xarray as xr


ROOT = Path(__file__).resolve().parents[1]
START_YEAR = 1980
LAST_COMPLETE_WINTER = 2024
LATEST_PARTIAL_WINTER = 2025
MIN_LON = 9.0
MAX_LON = 31.0
MIN_LAT = 53.20000076293945
MAX_LAT = 66.19999694824219
RESERVE_BYTES = 5 * 1024**3

PRODUCTS = {
    "sic": {
        "dataset_id": "cmems_obs-si_bal_seaice-conc_my_1km",
        "variable": "ice_concentration",
        "directory": ROOT / "data" / "raw" / "historical_baltic_sic_chunks",
        "filename_prefix": "baltic_sic",
    },
    "thickness": {
        "dataset_id": "cmems_obs-si_bal_phy-sit_my_l4-1km_P1D-m",
        "variable": "ice_thickness",
        "directory": ROOT / "data" / "raw" / "historical_baltic_thickness_chunks",
        "filename_prefix": "baltic_thickness",
    },
}

RECENT_SIC_FILES = [
    ROOT
    / "data"
    / "raw"
    / "recent_baltic_winter_subsets"
    / f"baltic_ice_concentration_winter_{year}_{year + 1}.nc"
    for year in range(2020, 2025)
]
MANIFEST_PATH = ROOT / "data" / "metadata" / "historical_basin_retrieval_manifest.json"


def build_requests(product_key: str) -> list[dict[str, str]]:
    """Build November-May requests, reusing the five local SIC winters."""
    product = PRODUCTS[product_key]
    requests: list[dict[str, str]] = []
    for first_year in range(START_YEAR, LAST_COMPLETE_WINTER + 1, 5):
        last_year = min(first_year + 4, LAST_COMPLETE_WINTER)
        if product_key == "sic" and first_year == 2020:
            continue
        start_date = "1980-11-03" if first_year == START_YEAR else f"{first_year}-11-01"
        requests.append(
            {
                "product": product_key,
                "dataset_id": product["dataset_id"],
                "variable": product["variable"],
                "start": start_date,
                "end": f"{last_year + 1}-05-31",
                "label": f"{first_year}_{last_year}",
                "filename": f"{product['filename_prefix']}_{first_year}_{last_year}.nc",
            }
        )

    requests.append(
        {
            "product": product_key,
            "dataset_id": product["dataset_id"],
            "variable": product["variable"],
            "start": f"{LATEST_PARTIAL_WINTER}-11-01",
            "end": "2026-05-10",
            "label": "2025_partial",
            "filename": f"{product['filename_prefix']}_2025_partial_to_2026-05-10.nc",
        }
    )
    return requests


def request_kwargs(request: dict[str, str], *, dry_run: bool) -> dict:
    product = PRODUCTS[request["product"]]
    return {
        "dataset_id": request["dataset_id"],
        "variables": [request["variable"]],
        "start_datetime": request["start"],
        "end_datetime": request["end"],
        "minimum_longitude": MIN_LON,
        "maximum_longitude": MAX_LON,
        "minimum_latitude": MIN_LAT,
        "maximum_latitude": MAX_LAT,
        "output_directory": str(product["directory"]),
        "output_filename": request["filename"],
        "dry_run": dry_run,
    }


def validate_netcdf(path: Path, variable: str) -> None:
    """Check that an existing or downloaded chunk opens and has expected data."""
    if not path.is_file() or path.stat().st_size < 1_000_000:
        raise ValueError(f"Missing or implausibly small NetCDF file: {path}")
    with xr.open_dataset(path, decode_cf=True, mask_and_scale=True) as dataset:
        if variable not in dataset:
            raise ValueError(f"{path.name} is missing required variable {variable!r}")
        if "time" not in dataset.coords or dataset.sizes.get("time", 0) == 0:
            raise ValueError(f"{path.name} has no time coordinate")
        if dataset[variable].ndim != 3:
            raise ValueError(f"{path.name} {variable!r} is not a time-latitude-longitude field")


def write_manifest(records: list[dict]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "retrieval_date_utc": datetime.now(timezone.utc).isoformat(),
        "product_id": "SEAICE_BAL_PHY_L4_MY_011_019",
        "geographic_bounds": {
            "minimum_longitude": MIN_LON,
            "maximum_longitude": MAX_LON,
            "minimum_latitude": MIN_LAT,
            "maximum_latitude": MAX_LAT,
        },
        "requests": records,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--products",
        nargs="+",
        choices=["sic", "thickness"],
        default=["sic", "thickness"],
        help="Products to estimate or retrieve (default: both).",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download after all planned chunks pass the disk-space preflight.",
    )
    args = parser.parse_args()

    if "sic" in args.products and any(not path.is_file() for path in RECENT_SIC_FILES):
        missing = [str(path) for path in RECENT_SIC_FILES if not path.is_file()]
        raise FileNotFoundError("Expected local recent SIC chunks are missing:\n" + "\n".join(missing))

    requests = [request for key in args.products for request in build_requests(key)]
    records: list[dict] = []
    estimated_bytes = 0
    for request in requests:
        product = PRODUCTS[request["product"]]
        target = product["directory"] / request["filename"]
        if args.download and target.exists():
            validate_netcdf(target, request["variable"])
            size = target.stat().st_size
            estimated_bytes += size
            records.append({**request, "path": str(target.relative_to(ROOT)), "size_bytes": size, "status": "reused"})
            print(f"Reusing validated chunk: {target.name}", flush=True)
            continue

        response = copernicusmarine.subset(**request_kwargs(request, dry_run=True))
        size_bytes = int(float(response.file_size) * 1024**2)
        estimated_bytes += size_bytes
        records.append(
            {
                **request,
                "path": str(target.relative_to(ROOT)),
                "estimated_size_bytes": size_bytes,
                "status": "estimated",
            }
        )
        print(
            f"{request['product']} {request['label']}: "
            f"{size_bytes / 1024**3:.2f} GiB estimated",
            flush=True,
        )

    disk = shutil.disk_usage(ROOT)
    print(
        f"Estimated selected output: {estimated_bytes / 1024**3:.2f} GiB; "
        f"free on destination drive: {disk.free / 1024**3:.2f} GiB; "
        f"reserved headroom: {RESERVE_BYTES / 1024**3:.0f} GiB.",
        flush=True,
    )
    if estimated_bytes + RESERVE_BYTES > disk.free:
        raise OSError("Insufficient free space for these requests plus the required 5 GiB reserve.")

    if not args.download:
        print("Dry-run only. Add --download to start/reuse the listed chunks.")
        return

    completed = [record for record in records if record["status"] == "reused"]
    for request in requests:
        product = PRODUCTS[request["product"]]
        target = product["directory"] / request["filename"]
        if target.exists():
            continue
        product["directory"].mkdir(parents=True, exist_ok=True)
        print(f"Downloading {request['product']} {request['label']} -> {target.name}", flush=True)
        copernicusmarine.subset(**request_kwargs(request, dry_run=False))
        validate_netcdf(target, request["variable"])
        completed.append(
            {
                **request,
                "path": str(target.relative_to(ROOT)),
                "size_bytes": target.stat().st_size,
                "status": "downloaded",
            }
        )
        write_manifest(completed)
        print(
            f"Completed {target.name}: {target.stat().st_size / 1024**3:.2f} GiB",
            flush=True,
        )

    # Record the five pre-existing recent SIC winter subsets in the final manifest.
    if "sic" in args.products:
        completed.extend(
            {
                "product": "sic",
                "dataset_id": PRODUCTS["sic"]["dataset_id"],
                "variable": PRODUCTS["sic"]["variable"],
                "path": str(path.relative_to(ROOT)),
                "size_bytes": path.stat().st_size,
                "status": "preexisting_recent_winter",
            }
            for path in RECENT_SIC_FILES
        )
    write_manifest(completed)
    print(f"Retrieval complete. Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
