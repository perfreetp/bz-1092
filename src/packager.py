import os
import json
import zipfile
import shutil
from datetime import datetime
from typing import List, Dict, Any
from collections import defaultdict


class Packager:
    def __init__(self, config):
        self.config = config

    def _generate_release_notes(self, materials, tag_summary: Dict[str, Any],
                                date_str: str, duplicates: List[Dict] = None,
                                quality_reports: Dict = None) -> str:
        total = tag_summary["total_materials"]
        by_theme = tag_summary["by_theme"]
        by_orientation = tag_summary["by_orientation"]

        notes = f"# 每日壁纸包 - {date_str}\n\n"
        notes += f"## 概览\n\n"
        notes += f"- 发布日期: {date_str}\n"
        notes += f"- 壁纸总数: {total} 张\n"

        if duplicates:
            notes += f"- 相似素材组: {len(duplicates)} 组 (请发布前确认保留哪张)\n"
        notes += "\n"

        if by_theme:
            notes += f"## 主题分布\n\n"
            for theme, count in sorted(by_theme.items()):
                notes += f"- {theme.capitalize()}: {count} 张\n"
            notes += "\n"

        if by_orientation:
            notes += f"## 画幅分布\n\n"
            orient_map = {"portrait": "竖屏", "landscape": "横屏", "square": "方形"}
            for orient, count in sorted(by_orientation.items()):
                orient_cn = orient_map.get(orient, orient)
                notes += f"- {orient_cn}: {count} 张\n"
            notes += "\n"

        if duplicates:
            notes += "## ⚠️ 相似素材提示\n\n"
            notes += "以下素材相似度较高，发布前请确认保留哪一张：\n\n"
            for i, dup in enumerate(duplicates, 1):
                f1 = os.path.basename(dup['file1'])
                f2 = os.path.basename(dup['file2'])
                notes += f"### 重复组 #{i} (相似度: {dup['similarity']:.1f}%)\n\n"
                notes += f"- **素材 A**: {f1}\n"
                notes += f"- **素材 B**: {f2}\n"
                if quality_reports:
                    r1 = quality_reports.get(dup['file1'])
                    r2 = quality_reports.get(dup['file2'])
                    if r1:
                        notes += f"  - 模糊分数: {r1.blur_score:.1f}\n"
                    if r2:
                        notes += f"  - 模糊分数: {r2.blur_score:.1f}\n"
                notes += "\n"

        notes += f"## 设备支持\n\n"
        notes += f"### 移动端\n"
        for device in self.config.get_device_resolutions("mobile"):
            notes += f"- {device['name']} ({device['width']}x{device['height']})\n"

        notes += f"\n### 桌面端\n"
        for device in self.config.get_device_resolutions("desktop"):
            notes += f"- {device['name']} ({device['width']}x{device['height']})\n"

        notes += f"\n### 平板端\n"
        for device in self.config.get_device_resolutions("tablet"):
            notes += f"- {device['name']} ({device['width']}x{device['height']})\n"

        notes += "\n## 壁纸清单\n\n"

        theme_groups = defaultdict(list)
        for m in materials:
            theme_groups[m.theme].append(m)

        for theme, items in sorted(theme_groups.items()):
            notes += f"### {theme.capitalize()}\n\n"
            for m in sorted(items, key=lambda x: x.filename):
                tags_str = ", ".join(m.tags) if m.tags else "无"
                notes += f"- **{m.filename}**\n"
                notes += f"  - 分辨率: {m.width}x{m.height}\n"
                notes += f"  - 作者: {m.author}\n"
                notes += f"  - 标签: {tags_str}\n"
            notes += "\n"

        return notes

    def _generate_social_media_post(self, materials, date_str: str) -> str:
        total = len(materials)
        themes = set(m.theme for m in materials)
        themes_str = "、".join(t.capitalize() for t in sorted(themes))

        post = f"【每日壁纸推荐】{date_str}\n\n"
        post += f"今日精选 {total} 张高质量壁纸\n"
        post += f"主题：{themes_str}\n\n"
        post += f"📱 支持 iPhone / Android / 平板 / 桌面全设备\n"
        post += f"🎨 自动适配各种分辨率\n"
        post += f"✅ 经过画质检测，拒绝模糊\n\n"
        post += f"#壁纸 #每日壁纸 #{date_str.replace('-', '')} #高清壁纸"

        return post

    def _generate_json_metadata(self, materials, resized_images: Dict[str, List],
                                date_str: str, preview_paths: Dict[str, str]) -> Dict[str, Any]:
        metadata = {
            "release_date": date_str,
            "total_wallpapers": len(materials),
            "generated_at": datetime.now().isoformat(),
            "wallpapers": []
        }

        for m in materials:
            resized = resized_images.get(m.filename, [])
            preview = preview_paths.get(m.filename, "")

            wallpaper_entry = {
                "filename": m.filename,
                "original_resolution": f"{m.width}x{m.height}",
                "orientation": m.orientation,
                "author": m.author,
                "theme": m.theme,
                "tags": m.tags,
                "preview": preview,
                "resolutions": []
            }

            for r in resized:
                wallpaper_entry["resolutions"].append({
                    "device": r.device_name,
                    "category": r.category,
                    "resolution": f"{r.width}x{r.height}",
                    "path": r.output_path
                })

            metadata["wallpapers"].append(wallpaper_entry)

        return metadata

    def create_package(self, materials, resized_images: Dict[str, List],
                       preview_paths: Dict[str, str], output_dir: str,
                       date_str: str = None, duplicates: List[Dict] = None,
                       quality_reports: Dict = None) -> Dict[str, Any]:
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")

        package_dir = os.path.join(output_dir, f"wallpaper_pack_{date_str}")
        os.makedirs(package_dir, exist_ok=True)

        from .tag_organizer import TagOrganizer
        tag_organizer = TagOrganizer(self.config)
        tag_summary = tag_organizer.generate_tag_summary(materials)

        release_notes = self._generate_release_notes(
            materials, tag_summary, date_str,
            duplicates=duplicates, quality_reports=quality_reports
        )
        release_notes_path = os.path.join(package_dir, "README.md")
        with open(release_notes_path, "w", encoding="utf-8") as f:
            f.write(release_notes)

        social_post = self._generate_social_media_post(materials, date_str)
        social_post_path = os.path.join(package_dir, "social_media_post.txt")
        with open(social_post_path, "w", encoding="utf-8") as f:
            f.write(social_post)

        metadata = self._generate_json_metadata(materials, resized_images, date_str, preview_paths)
        metadata_path = os.path.join(package_dir, "metadata.json")
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        for category in ["mobile", "desktop", "tablet"]:
            cat_dir = os.path.join(output_dir, category)
            if os.path.exists(cat_dir):
                dest_cat_dir = os.path.join(package_dir, category)
                if os.path.exists(dest_cat_dir):
                    shutil.rmtree(dest_cat_dir)
                shutil.copytree(cat_dir, dest_cat_dir)

        previews_src = os.path.join(output_dir, "previews")
        if os.path.exists(previews_src):
            previews_dest = os.path.join(package_dir, "previews")
            if os.path.exists(previews_dest):
                shutil.rmtree(previews_dest)
            shutil.copytree(previews_src, previews_dest)

        zip_path = os.path.join(output_dir, f"wallpaper_pack_{date_str}.zip")
        if os.path.exists(zip_path):
            os.remove(zip_path)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(package_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, package_dir)
                    zipf.write(file_path, arcname)

        return {
            "package_dir": package_dir,
            "zip_path": zip_path,
            "release_notes": release_notes_path,
            "social_post": social_post_path,
            "metadata": metadata_path,
            "total_wallpapers": len(materials),
            "total_resolutions": sum(len(v) for v in resized_images.values())
        }

    def generate_html_gallery(self, materials, preview_paths: Dict[str, str],
                              output_dir: str, date_str: str = None) -> str:
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")

        html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>每日壁纸包 - {date_str}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f5f5; }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 40px 20px; }}
        h1 {{ text-align: center; margin-bottom: 10px; color: #333; }}
        .date {{ text-align: center; color: #666; margin-bottom: 40px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 24px; }}
        .card {{ background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.2s, box-shadow 0.2s; }}
        .card:hover {{ transform: translateY(-4px); box-shadow: 0 8px 24px rgba(0,0,0,0.15); }}
        .preview {{ width: 100%; height: 280px; object-fit: cover; background: #eee; }}
        .info {{ padding: 16px; }}
        .filename {{ font-weight: 600; color: #333; margin-bottom: 8px; font-size: 14px; }}
        .meta {{ font-size: 12px; color: #666; margin-bottom: 8px; }}
        .tags {{ display: flex; flex-wrap: wrap; gap: 6px; }}
        .tag {{ background: #e3f2fd; color: #1976d2; padding: 4px 10px; border-radius: 20px; font-size: 11px; }}
        .tag.theme {{ background: #f3e5f5; color: #7b1fa2; }}
        .tag.color {{ background: #e8f5e9; color: #388e3c; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🎨 每日壁纸包</h1>
        <p class="date">{date_str} · 共 {len(materials)} 张壁纸</p>
        <div class="grid">
"""

        for m in materials:
            preview = preview_paths.get(m.filename, "")
            preview_rel = os.path.relpath(preview, output_dir) if preview else ""
            html_content += f"""
            <div class="card">
                <img src="{preview_rel}" alt="{m.filename}" class="preview" loading="lazy">
                <div class="info">
                    <div class="filename">{m.filename}</div>
                    <div class="meta">{m.width}×{m.height} · {m.author}</div>
                    <div class="tags">
                        <span class="tag theme">{m.theme}</span>
"""
            for tag in m.tags[:4]:
                tag_class = "color" if tag in self.config.get_color_tags() else ""
                html_content += f'                        <span class="tag {tag_class}">{tag}</span>\n'
            html_content += """                    </div>
                </div>
            </div>
"""

        html_content += """
        </div>
    </div>
</body>
</html>
"""

        gallery_path = os.path.join(output_dir, f"gallery_{date_str}.html")
        with open(gallery_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        return gallery_path
