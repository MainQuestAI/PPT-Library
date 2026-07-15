from __future__ import annotations

import shlex
from pathlib import Path

import yaml

from ppt_lib.cli import build_parser

ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = ROOT / "skills" / "ppt-library" / "SKILL.md"
ADAPTER_PATH = ROOT / "skills" / "ppt-library" / "references" / "agent-adapters.md"


def test_skill_has_discoverable_frontmatter() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    _, frontmatter, _ = text.split("---", maxsplit=2)
    metadata = yaml.safe_load(frontmatter)

    assert metadata["name"] == "ppt-library"
    assert "PPT Library CLI" in metadata["description"]
    assert metadata["version"] == "1.0.0"


def test_documented_representative_commands_match_current_parser() -> None:
    commands = [
        'search "retail architecture" --top-k 3 --threshold 0.2 --output json',
        'search "retail architecture" --top-k 3 --contract-v2 --output json',
        'compose --brief "retail proposal"',
        'compose --brief "retail proposal" --auto',
        'compose --confirm /tmp/run/narrative-plan.json',
        'capabilities --probe --output json',
        'contract validate capabilities.v1 --data "{}" --no-strict --output json',
        'workbench start --host 0.0.0.0 --port 9900 --allow-remote --auth-token-env TOKEN --workspace default',
        'workbench status --host localhost --port 9900 --auth-token-env TOKEN --output json',
    ]
    parser = build_parser()

    for command in commands:
        args = parser.parse_args(shlex.split(command))
        assert args.command


def test_skill_and_adapter_describe_actual_error_and_compose_semantics() -> None:
    skill = SKILL_PATH.read_text(encoding="utf-8")
    adapter = ADAPTER_PATH.read_text(encoding="utf-8")

    assert "[-k N]" not in skill
    assert "--top-k N" in skill
    assert "stderr 只承载人类进度" in skill
    assert "不会重新选页" in skill
    assert "退出码" in adapter
    assert "search --contract-v2 --output json" in adapter
    assert "--allow-remote --auth-token-env" in adapter
