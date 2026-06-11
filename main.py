#!/usr/bin/env python3
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.pipeline import WallpaperPipeline


def main():
    parser = argparse.ArgumentParser(
        description="壁纸自动化工具 - 批量生成每日壁纸包和发布清单",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s run -i ./my_images -d 2026-06-11
  %(prog)s run --skip-quality-check
  %(prog)s retry
  %(prog)s stats
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    run_parser = subparsers.add_parser("run", help="运行完整处理流程")
    run_parser.add_argument("-i", "--input", type=str, help="输入文件夹路径")
    run_parser.add_argument("-o", "--output", type=str, help="输出文件夹路径")
    run_parser.add_argument("-d", "--date", type=str, help="处理日期 (YYYY-MM-DD)")
    run_parser.add_argument("-c", "--config", type=str, help="配置文件路径")
    run_parser.add_argument("--skip-quality-check", action="store_true", help="跳过质量检查")

    retry_parser = subparsers.add_parser("retry", help="重跑失败的任务")
    retry_parser.add_argument("-c", "--config", type=str, help="配置文件路径")

    stats_parser = subparsers.add_parser("stats", help="查看统计信息")
    stats_parser.add_argument("-c", "--config", type=str, help="配置文件路径")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    if args.command == "run":
        pipeline = WallpaperPipeline(args.config)
        result = pipeline.run(
            input_dir=args.input,
            output_dir=args.output,
            date_str=args.date,
            skip_quality_check=args.skip_quality_check
        )
        print_result(result)

    elif args.command == "retry":
        pipeline = WallpaperPipeline(args.config)
        results = pipeline.retry_failed()
        print(f"\n重跑结果:")
        print(f"  成功: {len(results['success'])} 个任务")
        print(f"  失败: {len(results['failed'])} 个任务")
        if results['failed']:
            for fail in results['failed']:
                print(f"    - {fail['task_id']}: {fail['error']}")

    elif args.command == "stats":
        pipeline = WallpaperPipeline(args.config)
        stats = pipeline.task_logger.get_statistics()
        print("\n统计信息:")
        print(f"  总任务数: {stats['total_tasks']}")
        print(f"  成功: {stats['by_status'].get('success', 0)}")
        print(f"  失败: {stats['by_status'].get('failed', 0)}")
        print(f"  待重跑: {stats['failed_tasks']}")
        print(f"  备份文件: {stats['total_backups']}")
        print(f"  平均耗时: {stats['avg_duration_ms']:.0f}ms")


def print_result(result):
    if result.get("status") == "success":
        print("\n" + "=" * 60)
        print("处理完成! 输出文件:")
        print("=" * 60)
        print(f"  壁纸包目录: {result['package_info']['package_dir']}")
        print(f"  ZIP压缩包:   {result['package_info']['zip_path']}")
        print(f"  发布说明:   {result['package_info']['release_notes']}")
        print(f"  社交文案:   {result['package_info']['social_post']}")
        print(f"  HTML画廊:   {result['gallery_path']}")
        print(f"  归档目录:   {result['archive_dir']}")
        print(f"  任务报告:   {result['report_path']}")
        print("=" * 60)
        print(f"共处理 {result['total_materials']} 张图片, "
              f"通过 {result['passed_materials']} 张, "
              f"生成 {result['total_resolutions']} 张适配壁纸")
        print(f"总耗时: {result['duration_seconds']:.1f} 秒")
    elif result.get("status") == "no_materials":
        print("\n错误: 输入目录中没有找到可处理的图片文件。")
        print("请将图片放入 input 目录, 或使用 -i 参数指定其他目录。")
    elif result.get("status") == "all_failed":
        print("\n错误: 所有图片均未通过质量检查。")
        print("可使用 --skip-quality-check 参数跳过质量检查, 或调整配置文件中的阈值。")


if __name__ == "__main__":
    main()
