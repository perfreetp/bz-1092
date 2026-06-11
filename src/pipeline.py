import os
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
from tqdm import tqdm

from .config import Config
from .importer import MaterialImporter, Material
from .size_adapter import SizeAdapter
from .quality_checker import QualityChecker
from .tag_organizer import TagOrganizer
from .packager import Packager
from .task_logger import (
    TaskLogger, TaskRecord,
    STAGE_IMPORT, STAGE_QUALITY, STAGE_TAG, STAGE_RESIZE, STAGE_PACKAGE,
    STATUS_SUCCESS, STATUS_FAILED, STATUS_SKIPPED,
    STAGE_NAMES
)


class WallpaperPipeline:
    def __init__(self, config_path: str = None, date_str: str = None):
        self.config = Config(config_path)
        self.date_str = date_str or datetime.now().strftime("%Y-%m-%d")

        self.importer = MaterialImporter(self.config)
        self.size_adapter = SizeAdapter(self.config)
        self.quality_checker = QualityChecker(self.config)
        self.tag_organizer = TagOrganizer(self.config)
        self.packager = Packager(self.config)
        self.task_logger = TaskLogger(self.config, date_str=self.date_str)

        self.input_dir = self.config.get_path("input_dir")
        self.base_output_dir = self.config.get_path("output_dir")
        self.output_dir = os.path.join(self.base_output_dir, self.date_str)

        os.makedirs(self.input_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

    def _process_single_material(self, input_file: str, task_id: str) -> Optional[Material]:
        task = self.task_logger.get_task(task_id)
        if not task:
            return None

        try:
            self.task_logger.start_stage(task_id, STAGE_IMPORT)
            materials = self.importer.import_materials(os.path.dirname(input_file))
            material = None
            for m in materials:
                if m.file_path == input_file:
                    material = m
                    break

            if not material:
                raise ValueError(f"Material not found: {input_file}")

            self.task_logger.finish_stage(
                task_id, STAGE_IMPORT,
                output_files=[material.file_path],
                metadata={
                    "width": material.width,
                    "height": material.height,
                    "orientation": material.orientation,
                    "format": material.format,
                    "size_bytes": material.size_bytes
                }
            )

            self.task_logger.start_stage(task_id, STAGE_QUALITY)
            report = self.quality_checker.check_material(material)
            if not report.passed:
                issues = [i.issue_type for i in report.issues]
                raise ValueError(f"质量检查未通过: {', '.join(issues)}")

            self.task_logger.finish_stage(
                task_id, STAGE_QUALITY,
                metadata={
                    "blur_score": report.blur_score,
                    "phash": report.phash,
                    "passed": report.passed,
                    "issues": [i.issue_type for i in report.issues]
                }
            )

            self.task_logger.start_stage(task_id, STAGE_TAG)
            self.tag_organizer.process_material(material)
            self.task_logger.finish_stage(
                task_id, STAGE_TAG,
                metadata={
                    "theme": material.theme,
                    "tags": material.tags,
                    "author": material.author
                }
            )

            self.task_logger.start_stage(task_id, STAGE_RESIZE)
            resized = self.size_adapter.process_material(material, self.output_dir)
            preview = self.size_adapter.generate_thumbnail(material, self.output_dir)
            output_files = [r.output_path for r in resized] + [preview]
            self.task_logger.finish_stage(
                task_id, STAGE_RESIZE,
                output_files=output_files,
                metadata={
                    "resolutions_count": len(resized),
                    "devices": [r.device_name for r in resized]
                }
            )

            self.task_logger.start_stage(task_id, STAGE_PACKAGE)
            self.task_logger.finish_stage(
                task_id, STAGE_PACKAGE,
                metadata={"packaged": True}
            )

            return material

        except Exception as e:
            current_stage = task.current_stage if task else STAGE_IMPORT
            self.task_logger.fail_stage(task_id, current_stage, e)
            raise

    def run(self, input_dir: str = None, output_dir: str = None,
            date_str: str = None, skip_quality_check: bool = False) -> Dict[str, Any]:
        if input_dir is not None:
            self.input_dir = input_dir
        if date_str is not None:
            self.date_str = date_str
            self.output_dir = os.path.join(self.base_output_dir, date_str)
            self.task_logger = TaskLogger(self.config, date_str=date_str)
        if output_dir is not None:
            self.output_dir = output_dir

        os.makedirs(self.output_dir, exist_ok=True)

        print(f"{'='*60}")
        print(f"壁纸自动化处理工具 - {self.date_str}")
        print(f"输出目录: {self.output_dir}")
        print(f"{'='*60}")

        overall_start = time.time()

        print("\n[1/7] 导入素材并创建任务...")
        materials = self.importer.import_materials(self.input_dir)
        stats = self.importer.get_statistics(materials)
        print(f"  共导入 {stats['total']} 张图片")
        print(f"  横屏: {stats['by_orientation'].get('landscape', 0)}  "
              f"竖屏: {stats['by_orientation'].get('portrait', 0)}  "
              f"方形: {stats['by_orientation'].get('square', 0)}")

        if not materials:
            print("没有找到可处理的图片，任务结束。")
            return {"status": "no_materials"}

        for m in materials:
            self.task_logger.backup_original(m.file_path)
            task_id = self.task_logger.create_task(
                m.file_path,
                metadata={"filename": m.filename}
            )
            m.metadata["task_id"] = task_id

            self.task_logger.start_stage(task_id, STAGE_IMPORT)
            self.task_logger.finish_stage(
                task_id, STAGE_IMPORT,
                output_files=[m.file_path],
                metadata={
                    "width": m.width,
                    "height": m.height,
                    "orientation": m.orientation,
                    "format": m.format,
                    "size_bytes": m.size_bytes
                }
            )

        print(f"  创建 {len(materials)} 个处理任务")

        quality_reports = {}
        duplicates = []
        passed_materials = materials

        if not skip_quality_check:
            print("\n[2/7] 质量检查...")
            quality_reports = self.quality_checker.check_batch(materials)
            duplicates = self.quality_checker.detect_duplicates(quality_reports)
            passed_materials, failed_materials = self.quality_checker.filter_passed(
                materials, quality_reports
            )

            for m in materials:
                task_id = m.metadata.get("task_id", "")
                if task_id:
                    report = quality_reports.get(m.file_path)
                    if report:
                        self.task_logger.start_stage(task_id, STAGE_QUALITY)
                        if report.passed:
                            self.task_logger.finish_stage(
                                task_id, STAGE_QUALITY,
                                metadata={
                                    "blur_score": report.blur_score,
                                    "phash": report.phash,
                                    "passed": True,
                                    "issues": [i.issue_type for i in report.issues]
                                }
                            )
                        else:
                            err = ValueError(f"质量检查未通过: {', '.join([i.issue_type for i in report.issues])}")
                            self.task_logger.fail_stage(task_id, STAGE_QUALITY, err)

            qc_stats = self.quality_checker.get_statistics(quality_reports)
            print(f"  通过: {qc_stats['passed']}  "
                  f"失败: {qc_stats['failed']}  "
                  f"通过率: {qc_stats['pass_rate']*100:.1f}%")
            print(f"  平均模糊度: {qc_stats['avg_blur_score']:.1f}")

            if qc_stats['by_issue']:
                print(f"  问题分布:")
                for issue, count in qc_stats['by_issue'].items():
                    print(f"    - {issue}: {count}")

            if duplicates:
                print(f"  发现 {len(duplicates)} 组相似图片")
                for dup in duplicates[:3]:
                    f1 = os.path.basename(dup['file1'])
                    f2 = os.path.basename(dup['file2'])
                    print(f"    - {f1} ↔ {f2} (相似度: {dup['similarity']:.1f}%)")

        if not passed_materials:
            print("没有通过质量检查的图片，任务结束。")
            return {"status": "all_failed"}

        print("\n[3/7] 标签整理...")
        for m in passed_materials:
            task_id = m.metadata.get("task_id", "")
            if task_id:
                self.task_logger.start_stage(task_id, STAGE_TAG)

        self.tag_organizer.process_batch(passed_materials)

        for m in passed_materials:
            task_id = m.metadata.get("task_id", "")
            if task_id:
                self.task_logger.finish_stage(
                    task_id, STAGE_TAG,
                    metadata={
                        "theme": m.theme,
                        "tags": m.tags,
                        "author": m.author
                    }
                )

        tag_summary = self.tag_organizer.generate_tag_summary(passed_materials)
        print(f"  主题分布:")
        for theme, count in sorted(tag_summary['by_theme'].items()):
            print(f"    - {theme.capitalize()}: {count}")

        print(f"\n[4/7] 尺寸适配...")
        resized_results = {}
        preview_paths = {}

        for material in tqdm(passed_materials, desc="  处理中", unit="张"):
            task_id = material.metadata.get("task_id", "")

            try:
                if task_id:
                    self.task_logger.start_stage(task_id, STAGE_RESIZE)

                resized = self.size_adapter.process_material(material, self.output_dir)
                preview = self.size_adapter.generate_thumbnail(material, self.output_dir)
                resized_results[material.filename] = resized
                preview_paths[material.filename] = preview

                output_files = [r.output_path for r in resized] + [preview]
                if task_id:
                    self.task_logger.start_stage(task_id, STAGE_PACKAGE)
                    self.task_logger.finish_stage(
                        task_id, STAGE_RESIZE,
                        output_files=output_files,
                        metadata={
                            "resolutions_count": len(resized),
                            "devices": [r.device_name for r in resized]
                        }
                    )
                    self.task_logger.finish_stage(
                        task_id, STAGE_PACKAGE,
                        metadata={"packaged": True}
                    )
            except Exception as e:
                if task_id:
                    current_stage = STAGE_RESIZE
                    self.task_logger.fail_stage(task_id, current_stage, e)
                print(f"  [ERROR] {material.filename}: {e}")

        total_resized = sum(len(v) for v in resized_results.values())
        print(f"  生成 {total_resized} 张适配图片")
        print(f"  生成 {len(preview_paths)} 张预览图")

        print("\n[5/7] 打包输出...")
        package_info = self.packager.create_package(
            passed_materials, resized_results, preview_paths,
            self.output_dir, self.date_str,
            duplicates=duplicates,
            quality_reports=quality_reports
        )
        gallery_path = self.packager.generate_html_gallery(
            passed_materials, preview_paths,
            self.output_dir, self.date_str
        )
        print(f"  打包目录: {package_info['package_dir']}")
        print(f"  ZIP压缩包: {package_info['zip_path']}")
        print(f"  发布说明: {package_info['release_notes']}")
        print(f"  社交文案: {package_info['social_post']}")
        print(f"  HTML画廊: {gallery_path}")

        print("\n[6/7] 生成发布清单...")
        manifest_csv = self.task_logger.export_manifest_csv(
            passed_materials, quality_reports,
            resized_results, package_info,
            duplicates=duplicates
        )
        print(f"  发布清单: {manifest_csv}")

        print("\n[7/7] 生成报告...")
        report_path = self.task_logger.generate_summary_report(
            materials=passed_materials,
            quality_reports=quality_reports,
            duplicates=duplicates
        )
        logger_stats = self.task_logger.get_statistics()
        print(f"  任务报告: {report_path}")
        print(f"  成功率: {logger_stats['by_status'].get(STATUS_SUCCESS, 0)}/{logger_stats['total_tasks']}")

        total_duration = time.time() - overall_start
        print(f"\n{'='*60}")
        print(f"处理完成! 总耗时: {total_duration:.1f} 秒")
        print(f"{'='*60}")

        return {
            "status": "success",
            "date_str": self.date_str,
            "output_dir": self.output_dir,
            "total_materials": len(materials),
            "passed_materials": len(passed_materials),
            "failed_materials": len(materials) - len(passed_materials),
            "total_resolutions": total_resized,
            "duplicate_groups": len(duplicates),
            "package_info": package_info,
            "gallery_path": gallery_path,
            "manifest_csv": manifest_csv,
            "report_path": report_path,
            "quality_reports": quality_reports,
            "duplicates": duplicates,
            "duration_seconds": total_duration
        }

    def retry_task(self, task_id: str) -> Optional[TaskRecord]:
        return self.task_logger.retry_task(task_id, self)

    def retry_all_failed(self) -> Dict[str, Any]:
        print(f"正在重跑 {len(self.task_logger.get_failed_tasks())} 个失败任务...")
        results = self.task_logger.retry_all_failed(self)
        print(f"重跑完成: 成功 {len(results['success'])} 个, 失败 {len(results['failed'])} 个")
        return results

    def get_task_info(self, task_id: str) -> Optional[Dict[str, Any]]:
        task = self.task_logger.get_task(task_id)
        if not task:
            return None

        info = {
            "task_id": task.task_id,
            "filename": task.filename,
            "input_file": task.input_file,
            "status": task.overall_status,
            "current_stage": task.current_stage,
            "created_at": task.created_at,
            "stages": {}
        }

        for stage, record in task.stages.items():
            stage_cn = STAGE_NAMES.get(stage, stage)
            info["stages"][stage_cn] = {
                "status": record.status,
                "duration_ms": record.duration_ms,
                "error": record.error_message,
                "output_count": len(record.output_files)
            }

        return info

    def list_failed_tasks(self) -> List[Dict[str, Any]]:
        failed = self.task_logger.get_failed_tasks()
        result = []
        for task_id, task in failed.items():
            result.append({
                "task_id": task_id,
                "filename": task.filename,
                "failed_stage": task.current_stage,
                "error": task.stages.get(task.current_stage, None).error_message
                if task.current_stage in task.stages else ""
            })
        return result
