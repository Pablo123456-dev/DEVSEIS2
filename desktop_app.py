from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWebEngineWidgets import QWebEngineView

from dhi_platform.dhi import result_geojson, run_dhi_workflow
from dhi_platform.las_utils import read_las_files
from dhi_platform.segy_utils import build_target_time_grid, read_segy_metadata
from dhi_platform.visualization import basemap_figure, heatmap_figure, polygon_metrics, well_table


class DHIWorker(QObject):
    finished = Signal(object)
    error = Signal(str)

    def __init__(
        self,
        segy_path: str,
        las_paths: list[str],
        horizon_path: str | None,
        location_path: str | None,
        source_epsg: int | None,
        polarity: str,
        default_twt_ms: float,
        window_ms: float,
        threshold_quantile: float,
        min_cluster_size: int,
    ) -> None:
        super().__init__()
        self.segy_path = segy_path
        self.las_paths = las_paths
        self.horizon_path = horizon_path
        self.location_path = location_path
        self.source_epsg = source_epsg
        self.polarity = polarity
        self.default_twt_ms = default_twt_ms
        self.window_ms = window_ms
        self.threshold_quantile = threshold_quantile
        self.min_cluster_size = min_cluster_size

    @Slot()
    def run(self) -> None:
        try:
            location_df = pd.read_csv(self.location_path) if self.location_path else None
            horizon_df = pd.read_csv(self.horizon_path) if self.horizon_path else None

            metadata = read_segy_metadata(self.segy_path, source_epsg=self.source_epsg)
            wells = []
            if self.las_paths:
                wells = read_las_files(
                    self.las_paths,
                    source_epsg=self.source_epsg,
                    location_table=location_df,
                )
            target_time_grid = build_target_time_grid(
                metadata=metadata,
                default_time_ms=self.default_twt_ms,
                horizon_df=horizon_df,
            )
            result = run_dhi_workflow(
                metadata=metadata,
                target_time_grid=target_time_grid,
                window_ms=self.window_ms,
                polarity=self.polarity,
                threshold_quantile=self.threshold_quantile,
                min_cluster_size=self.min_cluster_size,
                wells=wells,
            )
            self.finished.emit(
                {
                    "metadata": metadata,
                    "wells": wells,
                    "wells_df": well_table(wells),
                    "result": result,
                    "geojson": result_geojson(result),
                }
            )
        except Exception as exc:
            self.error.emit(str(exc))


class DHIWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Seismic DHI Mapper Desktop")
        self.resize(1600, 980)

        self.segy_path: str | None = None
        self.las_paths: list[str] = []
        self.horizon_path: str | None = None
        self.location_path: str | None = None
        self.current_geojson: str | None = None
        self._worker_thread: QThread | None = None
        self._worker: DHIWorker | None = None

        self._build_ui()
        self._apply_start_state()

    def _build_ui(self) -> None:
        container = QWidget()
        root_layout = QHBoxLayout(container)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(splitter)
        self.setCentralWidget(container)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Choose SEG-Y and LAS files to start.")

        controls_panel = QWidget()
        controls_layout = QVBoxLayout(controls_panel)
        controls_layout.setContentsMargins(8, 8, 8, 8)
        controls_layout.setSpacing(10)

        controls_layout.addWidget(self._build_file_group())
        controls_layout.addWidget(self._build_parameter_group())
        controls_layout.addWidget(self._build_metric_group())
        controls_layout.addStretch(1)

        results_panel = QWidget()
        results_layout = QVBoxLayout(results_panel)
        results_layout.setContentsMargins(8, 8, 8, 8)
        results_layout.setSpacing(10)

        self.figure_tabs = QTabWidget()
        self.projected_view = QWebEngineView()
        self.map_view = QWebEngineView()
        self.figure_tabs.addTab(self.projected_view, "Projected DHI")
        self.figure_tabs.addTab(self.map_view, "Basemap")
        results_layout.addWidget(self.figure_tabs, stretch=3)

        self.info_tabs = QTabWidget()
        self.well_table_widget = QTableWidget()
        self.component_table_widget = QTableWidget()
        self.notes_text = QTextEdit()
        self.notes_text.setReadOnly(True)
        self.metadata_text = QTextEdit()
        self.metadata_text.setReadOnly(True)
        self.info_tabs.addTab(self.well_table_widget, "Well Summary")
        self.info_tabs.addTab(self.component_table_widget, "Anomaly Ranking")
        self.info_tabs.addTab(self.notes_text, "Workflow Notes")
        self.info_tabs.addTab(self.metadata_text, "Seismic Metadata")
        results_layout.addWidget(self.info_tabs, stretch=2)

        splitter.addWidget(controls_panel)
        splitter.addWidget(results_panel)
        splitter.setSizes([360, 1240])

        self._set_placeholder_views()

    def _build_file_group(self) -> QGroupBox:
        group = QGroupBox("Input Files")
        layout = QVBoxLayout(group)
        layout.setSpacing(8)

        self.segy_line = QLineEdit()
        self.segy_line.setReadOnly(True)
        segy_button = QPushButton("Browse SEG-Y")
        segy_button.clicked.connect(self._choose_segy)
        layout.addWidget(QLabel("3D seismic volume"))
        layout.addWidget(self.segy_line)
        layout.addWidget(segy_button)

        self.las_list = QListWidget()
        self.las_list.setMinimumHeight(110)
        las_buttons = QHBoxLayout()
        add_las_button = QPushButton("Add LAS Files")
        add_las_button.clicked.connect(self._choose_las)
        clear_las_button = QPushButton("Clear LAS")
        clear_las_button.clicked.connect(self._clear_las)
        las_buttons.addWidget(add_las_button)
        las_buttons.addWidget(clear_las_button)
        layout.addWidget(QLabel("Petroleum well logs"))
        layout.addWidget(self.las_list)
        layout.addLayout(las_buttons)

        self.horizon_line = QLineEdit()
        self.horizon_line.setReadOnly(True)
        horizon_button = QPushButton("Browse Horizon CSV")
        horizon_button.clicked.connect(self._choose_horizon)
        layout.addWidget(QLabel("Optional horizon surface"))
        layout.addWidget(self.horizon_line)
        layout.addWidget(horizon_button)

        self.location_line = QLineEdit()
        self.location_line.setReadOnly(True)
        location_button = QPushButton("Browse Well Location CSV")
        location_button.clicked.connect(self._choose_location)
        layout.addWidget(QLabel("Optional well locations"))
        layout.addWidget(self.location_line)
        layout.addWidget(location_button)

        self.run_button = QPushButton("Run DHI Delineation")
        self.run_button.clicked.connect(self._start_processing)
        self.export_button = QPushButton("Export Polygon GeoJSON")
        self.export_button.clicked.connect(self._export_geojson)
        layout.addWidget(self.run_button)
        layout.addWidget(self.export_button)

        return group

    def _build_parameter_group(self) -> QGroupBox:
        group = QGroupBox("Interpretation Parameters")
        layout = QFormLayout(group)

        self.epsg_spin = QSpinBox()
        self.epsg_spin.setRange(0, 999999)
        self.epsg_spin.setValue(0)

        self.polarity_box = QComboBox()
        self.polarity_box.addItems(["positive", "negative"])

        self.twt_spin = QDoubleSpinBox()
        self.twt_spin.setRange(0.0, 20000.0)
        self.twt_spin.setDecimals(1)
        self.twt_spin.setSingleStep(10.0)
        self.twt_spin.setValue(2200.0)

        self.window_spin = QDoubleSpinBox()
        self.window_spin.setRange(4.0, 120.0)
        self.window_spin.setDecimals(1)
        self.window_spin.setSingleStep(2.0)
        self.window_spin.setValue(24.0)

        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.70, 0.99)
        self.threshold_spin.setDecimals(2)
        self.threshold_spin.setSingleStep(0.01)
        self.threshold_spin.setValue(0.90)

        self.cluster_spin = QSpinBox()
        self.cluster_spin.setRange(5, 500)
        self.cluster_spin.setSingleStep(5)
        self.cluster_spin.setValue(50)

        layout.addRow("Seismic/projected EPSG", self.epsg_spin)
        layout.addRow("DHI polarity", self.polarity_box)
        layout.addRow("Target TWT (ms)", self.twt_spin)
        layout.addRow("Window (ms)", self.window_spin)
        layout.addRow("Threshold quantile", self.threshold_spin)
        layout.addRow("Minimum cluster cells", self.cluster_spin)
        return group

    def _build_metric_group(self) -> QGroupBox:
        group = QGroupBox("Summary")
        layout = QGridLayout(group)

        self.inline_value = QLabel("-")
        self.xline_value = QLabel("-")
        self.sample_value = QLabel("-")
        self.interval_value = QLabel("-")
        self.threshold_value = QLabel("-")
        self.area_value = QLabel("-")
        self.mean_score_value = QLabel("-")

        layout.addWidget(QLabel("Inlines"), 0, 0)
        layout.addWidget(self.inline_value, 0, 1)
        layout.addWidget(QLabel("Xlines"), 1, 0)
        layout.addWidget(self.xline_value, 1, 1)
        layout.addWidget(QLabel("Samples"), 2, 0)
        layout.addWidget(self.sample_value, 2, 1)
        layout.addWidget(QLabel("Trace interval (ms)"), 3, 0)
        layout.addWidget(self.interval_value, 3, 1)
        layout.addWidget(QLabel("Threshold"), 4, 0)
        layout.addWidget(self.threshold_value, 4, 1)
        layout.addWidget(QLabel("Polygon area"), 5, 0)
        layout.addWidget(self.area_value, 5, 1)
        layout.addWidget(QLabel("Mean score"), 6, 0)
        layout.addWidget(self.mean_score_value, 6, 1)
        return group

    def _apply_start_state(self) -> None:
        self.export_button.setEnabled(False)

    def _set_placeholder_views(self) -> None:
        projected_html = """
        <html><body style="font-family:Segoe UI;padding:20px;color:#334;">
        <h3>Projected DHI view</h3>
        <p>Load a SEG-Y cube and run the workflow to see the DHI score map and wells.</p>
        </body></html>
        """
        map_html = """
        <html><body style="font-family:Segoe UI;padding:20px;color:#334;">
        <h3>Basemap view</h3>
        <p>The desktop app will draw the final DHI polygon on OpenStreetMap when longitude and latitude are available.</p>
        </body></html>
        """
        self.projected_view.setHtml(projected_html)
        self.map_view.setHtml(map_html)

    def _choose_segy(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose SEG-Y", "", "SEG-Y Files (*.sgy *.segy)")
        if path:
            self.segy_path = path
            self.segy_line.setText(path)

    def _choose_las(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose LAS files", "", "LAS Files (*.las)")
        if paths:
            for path in paths:
                if path not in self.las_paths:
                    self.las_paths.append(path)
                    self.las_list.addItem(path)

    def _clear_las(self) -> None:
        self.las_paths = []
        self.las_list.clear()

    def _choose_horizon(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose horizon CSV", "", "CSV Files (*.csv)")
        if path:
            self.horizon_path = path
            self.horizon_line.setText(path)

    def _choose_location(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose well location CSV", "", "CSV Files (*.csv)")
        if path:
            self.location_path = path
            self.location_line.setText(path)

    def _start_processing(self) -> None:
        if not self.segy_path:
            QMessageBox.warning(self, "Missing SEG-Y", "Choose a SEG-Y file before running the workflow.")
            return

        polarity = self.polarity_box.currentText().strip().lower() or "positive"

        self.current_geojson = None
        self.run_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.statusBar().showMessage("Running seismic DHI workflow...")

        self._worker_thread = QThread(self)
        self._worker = DHIWorker(
            segy_path=self.segy_path,
            las_paths=self.las_paths,
            horizon_path=self.horizon_path,
            location_path=self.location_path,
            source_epsg=self.epsg_spin.value() or None,
            polarity=polarity,
            default_twt_ms=self.twt_spin.value(),
            window_ms=self.window_spin.value(),
            threshold_quantile=self.threshold_spin.value(),
            min_cluster_size=self.cluster_spin.value(),
        )
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._handle_result)
        self._worker.error.connect(self._handle_error)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.error.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._cleanup_worker)
        self._worker_thread.start()

    @Slot()
    def _cleanup_worker(self) -> None:
        self.run_button.setEnabled(True)
        if self._worker_thread is not None:
            self._worker_thread.deleteLater()
        if self._worker is not None:
            self._worker.deleteLater()
        self._worker_thread = None
        self._worker = None

    @Slot(str)
    def _handle_error(self, message: str) -> None:
        self.statusBar().showMessage("Workflow failed.")
        QMessageBox.critical(self, "DHI workflow failed", message)

    @Slot(object)
    def _handle_result(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        metadata = data["metadata"]
        wells_df = data["wells_df"]
        result = data["result"]
        self.current_geojson = data["geojson"]

        self.inline_value.setText(str(len(metadata.ilines)))
        self.xline_value.setText(str(len(metadata.xlines)))
        self.sample_value.setText(str(len(metadata.samples_ms)))
        self.interval_value.setText(f"{metadata.sample_interval_ms:.2f}")

        metrics = polygon_metrics(result)
        self.threshold_value.setText(str(metrics["Threshold"]))
        self.area_value.setText("N/A" if metrics["Polygon area"] is None else str(metrics["Polygon area"]))
        self.mean_score_value.setText("N/A" if metrics["Mean score"] is None else str(metrics["Mean score"]))

        projected = heatmap_figure(
            result.score_grid,
            metadata.x_grid,
            metadata.y_grid,
            wells_df if not wells_df.empty else None,
        )
        self._set_figure_html(self.projected_view, projected)

        basemap = basemap_figure(result, wells_df)
        if basemap is None:
            self.map_view.setHtml(
                """
                <html><body style="font-family:Segoe UI;padding:20px;color:#334;">
                <h3>Basemap unavailable</h3>
                <p>Provide the seismic CRS EPSG or SEG-Y coordinates already in WGS84 to display the polygon on the map.</p>
                </body></html>
                """
            )
        else:
            self._set_figure_html(self.map_view, basemap)

        self._fill_table(self.well_table_widget, wells_df)
        self._fill_table(self.component_table_widget, pd.DataFrame(result.component_report))
        self.notes_text.setPlainText("\n".join(result.workflow_notes))
        self.metadata_text.setPlainText(
            json.dumps(
                {
                    "path": metadata.path,
                    "source_epsg": metadata.source_epsg,
                    "has_lonlat_grid": metadata.lon_grid is not None and metadata.lat_grid is not None,
                    **metadata.extent,
                },
                indent=2,
            )
        )

        self.export_button.setEnabled(True)
        self.statusBar().showMessage("DHI workflow completed.")

    def _set_figure_html(self, view: QWebEngineView, figure) -> None:
        html = figure.to_html(include_plotlyjs="inline", full_html=False)
        view.setHtml(html)

    def _fill_table(self, widget: QTableWidget, df: pd.DataFrame) -> None:
        widget.clear()
        widget.setRowCount(0)
        widget.setColumnCount(0)
        if df.empty:
            widget.setRowCount(1)
            widget.setColumnCount(1)
            widget.setHorizontalHeaderLabels(["Info"])
            widget.setItem(0, 0, QTableWidgetItem("No data available"))
            widget.resizeColumnsToContents()
            return

        widget.setRowCount(len(df.index))
        widget.setColumnCount(len(df.columns))
        widget.setHorizontalHeaderLabels([str(column) for column in df.columns])
        for row_index, (_, row) in enumerate(df.iterrows()):
            for col_index, value in enumerate(row):
                widget.setItem(row_index, col_index, QTableWidgetItem("" if pd.isna(value) else str(value)))
        widget.resizeColumnsToContents()

    def _export_geojson(self) -> None:
        if not self.current_geojson:
            QMessageBox.information(self, "Nothing to export", "Run the workflow first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export DHI polygon",
            str(Path.home() / "dhi_polygon.geojson"),
            "GeoJSON Files (*.geojson)",
        )
        if not path:
            return
        Path(path).write_text(self.current_geojson, encoding="utf-8")
        self.statusBar().showMessage(f"Saved polygon to {path}")


def main() -> int:
    app = QApplication(sys.argv)
    window = DHIWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
