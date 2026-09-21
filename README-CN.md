<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset=".github/logo-light.svg">
    <img alt="xpx" src=".github/logo-light.svg" width="440">
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
  <a href="#核心特性">核心特性</a> &middot;
  <a href="#使用指南">使用指南</a> &middot;
  <a href="docs/command-reference.md">命令参考</a> &middot;
  <a href="docs/architecture.md">架构设计</a> &middot;
  <a href="https://github.com/Fel1xKan/codex-provider/issues/new?labels=bug">反馈问题</a>
</div>

> 面向 Codex、OpenCode、Claude、Cursor、Antigravity 和 Pi 的统一 AI Coding Agent 控制中枢。

---

## 为什么选择 xpx？

现代 AI 辅助编程工具（如 Codex、OpenCode、Claude Code、Cursor、Antigravity、Pi 等）在本地存储提供商、凭据和模型配置的方式各不相同（TOML、JSON、SQLite、环境配置文件等）。当你需要维护多个第三方 API（如 DeepSeek、OpenRouter、SiliconFlow）、切换企业与个人账号、或在不同工具间共享配置时，手动修改配置文件不仅极其繁琐，而且极易出现语法错误或泄露凭据。

**`xpx` 将所有 AI Coding Agent 的配置收敛至统一控制平面。** 你只需在 `~/.xpx/` 中一次性录入 Provider 资产或账号，即可通过 `xpx apply` 将配置一键渲染分发至任何客户端，并具备自动记忆机制与零端侧污染保障。

---

## 支持的客户端矩阵

| 目标客户端 | 配置文件路径 | 支持的差异化能力 |
|------------|--------------|------------------|
| **Codex** | `~/.codex/config.toml` | 自定义提供商、Fast 模式、Wire API、联网搜索、Reasoning 阶梯 |
| **OpenCode** | `opencode.json` (XDG 目录) | 提供商自动发现、模型目录同步、保持 JSONC 格式与注释 |
| **Claude Code** | `~/.claude/settings.json` | Anthropic 兼容端点、默认模型注入 |
| **Cursor** | `state.vscdb` (SQLite 数据库) | 自定义 OpenAI 兼容提供商、模型切换、官方账号快照 |
| **Antigravity** | `~/.gemini/antigravity-cli` | Google OAuth 登录、会话切换、5 小时与每周配额余量查询 |
| **Pi Agent** | `~/.pi/agent/models.json` / `config.yaml` | 多模型定义、自定义 Provider |

---

## 核心特性

- **动静分离与副作用唯一收敛**：`xpx add`、`xpx auth set`、`xpx config set`、`xpx models sync` 等命令**仅读写 `~/.xpx/` 目录**。对任何外部客户端原生配置的修改 100% 收敛在 `xpx apply` 域下。
- **客户端专属参数自动记忆**：在执行 `xpx apply codex deepseek --fast` 时，系统不仅完成渲染，还会自动持久化记住 `--fast`，下次执行 `xpx apply codex deepseek` 无需重复敲参。
- **全景控制大盘**：运行 `xpx status` 一键查看所有客户端当前激活的 Provider、主力模型、状态指示灯与配额余量。
- **全端并发连通性测试**：运行 `xpx ping --all` 自动并发拉起本机所有已安装的 Agent CLI，发送微测试 prompt 验证全链路端到端可用性。
- **内置模型与 Reasoning 知识库**：自动从上游官方文档补充上下文窗口大小、最大输出 token 与思维链档位（`xpx models sync`）。
- **完整账号生命周期**：支持原生 OAuth 登录与本地已登录会话快照（`xpx account login`、`xpx account snapshot`、`xpx account usage`）。
- **全端健康巡检**：运行 `xpx doctor [--fix]` 校验各客户端配置文件语法、测试网络可用性并自动修复孤儿状态。
- **零 Python 运行时依赖**：提供单个独立二进制可执行文件，内置无缝自升级命令（`xpx upgrade`）。

---

## 快速开始

### 独立二进制安装（推荐）

Linux / macOS：
```bash
curl -LsSf https://raw.githubusercontent.com/Fel1xKan/codex-provider/master/scripts/install.sh | sh
```

