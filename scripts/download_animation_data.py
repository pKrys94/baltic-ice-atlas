"""Download the five recent winters used by the animation.

Run without --download first to check the estimated transfer size. Credentials
are read from the local Copernicus Marine Toolbox configuration.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import copernicusmarine
import xarray as xr


ROOT = Path(__file__).resolve().parents[1]
DATASET_ID = "cmems_obs-si_bal_seaice-conc_my_1km"
BOUNDS = {
    "minimum_longitude": 9.0,
    "maximum_longitude": 31.0,
    "minimum_latitude": 53.2,
    "maximum_latitude": 66.2,
}
RECENT_DIR = ROOT / "data" / "raw" / "recent_baltic_winter_subsets"
EXTENT_DIR = ROOT / "data" / "raw"


def requests() -> list[dict]:
    jobs = []
    for year in range(2020, 2025):
        jobs.append({
            "variables": ["ice_concentration"],
            "start_datetime": f"{year}-11-01",
            "end_datetime": f"{year + 1}-05-31",
            "output_directory": str(RECENT_DIR),
            "output_filename": f"baltic_ice_concentration_winter_{year}_{year + 1}.nc",
        })
    jobs.append({
        "variables": ["sea_ice_extent"],
        "start_datetime": "1980-11-03",
        "end_datetime": "2026-05-10",
        "output_directory": str(EXTENT_DIR),
        "output_filename": "baltic_ice_extent_full_record.nc",
    })
    return [{"dataset_id": DATASET_ID, **BOUNDS, **job} for job in jobs]


def check_file(path: Path, variable: str) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise FileNotFoundError(f"Download did not create {path}")
    with xr.open_dataset(path, decode_cf=True, mask_and_scale=True) as ds:
        if variable not in ds or "time" not in ds.coords:
            raise ValueError(f"{path.name} is missing {variable} or its time coordinate")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Download after checking all request sizes.")
    args = parser.parse_args()

    jobs = requests()
    estimates = []
    for job in jobs:
        result = copernicusmarine.subset(**job, dry_run=True)
        size = float(result.file_size) * 1024**2
        estimates.append(size)
        print(f"{job['output_filename']}: about {size / 1024**3:.2f} GiB")
    total = sum(estimates)
    free = shutil.disk_usage(ROOT).free
    print(f"Estimated total: {total / 1024**3:.2f} GiB; free space: {free / 1024**3:.2f} GiB")
    if not args.download:
        print("Estimate only. Add --download to retrieve these files.")
        return
    if total + 3 * 1024**3 > free:
        raise OSError("Not enough free space for the estimated download plus 3 GiB headroom.")

    for job in jobs:
        variable = job["variables"][0]
        target_dir = Path(job["output_directory"])
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / job["output_filename"]
        if target.exists() and target.stat().st_size > 0:
            check_file(target, variable)
            print(f"Using existing file: {target.name}")
            continue
        print(f"Downloading {target.name} ...", flush=True)
        copernicusmarine.subset(**job, dry_run=False)
        check_file(target, variable)
        print(f"Saved {target.name}", flush=True)


if __name__ == "__main__":
    main()
