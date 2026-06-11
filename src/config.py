import os
import yaml
from typing import Dict, Any, List


class Config:
    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "config",
                "default_config.yaml"
            )
        self.config_path = config_path
        self._config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        with open(self.config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def get(self, key: str, default: Any = None) -> Any:
        keys = key.split(".")
        value = self._config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    def get_device_resolutions(self, category: str = None) -> List[Dict[str, Any]]:
        resolutions = self.get("device_resolutions", {})
        if category:
            return resolutions.get(category, [])
        result = []
        for cat, devices in resolutions.items():
            for device in devices:
                device["category"] = cat
                result.append(device)
        return result

    def get_allowed_formats(self) -> List[str]:
        return self.get("quality_check.allowed_formats", [])

    def get_blur_threshold(self) -> float:
        return self.get("quality_check.blur_threshold", 100.0)

    def get_duplicate_threshold(self) -> int:
        return self.get("quality_check.duplicate_threshold", 5)

    def get_min_resolution(self) -> Dict[str, int]:
        return self.get("quality_check.min_resolution", {"width": 1920, "height": 1080})

    def get_path(self, path_name: str) -> str:
        return self.get(f"paths.{path_name}", "./")

    def get_color_tags(self) -> List[str]:
        return self.get("organization.color_tags", [])

    def get_themes(self) -> List[str]:
        return self.get("organization.themes", [])

    def get_default_author(self) -> str:
        return self.get("organization.default_author", "Design Team")

    def get_jpeg_quality(self) -> int:
        return self.get("output.jpeg_quality", 95)

    def get_png_compression(self) -> int:
        return self.get("output.png_compression", 6)

    def get_preview_size(self) -> Dict[str, int]:
        return self.get("output.preview_size", {"width": 400, "height": 400})
