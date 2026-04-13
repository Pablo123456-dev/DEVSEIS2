# Seismic DHI Mapper

Python desktop application for delineating a seismic direct hydrocarbon indicator area from a 3D SEG-Y volume and petroleum well logs in LAS format, then exporting the result as a polygon and displaying it with wells on a basemap.

## Why this workflow

For a first interpretation platform, the most practical workflow is:

1. Read SEG-Y geometry and coordinates without loading the full 3D cube into memory.
2. Use a reservoir target time window, ideally guided by a horizon surface.
3. Extract amplitude-sensitive DHI attributes around that window.
4. Use LAS logs to identify which wells support hydrocarbons.
5. Threshold and clean the anomaly mask.
6. Select the best connected anomaly, convert it to a polygon, and QC it on a basemap.

This is a good starting point because it is fast enough for an interactive desktop app and it follows how DHI mapping is usually done in interpretation: within a reservoir-focused time window, not as a blind whole-volume classifier.

## Implemented interpretation logic

The app computes a composite DHI score for each inline/xline cell using:

- RMS amplitude inside the analysis window
- Peak amplitude, honoring bright-spot or dim-spot polarity
- Reflection envelope from the analytic trace

The score is thresholded by quantile, cleaned morphologically, and split into connected anomalies. The final anomaly is ranked using:

- seismic anomaly strength
- anomaly size
- proximity to wells whose LAS logs suggest hydrocarbon support

The chosen anomaly is vectorized to a polygon and exported as GeoJSON.

## Inputs

- One 3D SEG-Y file with structured inline/xline geometry and trace coordinates
- One or more LAS files
- Optional horizon CSV with either:
  - `inline`, `xline`, `twt_ms`
  - `x`, `y`, `twt_ms`
- Optional well location CSV with columns:
  - `well`, `x`, `y`
  - or `well`, `lon`, `lat`

## Outputs

- DHI score map in projected coordinates
- DHI polygon on an OpenStreetMap basemap
- Well locations and hydrocarbon support flags
- Downloadable GeoJSON polygon

## Desktop interface

The main interface is now a classic desktop window built with `PySide6`:

- left panel for SEG-Y, LAS, horizon, and well-location file selection
- parameter controls for CRS, polarity, TWT window, threshold, and cluster size
- projected DHI map and basemap in embedded tabs
- well summary, anomaly ranking, workflow notes, and seismic metadata in dock-style tabs
- GeoJSON export button for the final polygon

The seismic interpretation core remains in the `dhi_platform` package so the desktop app and any future web or CLI front ends can share the same workflow.

## Project layout

- [desktop_app.py](</C:/Users/USER/Documents/project codex/desktop_app.py>)
- [streamlit_app.py](</C:/Users/USER/Documents/project codex/streamlit_app.py>)
- [dhi_platform/models.py](</C:/Users/USER/Documents/project codex/dhi_platform/models.py>)
- [dhi_platform/segy_utils.py](</C:/Users/USER/Documents/project codex/dhi_platform/segy_utils.py>)
- [dhi_platform/las_utils.py](</C:/Users/USER/Documents/project codex/dhi_platform/las_utils.py>)
- [dhi_platform/dhi.py](</C:/Users/USER/Documents/project codex/dhi_platform/dhi.py>)
- [dhi_platform/visualization.py](</C:/Users/USER/Documents/project codex/dhi_platform/visualization.py>)

## Run Desktop App

Install Python and the dependencies first, then run:

```bash
pip install -r desktop_requirements.txt
python desktop_app.py
```

## Run In Anaconda

```bash
cd "C:\Users\USER\Documents\project codex"
conda create -n seismic-dhi python=3.11 -y
conda activate seismic-dhi
pip install -r desktop_requirements.txt
python desktop_app.py
```

If `PySide6` or `segyio` is easier to install from conda on your machine, this also works well:

```bash
conda install -c conda-forge pyside6 numpy pandas scipy shapely pyproj scikit-image
pip install plotly lasio segyio streamlit
python desktop_app.py
```

## Optional Browser Version

The previous browser-based version is still available:

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Streamlit Cloud

For Streamlit Cloud or any browser-only deployment, use `requirements.txt` only. It intentionally excludes `PySide6`, because that dependency is needed for the desktop window but not for the web app.

If the app starts and shows a backend import error panel, the expanded traceback will now reveal the exact missing or incompatible dependency instead of failing during module import.

## Build A Windows Executable

For Windows packaging, the project now includes:

- [seismic_dhi_mapper.spec](</C:/Users/USER/Documents/project codex/seismic_dhi_mapper.spec>)
- [build_windows_exe.bat](</C:/Users/USER/Documents/project codex/build_windows_exe.bat>)
- [build_requirements.txt](</C:/Users/USER/Documents/project codex/build_requirements.txt>)

Recommended Anaconda build flow:

```bash
cd "C:\Users\USER\Documents\project codex"
conda activate seismic-dhi
pip install -r requirements.txt
pip install -r desktop_requirements.txt
pip install -r build_requirements.txt
build_windows_exe.bat
```

The executable will be created in:

```text
dist\SeismicDHIMapper\SeismicDHIMapper.exe
```

This is a `onedir` build on purpose. It is more reliable than `onefile` for `PySide6` with `QtWebEngine`, which the embedded basemap and chart panels depend on.

## Notes and limitations

- This MVP assumes post-stack seismic amplitude is the main DHI signal.
- The best results come from providing a mapped structural horizon rather than a single constant TWT.
- LAS files often do not contain reliable coordinates, so the well location CSV is important in many projects.
- Polygon area is only geodetically meaningful when the coordinates are in a projected CRS or the GeoJSON is later reprojected appropriately.
- The basemap tab depends on longitude and latitude being available, either directly in the SEG-Y coordinates or by supplying the correct EPSG code.
- The current environment did not have a working Python interpreter available, so the code was scaffolded but not executed here.
