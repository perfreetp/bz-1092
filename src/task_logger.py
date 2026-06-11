import os
import json
import csv
import shutil
import traceback
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable, Tuple
from dataclasses import dataclass, field, asdict
from collections import defaultdict


STAGE_IMPORT = "import"
STAGE_QUALITY = "quality"
STAGE_TAG = "tag"
STAGE_RESIZE = "resize"
STAGE_PACKAGE = "package"
STAGE_DONE = "done"

STAGE_NAMES = {
    STAGE_IMPORT: "素材导入",
    STAGE_QUALITY: "质量检查",
    STAGE_TAG: "标签整理",
    STAGE_RESIZE: "尺寸适配",
    STAGE_PACKAGE: "打包输出",
    STAGE_DONE: "完成",
}

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

STATUS_NAMES_CN = {
    STATUS_PENDING: "等待",
    STATUS_RUNNING: "运行中",
    STATUS_SUCCESS: "成功",
    STATUS_FAILED: "失败",
    STATUS_SKIPPED: "跳过",
}

NEEDS_REVIEW_QC_FAILED = "qc_failed"
NEEDS_REVIEW_DUPLICATE = "duplicate"


@dataclass
class StageRecord:
    stage: str
    status: str = STATUS_PENDING
    started_at: str = ""
    finished_at: str = ""
    duration_ms: int = 0
    error_message: str = ""
    error_traceback: str = ""
    output_files: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TaskRecord:
    task_id: str
    filename: str
    input_file: str
    created_at: str
    current_stage: str = STAGE_IMPORT
    overall_status: str = STATUS_PENDING
    stages: Dict[str, StageRecord] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.stages:
            for stage in [STAGE_IMPORT, STAGE_QUALITY, STAGE_TAG, STAGE_RESIZE, STAGE_PACKAGE]:
                self.stages[stage] = StageRecord(stage=stage)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "filename": self.filename,
            "input_file": self.input_file,
            "created_at": self.created_at,
            "current_stage": self.current_stage,
            "overall_status": self.overall_status,
            "stages": {k: v.to_dict() for k, v in self.stages.items()},
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskRecord":
        stages = {}
        for stage_name, stage_data in data.get("stages", {}).items():
            stages[stage_name] = StageRecord(**stage_data)
        record = cls(
            task_id=data["task_id"],
            filename=data["filename"],
            input_file=data["input_file"],
            created_at=data["created_at"],
            current_stage=data.get("current_stage", STAGE_IMPORT),
            overall_status=data.get("overall_status", STATUS_PENDING),
            stages=stages,
            metadata=data.get("metadata", {})
        )
        return record


@dataclass
class BackupRecord:
    backup_id: str
    original_path: str
    backup_path: str
    timestamp: str
    file_size: int = 0
    file_hash: str = ""


