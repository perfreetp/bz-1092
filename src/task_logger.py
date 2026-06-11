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

        self._tasks: Dict[str, TaskRecord] = {}
        self._failed: Dict[str, TaskRecord] = {}
        self._backups: Dict[str, BackupRecord] = {}

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
        total_duration = 0

        for task in self._tasks.values():
            by_status[task.overall_status] += 1
            by_stage[task.current_stage] += 1
            for stage in task.stages.values():
                total_duration += stage.duration_ms

        return {
            "total_tasks": total,
            "by_status": dict(by_status),
            "by_stage": dict(by_stage),
            "failed_tasks": len(self._failed),
            "total_backups": len(self._backups),
            "total_duration_ms": total_duration,
            "avg_duration_ms": total_duration / total if total > 0 else 0
        }

    def export_manifest_csv(self, materials, quality_reports: Dict,
                            resized_results: Dict, package_info: Dict,
                            duplicates: List[Dict] = None,
                            output_path: str = None) -> str:
        if output_path is None:
            output_path = os.path.join(self.log_dir, "publish_manifest.csv")

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        device_list = []
        for category in ["mobile", "desktop", "tablet"]:
            for device in self.config.get_device_resolutions(category):
                device_list.append(device["name"])

        with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)

            header = [
                "文件名", "主题", "颜色标签", "作者",
                "原分辨率", "画幅方向",
                "质检状态", "模糊分数", "质检问题",
                "重复组", "相似素材",
                "各设备分辨率数量",
            ] + device_list + [
                "预览图路径", "下载包路径", "任务状态"
            ]
            writer.writerow(header)

            duplicate_map = {}
            if duplicates:
                for i, dup in enumerate(duplicates):
                    f1 = os.path.basename(dup["file1"])
                    f2 = os.path.basename(dup["file2"])
                    duplicate_map[f1] = (f"组{i+1}", f2, dup["similarity"])
                    duplicate_map[f2] = (f"组{i+1}", f1, dup["similarity"])

            for m in materials:
                report = quality_reports.get(m.file_path)
                qc_status = "通过"
                blur_score = ""
                qc_issues = ""
                if report:
                    qc_status = "通过" if report.passed else "未通过"
                    blur_score = f"{report.blur_score:.1f}"
                    qc_issues = "; ".join([f"{i.issue_type}({i.severity})" for i in report.issues])

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
                for task in self._tasks.values():
                    if task.filename == m.filename:
                        status_map = {
                            STATUS_SUCCESS: "成功",
                            STATUS_FAILED: "失败",
                            STATUS_RUNNING: "运行中",
                            STATUS_PENDING: "等待中",
                        }
                        task_status = status_map.get(task.overall_status, task.overall_status)
                        break

                zip_path = package_info.get("zip_path", "")

                writer.writerow([
                    m.filename,
                    m.theme,
                    ", ".join([t for t in m.tags if t in self.config.get_color_tags()]),
                    m.author,
                    f"{m.width}x{m.height}",
                    "横屏" if m.orientation == "landscape" else "竖屏" if m.orientation == "portrait" else "方形",
                    qc_status,
                    blur_score,
                    qc_issues,
                    dup_group,
                    dup_similar,
                    total_resolutions,
                ] + device_cells + [
                    os.path.basename(package_info.get("package_dir", "")) + "/previews/" + m.filename.replace(".jpg", "_preview.jpg").replace(".png", "_preview.jpg"),
                    os.path.basename(zip_path) if zip_path else "",
                    task_status
                ])

        return output_path

    def generate_summary_report(self, materials=None,
                                quality_reports: Dict = None,
                                duplicates: List[Dict] = None,
                                output_path: str = None) -> str:
        stats = self.get_statistics()

        report = "# 壁纸包处理报告\n\n"
        report += f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        report += "## 📊 统计概览\n\n"
        report += f"- 总任务数: {stats['total_tasks']}\n"
        status_map_cn = {
            STATUS_SUCCESS: "成功",
            STATUS_FAILED: "失败",
            STATUS_RUNNING: "运行中",
            STATUS_PENDING: "等待中",
        }
        for status, count in stats['by_status'].items():
            cn = status_map_cn.get(status, status)
            report += f"- {cn}: {count}\n"
        report += f"- 备份文件数: {stats['total_backups']}\n"
        report += f"- 总处理时长: {stats['total_duration_ms']/1000:.1f} 秒\n\n"

        report += "## 📋 各阶段状态\n\n"
        report += "| 阶段 | 等待 | 运行中 | 成功 | 失败 | 跳过 |\n"
        report += "|------|------|--------|------|------|------|\n"

        for stage in [STAGE_IMPORT, STAGE_QUALITY, STAGE_TAG, STAGE_RESIZE, STAGE_PACKAGE]:
            stage_cn = STAGE_NAMES.get(stage, stage)
            pending = running = success = failed = skipped = 0
            for task in self._tasks.values():
                if stage in task.stages:
                    s = task.stages[stage].status
                    if s == STATUS_PENDING:
                        pending += 1
                    elif s == STATUS_RUNNING:
                        running += 1
                    elif s == STATUS_SUCCESS:
                        success += 1
                    elif s == STATUS_FAILED:
                        failed += 1
                    elif s == STATUS_SKIPPED:
                        skipped += 1
            report += f"| {stage_cn} | {pending} | {running} | {success} | {failed} | {skipped} |\n"

        report += "\n"

        if duplicates:
            report += "## ⚠️ 重复素材检测\n\n"
            report += f"共检测到 **{len(duplicates)}** 组相似素材:\n\n"
            for i, dup in enumerate(duplicates, 1):
                f1 = os.path.basename(dup['file1'])
                f2 = os.path.basename(dup['file2'])
                report += f"### 重复组 #{i} (相似度: {dup['similarity']:.1f}%)\n\n"
                report += f"- **素材A**: {f1}\n"
                report += f"- **素材B**: {f2}\n"
                report += f"- 汉明距离: {dup['hamming_distance']}\n\n"

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
                report += f"- 创建时间: {task.created_at}\n\n"

        if materials and quality_reports:
            report += "## 📝 完整素材清单\n\n"

            from collections import defaultdict as dd
            theme_groups = dd(list)
            for m in materials:
                theme_groups[m.theme].append(m)

            for theme, items in sorted(theme_groups.items()):
                report += f"### {theme.capitalize()} ({len(items)} 张)\n\n"
                report += "| 文件名 | 分辨率 | 画幅 | 质检 | 标签 |\n"
                report += "|--------|--------|------|------|------|\n"

                for m in sorted(items, key=lambda x: x.filename):
                    report_q = quality_reports.get(m.file_path)
                    qc_icon = "✅" if report_q and report_q.passed else "❌"
                    orient_cn = "横屏" if m.orientation == "landscape" else "竖屏" if m.orientation == "portrait" else "方形"
                    tags_str = ", ".join(m.tags[:5]) if m.tags else "无"
                    report += f"| {m.filename} | {m.width}x{m.height} | {orient_cn} | {qc_icon} | {tags_str} |\n"

                report += "\n"

        if output_path is None:
            output_path = os.path.join(self.log_dir, f"report_{self.date_str}.md")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)

        return output_path
