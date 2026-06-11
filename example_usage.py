#!/usr/bin/env python3
import os
import sys
from PIL import Image
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.pipeline import WallpaperPipeline
from src.importer import MaterialImporter
from src.quality_checker import QualityChecker
from src.tag_organizer import TagOrganizer
from src.size_adapter import SizeAdapter
from src.packager import Packager
from src.task_logger import TaskLogger
from src.config import Config


def generate_test_images(output_dir: str, count: int = 5):
    os.makedirs(output_dir, exist_ok=True)

    themes = ["nature_mountain", "city_night", "abstract_gradient",
              "minimal_clean", "dark_tech", "light_bright"]
    colors = [
        [(255, 100, 100), (100, 200, 255)],
        [(50, 50, 80), (200, 100, 50)],
        [(100, 200, 150), (150, 100, 200)],
        [(240, 240, 245), (200, 200, 210)],
        [(20, 20, 30), (80, 50, 150)],
        [(255, 250, 240), (250, 230, 200)],
    ]

    for i in range(count):
        theme = themes[i % len(themes)]

        landscape_img = create_gradient_image(3840, 2160, colors[i % len(colors)])
        landscape_path = os.path.join(output_dir, f"{theme}_{i:03d}_landscape.jpg")
        landscape_img.save(landscape_path, "JPEG", quality=95)

        portrait_img = create_gradient_image(2556, 1179, colors[(i + 2) % len(colors)])
        portrait_path = os.path.join(output_dir, f"{theme}_{i:03d}_portrait.jpg")
        portrait_img.save(portrait_path, "JPEG", quality=95)

        print(f"  生成测试图片: {os.path.basename(landscape_path)}")
        print(f"  生成测试图片: {os.path.basename(portrait_path)}")


def create_gradient_image(width: int, height: int, colors) -> Image.Image:
    img = Image.new("RGB", (width, height))
    pixels = img.load()

    for y in range(height):
        ratio = y / height
        r = int(colors[0][0] * (1 - ratio) + colors[1][0] * ratio)
        g = int(colors[0][1] * (1 - ratio) + colors[1][1] * ratio)
        b = int(colors[0][2] * (1 - ratio) + colors[1][2] * ratio)

        for x in range(width):
            noise = np.random.randint(-10, 11)
            pixels[x, y] = (
                max(0, min(255, r + noise)),
                max(0, min(255, g + noise)),
                max(0, min(255, b + noise))
            )

    return img


