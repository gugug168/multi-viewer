import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import multi_viewer  # noqa: E402


class MultiViewerTests(unittest.TestCase):
    def test_parse_reviewers_rejects_duplicates_and_unknown_names(self):
        self.assertEqual(multi_viewer.parse_reviewers("codex,gemini"), ["codex", "gemini"])
        with self.assertRaises(ValueError):
            multi_viewer.parse_reviewers("codex,codex")
        with self.assertRaises(ValueError):
            multi_viewer.parse_reviewers("codex,unknown")

    def test_summary_keeps_failed_and_pending_separate(self):
        summary = multi_viewer.compute_summary(
            ["codex", "gemini", "grok"],
            {
                "codex": {"ok": True, "elapsed_s": 1.0},
                "gemini": {"ok": False, "elapsed_s": 2.0},
            },
            3.0,
        )
        self.assertEqual(summary["ok"], ["codex"])
        self.assertEqual(summary["failed"], ["gemini"])
        self.assertEqual(summary["pending"], ["grok"])
        self.assertFalse(summary["quorum_met"])

    def test_snapshot_is_valid_json_and_final(self):
        result = {
            "name": "codex",
            "ok": True,
            "output": "意见",
            "error": None,
            "elapsed_s": 1.2,
            "returncode": 0,
            "attempts": 1,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "review.json"
            multi_viewer.write_snapshot(path, ["codex", "gemini"], {"codex": result}, partial=True, total_wall_s=1.2)
            data = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(data["partial"])
        self.assertEqual(data["summary"]["pending"], ["gemini"])
        self.assertEqual(data["codex"]["output"], "意见")

    @patch("multi_viewer.shutil.which", return_value="C:/tools/codex")
    @patch("multi_viewer.find_bash", return_value="C:/Program Files/Git/bin/bash.exe")
    @patch("multi_viewer.subprocess.run")
    def test_prompt_is_passed_to_codex_over_stdin(self, run, _bash, _which):
        run.return_value.returncode = 0
        run.return_value.stdout = "审查完成"
        run.return_value.stderr = ""
        result = multi_viewer.run_reviewer("codex", "$(not executed)", working_dir="C:/isolated")
        self.assertTrue(result["ok"])
        self.assertEqual(run.call_args[1]["input"], "$(not executed)")
        self.assertNotIn("$(not executed)", run.call_args[0][0])
        self.assertEqual(run.call_args[1]["cwd"], "C:/isolated")


if __name__ == "__main__":
    unittest.main()
