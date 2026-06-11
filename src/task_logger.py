import os
import json
import shutil
import traceback
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field, asdict
from collections import defaultdict


@dataclass
class TaskRecord:
    task_id: str
    timestamp: str
    status: str
    input_file: str
    output_files: List[str] = field(default_factory=list)
    error_message: str = ""
    error_traceback: str = ""
    duration_ms: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BackupRecord:
    original_path: str
    backup_path: str
    timestamp: str
    file_hash: str = ""


class TaskLogger:
    def __init__(self, config):
        self.config = config
        self.log_dir = config.get_path("log_dir")
        self.backup_dir = config.get_path("backup_dir")
        self.archive_dir = config.get_path("archive_dir")

        os.makedirs(self.log_dir, exist_ok=True)
        os.makedirs(self.backup_dir, exist_ok=True)
        os.makedirs(self.archive_dir, exist_ok=True)

        self._task_log_path = os.path.join(self.log_dir, "tasks.json")
        self._failed_log_path = os.path.join(self.log_dir, "failed.json")
        self._backup_log_path = os.path.join(self.log_dir, "backups.json")

        self._tasks = self._load_json(self._task_log_path)
        self._failed = self._load_json(self._failed_log_path)
        self._backups = self._load_json(self._backup_log_path)

    def _load_json(self, path: str) -> Dict[str, Any]:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_json(self, data: Dict[str, Any], path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _generate_task_id(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        return f"task_{timestamp}"

    def log_start(self, input_file: str, metadata: Dict[str, Any] = None) -> str:
        task_id = self._generate_task_id()
        record = TaskRecord(
            task_id=task_id,
            timestamp=datetime.now().isoformat(),
            status="running",
            input_file=input_file,
            metadata=metadata or {}
        )
        self._tasks[task_id] = record.to_dict()
        self._save_json(self._tasks, self._task_log_path)
        return task_id

    def log_success(self, task_id: str, output_files: List[str],
                    duration_ms: int = 0, metadata: Dict[str, Any] = None) -> None:
        if task_id in self._tasks:
            self._tasks[task_id]["status"] = "success"
            self._tasks[task_id]["output_files"] = output_files
            self._tasks[task_id]["duration_ms"] = duration_ms
            if metadata:
                self._tasks[task_id]["metadata"].update(metadata)
            self._save_json(self._tasks, self._task_log_path)

    def log_failure(self, task_id: str, error: Exception,
                    duration_ms: int = 0, metadata: Dict[str, Any] = None) -> None:
        if task_id in self._tasks:
            self._tasks[task_id]["status"] = "failed"
            self._tasks[task_id]["error_message"] = str(error)
            self._tasks[task_id]["error_traceback"] = traceback.format_exc()
            self._tasks[task_id]["duration_ms"] = duration_ms
            if metadata:
                self._tasks[task_id]["metadata"].update(metadata)
            self._save_json(self._tasks, self._task_log_path)

            self._failed[task_id] = self._tasks[task_id]
            self._save_json(self._failed, self._failed_log_path)

    def get_failed_tasks(self) -> Dict[str, Any]:
        return self._failed

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self._tasks.get(task_id)

    def get_tasks_by_status(self, status: str) -> List[Dict[str, Any]]:
        return [t for t in self._tasks.values() if t["status"] == status]

    def retry_failed_task(self, task_id: str, processor: Callable[[str], Any]) -> Optional[Any]:
        if task_id not in self._failed:
            print(f"Task {task_id} not found in failed tasks")
            return None

        task_data = self._failed[task_id]
        input_file = task_data["input_file"]
        metadata = task_data.get("metadata", {})

        new_task_id = self.log_start(input_file, metadata)
        start_time = datetime.now()

        try:
            result = processor(input_file)
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            output_files = result if isinstance(result, list) else [str(result)]
            self.log_success(new_task_id, output_files, duration_ms)

            del self._failed[task_id]
            self._save_json(self._failed, self._failed_log_path)

            return result
        except Exception as e:
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            self.log_failure(new_task_id, e, duration_ms, metadata)
            raise

    def retry_all_failed(self, processor: Callable[[str], Any]) -> Dict[str, Any]:
        results = {"success": [], "failed": []}
        failed_ids = list(self._failed.keys())

        for task_id in failed_ids:
            try:
                result = self.retry_failed_task(task_id, processor)
                if result is not None:
                    results["success"].append(task_id)
            except Exception as e:
                results["failed"].append({"task_id": task_id, "error": str(e)})

        return results

    def backup_original(self, file_path: str, file_hash: str = "") -> str:
        date_str = datetime.now().strftime("%Y-%m-%d")
        backup_subdir = os.path.join(self.backup_dir, date_str)
        os.makedirs(backup_subdir, exist_ok=True)

        filename = os.path.basename(file_path)
        base_name, ext = os.path.splitext(filename)
        timestamp = datetime.now().strftime("%H%M%S")
        backup_filename = f"{base_name}_{timestamp}{ext}"
        backup_path = os.path.join(backup_subdir, backup_filename)

        shutil.copy2(file_path, backup_path)

        record = BackupRecord(
            original_path=file_path,
            backup_path=backup_path,
            timestamp=datetime.now().isoformat(),
            file_hash=file_hash
        )

        backup_id = f"backup_{len(self._backups) + 1}"
        self._backups[backup_id] = asdict(record)
        self._save_json(self._backups, self._backup_log_path)

        return backup_path

    def archive_by_date(self, source_dir: str, date_str: str = None) -> str:
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")

        archive_subdir = os.path.join(self.archive_dir, date_str)
        os.makedirs(archive_subdir, exist_ok=True)

        items = os.listdir(source_dir)
        for item in items:
            src = os.path.join(source_dir, item)
            dst = os.path.join(archive_subdir, item)

            if os.path.exists(dst):
                base, ext = os.path.splitext(dst)
                counter = 1
                while os.path.exists(f"{base}_{counter}{ext}"):
                    counter += 1
                dst = f"{base}_{counter}{ext}"

            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)

        archive_record = {
            "source_dir": source_dir,
            "archive_dir": archive_subdir,
            "timestamp": datetime.now().isoformat(),
            "items_count": len(items)
        }

        archive_log_path = os.path.join(self.log_dir, "archives.json")
        archives = self._load_json(archive_log_path)
        archive_id = f"archive_{len(archives) + 1}"
        archives[archive_id] = archive_record
        self._save_json(archives, archive_log_path)

        return archive_subdir

    def get_statistics(self) -> Dict[str, Any]:
        total_tasks = len(self._tasks)
        by_status = defaultdict(int)
        for task in self._tasks.values():
            by_status[task["status"]] += 1

        total_duration = sum(t.get("duration_ms", 0) for t in self._tasks.values())
        avg_duration = total_duration / total_tasks if total_tasks > 0 else 0

        return {
            "total_tasks": total_tasks,
            "by_status": dict(by_status),
            "failed_tasks": len(self._failed),
            "total_backups": len(self._backups),
            "avg_duration_ms": avg_duration,
            "total_duration_ms": total_duration
        }

    def generate_summary_report(self, output_path: str = None) -> str:
        stats = self.get_statistics()

        report = "# 任务处理报告\n\n"
        report += f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        report += "## 统计概览\n\n"
        report += f"- 总任务数: {stats['total_tasks']}\n"
        report += f"- 成功: {stats['by_status'].get('success', 0)}\n"
        report += f"- 失败: {stats['by_status'].get('failed', 0)}\n"
        report += f"- 失败待重跑: {stats['failed_tasks']}\n"
        report += f"- 备份文件数: {stats['total_backups']}\n"
        report += f"- 平均处理时长: {stats['avg_duration_ms']:.0f}ms\n\n"

        if self._failed:
            report += "## 失败任务列表\n\n"
            for task_id, task in self._failed.items():
                report += f"### {task_id}\n"
                report += f"- 文件: {task['input_file']}\n"
                report += f"- 错误: {task['error_message']}\n"
                report += f"- 时间: {task['timestamp']}\n\n"

        if output_path is None:
            output_path = os.path.join(self.log_dir, f"report_{datetime.now().strftime('%Y%m%d')}.md")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)

        return output_path
