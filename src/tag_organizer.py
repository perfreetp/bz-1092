import os
import re
from colorthief import ColorThief
from typing import List, Dict, Any, Tuple
from collections import defaultdict


class TagOrganizer:
    def __init__(self, config):
        self.config = config
        self.color_tags = config.get_color_tags()
        self.themes = config.get_themes()
        self.default_author = config.get_default_author()

        self._color_ranges = self._init_color_ranges()

    def _init_color_ranges(self) -> Dict[str, Tuple[Tuple[int, int, int], Tuple[int, int, int]]]:
        return {
            "red": ((128, 0, 0), (255, 100, 100)),
            "orange": ((200, 100, 0), (255, 180, 80)),
            "yellow": ((180, 160, 0), (255, 255, 120)),
            "green": ((0, 100, 0), (100, 255, 100)),
            "cyan": ((0, 150, 150), (100, 255, 255)),
            "blue": ((0, 0, 128), (100, 150, 255)),
            "purple": ((100, 0, 128), (200, 100, 255)),
            "pink": ((180, 80, 120), (255, 150, 200)),
            "brown": ((80, 40, 20), (150, 100, 60)),
            "black": ((0, 0, 0), (50, 50, 50)),
            "white": ((200, 200, 200), (255, 255, 255)),
            "gray": ((60, 60, 60), (180, 180, 180)),
        }

    def _color_distance(self, c1: Tuple[int, int, int], c2: Tuple[int, int, int]) -> float:
        return sum((a - b) ** 2 for a, b in zip(c1, c2)) ** 0.5

    def _classify_color(self, rgb: Tuple[int, int, int]) -> str:
        min_distance = float("inf")
        closest_color = "gray"

        for color_name, (min_rgb, max_rgb) in self._color_ranges.items():
            center = (
                (min_rgb[0] + max_rgb[0]) // 2,
                (min_rgb[1] + max_rgb[1]) // 2,
                (min_rgb[2] + max_rgb[2]) // 2,
            )
            distance = self._color_distance(rgb, center)
            if distance < min_distance:
                min_distance = distance
                closest_color = color_name

        return closest_color

    def extract_colors(self, file_path: str, num_colors: int = 3) -> List[str]:
        try:
            color_thief = ColorThief(file_path)
            palette = color_thief.get_palette(color_count=num_colors, quality=1)

            color_tags = []
            for rgb in palette:
                color_name = self._classify_color(rgb)
                if color_name not in color_tags and color_name in self.color_tags:
                    color_tags.append(color_name)

            return color_tags
        except Exception as e:
            print(f"Color extraction failed for {file_path}: {e}")
            return []

    def _extract_from_filename(self, filename: str) -> Tuple[List[str], str]:
        name_lower = filename.lower()

        tags = []
        theme = ""

        for t in self.themes:
            if t in name_lower:
                theme = t
                tags.append(t)
                break

        keyword_mapping = {
            "mountain": "nature",
            "forest": "nature",
            "ocean": "nature",
            "sea": "nature",
            "lake": "nature",
            "sunset": "nature",
            "sunrise": "nature",
            "sky": "nature",
            "cloud": "nature",
            "flower": "nature",
            "tree": "nature",
            "building": "city",
            "city": "city",
            "street": "city",
            "urban": "city",
            "architecture": "city",
            "bridge": "city",
            "geometric": "abstract",
            "pattern": "abstract",
            "gradient": "abstract",
            "minimal": "minimal",
            "simple": "minimal",
            "clean": "minimal",
            "dark": "dark",
            "black": "dark",
            "night": "dark",
            "light": "light",
            "bright": "light",
            "white": "light",
            "art": "art",
            "painting": "art",
            "illustration": "art",
            "tech": "technology",
            "technology": "technology",
            "digital": "technology",
            "circuit": "technology",
            "space": "technology",
        }

        for keyword, tag in keyword_mapping.items():
            if keyword in name_lower and tag not in tags:
                tags.append(tag)
                if not theme:
                    theme = tag

        return tags, theme

    def _parse_author_from_metadata(self, metadata: Dict[str, Any]) -> str:
        author_keys = ["Artist", "Photographer", "Creator", "Author", "Owner"]
        for key in author_keys:
            if key in metadata:
                return metadata[key]
            if str(key) in metadata:
                return metadata[str(key)]
        return ""

    def process_material(self, material) -> None:
        color_tags = self.extract_colors(material.file_path)
        filename_tags, theme = self._extract_from_filename(material.filename)
        author_from_meta = self._parse_author_from_metadata(material.metadata)

        all_tags = list(set(color_tags + filename_tags + material.tags))

        material.tags = all_tags
        if not material.theme:
            material.theme = theme if theme else "uncategorized"
        if not material.author:
            material.author = author_from_meta if author_from_meta else self.default_author

    def process_batch(self, materials) -> None:
        for material in materials:
            self.process_material(material)

    def group_by_theme(self, materials) -> Dict[str, List]:
        groups = defaultdict(list)
        for material in materials:
            groups[material.theme].append(material)
        return dict(groups)

    def group_by_color(self, materials) -> Dict[str, List]:
        groups = defaultdict(list)
        for material in materials:
            for tag in material.tags:
                if tag in self.color_tags:
                    groups[tag].append(material)
                    break
        return dict(groups)

    def group_by_orientation(self, materials) -> Dict[str, List]:
        groups = defaultdict(list)
        for material in materials:
            groups[material.orientation].append(material)
        return dict(groups)

    def generate_tag_summary(self, materials) -> Dict[str, Any]:
        summary = {
            "total_materials": len(materials),
            "by_theme": {},
            "by_color": {},
            "by_orientation": {},
            "all_tags": [],
        }

        theme_groups = self.group_by_theme(materials)
        for theme, items in theme_groups.items():
            summary["by_theme"][theme] = len(items)

        color_groups = self.group_by_color(materials)
        for color, items in color_groups.items():
            summary["by_color"][color] = len(items)

        orientation_groups = self.group_by_orientation(materials)
        for orient, items in orientation_groups.items():
            summary["by_orientation"][orient] = len(items)

        all_tags = set()
        for m in materials:
            all_tags.update(m.tags)
        summary["all_tags"] = sorted(list(all_tags))

        return summary
