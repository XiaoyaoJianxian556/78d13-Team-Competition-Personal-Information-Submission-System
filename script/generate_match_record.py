#!/usr/bin/env python3
"""Generate a Markdown match record from exported participant JSON files."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_DIR = ROOT / "script" / "input"
DEFAULT_OUTPUT_DIR = ROOT / "out"


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise ValueError(f"无法按 UTF-8 读取 {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 格式错误：{path}（{exc.msg}）") from exc


def load_match_config(path: Path) -> tuple[dict[str, Any], Path]:
    data = read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"比赛配置必须是 JSON 对象：{path}")
    return data, path


def collect_input_paths(values: list[str]) -> list[Path]:
    paths: list[Path] = []
    for value in values:
        path = Path(value)
        if path.is_dir():
            paths.extend(sorted(path.glob("*.json")))
        elif path.is_file():
            paths.append(path)
        else:
            raise ValueError(f"找不到报名文件或目录：{value}")

    unique_paths = list(dict.fromkeys(path.resolve() for path in paths))
    if not unique_paths:
        raise ValueError("没有找到报名 JSON 文件")
    return unique_paths


def normalize_teams(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    return [item.strip() for item in str(value).replace("，", ",").split(",") if item.strip()]


def load_submissions(paths: list[Path]) -> list[dict[str, Any]]:
    submissions: list[dict[str, Any]] = []
    for path in paths:
        data = read_json(path)
        if not isinstance(data, dict):
            raise ValueError(f"报名文件必须是 JSON 对象：{path}")
        required = ("nickname", "gaijinId", "team", "identity", "techTree", "slots")
        missing = [field for field in required if field not in data]
        if missing:
            raise ValueError(f"报名文件缺少字段 {', '.join(missing)}：{path}")
        if not isinstance(data["slots"], list):
            raise ValueError(f"slots 必须是数组：{path}")
        item = dict(data)
        item["_source"] = path.name
        submissions.append(item)
    return submissions


def markdown_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", "<br>")


def format_slots(slots: list[dict[str, Any]]) -> str:
    result = []
    for slot in slots:
        if not isinstance(slot, dict):
            result.append(str(slot))
            continue
        vehicle = " ".join(
            str(slot.get(field, "")).strip()
            for field in ("type", "level", "name")
            if str(slot.get(field, "")).strip()
        )
        loadout = str(slot.get("loadout", "")).strip()
        result.append(f"{vehicle}（挂载：{loadout or '无'}）")
    return "<br>".join(markdown_cell(item) for item in result) or "无"


def render_team(team: str, members: list[dict[str, Any]]) -> list[str]:
    lines = [f"## {markdown_cell(team)}", "", f"参赛人数：{len(members)}", ""]
    lines.extend(
        [
            "| 序号 | 游戏昵称 | 玩家 ID | 身份 | 科技树 | 车位信息 |",
            "| ---: | --- | ---: | --- | --- | --- |",
        ]
    )
    for index, member in enumerate(members, 1):
        lines.append(
            "| {index} | {nickname} | {gaijin_id} | {identity} | {tech_tree} | {slots} |".format(
                index=index,
                nickname=markdown_cell(member["nickname"]),
                gaijin_id=markdown_cell(member["gaijinId"]),
                identity=markdown_cell(member["identity"]),
                tech_tree=markdown_cell(member["techTree"]),
                slots=format_slots(member["slots"]),
            )
        )
    return lines


def render_record(config: dict[str, Any], submissions: list[dict[str, Any]], teams: list[str]) -> str:
    title = config.get("name") or config.get("id") or "比赛记录"
    lines = [f"# {markdown_cell(title)}", "", "## 比赛信息", ""]
    info = (
        ("比赛模式", config.get("mode")),
        ("难度", config.get("difficulty")),
        ("条件", config.get("condition")),
        ("时间", config.get("time")),
        ("燃料有限", config.get("fuel")),
        ("弹药有限", config.get("ammo")),
        ("重生次数限制", config.get("respawn")),
        ("比赛局数", config.get("rounds")),
    )
    lines.extend(["| 项目 | 内容 |", "| --- | --- |"])
    for label, value in info:
        if value is not None and str(value).strip():
            lines.append(f"| {label} | {markdown_cell(value)} |")

    grouped = {team: [] for team in teams}
    for submission in submissions:
        grouped.setdefault(str(submission["team"]), []).append(submission)

    lines.extend(["", "## 队伍汇总", "", "| 队伍 | 参赛人数 | 队长 |", "| --- | ---: | --- |"])
    for team in teams:
        members = grouped.get(team, [])
        captains = [member["nickname"] for member in members if member["identity"] == "队长"]
        lines.append(f"| {markdown_cell(team)} | {len(members)} | {markdown_cell(', '.join(captains) or '未填写')} |")

    for team in teams:
        lines.extend(["", *render_team(team, grouped.get(team, []))])
    return "\n".join(lines) + "\n"


def validate_submissions(config: dict[str, Any], submissions: list[dict[str, Any]]) -> list[str]:
    configured_teams = normalize_teams(config.get("teams"))
    errors = []
    if len(configured_teams) != 2:
        errors.append("比赛配置必须正好包含两支队伍")

    seen_ids: Counter[str] = Counter()
    for submission in submissions:
        team = str(submission["team"]).strip()
        if configured_teams and team not in configured_teams:
            errors.append(f"{submission['_source']}：队伍“{team}”不在比赛配置中")
        player_id = str(submission["gaijinId"]).strip()
        if player_id:
            seen_ids[player_id] += 1
        if not str(submission["nickname"]).strip():
            errors.append(f"{submission['_source']}：nickname 不能为空")

    duplicates = [player_id for player_id, count in seen_ids.items() if count > 1]
    if duplicates:
        errors.append(f"玩家 ID 重复：{', '.join(duplicates)}")
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="将网页导出的参赛人员 JSON 汇总为比赛记录 Markdown")
    parser.add_argument(
        "submissions",
        nargs="*",
        default=[str(DEFAULT_INPUT_DIR)],
        help="报名 JSON 文件或目录，省略时扫描 script/input/",
    )
    parser.add_argument("--match-config", type=Path, required=True, help="比赛配置 JSON（必填）")
    parser.add_argument("--output", type=Path, help="输出 Markdown 文件路径，默认写入 out/")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        input_paths = collect_input_paths(args.submissions)
        config, config_path = load_match_config(args.match_config)
        submissions = load_submissions(input_paths)
        configured_teams = normalize_teams(config.get("teams"))
        teams = configured_teams or list(dict.fromkeys(str(item["team"]).strip() for item in submissions))
        errors = validate_submissions(config, submissions)
        if errors:
            raise ValueError("\n".join(errors))
        if len(teams) != 2:
            raise ValueError("报名数据必须包含正好两支队伍")

        output_path = args.output
        if output_path is None:
            match_id = str(config.get("id") or (config_path.stem if config_path else "match-record"))
            output_path = DEFAULT_OUTPUT_DIR / f"{match_id}-比赛记录.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(render_record(config, submissions, teams), encoding="utf-8")
        print(f"已生成：{output_path}")
        print(f"参赛人数：{len(submissions)}（{', '.join(f'{team} {sum(item['team'] == team for item in submissions)}人' for team in teams)}）")
        return 0
    except (OSError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())