Windows (PowerShell)：
```powershell
irm https://raw.githubusercontent.com/Fel1xKan/codex-provider/master/scripts/install.ps1 | iex
```

### 使用 pipx 安装

```bash
pipx install git+https://github.com/Fel1xKan/codex-provider.git
```

---

## 使用指南

### 1. 录入与管理 Provider

```bash
# 交互式输入 API Key 录入提供商
xpx add deepseek https://api.deepseek.com/v1 --default-model deepseek-reasoner

# 或通过管道标准输入传入 Key
echo "sk-secret" | xpx add openrouter https://openrouter.ai/api/v1 --key-stdin

# 查看所有已保存的 Provider 资产
xpx list

# 更新 API Key（若有客户端正在激活该 Provider，会自动重放渲染刷新）
xpx auth set deepseek --key "sk-new-key"
```

### 2. 生效与分发至客户端 (Apply)

```bash
# 生效至 Codex 并开启 fast 模式（会自动记住 fast 偏好）
xpx apply codex deepseek --fast

# 同时分发至多个目标客户端
xpx apply codex,opencode deepseek

# 全量分发至本机所有已安装客户端
xpx apply --all deepseek

# 仅切换当前客户端的模型（保持 Provider 不变）
xpx apply opencode :deepseek-chat

# 预演变更（查看 diff，不真正写入文件）
xpx apply codex deepseek --dry-run

# 重置客户端并切回官方默认登录态
xpx apply codex --reset
```

### 3. 同步模型目录与思维链阶梯

```bash
# 拉取远端模型列表并自动合并元数据与思考档位
xpx models sync deepseek

# 查看缓存的模型列表
xpx models list deepseek

# 设置默认模型与默认思考强度
xpx models set deepseek-reasoner deepseek --default --effort high
```

### 4. 账号生命周期与配额查询

```bash
# 唤起官方 OAuth 授权（如 Antigravity 的 Google OAuth）
xpx account login agy work

# 查看 Antigravity 5 小时和每周配额使用情况
xpx account usage agy work

# 快照当前已登录的官方会话或 Cursor 本地认证
xpx account snapshot codex official-work
xpx account snapshot cursor personal
```

### 5. 观测、诊断与健康巡检

```bash
# 查看全景控制大盘
xpx status

# 全端健康检查与孤儿状态修复
xpx doctor --fix

# HTTP 接口探测
xpx test --all

# 全端并发端到端 ping 测试
xpx ping --all
```

### 6. 迁移、备份与升级

```bash
# 预演旧工具（cpx, opx, apx, cupx, clpx）历史配置探测结果
xpx migrate --dry-run

# 一键将所有旧工具配置与账号资产迁移导入至 ~/.xpx/
xpx migrate

# 从指定配置文件或 JSON 备份中导入
xpx import backup.json

# 导出全量中枢配置至单一 JSON 备份
xpx export backup.json

# 检查并自升级至最新发布版本
xpx upgrade
```

---

## 深入了解

- [命令详细规范](docs/command-reference.md)：各个命令的位置参数、选项说明与终端输出格式。
- [架构设计指南](docs/architecture.md)：控制中枢分层设计理念、数据拓扑与 TargetAdapter 扩展开发指南。
- [贡献指南](CONTRIBUTING.md)：本地开发、测试与跨平台打包构建流程。

---

## 许可证

本项目遵循 MIT 许可证。详见 [LICENSE](LICENSE) 文件。

[license-shield]: https://img.shields.io/badge/License-MIT-green.svg
[license-url]: LICENSE
[release-shield]: https://img.shields.io/github/v/release/Fel1xKan/codex-provider
[release-url]: https://github.com/Fel1xKan/codex-provider/releases
[ci-shield]: https://img.shields.io/github/actions/workflow/status/Fel1xKan/codex-provider/ci.yml?branch=master
[ci-url]: https://github.com/Fel1xKan/codex-provider/actions/workflows/ci.yml
[python-shield]: https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white
[python-url]: https://www.python.org/downloads/
