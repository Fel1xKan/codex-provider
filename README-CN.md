<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset=".github/logo-light.svg">
    <img alt="codex-provider" src=".github/logo-light.svg" width="440">
  </picture>
</div>

<div align="center">

[![License: MIT][license-shield]][license-url]
[![Release][release-shield]][release-url]
[![CI][ci-shield]][ci-url]
[![Python 3.11+][python-shield]][python-url]

</div>

<div align="center">
  <a href="README.md">English</a> &middot;
  <a href="#快速开始">快速开始</a> &middot;
  <a href="#使用方法">使用方法</a> &middot;
  <a href="docs/command-reference.md">命令参考</a> &middot;
  <a href="https://github.com/Fel1xKan/codex-provider/issues/new?labels=bug">报告问题</a>
</div>

> 无需手动修改凭据或全局配置，即可切换 Codex、OpenCode 和 Antigravity 的提供商与账号。

---

## 为什么使用 codex-provider？

不同的 AI 编程 CLI 会用不同的格式和目录保存提供商、模型与凭据。如果你经常在官方账号、
OpenAI 兼容 API 提供商或多个 Antigravity 账号之间切换，手动编辑配置既容易出错，也难以
检查。本项目为每个目标工具提供专用 CLI，同时统一常用命令、验证方式、安全写入和预览机制。

## 功能亮点

- **无需手动编辑即可切换**：选择已保存的提供商或账号，同时保留无关的全局配置。
- **避免在终端泄露秘密**：可以查看认证字段元数据和脱敏配置，不会打印凭据值。
- **验证完整调用链**：既能探测 `/models` 接口，也能通过 Codex、OpenCode 或 Antigravity 执行最小命令。
- **管理 OpenCode 模型**：发现远端模型 ID、只同步新增模型，并在切换提供商时选择默认模型。
- **管理 Antigravity 账号**：登录、导入账号快照、切换账号，并查看 5 小时和每周配额余量。
- **预览和恢复变更**：修改类命令支持预演，并可用 JSON 导出或导入提供商数据。
- **快速返回最近使用项**：交互式选择器和列表会优先显示最近使用的提供商或账号。

## 选择对应的 CLI

| CLI | 适用场景 | 原生配置位置 |
|-----|----------|--------------|
| `codex-provider` | Codex 兼容 API 提供商和认证快照 | `~/.codex` 与 `~/.codex-provider` |
| `opencode-provider` | OpenCode 提供商、凭据、默认模型与模型发现 | OpenCode 的 XDG 配置、数据和状态目录 |
| `agy-provider` | Antigravity 账号、登录快照、切换和配额查询 | `~/.gemini/antigravity-cli` 与 `~/.gemini/agy-provider` |

Codex 与 OpenCode CLI 的公共操作会保持命令名称和行为一致。OpenCode 额外提供 `models`，
Antigravity 额外提供 `login` 和 `usage`，用于各自特有的工作流。

## 适用场景

当你维护多个提供商或账号，并希望用可重复的方式完成切换、验证、备份和故障排查时，
可以使用这些 CLI。修改类命令支持 `--dry-run`，失败时返回非零状态码，因此也适合脚本调用。

本项目不会创建提供商订阅，不会安装目标 Codex、OpenCode 或 Antigravity CLI，也不会绕过
提供商认证。它只管理你已有并有权使用的配置和凭据。

## 快速开始

```bash
pipx install git+https://github.com/Fel1xKan/codex-provider.git
codex-provider status
```

如果你使用的是另外两个工具，将第二条命令替换为 `opencode-provider status` 或
`agy-provider status`。

## 安装

### 使用 pipx

```bash
pipx install git+https://github.com/Fel1xKan/codex-provider.git
```

该命令会在隔离的 Python 环境中安装全部三个 CLI。升级命令为：

```bash
pipx upgrade opencode-provider
```

### 独立二进制文件

[GitHub Releases 页面][release-url]提供 Linux 和 Windows 二进制文件以及对应的 SHA-256
校验文件。独立二进制文件不需要本地 Python 环境。

## 使用方法

### 切换、检查并验证提供商

```bash
codex-provider list
codex-provider switch my-provider --dry-run
codex-provider switch my-provider
codex-provider status
codex-provider doctor
codex-provider test my-provider
```

省略 `switch` 的提供商参数会打开交互式选择器，最近使用的提供商会排在前面。`doctor`
检查保存的配置和认证数据，`test` 则探测提供商接口。

### 使用后端专属能力

```bash
opencode-provider models list my-provider
opencode-provider models sync my-provider --dry-run
agy-provider login work-account
agy-provider usage work-account
```

OpenCode 模型同步只添加新 ID，并保留现有元数据。Antigravity `usage` 会在不切换账号的
情况下显示 5 小时和每周配额。端到端 `ping`、批量检查、提供商生命周期操作，以及 JSON
备份和恢复方式见[命令参考](docs/command-reference.md)。

## 安全保证

- 检查命令不会打印 API 密钥或认证值。
- 配置采用原子写入，并保留现有 POSIX 权限。
- OpenCode 的 JSONC 注释、尾逗号和无关全局配置会被保留。
- 工具会遵守提供商过滤规则，避免误选已禁用的提供商。
- `switch`、`add`、`delete`、`rename`、`import` 以及支持的账号操作提供预演模式。
- 工具拒绝把 API 密钥作为位置参数传入；请使用隐藏输入或 `--api-key-stdin`。

## 命令参考

三个 CLI 提供一致的提供商管理命令，并分别扩展 OpenCode 模型发现和 Antigravity 账号工作流。
参考文档还包含文件位置、切换行为、秘密处理和退出码语义。

→ [查看完整命令参考（英文）](docs/command-reference.md)

## 前置条件

| 要求 | 何时需要 |
|------|----------|
| Python 3.11+ 与 `pipx` | 从源码安装 |
| Codex、OpenCode 或 Antigravity CLI | 执行对应工具的原生 `ping` 命令 |
| 网络连接 | 提供商测试、模型发现、登录和配额查询 |

## 参与贡献

仓库包含镜像式 CLI 一致性测试、隔离文件系统测试、静态检查和跨平台 PyInstaller 构建。

→ [查看贡献、测试、构建和发布指南（英文）](CONTRIBUTING.md)

## 许可证

本项目基于 MIT License 分发，详情见 [LICENSE](LICENSE)。

---

[license-shield]: https://img.shields.io/badge/License-MIT-green.svg
[license-url]: LICENSE
[release-shield]: https://img.shields.io/github/v/release/Fel1xKan/codex-provider
[release-url]: https://github.com/Fel1xKan/codex-provider/releases
[ci-shield]: https://img.shields.io/github/actions/workflow/status/Fel1xKan/codex-provider/ci.yml?branch=master
[ci-url]: https://github.com/Fel1xKan/codex-provider/actions/workflows/ci.yml
[python-shield]: https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white
[python-url]: https://www.python.org/downloads/
