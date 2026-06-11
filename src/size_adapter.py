import os
from PIL import Image
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass


@dataclass
class ResizedImage:
    original_path: str
    output_path: str
    device_name: str
    category: str
    width: int
    height: int
    orientation: str


class SizeAdapter:
    def __init__(self, config):
        self.config = config
        self.jpeg_quality = config.get_jpeg_quality()
        self.png_compression = config.get_png_compression()

    def _calculate_crop_region(self, img_width: int, img_height: int,
                              target_width: int, target_height: int) -> Tuple[int, int, int, int]:
        img_aspect = img_width / img_height
        target_aspect = target_width / target_height

        if img_aspect > target_aspect:
            new_height = img_height
            new_width = int(target_aspect * new_height)
            left = (img_width - new_width) // 2
            top = 0
        else:
            new_width = img_width
            new_height = int(new_width / target_aspect)
            left = 0
            top = (img_height - new_height) // 2

        return (left, top, left + new_width, top + new_height)

    def _resize_image(self, img: Image.Image, target_width: int, target_height: int) -> Image.Image:
        crop_region = self._calculate_crop_region(img.width, img.height, target_width, target_height)
        cropped = img.crop(crop_region)
        resized = cropped.resize((target_width, target_height), Image.LANCZOS)
        return resized

    def _save_image(self, img: Image.Image, output_path: str, original_format: str) -> None:
        ext = os.path.splitext(output_path)[1].lower()

        if ext in ('.jpg', '.jpeg'):
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            img.save(output_path, 'JPEG', quality=self.jpeg_quality, optimize=True)
        elif ext == '.png':
            img.save(output_path, 'PNG', compress_level=self.png_compression, optimize=True)
        elif ext == '.webp':
            img.save(output_path, 'WEBP', quality=self.jpeg_quality)
        else:
            img.save(output_path)

    def _get_matching_resolutions(self, material_orientation: str) -> List[Dict[str, Any]]:
        all_resolutions = self.config.get_device_resolutions()
        if material_orientation == "square":
            return all_resolutions
        return [r for r in all_resolutions if r["orientation"] == material_orientation]

    def process_material(self, material, output_dir: str) -> List[ResizedImage]:
        results = []
        resolutions = self._get_matching_resolutions(material.orientation)

        try:
            with Image.open(material.file_path) as img:
                original_format = material.format

                for res in resolutions:
                    target_width = res["width"]
                    target_height = res["height"]

                    if img.width < target_width or img.height < target_height:
                        print(f"Warning: {material.filename} ({img.width}x{img.height}) "
                              f"smaller than target {target_width}x{target_height}")

                    resized_img = self._resize_image(img, target_width, target_height)

                    base_name = os.path.splitext(material.filename)[0]
                    safe_device_name = res["name"].replace(" ", "_").lower()
                    output_filename = f"{base_name}_{safe_device_name}_{target_width}x{target_height}.jpg"
                    output_path = os.path.join(
                        output_dir,
                        res["category"],
                        res["orientation"],
                        output_filename
                    )

                    os.makedirs(os.path.dirname(output_path), exist_ok=True)
                    self._save_image(resized_img, output_path, original_format)

                    results.append(ResizedImage(
                        original_path=material.file_path,
                        output_path=output_path,
                        device_name=res["name"],
                        category=res["category"],
                        width=target_width,
                        height=target_height,
                        orientation=res["orientation"]
                    ))

        except Exception as e:
            print(f"Failed to process {material.filename}: {e}")
            raise

        return results

    def process_batch(self, materials, output_dir: str) -> Dict[str, List[ResizedImage]]:
        results = {}
        for material in materials:
            try:
                results[material.filename] = self.process_material(material, output_dir)
            except Exception as e:
                print(f"Skipping {material.filename}: {e}")
                results[material.filename] = []
        return results

    def generate_thumbnail(self, material, output_dir: str,
                          width: int = None, height: int = None) -> str:
        if width is None or height is None:
            preview_size = self.config.get_preview_size()
            width = preview_size["width"]
            height = preview_size["height"]

        try:
            with Image.open(material.file_path) as img:
                img.thumbnail((width, height), Image.LANCZOS)

                base_name = os.path.splitext(material.filename)[0]
                output_filename = f"{base_name}_preview.jpg"
                output_path = os.path.join(output_dir, "previews", output_filename)

                os.makedirs(os.path.dirname(output_path), exist_ok=True)

                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')
                img.save(output_path, 'JPEG', quality=85, optimize=True)

                return output_path
        except Exception as e:
            print(f"Failed to generate thumbnail for {material.filename}: {e}")
            raise
