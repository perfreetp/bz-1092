import os
import cv2
import numpy as np
import imagehash
from PIL import Image
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass, field


@dataclass
class QualityIssue:
    file_path: str
    issue_type: str
    severity: str
    details: str


@dataclass
class QualityReport:
    file_path: str
    passed: bool
    blur_score: float = 0.0
    issues: List[QualityIssue] = field(default_factory=list)
    phash: str = ""


class QualityChecker:
    def __init__(self, config):
        self.config = config
        self.blur_threshold = config.get_blur_threshold()
        self.duplicate_threshold = config.get_duplicate_threshold()
        self.min_res = config.get_min_resolution()

    def _detect_blur(self, file_path: str) -> float:
        try:
            img = cv2.imread(file_path, cv2.IMREAD_GRAYSCALE)
            if img is None:
                return 0.0
            laplacian = cv2.Laplacian(img, cv2.CV_64F)
            variance = np.var(laplacian)
            return float(variance)
        except Exception as e:
            print(f"Blur detection failed for {file_path}: {e}")
            return 0.0

    def _compute_phash(self, file_path: str) -> str:
        try:
            with Image.open(file_path) as img:
                phash = imagehash.phash(img)
                return str(phash)
        except Exception as e:
            print(f"PHash computation failed for {file_path}: {e}")
            return ""

    def _check_resolution(self, width: int, height: int) -> Tuple[bool, str]:
        min_w = self.min_res["width"]
        min_h = self.min_res["height"]
        if width < min_w or height < min_h:
            return False, f"Resolution {width}x{height} below minimum {min_w}x{min_h}"
        return True, ""

    def check_material(self, material) -> QualityReport:
        report = QualityReport(
            file_path=material.file_path,
            passed=True
        )

        blur_score = self._detect_blur(material.file_path)
        report.blur_score = blur_score

        if blur_score < self.blur_threshold:
            report.passed = False
            report.issues.append(QualityIssue(
                file_path=material.file_path,
                issue_type="blur",
                severity="warning",
                details=f"Blur score {blur_score:.1f} below threshold {self.blur_threshold}"
            ))

        res_ok, res_msg = self._check_resolution(material.width, material.height)
        if not res_ok:
            report.passed = False
            report.issues.append(QualityIssue(
                file_path=material.file_path,
                issue_type="resolution",
                severity="error",
                details=res_msg
            ))

        report.phash = self._compute_phash(material.file_path)

        return report

    def check_batch(self, materials) -> Dict[str, QualityReport]:
        reports = {}
        for material in materials:
            reports[material.file_path] = self.check_material(material)
        return reports

    def detect_duplicates(self, reports: Dict[str, QualityReport]) -> List[Dict[str, Any]]:
        duplicates = []
        file_list = list(reports.keys())

        for i in range(len(file_list)):
            for j in range(i + 1, len(file_list)):
                file1 = file_list[i]
                file2 = file_list[j]

                hash1 = reports[file1].phash
                hash2 = reports[file2].phash

                if not hash1 or not hash2:
                    continue

                try:
                    hamming_distance = imagehash.hex_to_hash(hash1) - imagehash.hex_to_hash(hash2)
                    if hamming_distance <= self.duplicate_threshold:
                        duplicates.append({
                            "file1": file1,
                            "file2": file2,
                            "similarity": 100 - (hamming_distance * 100 / 64),
                            "hamming_distance": hamming_distance
                        })
                except Exception as e:
                    print(f"Duplicate check failed: {e}")
                    continue

        return duplicates

    def filter_passed(self, materials, reports: Dict[str, QualityReport]):
        passed = []
        failed = []
        for m in materials:
            if reports.get(m.file_path, QualityReport(file_path=m.file_path, passed=False)).passed:
                passed.append(m)
            else:
                failed.append(m)
        return passed, failed

    def get_statistics(self, reports: Dict[str, QualityReport]) -> Dict[str, Any]:
        total = len(reports)
        passed = sum(1 for r in reports.values() if r.passed)
        by_issue = {}

        for report in reports.values():
            for issue in report.issues:
                by_issue[issue.issue_type] = by_issue.get(issue.issue_type, 0) + 1

        avg_blur = sum(r.blur_score for r in reports.values()) / total if total > 0 else 0

        return {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": passed / total if total > 0 else 0,
            "by_issue": by_issue,
            "avg_blur_score": avg_blur
        }