class TaskLogger:
    def __init__(self, config, date_str: str = None):
        self.config = config
        self.date_str = date_str or datetime.now().strftime("%Y-%m-%d")

        self.log_dir = os.path.join(config.get_path("log_dir"), self.date_str)
        self.backup_dir = os.path.join(config.get_path("backup_dir"), self.date_str)
        self.archive_dir = config.get_path("archive_dir")

        os.makedirs(self.log_dir, exist_ok=True)
        os.makedirs(self.backup_dir, exist_ok=True)
        os.makedirs(self.archive_dir, exist_ok=True)

        self._task_log_path = os.path.join(self.log_dir, "tasks.json")
        self._failed_log_path = os.path.join(self.log_dir, "failed.json")
        self._backup_log_path = os.path.join(self.log_dir, "backups.json")
        self._cache_path = os.path.join(self.log_dir, "cache.json")

        self._tasks: Dict[str, TaskRecord] = {}
        self._failed: Dict[str, TaskRecord] = {}
        self._backups: Dict[str, BackupRecord] = {}
        self._cache: Dict[str, Any] = {}

        self._load_all()

    def _load_all(self):
        task_data = self._load_json(self._task_log_path)
        for tid, tdata in task_data.items():
            self._tasks[tid] = TaskRecord.from_dict(tdata)

        failed_data = self._load_json(self._failed_log_path)
        for tid, tdata in failed_data.items():
            self._failed[tid] = TaskRecord.from_dict(tdata)

        backup_data = self._load_json(self._backup_log_path)
        for bid, bdata in backup_data.items():
            self._backups[bid] = BackupRecord(**bdata)

        self._cache = self._load_json(self._cache_path)

    def _load_json(self, path: str) -> Dict[str, Any]:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_tasks(self) -> None:
        data = {k: v.to_dict() for k, v in self._tasks.items()}
        self._save_json(data, self._task_log_path)

    def _save_failed(self) -> None:
        data = {k: v.to_dict() for k, v in self._failed.items()}
        self._save_json(data, self._failed_log_path)

    def _save_backups(self) -> None:
        data = {k: asdict(v) for k, v in self._backups.items()}
        self._save_json(data, self._backup_log_path)

    def save_cache(self, key: str, value: Any) -> None:
        self._cache[key] = value
        self._save_json(self._cache, self._cache_path)

    def get_cache(self, key: str, default: Any = None) -> Any:
        return self._cache.get(key, default)

    def clear_cache(self) -> None:
        self._cache = {}
        if os.path.exists(self._cache_path):
            os.remove(self._cache_path)

    def _save_json(self, data: Dict[str, Any], path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _generate_task_id(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        return f"task_{timestamp}"

    def create_task(self, input_file: str, metadata: Dict[str, Any] = None) -> str:
        task_id = self._generate_task_id()
        filename = os.path.basename(input_file)

        task = TaskRecord(
            task_id=task_id,
            filename=filename,
            input_file=input_file,
            created_at=datetime.now().isoformat(),
            current_stage=STAGE_IMPORT,
            overall_status=STATUS_PENDING,
            metadata=metadata or {}
        )

        self._tasks[task_id] = task
        self._save_tasks()
        return task_id

    def start_stage(self, task_id: str, stage: str) -> None:
        if task_id not in self._tasks:
            return

        task = self._tasks[task_id]
        if stage in task.stages:
            task.stages[stage].status = STATUS_RUNNING
            task.stages[stage].started_at = datetime.now().isoformat()
            task.current_stage = stage
            task.overall_status = STATUS_RUNNING
            self._save_tasks()

    def finish_stage(self, task_id: str, stage: str,
                     output_files: List[str] = None,
                     metadata: Dict[str, Any] = None) -> None:
        if task_id not in self._tasks:
            return

        task = self._tasks[task_id]
        if stage in task.stages:
            record = task.stages[stage]
            record.status = STATUS_SUCCESS
            record.finished_at = datetime.now().isoformat()
            record.output_files = output_files or []
            if metadata:
                record.metadata.update(metadata)

            if record.started_at:
                start = datetime.fromisoformat(record.started_at)
                end = datetime.fromisoformat(record.finished_at)
                record.duration_ms = int((end - start).total_seconds() * 1000)

            if stage == STAGE_PACKAGE:
                task.overall_status = STATUS_SUCCESS
                task.current_stage = STAGE_DONE

                if task_id in self._failed:
                    del self._failed[task_id]
                    self._save_failed()

            self._save_tasks()

    def fail_stage(self, task_id: str, stage: str, error: Exception) -> None:
        if task_id not in self._tasks:
            return

        task = self._tasks[task_id]
        if stage in task.stages:
            record = task.stages[stage]
            record.status = STATUS_FAILED
            record.finished_at = datetime.now().isoformat()
            record.error_message = str(error)
            record.error_traceback = traceback.format_exc()

            if record.started_at:
                start = datetime.fromisoformat(record.started_at)
                end = datetime.fromisoformat(record.finished_at)
                record.duration_ms = int((end - start).total_seconds() * 1000)

            task.overall_status = STATUS_FAILED
            task.current_stage = stage

            self._failed[task_id] = task
            self._save_tasks()
            self._save_failed()

    def skip_stage(self, task_id: str, stage: str, reason: str = "") -> None:
        if task_id not in self._tasks:
            return

        task = self._tasks[task_id]
        if stage in task.stages:
            record = task.stages[stage]
            record.status = STATUS_SKIPPED
            record.finished_at = datetime.now().isoformat()
            record.metadata["skip_reason"] = reason
            record.duration_ms = 0

            self._save_tasks()

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> Dict[str, TaskRecord]:
        return self._tasks.copy()

    def get_failed_tasks(self) -> Dict[str, TaskRecord]:
        return self._failed.copy()

    def get_tasks_by_stage(self, stage: str) -> List[TaskRecord]:
        return [t for t in self._tasks.values() if t.current_stage == stage]

    def get_tasks_by_status(self, status: str) -> List[TaskRecord]:
        return [t for t in self._tasks.values() if t.overall_status == status]

    def retry_task(self, task_id: str, pipeline_instance) -> Optional[TaskRecord]:
        if task_id not in self._failed:
            print(f"任务 {task_id} 不在失败列表中")
            return None

        task = self._failed[task_id]
        print(f"正在重跑任务 {task_id} ({task.filename})...")

        new_task_id = self.create_task(
            task.input_file,
            metadata={**task.metadata, "retry_from": task_id}
        )

        try:
            result = pipeline_instance._process_single_material(
                task.input_file, new_task_id
            )
            if result:
                if task_id in self._failed:
                    del self._failed[task_id]
                    self._save_failed()
                return self._tasks.get(new_task_id)
            else:
                return None
        except Exception as e:
            print(f"重跑失败: {e}")
            return None

    def retry_all_failed(self, pipeline_instance) -> Dict[str, Any]:
        results = {"success": [], "failed": []}
        failed_ids = list(self._failed.keys())

        for task_id in failed_ids:
            try:
                result = self.retry_task(task_id, pipeline_instance)
                if result and result.overall_status == STATUS_SUCCESS:
                    results["success"].append(task_id)
                else:
                    results["failed"].append(task_id)
            except Exception as e:
                results["failed"].append({"task_id": task_id, "error": str(e)})

        return results

    def backup_original(self, file_path: str, file_hash: str = "") -> str:
        filename = os.path.basename(file_path)
        base_name, ext = os.path.splitext(filename)
        timestamp = datetime.now().strftime("%H%M%S_%f")[:-3]
        backup_filename = f"{base_name}_{timestamp}{ext}"
        backup_path = os.path.join(self.backup_dir, backup_filename)

        shutil.copy2(file_path, backup_path)

        backup_id = f"backup_{len(self._backups) + 1:04d}"
        record = BackupRecord(
            backup_id=backup_id,
            original_path=file_path,
            backup_path=backup_path,
            timestamp=datetime.now().isoformat(),
            file_size=os.path.getsize(file_path),
            file_hash=file_hash
        )

        self._backups[backup_id] = record
        self._save_backups()

        return backup_path

    def archive_output(self, output_dir: str, date_str: str = None) -> str:
        if date_str is None:
            date_str = self.date_str

        archive_subdir = os.path.join(self.archive_dir, date_str)
        os.makedirs(archive_subdir, exist_ok=True)

        items = os.listdir(output_dir)
        for item in items:
            src = os.path.join(output_dir, item)
            dst = os.path.join(archive_subdir, item)

            if os.path.exists(dst):
                if os.path.isdir(src):
                    shutil.rmtree(dst)
                else:
                    os.remove(dst)

            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)

        archive_log_path = os.path.join(self.log_dir, "archives.json")
        archives = self._load_json(archive_log_path)
        archive_id = f"archive_{len(archives) + 1:03d}"
        archives[archive_id] = {
            "source_dir": output_dir,
            "archive_dir": archive_subdir,
            "timestamp": datetime.now().isoformat(),
            "items_count": len(items)
        }
        self._save_json(archives, archive_log_path)

        return archive_subdir

    def get_statistics(self) -> Dict[str, Any]:
        total = len(self._tasks)
        by_status = defaultdict(int)
        by_stage = defaultdict(int)
        stage_status = defaultdict(lambda: defaultdict(int))
        total_duration = 0

        for task in self._tasks.values():
            by_status[task.overall_status] += 1
            by_stage[task.current_stage] += 1
            for stage_name, stage in task.stages.items():
                stage_status[stage_name][stage.status] += 1
                total_duration += stage.duration_ms

        return {
            "total_tasks": total,
            "by_status": dict(by_status),
            "by_stage": dict(by_stage),
            "stage_status": {k: dict(v) for k, v in stage_status.items()},
            "failed_tasks": len(self._failed),
            "total_backups": len(self._backups),
            "total_duration_ms": total_duration,
            "avg_duration_ms": total_duration / total if total > 0 else 0
        }

    def _get_device_list(self) -> List[str]:
        device_list = []
        for category in ["mobile", "desktop", "tablet"]:
            for device in self.config.get_device_resolutions(category):
                device_list.append(device["name"])
        return device_list

    def _build_duplicate_map(self, duplicates: List[Dict]) -> Dict[str, Tuple[str, str, float]]:
        duplicate_map = {}
        if duplicates:
            for i, dup in enumerate(duplicates):
                f1 = os.path.basename(dup["file1"])
                f2 = os.path.basename(dup["file2"])
                duplicate_map[f1] = (f"组{i+1:02d}", f2, dup["similarity"])
                duplicate_map[f2] = (f"组{i+1:02d}", f1, dup["similarity"])
        return duplicate_map

    def export_manifest_csv(self, materials, quality_reports: Dict,
                            resized_results: Dict, package_info: Dict,
                            duplicates: List[Dict] = None,
                            output_path: str = None) -> str:
        if output_path is None:
            output_path = os.path.join(self.log_dir, "publish_manifest.csv")

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        device_list = self._get_device_list()
        duplicate_map = self._build_duplicate_map(duplicates)

        with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)

            header = [
                "文件名", "主题", "颜色标签", "作者",
                "原分辨率", "画幅方向",
                "质检状态", "模糊分数", "质检问题",
                "重复组", "相似素材",
                "各设备分辨率数量",
            ] + device_list + [
                "预览图路径", "下载包路径", "任务状态", "任务ID"
            ]
            writer.writerow(header)

            for m in materials:
                report = quality_reports.get(m.file_path)
                qc_status = "跳过"
                blur_score = "—"
                qc_issues = "已跳过"
                if report:
                    qc_status = "通过" if report.passed else "未通过"
                    blur_score = f"{report.blur_score:.1f}"
                    qc_issues = "; ".join([f"{i.issue_type}({i.severity})" for i in report.issues]) if report.issues else "—"

                dup_group = ""
                dup_similar = ""
                if m.filename in duplicate_map:
                    info = duplicate_map[m.filename]
                    dup_group = info[0]
                    dup_similar = f"{info[1]} ({info[2]:.1f}%)"

                resized = resized_results.get(m.filename, [])
                device_counts = defaultdict(int)
                for r in resized:
                    device_counts[r.device_name] += 1

                total_resolutions = len(resized)

                device_cells = []
                for dev_name in device_list:
                    device_cells.append(device_counts.get(dev_name, 0))

                task_status = "未知"
                task_id = ""
                for task in self._tasks.values():
                    if task.filename == m.filename:
                        status_map = {
                            STATUS_SUCCESS: "成功",
                            STATUS_FAILED: "失败",
                            STATUS_RUNNING: "运行中",
                            STATUS_PENDING: "等待中",
                            STATUS_SKIPPED: "跳过",
                        }
                        task_status = status_map.get(task.overall_status, task.overall_status)
                        task_id = task.task_id
                        break

                zip_path = package_info.get("zip_path", "")
                preview_name = os.path.splitext(m.filename)[0] + "_preview.jpg"
                preview_rel = f"previews/{preview_name}"

                orient_cn = "横屏" if m.orientation == "landscape" else "竖屏" if m.orientation == "portrait" else "方形"
                color_tags = ", ".join([t for t in m.tags if t in self.config.get_color_tags()])

                writer.writerow([
                    m.filename,
                    m.theme,
                    color_tags,
                    m.author,
                    f"{m.width}x{m.height}",
                    orient_cn,
                    qc_status,
                    blur_score,
                    qc_issues,
                    dup_group,
                    dup_similar,
                    total_resolutions,
                ] + device_cells + [
                    preview_rel,
                    os.path.basename(zip_path) if zip_path else "",
                    task_status,
                    task_id
                ])

        return output_path

    def export_review_csv(self, materials, quality_reports: Dict,
                          duplicates: List[Dict] = None,
                          filter_duplicate: bool = True,
                          filter_qc_failed: bool = True,
                          filter_theme: str = None,
                          filter_author: str = None,
                          filter_orientation: str = None,
                          output_path: str = None) -> str:
        if output_path is None:
            output_path = os.path.join(self.log_dir, "review_manifest.csv")

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        duplicate_map = self._build_duplicate_map(duplicates)

        review_items = []
        for m in materials:
            is_dup = m.filename in duplicate_map
            report = quality_reports.get(m.file_path)
            qc_passed = report.passed if report else True

            needs_review = False
            review_reasons = []

            if filter_duplicate and is_dup:
                needs_review = True
                info = duplicate_map[m.filename]
                review_reasons.append(f"重复素材({info[0]})")

            if filter_qc_failed and not qc_passed:
                needs_review = True
                issues = [i.issue_type for i in (report.issues if report else [])]
                review_reasons.append(f"质检未通过({', '.join(issues)})")

            if filter_theme and m.theme != filter_theme:
                continue
            if filter_author and m.author != filter_author:
                continue
            if filter_orientation and m.orientation != filter_orientation:
                continue

            if needs_review or (not filter_duplicate and not filter_qc_failed):
                review_items.append((m, report, is_dup, review_reasons))

        with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)

            header = [
                "确认状态", "文件名", "主题", "作者",
                "原分辨率", "画幅方向",
                "质检状态", "模糊分数", "质检问题",
                "重复组", "相似素材", "相似度",
                "需确认原因",
                "建议保留", "备注"
            ]
            writer.writerow(header)

            for m, report, is_dup, reasons in review_items:
                qc_status = "跳过"
                blur_score = "—"
                qc_issues = "已跳过"
                if report:
                    qc_status = "✅通过" if report.passed else "❌未通过"
                    blur_score = f"{report.blur_score:.1f}"
                    qc_issues = "; ".join([f"{i.issue_type}({i.severity})" for i in report.issues]) if report.issues else "—"

                dup_group = ""
                dup_similar = ""
                dup_similarity = ""
                if is_dup:
                    info = duplicate_map[m.filename]
                    dup_group = info[0]
                    dup_similar = info[1]
                    dup_similarity = f"{info[2]:.1f}%"

                orient_cn = "横屏" if m.orientation == "landscape" else "竖屏" if m.orientation == "portrait" else "方形"

                writer.writerow([
                    "待确认",
                    m.filename,
                    m.theme,
                    m.author,
                    f"{m.width}x{m.height}",
                    orient_cn,
                    qc_status,
                    blur_score,
                    qc_issues,
                    dup_group,
                    dup_similar,
                    dup_similarity,
                    "; ".join(reasons),
                    "是/否",
                    ""
                ])

        return output_path, len(review_items)

    def get_review_summary(self, materials, quality_reports: Dict,
                           duplicates: List[Dict] = None) -> Dict[str, Any]:
        duplicate_map = self._build_duplicate_map(duplicates)

        total = len(materials)
        duplicate_count = 0
        qc_failed_count = 0
        both_count = 0
        clean_count = 0

        by_theme = defaultdict(lambda: {"total": 0, "duplicate": 0, "qc_failed": 0, "clean": 0})
        by_orientation = defaultdict(lambda: {"total": 0, "duplicate": 0, "qc_failed": 0, "clean": 0})
        by_author = defaultdict(lambda: {"total": 0, "duplicate": 0, "qc_failed": 0, "clean": 0})

        duplicate_groups = defaultdict(list)
        if duplicates:
            for i, dup in enumerate(duplicates):
                group_name = f"组{i+1:02d}"
                duplicate_groups[group_name].append(dup)

        for m in materials:
            is_dup = m.filename in duplicate_map
            report = quality_reports.get(m.file_path)
            qc_passed = report.passed if report else True

            has_issue = is_dup or not qc_passed
            if is_dup and not qc_passed:
                both_count += 1
            elif is_dup:
                duplicate_count += 1
            elif not qc_passed:
                qc_failed_count += 1
            else:
                clean_count += 1

            for counter in [by_theme[m.theme], by_orientation[m.orientation], by_author[m.author]]:
                counter["total"] += 1
                if is_dup:
                    counter["duplicate"] += 1
                if report and not report.passed:
                    counter["qc_failed"] += 1
                if not is_dup and (report and report.passed):
                    counter["clean"] += 1

        return {
            "total": total,
            "duplicate_only": duplicate_count,
            "qc_failed_only": qc_failed_count,
            "both_issues": both_count,
            "clean": clean_count,
            "needs_review": total - clean_count,
            "duplicate_groups_count": len(duplicate_groups),
            "by_theme": dict(by_theme),
            "by_orientation": dict(by_orientation),
            "by_author": dict(by_author),
        }

    def generate_batch_summary(self, materials=None,
                               quality_reports: Dict = None,
                               duplicates: List[Dict] = None,
                               package_info: Dict = None,
                               output_path: str = None) -> str:
        if output_path is None:
            output_path = os.path.join(self.log_dir, "batch_summary.csv")

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        review_summary = self.get_review_summary(materials or [], quality_reports or {}, duplicates or [])
        stats = self.get_statistics()

        by_theme_data = review_summary.get("by_theme", {})

        with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)

            writer.writerow([f"发布批次摘要 - {self.date_str}"])
            writer.writerow([])
            writer.writerow(["概览"])
            writer.writerow(["日期", self.date_str])
            writer.writerow(["素材总数", review_summary["total"]])
            writer.writerow(["可直接发布", review_summary["clean"]])
            writer.writerow(["重复待确认", review_summary["duplicate_only"] + review_summary["both_issues"]])
            writer.writerow(["质检失败", review_summary["qc_failed_only"] + review_summary["both_issues"]])
            writer.writerow(["任务成功", stats["by_status"].get(STATUS_SUCCESS, 0)])
            writer.writerow(["任务失败", stats["by_status"].get(STATUS_FAILED, 0)])
            writer.writerow(["下载包", os.path.basename(package_info.get("zip_path", "")) if package_info else ""])
            writer.writerow([])

            writer.writerow(["按主题汇总"])
            writer.writerow(["主题", "总数", "可发布", "重复待确认", "质检失败", "失败任务数"])

            failed_by_theme = defaultdict(int)
            for task in self._tasks.values():
                if task.overall_status == STATUS_FAILED:
                    theme = task.metadata.get("theme", "未分类")
                    failed_by_theme[theme] += 1

            for theme in sorted(by_theme_data.keys()):
                tdata = by_theme_data[theme]
                dup_count = tdata.get("duplicate", 0)
                qc_fail = tdata.get("qc_failed", 0)
                writer.writerow([
                    theme,
                    tdata["total"],
                    tdata.get("clean", 0),
                    dup_count,
                    qc_fail,
                    failed_by_theme.get(theme, 0)
                ])
            writer.writerow([])

            writer.writerow(["失败任务列表"])
            writer.writerow(["任务ID", "文件名", "失败阶段", "错误信息"])
            for task_id, task in self._failed.items():
                failed_stage = task.current_stage
                stage_cn = STAGE_NAMES.get(failed_stage, failed_stage)
                error = task.stages.get(failed_stage, None).error_message if failed_stage in task.stages else ""
                writer.writerow([task_id, task.filename, stage_cn, error])

        return output_path

    def generate_summary_report(self, materials=None,
                                quality_reports: Dict = None,
                                duplicates: List[Dict] = None,
                                package_info: Dict = None,
                                output_path: str = None) -> str:
        stats = self.get_statistics()

        report = f"# 壁纸包处理报告 - {self.date_str}\n\n"
        report += f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        report += "## 📊 统计概览\n\n"
        report += f"- 总任务数: {stats['total_tasks']}\n"
        for status, count in stats['by_status'].items():
            cn = STATUS_NAMES_CN.get(status, status)
            report += f"- {cn}: {count}\n"
        report += f"- 备份文件数: {stats['total_backups']}\n"
        report += f"- 总处理时长: {stats['total_duration_ms']/1000:.1f} 秒\n\n"

        report += "## 📋 各阶段状态\n\n"
        report += "| 阶段 | 等待 | 运行中 | 成功 | 失败 | 跳过 |\n"
        report += "|------|------|--------|------|------|------|\n"

        stage_status = stats.get("stage_status", {})
        for stage in [STAGE_IMPORT, STAGE_QUALITY, STAGE_TAG, STAGE_RESIZE, STAGE_PACKAGE]:
            stage_cn = STAGE_NAMES.get(stage, stage)
            sdata = stage_status.get(stage, {})
            pending = sdata.get(STATUS_PENDING, 0)
            running = sdata.get(STATUS_RUNNING, 0)
            success = sdata.get(STATUS_SUCCESS, 0)
            failed = sdata.get(STATUS_FAILED, 0)
            skipped = sdata.get(STATUS_SKIPPED, 0)
            report += f"| {stage_cn} | {pending} | {running} | {success} | {failed} | {skipped} |\n"

        report += "\n"

        if duplicates or (quality_reports and materials):
            review = self.get_review_summary(materials or [], quality_reports or {}, duplicates or [])
            report += "## 🔍 发布复核\n\n"
            report += f"| 类别 | 数量 |\n"
            report += f"|------|------|\n"
            report += f"| 素材总数 | {review['total']} |\n"
            report += f"| ✅ 可直接发布 | {review['clean']} |\n"
            report += f"| ⚠️ 重复待确认 | {review['duplicate_only'] + review['both_issues']} |\n"
            report += f"| ❌ 质检失败 | {review['qc_failed_only'] + review['both_issues']} |\n"
            report += f"| 🔁 两项都有问题 | {review['both_issues']} |\n"
            report += "\n"

            if review['by_theme']:
                report += "### 按主题分布\n\n"
                report += "| 主题 | 总数 | 可发布 | 重复 | 质检失败 |\n"
                report += "|------|------|--------|------|----------|\n"
                for theme, tdata in sorted(review['by_theme'].items()):
                    report += f"| {theme} | {tdata['total']} | {tdata.get('clean', 0)} | {tdata.get('duplicate', 0)} | {tdata.get('qc_failed', 0)} |\n"
                report += "\n"

        if duplicates:
            report += "## ⚠️ 重复素材检测\n\n"
            report += f"共检测到 **{len(duplicates)}** 组相似素材 (发布前请确认保留哪一张):\n\n"
            for i, dup in enumerate(duplicates, 1):
                f1 = os.path.basename(dup['file1'])
                f2 = os.path.basename(dup['file2'])
                report += f"### 重复组 #{i:02d} (相似度: {dup['similarity']:.1f}%)\n\n"
                report += f"- **素材A**: {f1}\n"
                report += f"- **素材B**: {f2}\n"
                if quality_reports:
                    r1 = quality_reports.get(dup['file1'])
                    r2 = quality_reports.get(dup['file2'])
                    if r1:
                        qc_a = "✅通过" if r1.passed else "❌未通过"
                        report += f"  - 质检: {qc_a}, 模糊分: {r1.blur_score:.1f}\n"
                    if r2:
                        qc_b = "✅通过" if r2.passed else "❌未通过"
                        report += f"  - 质检: {qc_b}, 模糊分: {r2.blur_score:.1f}\n"
                report += "\n"

        if self._failed:
            report += "## ❌ 失败任务详情\n\n"
            for task_id, task in self._failed.items():
                failed_stage = task.current_stage
                stage_cn = STAGE_NAMES.get(failed_stage, failed_stage)
                error_msg = ""
                if failed_stage in task.stages:
                    error_msg = task.stages[failed_stage].error_message

                report += f"### {task_id}\n\n"
                report += f"- 文件: {task.filename}\n"
                report += f"- 失败阶段: {stage_cn}\n"
                report += f"- 错误信息: {error_msg}\n"
                report += f"- 创建时间: {task.created_at}\n"
                if task.metadata.get("retry_from"):
                    report += f"- 重跑来源: {task.metadata['retry_from']}\n"
                report += "\n"

        if materials and quality_reports:
            report += "## 📝 完整素材清单\n\n"

            from collections import defaultdict as dd
            theme_groups = dd(list)
            for m in materials:
                theme_groups[m.theme].append(m)

            for theme, items in sorted(theme_groups.items()):
                report += f"### {theme.capitalize()} ({len(items)} 张)\n\n"
                report += "| 文件名 | 分辨率 | 画幅 | 质检 | 标签 | 任务状态 |\n"
                report += "|--------|--------|------|------|------|----------|\n"

                for m in sorted(items, key=lambda x: x.filename):
                    report_q = quality_reports.get(m.file_path)
                    qc_icon = "✅" if report_q and report_q.passed else "⏭️" if report_q is None else "❌"
                    orient_cn = "横屏" if m.orientation == "landscape" else "竖屏" if m.orientation == "portrait" else "方形"
                    tags_str = ", ".join(m.tags[:5]) if m.tags else "无"

                    task_status = "—"
                    for task in self._tasks.values():
                        if task.filename == m.filename:
                            task_status = STATUS_NAMES_CN.get(task.overall_status, task.overall_status)
                            break

                    report += f"| {m.filename} | {m.width}x{m.height} | {orient_cn} | {qc_icon} | {tags_str} | {task_status} |\n"

                report += "\n"

        if output_path is None:
            output_path = os.path.join(self.log_dir, f"report_{self.date_str}.md")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)

        return output_path
