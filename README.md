# caoyu Skill 自我完善器

**版本：1.3.0**

一个用于维护个人 Codex Skill 的证据驱动流程。它会轻量观察与当前任务直接相关的个人 Skill 使用情况；只有出现真实失败、返工、冲突或结构问题时才进入诊断，无异常时保持静默。

## 工作原则

- 默认只读。自动观察与诊断不会直接改写 Skill。
- 提出修改前先给出证据、根因、最小变更、风险和验证方式。
- 只有获得用户明确授权后才修改；执行时先测基线、备份，再修复、回归测试，失败则回滚。
- 修改本 Skill 自身时执行额外确认门禁。

## 仓库内容

| 路径 | 内容 |
| --- | --- |
| `SKILL.md` | 主要行为、权限边界与维护流程 |
| `agents/openai.yaml` | Skill 展示信息与调用配置 |
| `references/` | 改进流程、评估矩阵与匿名共享学习说明 |
| `scripts/` | Skill 结构审计、匿名同步客户端及 Cloudflare Worker |
| `tests/` | 结构、安全边界与匿名同步测试 |

## 安装

将仓库克隆到 Codex 的个人 Skill 目录。

### Windows PowerShell

```powershell
$skillRoot = Join-Path $HOME ".codex\skills"
New-Item -ItemType Directory -Force $skillRoot | Out-Null
git clone https://github.com/lorlcao/caoyu-skill-self-improver.git (Join-Path $skillRoot "caoyu-skill-self-improver")
```

### macOS / Linux

```sh
mkdir -p ~/.codex/skills
git clone https://github.com/lorlcao/caoyu-skill-self-improver.git ~/.codex/skills/caoyu-skill-self-improver
```

更新已克隆的版本：

```sh
git -C ~/.codex/skills/caoyu-skill-self-improver pull
```

Windows PowerShell 可使用：

```powershell
git -C (Join-Path $HOME ".codex\skills\caoyu-skill-self-improver") pull
```

安装后，按当前 Codex 环境的 Skill 发现机制加载；如未出现，可重新打开会话。

## 匿名共享学习

匿名同步默认关闭。只有明确启用并同意说明后，才会同步固定白名单中的结构化事件；不会上传聊天原文、提示词、附件、文件内容、凭据或身份标识。可随时关闭。详见 [`references/shared_learning.md`](references/shared_learning.md)。

## 测试

```sh
python -m unittest discover -s tests -v
python scripts/audit_skills.py --root .. --format markdown
```

## 许可证

当前仓库未附 `LICENSE`。公开可见不等于授予复制、修改或分发许可。
