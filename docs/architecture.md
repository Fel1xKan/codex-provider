# 架构与扩展指南 (xpx 2.0.0)

`xpx` 是开发者本机所有 AI Coding Agent 的统一 Provider 资产池、OAuth 账号管家与运行时配置中枢（Unified AI Agent Control Plane）。

## 核心设计哲学

1. **动静分离与副作用唯一收敛（Single Point of Mutation）**：
   - **中枢资产操作（纯静态、零副作用）**：`xpx add`、`xpx delete`、`xpx auth set`、`xpx config set`、`xpx models sync` 等命令**只操作 `~/.xpx/` 目录内部的数据**，严禁触碰或修改任何外部 Agent 的原生配置文件。
   - **客户端配置落地（唯一副作用收敛在 `apply`）**：所有修改、生成、重置外部 Agent 客户端原生配置的行为，100% 且唯一收敛在 `xpx apply` 域下。
2. **二维配置矩阵与两层继承（Universal Base + Target Overrides）**：
   - **通用层（Universal Base）**：Provider 的核心凭据和基础地址（`base_url`、`api_key`、`protocol`、`default_model`）属于全局共有资产。
   - **客户端专属层（Target Overrides）**：特定 Agent 的特异性需求绑定在 `(provider, target)` 档案下。
   - **自动记忆机制**：当执行 `xpx apply <target> <provider> [options]` 时，系统自动将专属选项持久化记入该 Target 专属档案中。
3. **Target Adapter 插件化架构（Open-Closed Principle）**：
   - 核心中枢与具体 Target 客户端代码物理隔离。
   - 每个 Target 客户端（Codex, OpenCode, Cursor, Claude, AGY, Pi）作为一个独立的 `TargetAdapter` 插件实现。

## 架构拓扑图

```text
                                  ┌─────────────────────────────┐
                                  │      用户终端交互入口        │
                                  │   (xpx 单一二进制可执行文件) │
                                  └──────────────┬──────────────┘
                                                 │
                   ┌─────────────────────────────┴─────────────────────────────┐
                   ▼                                                           ▼
    ┌──────────────────────────────┐                            ┌──────────────────────────────┐
    │    中枢管理域 (Store/Hub)    │                            │    分发执行域 (Apply Engine) │
    │   【只读写 ~/.xpx/ 数据】    │                            │   【唯一具有外部端侧副作用】 │
    │                              │                            │                              │
    │  • Provider 资产池 (JSON)    │                            │  根据 (Provider, Target) 矩阵│
    │  • Account 登录态 (JSON)     │                            │  提取并合并专属覆盖参数      │
    │  • Models 元数据知识库       │                            └──────────────┬───────────────┘
    └──────────────┬───────────────┘                                           │
                   │ 读取数据                                                   ▼
                   └───────────────────────────► ┌──────────────────────────────────────────────┐
                                                 │       Target Adapter 适配器层                │
                                                 │  (统一接口: detect, get_status, apply, reset)│
                                                 └──────┬────────┬────────┬────────┬────────────┘
                                                        │        │        │        │
                   ┌────────────────────────────────────┘        │        │        └───────────────────────────────┐
                   ▼                                             ▼        ▼                                        ▼
    ┌──────────────────────────────┐              ┌──────────────┐ ┌──────────────┐          ┌─────────────────────────────┐
    │       Codex Adapter          │              │OpenCode Adp. │ │  Pi Adapter  │          │       Cursor Adapter        │
    │   ~/.codex/config.toml       │              │opencode.json │ │ ~/.pi/config │          │ state.vscdb (SQLite 数据库) │
    └──────────────────────────────┘              └──────────────┘ └──────────────┘          └─────────────────────────────┘
```

## 代码模块组织

```text
src/
├── cli/
│   └── xpx.py                     # 统一 CLI 主入口
├── lib/
│   ├── common/                    # 基础公用库 (constants, errors, common_store, self_upgrade, oscrypt)
│   └── xpx/                       # 统一控制平面核心
│       ├── store/                 # 中枢持久化 (provider_store, account_store, state_store)
│       ├── models/                # 模型拉取与元数据合并 (remote_sync, catalog_merge)
│       ├── adapters/              # 客户端适配器插件体系 (base, registry, codex, opencode, cursor, claude, agy, pi)
│       ├── commands/              # CLI 各域业务逻辑 (cmd_apply, cmd_provider, cmd_auth, cmd_config, cmd_status, etc.)
│       └── parser.py              # 全量 argparse 解析器构建
```

## 接入新 Agent 流程

1. 在 `src/lib/xpx/adapters/` 下新建 `<target>.py`，继承 `TargetAdapter` 基类；
2. 实现四个核心方法：
   - `detect() -> bool`：检测本地是否已安装或配置该 Agent；
   - `get_status() -> AdapterStatus`：返回当前激活的 Provider/Model/Account；
   - `apply(spec, model, options, dry_run) -> ApplyResult`：将配置渲染到该 Agent 原生配置文件；
   - `reset(dry_run) -> ApplyResult`：清理注入项并还原官方配置；
3. 在 `src/lib/xpx/adapters/registry.py` 的注册表追加注册；
4. 运行 `./.venv/bin/python -m pytest tests/` 进行全套适配器测试与回归验证。
