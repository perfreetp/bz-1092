import os
from PIL import Image
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass, field


@dataclass
class Material:
    file_path: str
    filename: str
    width: int
    height: int
    orientation: str
    format: str
    size_bytes: int
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    theme: str = ""
    author: str = ""

    @property
    def aspect_ratio(self) -> float:
        return self.width / self.height if self.height > 0 else 0


class MaterialImporter:
    def __init__(self, config):
        self.config = config
        self.allowed_formats = tuple(self.config.get_allowed_formats())

    def scan_directory(self, input_dir: str) -> List[str]:
        image_files = []
        for root, _, files in os.walk(input_dir):
            for file in files:
                if file.lower().endswith(self.allowed_formats):
                    image_files.append(os.path.join(root, file))
        return sorted(image_files)

    def _get_image_info(self, file_path: str) -> Tuple[int, int, str]:
        with Image.open(file_path) as img:
            width, height = img.size
            img_format = img.format
        return width, height, img_format

    def _determine_orientation(self, width: int, height: int) -> str:
        if width > height:
            return "landscape"
        elif height > width:
            return "portrait"
        else:
            return "square"

    def _extract_metadata(self, file_path: str) -> Dict[str, Any]:
        metadata = {}
        try:
            with Image.open(file_path) as img:
                exif_data = img._getexif()
                if exif_data:
                    for tag_id, value in exif_data.items():
                        tag = str(tag_id)
                        if not isinstance(value, (bytes, bytearray)):
                            metadata[tag] = str(value)
        except Exception:
            pass
        return metadata

    def import_materials(self, input_dir: str) -> List[Material]:
        if not os.path.exists(input_dir):
            raise FileNotFoundError(f"Input directory not found: {input_dir}")

        files = self.scan_directory(input_dir)
        materials = []

        for file_path in files:
            try:
                width, height, img_format = self._get_image_info(file_path)
                orientation = self._determine_orientation(width, height)
                metadata = self._extract_metadata(file_path)

                material = Material(
                    file_path=file_path,
                    filename=os.path.basename(file_path),
                    width=width,
                    height=height,
                    orientation=orientation,
                    format=img_format,
                    size_bytes=os.path.getsize(file_path),
                    metadata=metadata,
                    author=self.config.get_default_author()
                )
                materials.append(material)
            except Exception as e:
                print(f"Failed to import {file_path}: {e}")

        return materials

    def filter_by_orientation(self, materials: List[Material], orientation: str) -> List[Material]:
        return [m for m in materials if m.orientation == orientation]

    def get_statistics(self, materials: List[Material]) -> Dict[str, Any]:
        stats = {
            "total": len(materials),
            "by_orientation": {},
            "by_format": {},
            "total_size_bytes": 0,
            "avg_resolution": {"width": 0, "height": 0}
        }

        for m in materials:
            stats["by_orientation"][m.orientation] = stats["by_orientation"].get(m.orientation, 0) + 1
            stats["by_format"][m.format] = stats["by_format"].get(m.format, 0) + 1
            stats["total_size_bytes"] += m.size_bytes
            stats["avg_resolution"]["width"] += m.width
            stats["avg_resolution"]["height"] += m.height

        if materials:
            stats["avg_resolution"]["width"] //= len(materials)
            stats["avg_resolution"]["height"] //= len(materials)

        return stats