def run_module_demo():
    print("=" * 60)
    print("模块功能演示")
    print("=" * 60)

    test_dir = "./test_input"
    print("\n1. 生成测试图片...")
    generate_test_images(test_dir, count=3)

    config = Config()

    print("\n2. 素材导入演示 (MaterialImporter)...")
    importer = MaterialImporter(config)
    materials = importer.import_materials(test_dir)
    stats = importer.get_statistics(materials)
    print(f"  导入 {stats['total']} 张图片")
    print(f"  横屏: {stats['by_orientation'].get('landscape', 0)}  "
          f"竖屏: {stats['by_orientation'].get('portrait', 0)}")

    if materials:
        m = materials[0]
        print(f"\n  第一张图片信息:")
        print(f"    文件名: {m.filename}")
        print(f"    分辨率: {m.width}x{m.height}")
        print(f"    方向: {m.orientation}")
        print(f"    大小: {m.size_bytes // 1024} KB")

    print("\n3. 质量检查演示 (QualityChecker)...")
    checker = QualityChecker(config)
    reports = checker.check_batch(materials)
    qc_stats = checker.get_statistics(reports)
    print(f"  通过: {qc_stats['passed']}, 失败: {qc_stats['failed']}")
    print(f"  平均模糊度: {qc_stats['avg_blur_score']:.1f}")

    duplicates = checker.detect_duplicates(reports)
    print(f"  重复图片: {len(duplicates)} 组")

    passed, failed = checker.filter_passed(materials, reports)
    print(f"  通过质量检查: {len(passed)} 张")

    print("\n4. 标签整理演示 (TagOrganizer)...")
    organizer = TagOrganizer(config)
    organizer.process_batch(passed)

    if passed:
        m = passed[0]
        print(f"  {m.filename}:")
        print(f"    主题: {m.theme}")
        print(f"    作者: {m.author}")
        print(f"    标签: {', '.join(m.tags)}")

    tag_summary = organizer.generate_tag_summary(passed)
    print(f"\n  主题分布:")
    for theme, count in tag_summary['by_theme'].items():
        print(f"    {theme}: {count}")

    print("\n5. 尺寸适配演示 (SizeAdapter)...")
    adapter = SizeAdapter(config)
    output_dir = "./test_output"
    os.makedirs(output_dir, exist_ok=True)

    if passed:
        m = passed[0]
        try:
            resized = adapter.process_material(m, output_dir)
            preview = adapter.generate_thumbnail(m, output_dir)
            print(f"  为 {m.filename} 生成 {len(resized)} 张适配图片")
            for r in resized[:2]:
                print(f"    - {r.device_name}: {r.width}x{r.height} -> {os.path.basename(r.output_path)}")
            print(f"  预览图: {os.path.basename(preview)}")
        except Exception as e:
            print(f"  处理出错: {e}")

    print("\n6. 任务日志演示 (TaskLogger)...")
    logger = TaskLogger(config)

    if passed:
        m = passed[0]
        backup_path = logger.backup_original(m.file_path)
        print(f"  备份文件: {os.path.basename(backup_path)}")

        task_id = logger.log_start(m.file_path, {"test": True})
        print(f"  任务ID: {task_id}")

        logger.log_success(task_id, ["output1.jpg", "output2.jpg"], duration_ms=1500)
        print(f"  任务已标记为成功")

    logger_stats = logger.get_statistics()
    print(f"\n  总任务数: {logger_stats['total_tasks']}")
    print(f"  备份数: {logger_stats['total_backups']}")

    print("\n7. 打包输出演示 (Packager)...")
    packager = Packager(config)

    resized_results = {}
    preview_paths = {}
    for m in passed:
        try:
            resized = adapter.process_material(m, output_dir)
            preview = adapter.generate_thumbnail(m, output_dir)
            resized_results[m.filename] = resized
            preview_paths[m.filename] = preview
        except Exception:
            pass

    package_info = packager.create_package(
        passed, resized_results, preview_paths, output_dir, "2026-06-11"
    )
    print(f"  打包目录: {os.path.basename(package_info['package_dir'])}")
    print(f"  ZIP包: {os.path.basename(package_info['zip_path'])}")
    print(f"  发布说明: {os.path.basename(package_info['release_notes'])}")

    gallery_path = packager.generate_html_gallery(
        passed, preview_paths, output_dir, "2026-06-11"
    )
    print(f"  HTML画廊: {os.path.basename(gallery_path)}")

    print("\n" + "=" * 60)
    print("模块演示完成!")
    print("=" * 60)
    print("\n要运行完整的处理流程, 请执行:")
    print("  python main.py run")
    print("\n或查看帮助:")
    print("  python main.py --help")


def run_full_pipeline_demo():
    print("=" * 60)
    print("完整流水线演示")
    print("=" * 60)

    test_input = "./demo_input"
    test_output = "./demo_output"

    print(f"\n生成测试图片到 {test_input}...")
    generate_test_images(test_input, count=3)

    print(f"\n启动完整处理流程...")
    pipeline = WallpaperPipeline()
    result = pipeline.run(
        input_dir=test_input,
        output_dir=test_output,
        date_str="2026-06-11"
    )

    if result.get("status") == "success":
        print("\n演示成功! 你可以查看生成的文件:")
        print(f"  壁纸包: {result['package_info']['package_dir']}")
        print(f"  HTML画廊: {result['gallery_path']}")
        print(f"  发布说明: {result['package_info']['release_notes']}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="壁纸工具演示脚本")
    parser.add_argument("--demo", choices=["modules", "pipeline"],
                       default="modules", help="演示类型: modules(模块演示) 或 pipeline(完整流水线)")

    args = parser.parse_args()

    if args.demo == "modules":
        run_module_demo()
    else:
        run_full_pipeline_demo()
