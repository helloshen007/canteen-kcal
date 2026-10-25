"""评估/缓存的回归测试：只使用临时合成数据，不作为实验指标。"""
import copy
import csv
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from compare.evaluate import evaluate, summarize_rows
from compare.provenance import load_prediction, write_json
from compare.report import main as report_main, runs
from detector.extract import read_features
from detector.fit_eval import class_pixels, main as fit_main


CONTEXT = {"data_sha256": "fixture-v1", "vocabulary": ["watermelon"]}
GT = {
    "calib": {"split": "calib", "kcal": 100, "mass": 100, "names": {"watermelon"},
              "grams": {"watermelon": 100}, "difficulty": "single"},
    "test": {"split": "test", "kcal": 30, "mass": 100, "names": {"watermelon"},
             "grams": {"watermelon": 100}, "difficulty": "single"},
}


def prediction(iid="test", model="fixture"):
    return {"status": "success", "parse_ok": True, "context": copy.deepcopy(CONTEXT),
            "dishes": [{"name": "watermelon", "weight_g": 100, "kcal": 30.0,
                        "protein_g": 0.6, "fat_g": 0.1, "carb_g": 7.6}],
            "total": {"kcal": 30.0, "protein_g": 0.6, "fat_g": 0.1, "carb_g": 7.6},
            "raw": '{"items":[{"name":"watermelon","grams":100}]}',
            "image_id": iid, "experiment": {"provider": "openai", "model": model, "prompt": "fixture",
                                           "image_id": iid, "disable_thinking": "0"}}


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        # 指标回归只依赖显式合成营养表，不跟随全量元数据聚合密度变动。
        table = {"watermelon": {"kcal": 30, "protein": .6, "fat": .1, "carb": 7.6}}
        patcher = patch("compare.report.nutrition_table", return_value=table)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_legacy_and_stale_predictions_are_not_successes(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "test.json"
            for result in ({"dishes": [], "total": {"kcal": 0}},
                           {**prediction(), "context": {**CONTEXT, "data_sha256": "old"}}):
                write_json(target, result)
                with self.assertRaises(ValueError):
                    load_prediction(target, CONTEXT)

    def test_failure_prediction_is_not_a_zero_kcal_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "vlm/test.json"
            write_json(target, {"status": "failed", "context": CONTEXT, "dishes": [], "total": {"kcal": 0}})
            with self.assertRaises(ValueError):
                evaluate("vlm", GT, directory, CONTEXT)

    def test_changed_vocabulary_invalidates_feature_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_context = {"data_sha256": "fixture-v1", "vocabulary": []}
            write_json(root / "test.json", {"context": old_context, "h": 2, "w": 2, "dets": []})
            np.savez_compressed(root / "test.npz", masks=np.zeros((0, 2, 2), dtype=bool))
            with self.assertRaisesRegex(ValueError, "上下文"):
                read_features("test", root, CONTEXT)

    def test_mask_union_is_used_instead_of_sum(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "fixture.json", {"context": CONTEXT, "h": 2, "w": 2,
                        "dets": [{"name": "watermelon", "conf": .8}, {"name": "watermelon", "conf": .7}]})
            masks = np.array([[[1, 1], [0, 0]], [[0, 1], [1, 0]]], dtype=bool)
            np.savez_compressed(root / "fixture.npz", masks=masks)
            self.assertEqual(class_pixels("fixture", .05, root, CONTEXT), {"watermelon": (3, .8)})

    def test_fit_refuses_missing_or_stale_features(self):
        with tempfile.TemporaryDirectory() as directory, patch("detector.fit_eval.load_gt", return_value=GT), patch("detector.fit_eval.evaluation_context", return_value=CONTEXT):
            with self.assertRaisesRegex(SystemExit, "未进行拟合"):
                fit_main(["0.05", "--results-root", directory])
            self.assertFalse((Path(directory) / "yolo_sam").exists())

    def test_zero_ground_truth_does_not_divide_by_zero(self):
        gt = copy.deepcopy(GT)
        gt["test"].update(kcal=0, names=set(), grams={}, mass=0)
        with tempfile.TemporaryDirectory() as directory:
            write_json(Path(directory) / "yolo_sam/test.json", prediction())
            rows = evaluate("yolo_sam", gt, directory, CONTEXT)
        self.assertEqual(rows[0]["abs_err"], 30)
        self.assertIsNone(rows[0]["pct_err"])
        self.assertIsNone(summarize_rows(rows)["MAPE_%"])

    def test_missing_b_blocks_complete_report_and_partial_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "yolo_sam/test.json", prediction())
            output = root / "report.md"
            with patch("compare.report.load_gt", return_value=GT), patch("compare.report.evaluation_context", return_value=CONTEXT):
                with self.assertRaises(SystemExit):
                    report_main(["--results-root", directory, "--output", str(output)])
                self.assertFalse(output.exists())
                with redirect_stdout(StringIO()):
                    report_main(["--results-root", directory, "--output", str(output), "--allow-partial"])
            summary = json.loads(output.with_suffix(".json").read_text())
            self.assertEqual(summary["coverage"]["vlm"], {"success": 0, "expected": 1})
            self.assertIn("覆盖不完整", output.read_text())
            with output.with_suffix(".per-image.csv").open() as stream:
                rows = list(csv.DictReader(stream))
            b = next(row for row in rows if row["method"] == "vlm")
            self.assertEqual(b["status"], "missing")
            self.assertEqual(b["kcal_mae"], "")

    def test_mixed_models_and_image_mismatch_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "vlm/test_r0.json", prediction())
            write_json(root / "vlm/test_r1.json", prediction(model="other-model"))
            with self.assertRaisesRegex(ValueError, "不同模型"):
                runs("vlm", "test", root, CONTEXT)
            (root / "vlm/test_r1.json").unlink()
            write_json(root / "vlm/test_r0.json", prediction(iid="wrong-image"))
            with self.assertRaisesRegex(ValueError, "图片编号"):
                runs("vlm", "test", root, CONTEXT)

    def test_fake_success_or_raw_mismatch_cannot_enter_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "vlm/test_r0.json"
            for raw in ("not JSON", "{}", '{"items":[{"name":"watermelon","grams":50}]}'):
                result = prediction()
                result["raw"] = raw
                write_json(target, result)
                with self.subTest(raw=raw), self.assertRaises(ValueError):
                    runs("vlm", "test", directory, CONTEXT)
                with self.subTest(entry="evaluate", raw=raw), self.assertRaises(ValueError):
                    evaluate("vlm", GT, directory, CONTEXT)
            result = prediction()
            result.pop("raw")
            write_json(target, result)
            with self.assertRaisesRegex(ValueError, "原始回复"):
                runs("vlm", "test", directory, CONTEXT)

    def test_invalid_raw_is_reported_invalid_instead_of_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "yolo_sam/test.json", prediction())
            fake = prediction()
            fake.update(raw="bad JSON", dishes=[], total={"kcal": 0})
            write_json(root / "vlm/test_r0.json", fake)
            output = root / "report.md"
            with patch("compare.report.load_gt", return_value=GT), patch("compare.report.evaluation_context", return_value=CONTEXT):
                with self.assertRaises(SystemExit):
                    report_main(["--results-root", directory, "--output", str(output)])
                with redirect_stdout(StringIO()):
                    report_main(["--results-root", directory, "--output", str(output), "--allow-partial"])
            summary = json.loads(output.with_suffix(".json").read_text())
            self.assertEqual(summary["coverage"]["vlm"]["success"], 0)
            self.assertIn({"method": "vlm", "image_id": "test", "status": "invalid"}, summary["issues"])
            row = next(row for row in summary["per_image"] if row["method"] == "vlm")
            self.assertNotIn("kcal_mae", row)


if __name__ == "__main__":
    unittest.main()
