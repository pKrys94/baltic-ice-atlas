# Data files

The tables in `processed/` contain chart-date extent and thickness values used in the historical figure, winter means, and the corresponding trend estimates. They come from Copernicus Marine's Baltic Sea Ice product. Mapped extent uses the 15% SIC threshold. Only dates with at least 80% basin mapped-area coverage are included.

The original NetCDF files are not included because of their size. The full historical SIC and thickness archive is about 95 GB. `scripts/download_historical_basin_data.py` can retrieve it in resumable chunks. Run it without `--download` first to see the current size estimate.

The animation uses five recent SIC subsets and the compact basin extent series. Use `scripts/download_animation_data.py` to check and retrieve those files.

Sources: [Copernicus Marine product](https://data.marine.copernicus.eu/product/SEAICE_BAL_PHY_L4_MY_011_019/description), [Product User Manual](https://documentation.marine.copernicus.eu/PUM/CMEMS-SEAICE-PUM-011-019.pdf), and [Quality Information Document](https://documentation.marine.copernicus.eu/QUID/CMEMS-SEAICE-QUID-011-004-011-019.pdf).
