# 78d13-Team-Competition-Personal-Information-Submission-System

## 项目说明
78D13联队队内赛队员信息收集管理系统

## 项目结构
- index.html: 网页部署工具，供参赛队员填写报名与队列信息后导出格式化文件提交给裁判组
- config/ : 网页工具的信息预设，包含可用比赛信息，队员信息，载具信息（国家分）
- docs: 项目文件
- records: 比赛记录

## 生成比赛记录

网页导出的报名 JSON 放入 `script/input/` 后，可以通过 `script/generate_match_record.py` 汇总为 Markdown。比赛配置必须通过 `--match-config` 指定，结果默认写入 `out/`：

```bash
python script/generate_match_record.py --match-config config/available_matches/20260919.json
```

也可以显式指定输入目录或输出文件：

```bash
python script/generate_match_record.py script/input --match-config config/available_matches/20260919.json --output out/20260919-比赛记录.md
```

脚本会检查报名文件字段、队伍是否属于当前比赛、玩家 ID 是否重复，以及比赛配置是否正好包含两支队伍。

## 比赛配置

页面从 `config/available_matches/index.json` 读取可选比赛，再读取其中 `file` 指向的比赛 JSON。新增比赛时，在该目录添加配置文件，并在 `index.json` 中加入对应的 `id`、`name` 和 `file`。

比赛配置支持 `teams`、`maxSlots`、`mode`、`difficulty`、`condition`、`time`、`fuel`、`ammo`、`respawn` 和 `rounds` 字段。

载具配置文件暂不录入数据。页面支持按载具类型和等级组织的 JSON，例如：`{"固定翼飞机":{"VIII":[{"name":"示例载具","br":12.0}]}}`；其中 `name` 为载具名称，`br` 为载具权重。