"""PySide6 desktop application for interactive and batch photo protection."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QObject, QSettings, Qt, QThread, Signal, Slot, QTimer
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QSpinBox, QSplitter, QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
)

from . import config, device, perturb, pipeline

_IMAGE_FILTER = "Images (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff)"


class FileListWidget(QListWidget):
    files_dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setAlternatingRowColors(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        self.files_dropped.emit(paths)
        event.acceptProposedAction()

    def paths(self) -> list[Path]:
        return [Path(self.item(i).data(Qt.UserRole)) for i in range(self.count())]

    def add_paths(self, paths: Iterable[str | Path]) -> None:
        current = {str(path.resolve()) for path in self.paths()}
        for raw in paths:
            path = Path(raw)
            if not path.is_file() or str(path.resolve()) in current:
                continue
            from PySide6.QtWidgets import QListWidgetItem
            list_item = QListWidgetItem(path.name)
            list_item.setToolTip(str(path))
            list_item.setData(Qt.UserRole, str(path))
            self.addItem(list_item)
            current.add(str(path.resolve()))


@dataclass
class BatchItem:
    source: Path
    output: Path


class ProtectWorker(QObject):
    progress = Signal(int, int, str)
    item_done = Signal(str, str, str)
    finished = Signal(bool)

    def __init__(self, items: list[BatchItem], options: pipeline.ProtectOptions) -> None:
        super().__init__()
        self.items = items
        self.options = options
        self.cancelled = False

    @Slot()
    def run(self) -> None:
        if pipeline.LAYER_PERTURB in self.options.layers:
            self.options.perturber_kwargs["cancel_check"] = lambda: self.cancelled
            self.options.perturber_instance = perturb.get(
                self.options.perturber, **self.options.perturber_kwargs
            )
        for position, item in enumerate(self.items, start=1):
            if self.cancelled:
                break
            self.progress.emit(position - 1, len(self.items), item.source.name)
            try:
                pipeline.protect(item.source, item.output, self.options)
            except Exception as exc:
                self.item_done.emit(str(item.source), "失败", str(exc))
            else:
                self.item_done.emit(str(item.source), "成功", str(item.output))
            self.progress.emit(position, len(self.items), item.source.name)
        self.finished.emit(self.cancelled)

    @Slot()
    def cancel(self) -> None:
        self.cancelled = True
        # The shared perturber polls ``self.cancelled`` between PGD steps.


class VerifyWorker(QObject):
    progress = Signal(int, int, str)
    item_done = Signal(str, str, str)
    finished = Signal(bool)

    def __init__(self, paths: list[Path], expected: str, legacy_bytes: int | None) -> None:
        super().__init__()
        self.paths, self.expected, self.legacy_bytes = paths, expected, legacy_bytes
        self.cancelled = False

    @Slot()
    def run(self) -> None:
        for position, path in enumerate(self.paths, start=1):
            if self.cancelled:
                break
            self.progress.emit(position - 1, len(self.paths), path.name)
            try:
                if self.expected:
                    result = pipeline.verify_expected(path, self.expected)
                    value = result["payload"]
                else:
                    value = pipeline.verify(path, int(self.legacy_bytes or 0))
                    if not value or "�" in value:
                        raise ValueError("未恢复出可信 payload")
            except Exception as exc:
                self.item_done.emit(str(path), "未通过", str(exc))
            else:
                self.item_done.emit(str(path), "通过", value)
            self.progress.emit(position, len(self.paths), path.name)
        self.finished.emit(self.cancelled)

    @Slot()
    def cancel(self) -> None:
        self.cancelled = True


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Photo Guard 照片防盗保护")
        self.resize(1180, 780)
        self.settings = QSettings("PhotoGuard", "PhotoGuardDesktop")
        self.thread: QThread | None = None
        self.worker: QObject | None = None
        self._threads: list[QThread] = []
        self.protect_results: list[tuple[str, str, str]] = []
        self.verify_results: list[tuple[str, str, str]] = []
        tabs = QTabWidget()
        tabs.addTab(self._build_protect_tab(), "照片保护")
        tabs.addTab(self._build_verify_tab(), "水印验证")
        tabs.addTab(self._build_devices_tab(), "设备信息")
        self.setCentralWidget(tabs)
        self.statusBar().showMessage("就绪")
        self._load_settings()
        self.refresh_devices()

    def _file_panel(self, target: FileListWidget) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(QLabel("拖入图片，或使用按钮多选"))
        layout.addWidget(target, 1)
        buttons = QHBoxLayout()
        add = QPushButton("添加图片")
        remove = QPushButton("移除所选")
        clear = QPushButton("清空")
        add.clicked.connect(lambda: self._choose_images(target))
        remove.clicked.connect(lambda: [target.takeItem(target.row(x)) for x in target.selectedItems()])
        clear.clicked.connect(target.clear)
        buttons.addWidget(add); buttons.addWidget(remove); buttons.addWidget(clear)
        layout.addLayout(buttons)
        return panel

    def _build_protect_tab(self) -> QWidget:
        root = QWidget(); outer = QVBoxLayout(root)
        splitter = QSplitter()
        self.protect_files = FileListWidget()
        self.protect_files.files_dropped.connect(self.protect_files.add_paths)
        self.protect_files.currentItemChanged.connect(self._update_preview)
        splitter.addWidget(self._file_panel(self.protect_files))

        right = QWidget(); form_root = QVBoxLayout(right)
        self.preview = QLabel("图片预览")
        self.preview.setAlignment(Qt.AlignCenter); self.preview.setMinimumHeight(220)
        self.preview.setStyleSheet("QLabel { border: 1px solid #888; background: #202020; color: #ddd; }")
        form_root.addWidget(self.preview)

        layers = QGroupBox("保护操作"); layer_layout = QHBoxLayout(layers)
        self.layer_invisible = QCheckBox("隐形水印"); self.layer_invisible.setChecked(True)
        self.layer_sd = QCheckBox("PhotoGuard AI 扰动")
        self.layer_visible = QCheckBox("明水印"); self.layer_visible.setChecked(True)
        layer_layout.addWidget(self.layer_invisible); layer_layout.addWidget(self.layer_sd); layer_layout.addWidget(self.layer_visible)
        form_root.addWidget(layers)

        settings = QGroupBox("水印与输出设置"); form = QFormLayout(settings)
        self.payload = QLineEdit(config.DEFAULT_PAYLOAD)
        self.visible_text = QLineEdit(config.DEFAULT_VISIBLE_TEXT)
        self.visible_mode = QComboBox(); self.visible_mode.addItems(["subject", "tile", "center"])
        self.alpha = QDoubleSpinBox(); self.alpha.setRange(0, 1); self.alpha.setSingleStep(.01); self.alpha.setValue(config.DEFAULT_VISIBLE_ALPHA)
        self.long_edge = QSpinBox(); self.long_edge.setRange(0, 10000); self.long_edge.setValue(config.DEFAULT_LONG_EDGE); self.long_edge.setSpecialValueText("保持原尺寸")
        self.quality = QSpinBox(); self.quality.setRange(1, 100); self.quality.setValue(config.DEFAULT_JPEG_QUALITY)
        output_row = QWidget(); output_layout = QHBoxLayout(output_row); output_layout.setContentsMargins(0,0,0,0)
        self.output_dir = QLineEdit(str(Path.home() / "Pictures" / "PhotoGuard")); browse = QPushButton("选择")
        browse.clicked.connect(self._choose_output_dir); output_layout.addWidget(self.output_dir); output_layout.addWidget(browse)
        self.suffix = QLineEdit("_protected")
        form.addRow("隐水印内容", self.payload); form.addRow("明水印文字", self.visible_text)
        form.addRow("明水印模式", self.visible_mode); form.addRow("透明度", self.alpha)
        form.addRow("输出长边", self.long_edge); form.addRow("JPEG 质量", self.quality)
        form.addRow("输出目录", output_row); form.addRow("文件名后缀", self.suffix)
        form_root.addWidget(settings)

        ai = QGroupBox("AI 扰动设备与参数"); ai_form = QFormLayout(ai)
        self.device_combo = QComboBox()
        self.epsilon = QDoubleSpinBox(); self.epsilon.setDecimals(5); self.epsilon.setRange(0.00001, .2); self.epsilon.setValue(config.PHOTOGUARD_EPSILON)
        self.step_size = QDoubleSpinBox(); self.step_size.setDecimals(5); self.step_size.setRange(0.00001, .2); self.step_size.setValue(config.PHOTOGUARD_STEP_SIZE)
        self.steps = QSpinBox(); self.steps.setRange(1, 100); self.steps.setValue(config.PHOTOGUARD_STEPS)
        ai_form.addRow("计算设备", self.device_combo); ai_form.addRow("扰动强度 ε", self.epsilon)
        ai_form.addRow("单步大小", self.step_size); ai_form.addRow("迭代次数", self.steps)
        form_root.addWidget(ai)
        self.layer_sd.toggled.connect(ai.setEnabled); ai.setEnabled(False)
        splitter.addWidget(right); splitter.setSizes([360, 780]); outer.addWidget(splitter, 1)

        self.protect_progress = QProgressBar(); self.protect_progress.setRange(0, 1)
        self.protect_log = QTextEdit(); self.protect_log.setReadOnly(True); self.protect_log.setMaximumHeight(120)
        controls = QHBoxLayout(); self.protect_start = QPushButton("开始保护"); self.protect_cancel = QPushButton("取消"); self.protect_cancel.setEnabled(False)
        self.protect_start.clicked.connect(self.start_protect); self.protect_cancel.clicked.connect(self.cancel_task)
        controls.addWidget(self.protect_start); controls.addWidget(self.protect_cancel)
        outer.addWidget(self.protect_progress); outer.addWidget(self.protect_log); outer.addLayout(controls)
        return root

    def _build_verify_tab(self) -> QWidget:
        root = QWidget(); layout = QVBoxLayout(root)
        self.verify_files = FileListWidget(); self.verify_files.files_dropped.connect(self.verify_files.add_paths)
        layout.addWidget(self._file_panel(self.verify_files), 1)
        mode = QGroupBox("验证方式"); form = QFormLayout(mode)
        self.expected_payload = QLineEdit(); self.expected_payload.setPlaceholderText("新版本推荐：输入期望 payload")
        self.legacy_bytes = QSpinBox(); self.legacy_bytes.setRange(0, 10000); self.legacy_bytes.setSpecialValueText("不使用旧版模式")
        form.addRow("期望 payload", self.expected_payload); form.addRow("旧版 payload 字节数", self.legacy_bytes)
        layout.addWidget(mode)
        self.verify_table = QTableWidget(0, 3); self.verify_table.setHorizontalHeaderLabels(["文件", "结果", "详情"]); self.verify_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.verify_table, 1)
        self.verify_progress = QProgressBar(); self.verify_progress.setRange(0, 1); layout.addWidget(self.verify_progress)
        buttons = QHBoxLayout(); start = QPushButton("开始验证"); cancel = QPushButton("取消"); export = QPushButton("导出 CSV")
        start.clicked.connect(self.start_verify); cancel.clicked.connect(self.cancel_task); export.clicked.connect(self.export_csv)
        buttons.addWidget(start); buttons.addWidget(cancel); buttons.addWidget(export); layout.addLayout(buttons)
        return root

    def _build_devices_tab(self) -> QWidget:
        root = QWidget(); layout = QVBoxLayout(root)
        self.device_table = QTableWidget(0, 5); self.device_table.setHorizontalHeaderLabels(["后端", "设备", "索引", "显存", "支持状态"]); self.device_table.horizontalHeader().setStretchLastSection(True)
        refresh = QPushButton("重新检测"); refresh.clicked.connect(self.refresh_devices)
        layout.addWidget(QLabel("PhotoGuard 正式支持 CPU、NVIDIA CUDA 与 Apple Metal/MPS。其他显卡显示后回退 CPU。"))
        layout.addWidget(self.device_table, 1); layout.addWidget(refresh)
        return root

    def _choose_images(self, target: FileListWidget) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "选择图片", str(Path.home()), _IMAGE_FILTER)
        target.add_paths(paths)

    def _choose_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择输出目录", self.output_dir.text())
        if path: self.output_dir.setText(path)

    def _update_preview(self, current, _previous) -> None:
        if not current: return
        pixmap = QPixmap(current.data(Qt.UserRole))
        if pixmap.isNull(): self.preview.setText("无法预览"); return
        self.preview.setPixmap(pixmap.scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def refresh_devices(self) -> None:
        self.device_combo.clear(); self.device_combo.addItem("自动选择（CUDA → MPS → CPU）", ("auto", None))
        devices = device.discover_devices()
        self.device_table.setRowCount(len(devices))
        for row, item in enumerate(devices):
            memory = f"{item.memory_bytes / 2**30:.1f} GiB" if item.memory_bytes else "—"
            values = [item.backend, item.name, str(item.index) if item.index is not None else "—", memory, "支持" if item.supported else "仅识别，回退 CPU"]
            for col, value in enumerate(values): self.device_table.setItem(row, col, QTableWidgetItem(value))
            if item.supported:
                label = f"{item.backend.upper()} — {item.name}"
                self.device_combo.addItem(label, (item.backend, item.index))

    def _build_options(self) -> pipeline.ProtectOptions:
        layers = set()
        if self.layer_invisible.isChecked(): layers.add(pipeline.LAYER_INVISIBLE)
        if self.layer_sd.isChecked(): layers.add(pipeline.LAYER_PERTURB)
        if self.layer_visible.isChecked(): layers.add(pipeline.LAYER_VISIBLE)
        backend, index = self.device_combo.currentData() or ("auto", None)
        kwargs = {}
        perturber = "noop"
        if self.layer_sd.isChecked():
            perturber = "sd"
            kwargs = {
                "epsilon": self.epsilon.value(), "step_size": self.step_size.value(),
                "steps": self.steps.value(), "device": backend, "device_index": index,
            }
        return pipeline.ProtectOptions(
            payload=self.payload.text(), perturber=perturber, perturber_kwargs=kwargs,
            visible_mode=self.visible_mode.currentText(), visible_text=self.visible_text.text(),
            visible_alpha=self.alpha.value(), long_edge=self.long_edge.value(),
            quality=self.quality.value(), layers=frozenset(layers), payload_envelope=True,
        )

    @Slot()
    def start_protect(self) -> None:
        paths = self.protect_files.paths()
        if not paths: return self._error("请先添加图片")
        try:
            options = self._build_options(); pipeline.validate_options(options)
        except ValueError as exc: return self._error(str(exc))
        output_dir = Path(self.output_dir.text()).expanduser()
        suffix = self.suffix.text() or "_protected"
        items = [BatchItem(path, self._unique_output(output_dir, path.stem + suffix, ".jpg")) for path in paths]
        self.protect_results.clear(); self.protect_log.clear(); self._save_settings()
        worker = ProtectWorker(items, options)
        worker.item_done.connect(self._protect_item_done)
        worker.progress.connect(lambda done, total, name: self._set_progress(self.protect_progress, done, total, name))
        self._start_worker(worker, self._protect_finished)
        self.protect_start.setEnabled(False); self.protect_cancel.setEnabled(True)

    @Slot()
    def start_verify(self) -> None:
        paths = self.verify_files.paths(); expected = self.expected_payload.text()
        legacy = self.legacy_bytes.value() or None
        if not paths: return self._error("请先添加图片")
        if not expected and legacy is None: return self._error("请输入期望 payload，或填写旧版字节数")
        self.verify_results.clear(); self.verify_table.setRowCount(0)
        worker = VerifyWorker(paths, expected, legacy)
        worker.item_done.connect(self._verify_item_done)
        worker.progress.connect(lambda done, total, name: self._set_progress(self.verify_progress, done, total, name))
        self._start_worker(worker, lambda _: self.statusBar().showMessage("验证完成"))

    def _start_worker(self, worker: QObject, finish_callback) -> None:
        if self.thread and self.thread.isRunning(): return self._error("已有任务正在运行")
        self.thread = QThread(self); self._threads.append(self.thread)
        self.worker = worker; worker.moveToThread(self.thread)
        self.thread.started.connect(worker.run)
        worker.finished.connect(finish_callback); worker.finished.connect(self.thread.quit)
        worker.finished.connect(worker.deleteLater)
        current_thread = self.thread
        current_thread.finished.connect(current_thread.deleteLater)
        current_thread.finished.connect(lambda: self._threads.remove(current_thread) if current_thread in self._threads else None)
        current_thread.start()

    @Slot()
    def cancel_task(self) -> None:
        if self.worker and hasattr(self.worker, "cancel"):
            # Calling the slot directly is intentional: a queued call cannot run
            # while the worker thread is busy inside the synchronous pipeline.
            self.worker.cancel()

    def _protect_item_done(self, source: str, status: str, detail: str) -> None:
        self.protect_results.append((source, status, detail)); self.protect_log.append(f"[{status}] {Path(source).name}: {detail}")

    def _verify_item_done(self, source: str, status: str, detail: str) -> None:
        self.verify_results.append((source, status, detail)); row = self.verify_table.rowCount(); self.verify_table.insertRow(row)
        for col, value in enumerate((source, status, detail)): self.verify_table.setItem(row, col, QTableWidgetItem(value))

    def _protect_finished(self, cancelled: bool) -> None:
        self.protect_start.setEnabled(True); self.protect_cancel.setEnabled(False)
        self.statusBar().showMessage("任务已取消" if cancelled else "保护完成")

    def _set_progress(self, bar: QProgressBar, done: int, total: int, name: str) -> None:
        bar.setRange(0, max(1, total)); bar.setValue(done); bar.setFormat(f"{done}/{total}  {name}")

    def export_csv(self) -> None:
        if not self.verify_results: return self._error("没有可导出的验证结果")
        path, _ = QFileDialog.getSaveFileName(self, "导出 CSV", "photo-guard-verify.csv", "CSV (*.csv)")
        if not path: return
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle); writer.writerow(["文件", "结果", "详情"]); writer.writerows(self.verify_results)

    def _unique_output(self, directory: Path, stem: str, extension: str) -> Path:
        candidate = directory / f"{stem}{extension}"; number = 2
        while candidate.exists():
            candidate = directory / f"{stem}_{number}{extension}"; number += 1
        return candidate

    def _error(self, message: str):
        QMessageBox.warning(self, "Photo Guard", message)

    def _save_settings(self) -> None:
        for key, value in {
            "output_dir": self.output_dir.text(), "suffix": self.suffix.text(),
            "visible_text": self.visible_text.text(), "mode": self.visible_mode.currentText(),
            "alpha": self.alpha.value(), "long_edge": self.long_edge.value(), "quality": self.quality.value(),
        }.items(): self.settings.setValue(key, value)

    def _load_settings(self) -> None:
        self.output_dir.setText(self.settings.value("output_dir", self.output_dir.text()))
        self.suffix.setText(self.settings.value("suffix", self.suffix.text()))
        self.visible_text.setText(self.settings.value("visible_text", self.visible_text.text()))
        self.visible_mode.setCurrentText(self.settings.value("mode", self.visible_mode.currentText()))
        self.alpha.setValue(float(self.settings.value("alpha", self.alpha.value())))
        self.long_edge.setValue(int(self.settings.value("long_edge", self.long_edge.value())))
        self.quality.setValue(int(self.settings.value("quality", self.quality.value())))

    def closeEvent(self, event) -> None:
        if self.thread and self.thread.isRunning():
            self.cancel_task()
            event.ignore()
            QTimer.singleShot(100, self.close)
            return
        event.accept()


def main() -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("Photo Guard")
    app.setOrganizationName("PhotoGuard")
    window = MainWindow(); window.show()
    return app.exec()
