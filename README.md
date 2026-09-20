# 78d13-Team-Competition-Personal-Information-Submission-System

## 项目说明
78D13联队队内赛队员信息收集管理系统

## 项目结构
- index.html: 网页部署工具，供参赛队员填写报名与队列信息后导出格式化文件提交给裁判组
- config/ : 网页工具的信息预设，包含可用比赛信息，队员信息，载具信息（国家分）
- docs: 项目文件
- records: 比赛记录

## 比赛配置

页面从 `config/available_matches/index.json` 读取可选比赛，再读取其中 `file` 指向的比赛 JSON。新增比赛时，在该目录添加配置文件，并在 `index.json` 中加入对应的 `id`、`name` 和 `file`。

比赛配置支持 `teams`、`maxSlots`、`mode`、`difficulty`、`condition`、`time`、`fuel`、`ammo`、`respawn` 和 `rounds` 字段。