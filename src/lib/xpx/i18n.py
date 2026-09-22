from __future__ import annotations

import json
import locale
import os
from typing import Any

from lib.xpx.store import ensure_xpx_dirs, get_xpx_home

_CURRENT_LANGUAGE: str | None = None


def detect_system_language() -> str:
    """Detect default language: 'zh' for Chinese environments, 'en' otherwise."""
    env_lang = os.environ.get("XPX_LANG")
    if env_lang:
        clean = env_lang.strip().lower()
        if clean.startswith("zh") or clean in ("cn", "chinese"):
            return "zh"
        return "en"

    # Check saved setting in ~/.xpx/settings.json
    try:
        settings_file = get_xpx_home() / "settings.json"
        if settings_file.is_file():
            data = json.loads(settings_file.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("language"):
                lang = str(data["language"]).strip().lower()
                return "zh" if lang.startswith("zh") else "en"
    except Exception:
        pass

    # Check system environment locale
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(var, "")
        if val:
            val_lower = val.lower()
            if "zh" in val_lower or "chinese" in val_lower or "cn" in val_lower:
                return "zh"

    try:
        sys_loc = locale.getlocale()[0]
        if sys_loc and "zh" in sys_loc.lower():
            return "zh"
    except Exception:
        pass

    return "en"


def get_language() -> str:
    """Returns the currently active language ('zh' or 'en')."""
    global _CURRENT_LANGUAGE
    if _CURRENT_LANGUAGE is None:
        _CURRENT_LANGUAGE = detect_system_language()
    return _CURRENT_LANGUAGE


def set_language(lang: str, *, persist: bool = False) -> None:
    """Set active language ('zh' or 'en') and optionally persist to settings.json."""
    global _CURRENT_LANGUAGE
    norm = "zh" if lang.strip().lower().startswith("zh") else "en"
    _CURRENT_LANGUAGE = norm

    if persist:
        try:
            home = ensure_xpx_dirs()
            settings_file = home / "settings.json"
            current_data: dict[str, Any] = {}
            if settings_file.is_file():
                try:
                    current_data = json.loads(settings_file.read_text(encoding="utf-8"))
                except Exception:
                    current_data = {}
            current_data["language"] = norm
            settings_file.write_text(
                json.dumps(current_data, indent=2), encoding="utf-8"
            )
        except Exception:
            pass


MESSAGES: dict[str, dict[str, str]] = {
    "zh": {
        # Select & Checkbox primitives
        "ui.filter_label": "过滤",
        "ui.no_matches": "(无匹配选项)",
        "ui.overflow_up": "▲ ... (上方还有 {count} 项)",
        "ui.overflow_down": "▼ ... (下方还有 {count} 项)",
        "ui.selected_badge": "(已选 {selected}/{total})",
        "ui.hint_select": (
            "[↑/↓/滚轮: 移动 | Enter: 确认 | 直接输入: 过滤 | Esc: 返回上一步]"
        ),
        "ui.hint_checkbox": (
            "[空格: 勾选/取消 | a: 全选 | 回车: 确认 | Esc: 返回上一步]"
        ),
        "ui.hint_prompt_def": "(默认: {default} | Esc: 返回)",
        "ui.hint_prompt_nodef": "(Esc: 返回)",
        "ui.min_one_required": "请至少勾选 1 项（按空格键进行勾选）",
        "ui.yes": "是 (Yes)",
        "ui.no": "否 (No)",
        "ui.press_enter": "按 Enter 键返回...",
        "ui.cancelled": "操作已取消。",
        "ui.exit_msg": "已退出 xpx 交互模式。",
        "ui.back": "< 返回",
        "ui.back_menu": "< 返回主菜单",
        "ui.action_confirm": "🚀 确认执行 (Enter)",
        "ui.action_back": "↩ 返回上一步修改 (Esc)",
        # Banner & Main Menu
        "banner.title": "xpx · 统一 AI Agent 控制平面",
        "banner.default_state": "(当前各客户端均处于官方默认状态)",
        "main.prompt": "请选择要执行的操作",
        "main.apply": "⚡ 快速切换 (Apply)",
        "main.apply_desc": "切换客户端绑定的 Provider / 模型 / 账号",
        "main.status": "📊 状态看板 (Status)",
        "main.status_desc": "查看所有客户端与提供商详细生效状态",
        "main.agents": "🛠️ 客户端管理 (Agents)",
        "main.agents_desc": "安装与升级各 Agent CLI (Codex, Claude 等)",
        "main.providers": "🏢 供应商管理 (Providers)",
        "main.providers_desc": "新增、查看、修改 API Key / 远程同步",
        "main.models": "🤖 模型与偏好 (Models)",
        "main.models_desc": "拉取模型列表、配置默认模型与思考强度",
        "main.doctor": "🩺 健康诊断与测速 (Doctor & Ping)",
        "main.doctor_desc": "连通性测速、排查与自愈配置故障",
        "main.accounts": "👤 账号管理 (Accounts)",
        "main.accounts_desc": "OAuth 账号登录、用量与配额查看",
        "main.language": "🌐 语言设置 (Language)",
        "main.language_desc": "切换显示语言 (中文 / English)",
        "main.exit": "🚪 退出 (Exit)",
        "main.exit_desc": "退出交互模式",
        # Apply Wizard
        "apply.title": "=== 快速切换 (Apply 向导) ===",
        "apply.target_prompt": (
            "请勾选目标客户端 (按 [空格] 勾选/取消，按 [a] 全选，Esc 返回)"
        ),
        "apply.no_targets": "未检测到受支持的客户端（Codex, Claude, Cursor 等）。",
        "apply.mode_prompt": "[{targets}] 请选择切换类型 (Esc 返回上一步)",
        "apply.mode_provider": "预设 Provider 供应商",
        "apply.mode_provider_desc": "切换至配置好的 API 代理或大模型提供商",
        "apply.mode_account": "OAuth / Session 账号",
        "apply.mode_account_desc": "切换至 Google / GitHub / Agy 等已登录账号",
        "apply.mode_reset": "恢复为官方默认状态",
        "apply.mode_reset_desc": "清除第三方代理，恢复客户端初始设置",
        "apply.account_none": ("暂无已保存的 OAuth 账号。请先通过账号管理进行登录。"),
        "apply.account_prompt": "请选择要绑定的账号 (Esc 返回上一步)",
        "apply.provider_none": "暂无配置的 Provider。请先添加一个 Provider。",
        "apply.provider_prompt": (
            "请选择要绑定的 Provider (输入文字可实时过滤，Esc 返回上一步)"
        ),
        "apply.model_prompt": "[{provider}] 选择应用的模型 (Esc 返回上一步)",
        "apply.model_default": "[默认模型] {model}",
        "apply.model_default_desc": "供应商推荐主力模型",
        "apply.model_default_tag": "推荐主力",
        "apply.model_keep": "保持各客户端当前已绑定的模型不变",
        "apply.model_keep_desc": "保持各客户端当前已绑定的活跃模型不变",
        "apply.model_custom": "手动输入自定义 Model ID...",
        "apply.model_custom_desc": "手动输入未在列表中的私有/特定 Model ID",
        "apply.model_custom_prompt": (
            "请输入 Model ID (如 deepseek-reasoner，Esc 返回)"
        ),
        "apply.model_sync_remote": "在线同步该供应商最新模型列表...",
        "apply.model_sync_remote_desc": "请求 /models 接口拉取并更新可用模型",
        "apply.model_sync_connecting": "正在连接 {url}/models 获取模型列表...",
        "apply.model_sync_success": "成功拉取并同步了 {count} 个可用模型！",
        "apply.model_sync_failed": "拉取远端模型列表失败: {err}",
        "apply.gate_prompt": "准备就绪，如何处理？(Esc 返回上一步)",
        "apply.gate_now": "🚀 立即应用生效",
        "apply.gate_now_desc": "使用推荐的默认参数直接生效",
        "apply.gate_adv": "⚙️  微调高级参数...",
        "apply.gate_adv_desc": "配置 Fast 模式 / 联网搜索 / Wire-API / 仅预览",
        "apply.gate_adv_desc_non_codex": (
            "配置仅预览 (--dry-run) / 临时生效 (--no-save) 等"
        ),
        "apply.adv_prompt": (
            "请勾选需要启用的高级开关 (按 [空格] 勾选，[回车] 确定，Esc 返回)"
        ),
        "apply.flag_fast": "开启 Fast 模式 (--fast)",
        "apply.flag_fast_desc": "加速响应与代码补全",
        "apply.flag_web_search": "开启联网搜索 (--web-search)",
        "apply.flag_web_search_desc": "允许模型联网查询",
        "apply.flag_dry_run": "仅预览不实际修改 (--dry-run)",
        "apply.flag_dry_run_desc": "演练配置变更效果",
        "apply.flag_no_save": "不持久化到配置 (--no-save)",
        "apply.flag_no_save_desc": "仅本次临时生效",
        "apply.wire_prompt": "Codex Wire API 模式 (可选，Esc 返回)",
        "apply.wire_default": "保持默认 (不指定)",
        "apply.confirm_card_title": "最终配置确认",
        "apply.confirm_prompt": "请确认是否立即执行上述变更？",
        # Providers Wizard
        "pv.title": "=== 供应商管理 (Providers) ===",
        "pv.action_prompt": "请选择操作 (Esc 返回主菜单)",
        "pv.browse": "📋 浏览与管理现有供应商 (共 {count} 个)",
        "pv.add": "➕ 添加新供应商 (向导)",
        "pv.sync_all": "🔄 批量同步远程模型 (Models Sync)",
        "pv.add_title": "--- 添加新供应商 ---",
        "pv.name_prompt": "供应商名称 (例如 deepseek, openrouter，Esc 取消)",
        "pv.url_prompt": "[{name}] API Base URL (Esc 返回上一步)",
        "pv.proto_prompt": "[{name}] 协议类型 (Esc 返回上一步)",
        "pv.key_prompt": "[{name}] API Key (掩码隐藏，可留空，Esc 返回上一步)",
        "pv.model_prompt": "[{name}] 默认主力模型 (可选，Esc 返回上一步)",
        "pv.confirm_add_title": "确认添加供应商",
        "pv.confirm_add_prompt": "确认添加供应商 '{name}'？",
        "pv.add_success": "✔ 供应商 '{name}' 添加成功！",
        "pv.select_manage": "请选择要查看或管理的供应商 (Esc 返回)",
        "pv.details_title": "--- 供应商详情: {name} ---",
        "pv.action_auth_set": "🔑 修改 / 更新 API Key",
        "pv.action_model_set": "🎯 切换 / 设置默认模型 (Model)",
        "pv.action_sync": "🔄 同步远程模型列表 (Models Sync)",
        "pv.action_test": "⚡ 测试连接与延迟 (Test)",
        "pv.action_delete": "🗑️  删除此供应商 (Delete)",
        "pv.delete_confirm": "确定要彻底删除供应商 '{name}' 吗？",
        "pv.model_updated": "✔ 供应商 '{name}' 的默认模型已更新为 '{model}'！",
        # Doctor & Ping Wizard
        "doc.title": "=== 健康体检与网络测速 ===",
        "doc.doctor": "🩺 运行系统体检 (Doctor 检查损坏配置)",
        "doc.doctor_fix": "🔧 运行系统体检并自动修复 (--fix)",
        "doc.test": "⚡ 批量测试 Provider /models 响应延迟",
        "doc.ping": "💬 端到端 Prompt 连通性测试 (Ping)",
        "doc.fix_confirm": "确认执行 Doctor 自动修复？",
        "doc.test_prompt": (
            "请勾选要测速的 Provider (空格勾选，a 全选，回车确认，Esc 返回)"
        ),
        "doc.test_confirm": "确认对勾选的 {count} 个 Provider 进行延迟测速？",
        "doc.ping_client_prompt": "选择测试客户端 (Esc 返回)",
        "doc.ping_prompt": "发送的测试 Prompt (Esc 取消)",
        "doc.ping_confirm": "确认在 '{target}' 上运行 Prompt Ping？",
        # Models Wizard
        "models.title": "=== 模型与偏好管理 (Models) ===",
        "models.select_pv": ("请选择要查看或同步模型的 Provider (Esc 返回主菜单)"),
        "models.list": "📋 查看已缓存的模型列表",
        "models.sync": "🌐 立即从远端同步最新模型 (Sync)",
        "models.sync_confirm": "确认同步 '{name}' 的远程模型列表？",
        # Accounts Wizard
        "acc.title": "=== 账号管理 (Accounts) ===",
        "acc.list": "📋 查看已保存的账号列表",
        "acc.login": "🔑 登录新账号 (OAuth Login)",
        "acc.usage": "📊 查询账号配额与用量 (Usage)",
        "acc.select_target": "选择目标客户端 (如 agy，Esc 返回)",
        "acc.alias_prompt": "账号别名 (可选，如 personal / work，Esc 取消)",
        "acc.login_confirm": "确认启动 '{target}' 登录向导？",
        # Agent Wizard
        "agent.title": "=== Agent 客户端管理 ===",
        "agent.select_install": "请选择要安装的客户端 (Esc 返回)",
        "agent.select_update": "请选择要更新的客户端 (Esc 返回)",
        "agent.install_all": "一键安装全部缺失客户端",
        "agent.update_all": "一键更新全部已安装客户端",
        "agent.confirm_install": "确认安装客户端 '{name}'？",
        "agent.confirm_install_all": "确认一键安装所有 {count} 个缺失的客户端？",
        "agent.confirm_update": "确认更新客户端 '{name}'？",
        "agent.confirm_update_all": "确认一键更新所有 {count} 个已安装的客户端？",
        "agent.all_installed": "所有支持的 Agent CLI 均已安装。",
        "agent.no_installed": "未检测到已安装的 Agent CLI。",
        "agent.action_install_missing": "📥 一键安装缺失客户端",
        "agent.action_update_all": "🔄 一键更新已安装客户端",
        "agent.action_list": "📋 查看客户端列表与版本",
        "agent.not_installed": "未安装",
    },
    "en": {
        # Select & Checkbox primitives
        "ui.filter_label": "Filter",
        "ui.no_matches": "(No matching options)",
        "ui.overflow_up": "▲ ... ({count} more above)",
        "ui.overflow_down": "▼ ... ({count} more below)",
        "ui.selected_badge": "({selected}/{total} selected)",
        "ui.hint_select": (
            "[↑/↓/Scroll: Navigate | Enter: Select | Type: Filter | Esc: Back]"
        ),
        "ui.hint_checkbox": ("[Space: Toggle | a: All | Enter: Confirm | Esc: Back]"),
        "ui.hint_prompt_def": "(Default: {default} | Esc: Back)",
        "ui.hint_prompt_nodef": "(Esc: Back)",
        "ui.min_one_required": (
            "Please select at least 1 item (press Space to toggle)"
        ),
        "ui.yes": "Yes",
        "ui.no": "No",
        "ui.press_enter": "Press Enter to return...",
        "ui.cancelled": "Operation cancelled.",
        "ui.exit_msg": "Exited xpx interactive mode.",
        "ui.back": "< Back",
        "ui.back_menu": "< Back to Main Menu",
        "ui.action_confirm": "🚀 Confirm Execution (Enter)",
        "ui.action_back": "↩ Back to Previous Step (Esc)",
        # Banner & Main Menu
        "banner.title": "xpx · Unified AI Agent Control Plane",
        "banner.default_state": "(All clients currently in official default state)",
        "main.prompt": "Please select an action",
        "main.apply": "⚡ Quick Apply (Apply)",
        "main.apply_desc": "Switch Provider, Model, or Account for target clients",
        "main.status": "📊 Status Dashboard (Status)",
        "main.status_desc": ("Inspect global client and provider binding status"),
        "main.agents": "🛠️ Agent Management (Agents)",
        "main.agents_desc": "Install and update Agent CLIs (Codex, Claude, etc.)",
        "main.providers": "🏢 Provider Assets (Providers)",
        "main.providers_desc": ("Manage API providers, endpoints, and credentials"),
        "main.models": "🤖 Models & Preferences (Models)",
        "main.models_desc": (
            "Synchronize remote models and configure reasoning options"
        ),
        "main.doctor": "🩺 Health & Testing (Doctor & Ping)",
        "main.doctor_desc": ("Run system health check, auto-repair, and latency test"),
        "main.accounts": "👤 Account Management (Accounts)",
        "main.accounts_desc": ("OAuth account login, usage, and quota management"),
        "main.language": "🌐 Language (语言设置)",
        "main.language_desc": "Switch display language (English / 中文)",
        "main.exit": "🚪 Exit (Exit)",
        "main.exit_desc": "Exit interactive mode",
        # Apply Wizard
        "apply.title": "=== Quick Apply Wizard ===",
        "apply.target_prompt": (
            "Select target client(s) (Space: toggle, a: all, Esc: back)"
        ),
        "apply.no_targets": (
            "No supported clients detected (Codex, Claude, Cursor, etc.)."
        ),
        "apply.mode_prompt": "[{targets}] Select switch type (Esc: back)",
        "apply.mode_provider": "API Provider",
        "apply.mode_provider_desc": (
            "Switch to a configured API provider or model proxy"
        ),
        "apply.mode_account": "OAuth / Session Account",
        "apply.mode_account_desc": (
            "Switch to a saved Google / GitHub / Agy OAuth account"
        ),
        "apply.mode_reset": "Reset to Official Default",
        "apply.mode_reset_desc": (
            "Clear custom proxy and restore official client settings"
        ),
        "apply.account_none": (
            "No saved OAuth accounts. Please log in via Account first."
        ),
        "apply.account_prompt": "Select account to apply (Esc: back)",
        "apply.provider_none": (
            "No providers configured. Please add an API provider first."
        ),
        "apply.provider_prompt": "Select Provider (Type to filter, Esc: back)",
        "apply.model_prompt": "[{provider}] Select model to apply (Esc: back)",
        "apply.model_default": "[Default Model] {model}",
        "apply.model_default_desc": "Recommended primary model",
        "apply.model_default_tag": "Default",
        "apply.model_keep": "Keep target clients' current active models",
        "apply.model_keep_desc": "Retain currently active models on target clients",
        "apply.model_custom": "Enter custom Model ID...",
        "apply.model_custom_desc": "Manually enter private or custom model ID",
        "apply.model_custom_prompt": (
            "Enter Model ID (e.g. deepseek-reasoner; Esc: back)"
        ),
        "apply.model_sync_remote": "Fetch & sync latest models from provider...",
        "apply.model_sync_remote_desc": (
            "Query /models endpoint to discover all available models"
        ),
        "apply.model_sync_connecting": (
            "Connecting to {url}/models to fetch models..."
        ),
        "apply.model_sync_success": (
            "Successfully discovered and synced {count} models!"
        ),
        "apply.model_sync_failed": "Failed to fetch remote models: {err}",
        "apply.gate_prompt": ("Ready to apply, what would you like to do? (Esc: back)"),
        "apply.gate_now": "🚀 Apply Now",
        "apply.gate_now_desc": ("Apply immediately with recommended defaults"),
        "apply.gate_adv": "⚙️  Tune Advanced Options...",
        "apply.gate_adv_desc": ("Configure Fast mode, Web Search, Wire-API, Dry-Run"),
        "apply.gate_adv_desc_non_codex": ("Configure Dry-Run, No-Save options"),
        "apply.adv_prompt": (
            "Check advanced flags (Space: toggle, Enter: confirm, Esc: back)"
        ),
        "apply.flag_fast": "Enable Fast Mode (--fast)",
        "apply.flag_fast_desc": "Accelerate response and code completions",
        "apply.flag_web_search": "Enable Web Search (--web-search)",
        "apply.flag_web_search_desc": "Allow online web search query",
        "apply.flag_dry_run": "Preview changes only (--dry-run)",
        "apply.flag_dry_run_desc": ("Dry run configuration changes without saving"),
        "apply.flag_no_save": "Do not persist to profile (--no-save)",
        "apply.flag_no_save_desc": (
            "Apply for current session only without writing profile"
        ),
        "apply.wire_prompt": "Codex Wire API Mode (Optional, Esc: back)",
        "apply.wire_default": "Keep default (unspecified)",
        "apply.confirm_card_title": "Final Configuration Confirmation",
        "apply.confirm_prompt": "Confirm executing the changes above?",
        # Providers Wizard
        "pv.title": "=== Provider Management ===",
        "pv.action_prompt": "Select an action (Esc: back to main menu)",
        "pv.browse": "📋 Browse & Manage Existing Providers ({count} total)",
        "pv.add": "➕ Add New Provider (Wizard)",
        "pv.sync_all": "🔄 Synchronize Remote Models for All Providers",
        "pv.add_title": "--- Add New Provider ---",
        "pv.name_prompt": (
            "Provider identifier (e.g. deepseek, openrouter; Esc: cancel)"
        ),
        "pv.url_prompt": "[{name}] API Base URL (Esc: back)",
        "pv.proto_prompt": "[{name}] Protocol Type (Esc: back)",
        "pv.key_prompt": "[{name}] API Key (masked, optional; Esc: back)",
        "pv.model_prompt": "[{name}] Default Primary Model (optional; Esc: back)",
        "pv.confirm_add_title": "Confirm Adding Provider",
        "pv.confirm_add_prompt": "Confirm adding provider '{name}'?",
        "pv.add_success": "✔ Provider '{name}' added successfully!",
        "pv.select_manage": "Select a provider to inspect or manage (Esc: back)",
        "pv.details_title": "--- Provider Details: {name} ---",
        "pv.action_auth_set": "🔑 Update API Key",
        "pv.action_model_set": "🎯 Set / Change Default Model",
        "pv.action_sync": "🔄 Synchronize Remote Models",
        "pv.action_test": "⚡ Test Latency & Connectivity",
        "pv.action_delete": "🗑️  Delete Provider",
        "pv.delete_confirm": (
            "Are you sure you want to permanently delete provider '{name}'?"
        ),
        "pv.model_updated": "✔ Default model for '{name}' updated to '{model}'!",
        # Doctor & Ping Wizard
        "doc.title": "=== Health & Connectivity Testing ===",
        "doc.doctor": "🩺 Run Health Check (Doctor inspects broken configs)",
        "doc.doctor_fix": "🔧 Run Health Check with Auto-Repair (--fix)",
        "doc.test": "⚡ Test Latency across Providers (/models)",
        "doc.ping": "💬 End-to-End Prompt Connectivity Test (Ping)",
        "doc.fix_confirm": "Confirm running Doctor auto-repair?",
        "doc.test_prompt": (
            "Check providers to test (Space: toggle, a: all, Enter: ok, Esc: back)"
        ),
        "doc.test_confirm": ("Confirm latency test for {count} selected providers?"),
        "doc.ping_client_prompt": "Select client for ping test (Esc: back)",
        "doc.ping_prompt": "Test Prompt to send (Esc: cancel)",
        "doc.ping_confirm": "Confirm running Prompt Ping on '{target}'?",
        # Models Wizard
        "models.title": "=== Models & Preferences ===",
        "models.select_pv": "Select Provider to inspect or sync (Esc: back)",
        "models.list": "📋 View cached models catalog",
        "models.sync": "🌐 Synchronize latest remote models (Sync)",
        "models.sync_confirm": "Confirm syncing remote models for '{name}'?",
        # Accounts Wizard
        "acc.title": "=== Account Management ===",
        "acc.list": "📋 List saved accounts",
        "acc.login": "🔑 Log in to new account (OAuth Login)",
        "acc.usage": "📊 Query account quota & usage",
        "acc.select_target": "Select target client (e.g. agy; Esc: back)",
        "acc.alias_prompt": (
            "Account alias (optional, e.g. personal / work; Esc: cancel)"
        ),
        "acc.login_confirm": "Confirm launching login wizard for '{target}'?",
        # Agent Wizard
        "agent.title": "=== Agent CLI Management ===",
        "agent.select_install": "Select agent CLI to install (Esc: back)",
        "agent.select_update": "Select agent CLI to update (Esc: back)",
        "agent.install_all": "Install all missing agent CLIs",
        "agent.update_all": "Update all installed agent CLIs",
        "agent.confirm_install": "Confirm installing agent '{name}'?",
        "agent.confirm_install_all": (
            "Confirm installing all {count} missing agent CLIs?"
        ),
        "agent.confirm_update": "Confirm updating agent '{name}'?",
        "agent.confirm_update_all": (
            "Confirm updating all {count} installed agent CLIs?"
        ),
        "agent.all_installed": "All supported agent CLIs are already installed.",
        "agent.no_installed": "No installed agent CLIs detected.",
        "agent.action_install_missing": "📥 Install Missing Agents",
        "agent.action_update_all": "🔄 Update All Installed Agents",
        "agent.action_list": "📋 View Agent List & Versions",
        "agent.not_installed": "Not installed",
    },
}


def t(key: str, default: str = "", **kwargs: Any) -> str:
    """Lookup localized message for key, formatting with kwargs if provided."""
    lang = get_language()
    table = MESSAGES.get(lang) or MESSAGES.get("en", {})
    text = table.get(key) or MESSAGES.get("en", {}).get(key, default or key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text
