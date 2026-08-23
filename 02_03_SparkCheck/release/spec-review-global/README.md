# Spec Review 全局发行包

这是面向 OpenCode 1.18.x 的可直接复制发行物。发行物采用“直接插件入口 + 自包含运行包”
布局，复制后会同时注册：

- `spec-review` 专用子 Agent；
- `/spec-review` 命令；
- `spec_review_*` 受控工具；
- Python 审查运行时。

## 手动放置

把本目录中的 `opencode` 文件夹整体合并到：

```text
~/.config/
```

完成后必须形成：

```text
~/.config/opencode/plugins/spec-review.ts
~/.config/opencode/plugins/spec-review/index.ts
~/.config/opencode/plugins/spec-review/package.json
~/.config/opencode/plugins/spec-review/src/
~/.config/opencode/plugins/spec-review/runtime/
~/.config/opencode/plugins/spec-review/node_modules/
```

如果 `~/.config/opencode/` 已经存在，应选择“合并”，不要用本发行物替换或删除原目录。
完成复制后重启 OpenCode。无需执行 npm、Bun 或 pip 安装命令。

运行环境需要 OpenCode 1.18.0+、PATH 中可用的 Python 3.9+，目标代码目录需要是
Git 仓库。

本包不会自动部署，也不会覆盖你的其他 OpenCode 配置。GitHub PR 读取/回写需要网络；
私有仓库和真实发布需要在启动 OpenCode 的环境中提供 `GITHUB_TOKEN`。默认仅生成本地
报告，不会发布 Review 或修改业务代码。

## 使用

```text
/spec-review --docs docs/design.md --base main --head HEAD --mode auto
```

GitHub PR：

```text
/spec-review --docs docs/design.md --pr https://github.com/acme/repo/pull/123 --mode auto
```

真实回写前必须先查看 `spec_review_publish_preview`，并显式确认锁定的完整 head SHA。
建议 Patch 默认只预览；创建 Fix PR 还需要人工确认词 `CREATE_FIX_PR`。

或者：

```text
@spec-review 审查 HEAD 相对 main 的变更是否符合 docs/design.md
```
