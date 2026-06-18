from pathlib import Path
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DependencyDeclarationTest(unittest.TestCase):
    def test_httpx_socks_support_is_declared(self):
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
        project_dependencies = {item.lower() for item in pyproject["project"]["dependencies"]}
        requirements = {
            line.strip().lower()
            for line in (ROOT / "requirements.txt").read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        }

        self.assertTrue(
            any(item.startswith("httpx[socks]") or item.startswith("socksio") for item in project_dependencies),
            "pyproject.toml must declare SOCKS proxy support for httpx.",
        )
        self.assertTrue(
            any(item.startswith("httpx[socks]") or item.startswith("socksio") for item in requirements),
            "requirements.txt must install SOCKS proxy support for httpx.",
        )


if __name__ == "__main__":
    unittest.main()
