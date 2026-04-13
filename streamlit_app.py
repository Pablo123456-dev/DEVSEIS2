from __future__ import annotations

import sys
import tempfile
import traceback
from pathlib import Path

import pandas as pd
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


st.set_page_config(page_title="Seismic DHI Mapper", layout="wide")


def _persist_upload(uploaded_file, suffix: str) -> str:
    temp_dir = Path(tempfile.gettempdir()) / "seismic_dhi_mapper"
    temp_dir.mkdir(parents=True, exist_ok=True)
    file_id = getattr(uploaded_file, "file_id", uploaded_file.name)
    target = temp_dir / f"{file_id}{suffix}"
    target.write_bytes(uploaded_file.getbuffer())
    return str(target)


@st.cache_resource
def _load_backend():
    try:
        from dhi_platform.dhi import result_geojson, run_dhi_workflow
        from dhi_platform.las_utils import read_las_files
        from dhi_platform.segy_utils import build_target_time_grid, read_segy_metadata
        from dhi_platform.visualization import basemap_figure, heatmap_figure, polygon_metrics, well_table
    except Exception as exc:  # pragma: no cover - startup diagnostics for deployment
        return {
            "error": exc,
            "traceback": traceback.format_exc(),
        }

    return {
        "result_geojson": result_geojson,
        "run_dhi_workflow": run_dhi_workflow,
        "read_las_files": read_las_files,
        "build_target_time_grid": build_target_time_grid,
        "read_segy_metadata": read_segy_metadata,
        "basemap_figure": basemap_figure,
        "heatmap_figure": heatmap_figure,
        "polygon_metrics": polygon_metrics,
        "well_table": well_table,
    }


st.title("Seismic DHI Mapper")
st.caption(
    "Memory-safe interpretation workflow for mapping direct hydrocarbon indicators from 3D SEG-Y and LAS well logs."
)

backend = _load_backend()
if "error" in backend:
    exc = backend["error"]
    st.error(
        "The seismic backend could not be imported in this Streamlit environment. "
        "This is usually caused by a missing binary dependency such as `shapely`, `scipy`, or `scikit-image`."
    )
    st.code(f"{type(exc).__name__}: {exc}")
    with st.expander("Import traceback", expanded=False):
        st.code(backend["traceback"])
    st.stop()

result_geojson = backend["result_geojson"]
run_dhi_workflow = backend["run_dhi_workflow"]
read_las_files = backend["read_las_files"]
build_target_time_grid = backend["build_target_time_grid"]
read_segy_metadata = backend["read_segy_metadata"]
basemap_figure = backend["basemap_figure"]
heatmap_figure = backend["heatmap_figure"]
polygon_metrics = backend["polygon_metrics"]
well_table = backend["well_table"]

with st.sidebar:
    st.header("Inputs")
    segy_upload = st.file_uploader("3D seismic volume (SEG-Y)", type=["sgy", "segy"])
    las_uploads = st.file_uploader(
        "Petroleum well logs (LAS)",
        type=["las"],
        accept_multiple_files=True,
    )
    horizon_upload = st.file_uploader(
        "Optional horizon CSV (inline/xline/twt_ms or x/y/twt_ms)",
        type=["csv"],
    )
    location_upload = st.file_uploader(
        "Optional well location CSV (well, x, y, lon, lat)",
        type=["csv"],
    )
    source_epsg = st.number_input(
        "Seismic / projected CRS EPSG",
        min_value=0,
        step=1,
        value=0,
        help="Use 0 if SEG-Y coordinates are already longitude/latitude or if you only want projected display.",
    )
    polarity = st.selectbox(
        "DHI polarity",
        options=["positive", "negative"],
        help="Use positive for bright spots and negative for dim spots or trough-driven anomalies.",
    )
    default_twt_ms = st.number_input("Target TWT (ms)", min_value=0.0, value=2200.0, step=10.0)
    window_ms = st.slider("Analysis window (ms)", min_value=4, max_value=120, value=24, step=2)
    threshold_quantile = st.slider(
        "Anomaly threshold quantile",
        min_value=0.70,
        max_value=0.99,
        value=0.90,
        step=0.01,
    )
    min_cluster_size = st.slider("Minimum anomaly cells", min_value=5, max_value=500, value=50, step=5)
    run_button = st.button("Run DHI Delineation", type="primary", use_container_width=True)

