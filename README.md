# Multi Viewer

让多个 AI **独立**审同一份计划或方案的轻量命令行工具。

它解决的不是“让 AI 投票选答案”，而是一个更现实的问题：一个 AI 容易顺着原方案继续讲；换几个视角独立挑错，计划里的遗漏、假设、边界和验证方法更容易浮出来。

Multi Viewer 会把结果并排保留：

- 多方都指出的共识；
- 仅一方提出的独有视角；
- 审查方之间的分歧；
- 超时、失败和未完成方。

**它不投票，也不替人做最终决定。** 最后仍由人根据证据、约束和实际回执拍板。

## 适合什么场景

- 进入 Plan Mode 前：检查目标、边界、依赖、风险、验收和遗漏假设；
- 方案准备实施前：让不同模型从技术、业务、风险或用户视角独立质疑；
- 视频、文案、产品或系统方案复核：避免单一 AI 的盲点；
- 重要修改后的回归审查：确认新改动没有带来新的遗漏。

它不适合代替事实核验、法律意见、安全审计或人的授权决定。

## 工作方式

```text
同一份计划
  ├─ Codex
  ├─ Gemini
  ├─ Claude Code
  └─ Grok
       ↓（彼此看不到答案）
并排保留：共识 / 独有 / 分歧 / 失败或未完成
       ↓
人按证据修订计划并拍板
```

## 要求

- Windows 10/11（当前版本为 Windows-first）；
- Python 3.10+；
- Git for Windows（提供 Git Bash，不能用 WSL 的 `bash.exe` 替代）；
- 至少安装并登录两个支持的 CLI：`codex`、`gemini`、`claude`、`grok`。

不同 CLI 的模型、账号权限、额度和可用性由各自提供方决定。某一方失败时，Multi Viewer 会保留已完成结果并明确标记降级。

默认情况下，各 CLI 会继承你运行命令时的当前目录；部分 CLI 会把该目录识别为项目上下文。审查代码、文档或计划时，这有助于发现依赖和遗漏；若只想让它们读取 prompt，请通过 `--workdir` 指向一个空目录。

## 快速开始

```powershell
git clone https://github.com/gugug168/multi-viewer.git
cd multi-viewer
python .\multi_viewer.py --reviewers codex,gemini --prompt-file .\examples\plan-review.md --partial-out .\review-result.json
```

查看版本和完整参数：

```powershell
python .\multi_viewer.py --version
python .\multi_viewer.py --help
```

## 用在 Plan Mode

先把计划写到一个 UTF-8 Markdown 文件，再把它交给独立审查方：

```powershell
python .\multi_viewer.py `
  --reviewers codex,gemini,cc,grok `
  --prompt-file .\my-plan.md `
  --workdir E:\your-project `
  --partial-out .\my-plan-review.json
```

推荐给审查方的任务描述：

> 以独立审查者身份检查这个计划。重点找：目标是否清楚、边界是否遗漏、前提是否未经验证、步骤是否能验收、失败后怎么恢复、哪些决定必须由人做。不要重写计划；按“问题、依据、最小修正”列出意见。

## 如何读结果

`--partial-out` 会在开始时写出所有 `pending`，每个审查方完成后原子更新一次，最后写入 `partial: false` 的完整结果。

常用运行控制：

```powershell
# Git Bash 在非标准位置时显式指定
python .\multi_viewer.py --bash-path 'D:\Tools\Git\bin\bash.exe' --prompt-file .\my-plan.md

# 网络不稳定时，每方最多重试两次、间隔五秒
python .\multi_viewer.py --retries 2 --retry-delay 5 --prompt-file .\my-plan.md
```

当少于两方成功时，`quorum_met` 为 `false`：此时不能说“多方共识”。即使达到 quorum，失败方原本可能提供的独有视角仍然是缺口，不应被忽略。

## 安全边界

- Codex 适配器默认使用 `--sandbox read-only`；
- prompt 通过进程参数或标准输入传递，不拼进 shell 命令，避免 `$()`、反引号等文本被执行；
- 本工具只协调本机已登录的 CLI；发送给各模型的内容仍受其服务条款和账号设置约束；
- 提交前请移除密钥、个人信息、商业机密和不应交给第三方模型的内容。

## 验证

```powershell
python -m unittest discover -s tests -v
python .\multi_viewer.py --help
```

## 许可证

[MIT](LICENSE)
