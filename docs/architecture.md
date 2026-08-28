# 架构与扩展指南

五个 CLI（`cpx` / `opx` / `apx` / `cupx` / `clpx`，旧长名 `codex-provider` 等只打印改名提示）共享同一套命令定义与执行框架，后端只负责各自配置格式、凭据模型和 switch 语义的适配。

## 命令定义：单一来源

`src/lib/common/registry.py` 是命令的唯一事实来源：

- `CommandSpec` 声明命令名、别名、帮助、参数、子命令和能力门控；
- `COMMON_COMMANDS` 是所有 CLI 共用的命令表（list/status/auth/config/doctor/test/ping/switch/add/delete/rename/export/import）；
- 后端通过 `capabilities`、`extra_commands`、`command_args`、`command_help` 声明差异（如 opencode 的 `models`、agy 的 `usage`/`login`）；
- `build_parser_for(backend)` 从注册表生成解析器，所有 CLI 的 `--help` 与参数形状由此而来。

修改共享命令只改注册表，所有 CLI 自动同步，不再需要逐份维护 `build_parser`/`main`。

## 后端适配器

`src/lib/common/backend.py` 定义 `BaseBackend`：一个后端只需实现协议方法（list/status/switch/add/delete/rename/auth/config/doctor/test/ping/export/import），共享执行器（`src/lib/common/cli.py` 的 `generic_main` 与各 handler）负责分发、交互选择、dry-run、错误措辞和退出码。

## 共享 vs 私有边界

| 层 | 归属 | 内容 |
|---|---|---|
| 命令面 | `common/registry.py` | 命令表、解析器生成、帮助 |
| 执行分发 | `common/cli.py` | `generic_main`、switch/test/ping 共享 handler |
| 网络与协议 | `common/network.py` | `fetch_provider_models`、`run_models_test`、`WireProtocol` |
| 变更提交 | `common/common_store.py` | `FileChange` + `apply_changes`（快照、原子写、回滚） |
| 传输骨架 | `common/transfer.py` | 导入读取/类型校验、导出原子写入 |
| 批量流程 | `common/backend.py` | `test --all` / `ping --all` 遍历汇总（`TestTarget`、`ping_entries`） |
| 配置格式 | 各 `lib/<provider>/store.py`、`patch.py` | TOML / JSONC / agy store |
| 凭据模型 | 各 `lib/<provider>/admin.py` | auth profile / auth.json / OAuth |
| switch 语义 | 各 `lib/<provider>/switch.py`、`commands.py` | 注入 runtime provider / 改 model 字段 / 切 account |
| 专属命令 | `models`（opencode/cursor）、`provider`（cursor）、`usage`/`login`（agy） | 由能力门控声明 |

## 接入新 agent

1. 新建 `src/lib/<agent>/store.py`：实现配置解析与凭据读取；
2. 新建 `src/lib/<agent>/backend.py`：继承 `BaseBackend` 并实现协议方法（主要是格式适配）；
3. 新建 `src/cli/<agent>_provider.py`：约 30 行的转发壳，复用 `generic_main`；
4. 自动获得全部共享命令、帮助文本、dry-run/锁/回滚语义；
5. 只写差异化：配置 patch、`WireProtocol` 映射、专属命令。

成本估算：OpenAI 兼容 + JSON/TOML 配置的 agent 约半天到一天，核心工作从"复制一套 CLI"降为"写一个配置适配器"。
