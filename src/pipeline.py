import os
import time
from datetime import datetime
from typing import Dict, Any, List, Callable
from tqdm import tqdm

from .config import Config
from .importer import MaterialImporter
from .size_adapter import SizeAdapter
from .quality_checker import QualityChecker
from .tag_organizer import TagOrganizer
from .packager import Packager
from .task_logger import TaskLogger


class WallpaperPipeline:
    def __init__(self, config_path: str = None):
        self.config = Config(config_path)
        self.importer = MaterialImporter(self.config)
        self.size_adapter = SizeAdapter(self.config)
        self.quality_checker = QualityChecker(self.config)
        self.tag_organizer = TagOrganizer(self.config)
        self.packager = Packager(self.config)
        self.task_logger = TaskLogger(self.config)

        self.input_dir = self.config.get_path("input_dir")
        self.output_dir = self.config.get_path("output_dir")

        os.makedirs(self.input_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

    def _clean_output_dir(self, output_dir: str) -> None:
        for category in ["mobile", "desktop", "tablet", "previews"]:
            cat_dir = os.path.join(output_dir, category)
            if os.path.exists(cat_dir):
                import shutil
                shutil.rmtree(cat_dir)

    def run(self, input_dir: str = None, output_dir: str = None,
            date_str: str = None, skip_quality_check: bool = False) -> Dict[str, Any]:
        if input_dir is None:
            input_dir = self.input_dir
        if output_dir is None:
            output_dir = self.output_dir
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")

        print(f"{'='*60}")
        print(f"壁纸自动化处理工具 - {date_str}")
        print(f"{'='*60}")

        overall_start = time.time()

        self._clean_output_dir(output_dir)

        print("\n[1/7] 导入素材...")
        materials = self.importer.import_materials(input_dir)
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

        passed_materials = materials
        quality_reports = {}
        duplicates = []

        if not skip_quality_check:
            print("\n[2/7] 质量检查...")
            quality_reports = self.quality_checker.check_batch(materials)
            duplicates = self.quality_checker.detect_duplicates(quality_reports)
            passed_materials, failed_materials = self.quality_checker.filter_passed(materials, quality_reports)

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

            for m in failed_materials:
                report = quality_reports.get(m.file_path)
                if report:
                    for issue in report.issues:
                        print(f"    [FAILED] {m.filename}: {issue.details}")

        if not passed_materials:
            print("没有通过质量检查的图片，任务结束。")
            return {"status": "all_failed"}

        print("\n[3/7] 标签整理...")
        self.tag_organizer.process_batch(passed_materials)
        tag_summary = self.tag_organizer.generate_tag_summary(passed_materials)
        print(f"  主题分布:")
        for theme, count in sorted(tag_summary['by_theme'].items()):
            print(f"    - {theme.capitalize()}: {count}")

        print(f"\n[4/7] 尺寸适配...")
        resized_results = {}
        preview_paths = {}

        for material in tqdm(passed_materials, desc="  处理中", unit="张"):
            task_id = self.task_logger.log_start(
                material.file_path,
                {"filename": material.filename, "theme": material.theme}
            )
            start_time = time.time()

            try:
                resized = self.size_adapter.process_material(material, output_dir)
                preview = self.size_adapter.generate_thumbnail(material, output_dir)
                resized_results[material.filename] = resized
                preview_paths[material.filename] = preview

                output_files = [r.output_path for r in resized] + [preview]
                duration_ms = int((time.time() - start_time) * 1000)
                self.task_logger.log_success(
                    task_id, output_files, duration_ms,
                    {"resolutions_count": len(resized), "theme": material.theme}
                )
            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                self.task_logger.log_failure(task_id, e, duration_ms)
                print(f"  [ERROR] {material.filename}: {e}")

        total_resized = sum(len(v) for v in resized_results.values())
        print(f"  生成 {total_resized} 张适配图片")
        print(f"  生成 {len(preview_paths)} 张预览图")

        print("\n[5/7] 打包输出...")
        package_info = self.packager.create_package(
            passed_materials, resized_results, preview_paths, output_dir, date_str
        )
        gallery_path = self.packager.generate_html_gallery(
            passed_materials, preview_paths, output_dir, date_str
        )
        print(f"  打包目录: {package_info['package_dir']}")
        print(f"  ZIP压缩包: {package_info['zip_path']}")
        print(f"  发布说明: {package_info['release_notes']}")
        print(f"  社交文案: {package_info['social_post']}")
        print(f"  HTML画廊: {gallery_path}")

        print("\n[6/7] 归档...")
        archive_dir = self.task_logger.archive_by_date(output_dir, date_str)
        print(f"  归档目录: {archive_dir}")

        print("\n[7/7] 生成报告...")
        report_path = self.task_logger.generate_summary_report()
        logger_stats = self.task_logger.get_statistics()
        print(f"  任务报告: {report_path}")
        print(f"  成功率: {logger_stats['by_status'].get('success', 0)}/{logger_stats['total_tasks']}")

        total_duration = time.time() - overall_start
        print(f"\n{'='*60}")
        print(f"处理完成! 总耗时: {total_duration:.1f} 秒")
        print(f"{'='*60}")

        return {
            "status": "success",
            "date_str": date_str,
            "total_materials": len(materials),
            "passed_materials": len(passed_materials),
            "total_resolutions": total_resized,
            "package_info": package_info,
            "gallery_path": gallery_path,
            "archive_dir": archive_dir,
            "report_path": report_path,
            "quality_reports": quality_reports,
            "duplicates": duplicates,
            "duration_seconds": total_duration
        }

    def retry_failed(self, processor: Callable[[str], Any] = None) -> Dict[str, Any]:
        print("正在重跑失败任务...")

        def default_processor(input_file: str):
            materials = self.importer.import_materials(os.path.dirname(input_file))
            materials = [m for m in materials if m.file_path == input_file]
            if not materials:
                raise ValueError(f"Material not found: {input_file}")

            material = materials[0]
            self.tag_organizer.process_material(material)
            resized = self.size_adapter.process_material(material, self.output_dir)
            preview = self.size_adapter.generate_thumbnail(material, self.output_dir)
            return [r.output_path for r in resized] + [preview]

        if processor is None:
            processor = default_processor

        results = self.task_logger.retry_all_failed(processor)
        print(f"重跑完成: 成功 {len(results['success'])} 个, 失败 {len(results['failed'])} 个")
        return results