st.markdown(
    """
**Recommended workflow**

1. Load the SEG-Y cube and set the coordinate reference system.
2. Load LAS files so the app can score which wells support hydrocarbons.
3. If you have a mapped reservoir top, add a horizon CSV so the seismic window follows structure.
4. Run the DHI extraction and review the polygon both in projected view and on the basemap.
"""
)

if not segy_upload:
    st.info("Upload a SEG-Y cube to start the interpretation workflow.")
    st.stop()

segy_path = _persist_upload(segy_upload, Path(segy_upload.name).suffix or ".segy")
location_df = pd.read_csv(location_upload) if location_upload else None
source_epsg_value = int(source_epsg) if source_epsg else None

try:
    metadata = read_segy_metadata(segy_path, source_epsg=source_epsg_value)
except Exception as exc:
    st.error(f"Could not read SEG-Y metadata: {exc}")
    st.stop()

summary_col1, summary_col2, summary_col3, summary_col4 = st.columns(4)
summary_col1.metric("Inlines", len(metadata.ilines))
summary_col2.metric("Xlines", len(metadata.xlines))
summary_col3.metric("Samples", len(metadata.samples_ms))
summary_col4.metric("Trace interval (ms)", round(metadata.sample_interval_ms, 2))

with st.expander("SEG-Y extent and coordinate summary", expanded=False):
    st.json(
        {
            "path": metadata.path,
            "source_epsg": metadata.source_epsg,
            "has_lonlat_grid": metadata.lon_grid is not None and metadata.lat_grid is not None,
            **metadata.extent,
        }
    )

wells = []
if las_uploads:
    las_paths = [_persist_upload(upload, Path(upload.name).suffix or ".las") for upload in las_uploads]
    try:
        wells = read_las_files(las_paths, source_epsg=source_epsg_value, location_table=location_df)
    except Exception as exc:
        st.error(f"Could not read LAS files: {exc}")
        st.stop()

wells_df = well_table(wells) if wells else pd.DataFrame(columns=["Well", "HC support score"])
if not wells_df.empty:
    st.subheader("Well support summary")
    st.dataframe(wells_df, use_container_width=True, hide_index=True)

if not run_button:
    st.stop()

horizon_df = pd.read_csv(horizon_upload) if horizon_upload else None
target_time_grid = build_target_time_grid(
    metadata=metadata,
    default_time_ms=default_twt_ms,
    horizon_df=horizon_df,
)

with st.spinner("Extracting seismic attributes and delineating the DHI polygon..."):
    try:
        result = run_dhi_workflow(
            metadata=metadata,
            target_time_grid=target_time_grid,
            window_ms=float(window_ms),
            polarity=polarity,
            threshold_quantile=float(threshold_quantile),
            min_cluster_size=int(min_cluster_size),
            wells=wells,
        )
    except Exception as exc:
        st.error(f"DHI workflow failed: {exc}")
        st.stop()

metrics = polygon_metrics(result)
metric_col1, metric_col2, metric_col3 = st.columns(3)
metric_col1.metric("Threshold", metrics["Threshold"])
metric_col2.metric("Polygon area", metrics["Polygon area"] if metrics["Polygon area"] is not None else "N/A")
metric_col3.metric("Mean score", metrics["Mean score"] if metrics["Mean score"] is not None else "N/A")

figure_col1, figure_col2 = st.columns(2)
with figure_col1:
    st.plotly_chart(
        heatmap_figure(result.score_grid, metadata.x_grid, metadata.y_grid, wells_df if not wells_df.empty else None),
        use_container_width=True,
    )

with figure_col2:
    basemap = basemap_figure(result, wells_df)
    if basemap is None:
        st.warning(
            "Basemap view needs longitude/latitude. Provide the seismic CRS EPSG or use SEG-Y coordinates already in WGS84."
        )
    else:
        st.plotly_chart(basemap, use_container_width=True)

st.subheader("Connected anomaly ranking")
st.dataframe(pd.DataFrame(result.component_report), use_container_width=True, hide_index=True)

st.subheader("Workflow notes")
for note in result.workflow_notes:
    st.write(f"- {note}")

geojson_payload = result_geojson(result)
st.download_button(
    label="Download DHI polygon as GeoJSON",
    data=geojson_payload,
    file_name="dhi_polygon.geojson",
    mime="application/geo+json",
)

if result.polygon_xy is None and result.polygon_lonlat is None:
    st.warning("No polygon was extracted. Lower the threshold, widen the window, or add a structural horizon.")
