#!/usr/bin/env python3
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.pipeline import WallpaperPipeline
from src.task_logger import STAGE_NAMES, STATUS_SUCCESS, STATUS_FAILED


def main():
    parser = argparse.ArgumentParser(
        description="壁纸自动化工具 - 批量生成每日壁纸包和发布清单",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s run -i ./my_images -d 2026-06-11
  %(prog)s run --skip-quality-check
  %(prog)s retry --task task_20260611_120000_000
  %(prog)s retry --all
  %(prog)s list-failed
  %(prog)s task-info task_20260611_120000_000
  %(prog)s stats
  %(prog)s manifest -d 2026-06-11
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    run_parser = subparsers.add_parser("run", help="运行完整处理流程")
    run_parser.add_argument("-i", "--input", type=str, help="输入文件夹路径")
    run_parser.add_argument("-o", "--output", type=str, help="输出文件夹路径")
    run_parser.add_argument("-d", "--date", type=str, help="处理日期 (YYYY-MM-DD)")
    run_parser.add_argument("-c", "--config", type=str, help="配置文件路径")
    run_parser.add_argument("--skip-quality-check", action="store_true", help="跳过质量检查")

    retry_parser = subparsers.add_parser("retry", help="重跑失败任务")
    retry_parser.add_argument("--task", type=str, help="指定要重跑的任务ID")
    retry_parser.add_argument("--all", action="store_true", help="重跑所有失败任务")
    retry_parser.add_argument("-d", "--date", type=str, help="日期 (YYYY-MM-DD)")
    retry_parser.add_argument("-c", "--config", type=str, help="配置文件路径")

    list_parser = subparsers.add_parser("list-failed", help="列出所有失败任务")
    list_parser.add_argument("-d", "--date", type=str, help="日期 (YYYY-MM-DD)")
    list_parser.add_argument("-c", "--config", type=str, help="配置文件路径")

    task_info_parser = subparsers.add_parser("task-info", help="查看任务详情")
    task_info_parser.add_argument("task_id", type=str, help="任务ID")
    task_info_parser.add_argument("-d", "--date", type=str, help="日期 (YYYY-MM-DD)")
    task_info_parser.add_argument("-c", "--config", type=str, help="配置文件路径")

    stats_parser = subparsers.add_parser("stats", help="查看统计信息")
    stats_parser.add_argument("-d", "--date", type=str, help="日期 (YYYY-MM-DD)")
    stats_parser.add_argument("-c", "--config", type=str, help="配置文件路径")

    manifest_parser = subparsers.add_parser("manifest", help="重新生成发布清单")
    manifest_parser.add_argument("-d", "--date", type=str, help="日期 (YYYY-MM-DD)")
    manifest_parser.add_argument("-c", "--config", type=str, help="配置文件路径")
    manifest_parser.add_argument("-o", "--output", type=str, help="输出文件路径")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    if args.command == "run":
        pipeline = WallpaperPipeline(args.config, date_str=args.date)
        result = pipeline.run(
            input_dir=args.input,
            output_dir=args.output,
            date_str=args.date,
            skip_quality_check=args.skip_quality_check
        )
        print_result(result)

    elif args.command == "retry":
        pipeline = WallpaperPipeline(args.config, date_str=args.date)

        if args.task:
            print(f"正在重跑任务: {args.task}")
            result = pipeline.retry_task(args.task)
            if result:
                print(f"重跑完成! 任务状态: {result.overall_status}")
                print(f"当前阶段: {STAGE_NAMES.get(result.current_stage, result.current_stage)}")
            else:
                print(f"重跑失败，任务 {args.task} 不存在或无法处理")

        elif args.all:
            results = pipeline.retry_all_failed()
            print(f"\n重跑结果:")
            print(f"  成功: {len(results['success'])} 个任务")
            print(f"  失败: {len(results['failed'])} 个任务")
            if results['failed']:
                for fail in results['failed']:
                    if isinstance(fail, dict):
                        print(f"    - {fail['task_id']}: {fail['error']}")
                    else:
                        print(f"    - {fail}")

        else:
            print("请指定 --task <task_id> 或 --all")

    elif args.command == "list-failed":
        pipeline = WallpaperPipeline(args.config, date_str=args.date)
        failed = pipeline.list_failed_tasks()

        if not failed:
            print("没有失败的任务 ✅")
        else:
            print(f"共 {len(failed)} 个失败任务:\n")
            for i, task in enumerate(failed, 1):
                stage_cn = STAGE_NAMES.get(task['failed_stage'], task['failed_stage'])
                print(f"  [{i}] {task['task_id']}")
                print(f"      文件: {task['filename']}")
                print(f"      失败阶段: {stage_cn}")
                print(f"      错误: {task['error']}")
                print()

    elif args.command == "task-info":
        pipeline = WallpaperPipeline(args.config, date_str=args.date)
        info = pipeline.get_task_info(args.task_id)

        if not info:
            print(f"任务 {args.task_id} 不存在")
            return

        print(f"任务ID: {info['task_id']}")
        print(f"文件名: {info['filename']}")
        print(f"状态: {info['status']}")
        print(f"当前阶段: {STAGE_NAMES.get(info['current_stage'], info['current_stage'])}")
        print(f"创建时间: {info['created_at']}")
        print()
        print("各阶段详情:")
        for stage_name, stage_info in info['stages'].items():
            status_icon = {
                "success": "✅",
                "failed": "❌",
                "running": "🔄",
                "pending": "⏳",
                "skipped": "⏭️",
            }.get(stage_info['status'], "❓")

            print(f"  {status_icon} {stage_name}")
            print(f"     状态: {stage_info['status']}")
            print(f"     耗时: {stage_info['duration_ms']}ms")
            if stage_info['error']:
                print(f"     错误: {stage_info['error']}")
            if stage_info['output_count']:
                print(f"     输出文件: {stage_info['output_count']} 个")

    elif args.command == "stats":
        pipeline = WallpaperPipeline(args.config, date_str=args.date)
        stats = pipeline.task_logger.get_statistics()

        print("\n📊 处理统计")
        print("=" * 40)
        print(f"  总任务数: {stats['total_tasks']}")
        print(f"  成功: {stats['by_status'].get(STATUS_SUCCESS, 0)}")
        print(f"  失败: {stats['by_status'].get(STATUS_FAILED, 0)}")
        print(f"  待重跑: {stats['failed_tasks']}")
        print(f"  备份文件: {stats['total_backups']}")
        print(f"  总耗时: {stats['total_duration_ms']/1000:.1f} 秒")
        print(f"  平均耗时: {stats['avg_duration_ms']:.0f}ms")

        print("\n📋 各阶段状态:")
        for stage, count in stats.get('by_stage', {}).items():
            stage_cn = STAGE_NAMES.get(stage, stage)
            print(f"  {stage_cn}: {count}")

    elif args.command == "manifest":
        print("重新生成发布清单功能需要先运行处理流程")
        print("使用 'python main.py run' 生成完整的壁纸包和清单")


def print_result(result):
    if result.get("status") == "success":
        print("\n" + "=" * 60)
        print("✅ 处理完成! 输出文件:")
        print("=" * 60)
        print(f"  输出目录:   {result['output_dir']}")
        print(f"  壁纸包目录: {result['package_info']['package_dir']}")
        print(f"  ZIP压缩包: {result['package_info']['zip_path']}")
        print(f"  发布说明: {result['package_info']['release_notes']}")
        print(f"  社交文案: {result['package_info']['social_post']}")
        print(f"  HTML画廊: {result['gallery_path']}")
        print(f"  发布清单: {result['manifest_csv']}")
        print(f"  任务报告: {result['report_path']}")
        print("=" * 60)
        print(f"共处理 {result['total_materials']} 张图片")
        print(f"通过 {result['passed_materials']} 张, 失败 {result['failed_materials']} 张")
        print(f"生成 {result['total_resolutions']} 张适配壁纸")
        if result.get('duplicate_groups', 0) > 0:
            print(f"发现 {result['duplicate_groups']} 组重复素材")
        print(f"总耗时: {result['duration_seconds']:.1f} 秒")
    elif result.get("status") == "no_materials":
        print("\n❌ 错误: 输入目录中没有找到可处理的图片文件。")
        print("请将图片放入 input 目录, 或使用 -i 参数指定其他目录。")
    elif result.get("status") == "all_failed":
        print("\n❌ 错误: 所有图片均未通过质量检查。")
        print("可使用 --skip-quality-check 参数跳过质量检查, 或调整配置文件中的阈值。")


if __name__ == "__main__":
    main()
