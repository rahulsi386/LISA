from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path


class FastPublisherTests(unittest.TestCase):
    def test_javascript_runner_policies(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is unavailable")
        script = Path(__file__).with_suffix(".js")
        completed = subprocess.run(
            [node, str(script)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(
            0,
            completed.returncode,
            completed.stderr or completed.stdout,
        )
        self.assertIn("fast publisher tests passed", completed.stdout)


if __name__ == "__main__":
    unittest.main()
