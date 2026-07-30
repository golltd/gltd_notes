# GLTD Notes — 个人笔记应用，支持多机同步

## 什么是 GLTD Notes？

一款**私密、开源**的 Linux 笔记应用，作为 GNote 的替代方案。提供桌面图形界面（GTK 3）、本地 Web 服务器和 REST API —— 全部在您的机器上运行，无需依赖云端或外部服务器。

### 为什么选择它？

- **真正的隐私**：所有数据都保存在您的电脑文件夹中。
- **多机同步**：使用 **Syncthing** 在多台电脑之间保持笔记同步，无需中央服务器。存储格式可避免多人同时编辑时的冲突。
- **完整历史记录**：每次修改都会被记录。您可以恢复到笔记的任意先前版本。
- **内置 AI 代理**：用自然语言描述任务，让 DeepSeek（通过 opencode）、Grok 或 Gemini 自动执行。

> **本应用在 AI 辅助下开发完成，使用了 Grok（xAI）和 DeepSeek V4（通过 opencode）。**

---

## 安装方法

### 1. 系统依赖

在终端中运行以下命令（Linux Mint / Ubuntu / Debian）：

```bash
sudo apt install python3 python3-gi python3-gi-cairo \
  gir1.2-gtk-3.0 gir1.2-notify-0.7 \
  gir1.2-ayatanaappindicator3-0.1 libnotify-bin
```

### 2. 文件位置

程序安装在：

```
/var/PROGRAMAS/gltd_notes/          ← 应用代码
~/gltd_notes_data/                ← 您的数据（笔记、附件、历史记录）
~/.config/gltd_notes/config.json    ← 本地配置和密码
~/.local/share/gltd_notes/session/  ← 锁屏会话控制
```

### 3. 初始设置（首次使用）

打开程序前，先创建用户并设置密码：

```bash
/var/PROGRAMAS/gltd_notes/bin/gltd-notes init \
  --data-root ~/gltd_notes_data \
  --username 您的用户名 --password '您的密码'
```

### 4. 创建系统菜单快捷方式（可选）

```bash
/var/PROGRAMAS/gltd_notes/scripts/install_desktop.sh
```

这会在系统菜单中添加条目，并在 `~/.local/bin/` 中创建 `gltd-notes`、`gltd-notes-api` 和 `gltd-notes-web` 命令的链接。

---

## 使用方法

### 桌面图形界面（普通模式）

```bash
gltd-notes gui
```

- 创建、编辑和删除带富文本格式的笔记。
- 附加文件（图片、PDF、任何文件）—— 每个文件按内容存储，避免重复。
- 查看**历史记录**并恢复先前版本。
- 创建**事件/提醒**，触发桌面通知。
- 使用**系统托盘图标**快速访问：新建笔记、新建事件、显示窗口、退出。
- **锁定会话**（使用密码）—— 锁定期间无人可访问笔记。

### Web 界面

```bash
gltd-notes web
```

在浏览器中打开 `http://127.0.0.1:8765` 即可通过 Web 访问笔记。

### REST API

```bash
gltd-notes api
```

REST API 在 `http://127.0.0.1:8765` 上可用（仅限 localhost）。所有请求需要以下请求头：

```
X-API-Key: <来自 ~/.config/gltd_notes/config.json 的密钥>
```

示例：

```bash
# 获取 API 密钥
KEY=$(python3 -c "import json;print(json.load(open('$HOME/.config/gltd_notes/config.json'))['api']['api_key'])")

# 健康检查
curl -s -H "X-API-Key: $KEY" http://127.0.0.1:8765/api/v1/health

# 创建笔记
curl -s -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"title":"我的笔记","body":"通过 API 创建的笔记内容"}' \
  http://127.0.0.1:8765/api/v1/notes

# 列出所有笔记
curl -s -H "X-API-Key: $KEY" http://127.0.0.1:8765/api/v1/notes
```

---

## AI 代理任务

GLTD Notes 允许将任务委托给 AI 代理。您只需描述需要做什么，代理就会在终端中执行。

### 可用代理

| 界面名称 | CLI 工具 | 说明 |
|----------|----------|------|
| `opencode-deepseek4` | `opencode run` | 使用 DeepSeek V4 执行任务 |
| `grok` | `grok` | 使用 Grok 执行任务 |
| `gemini` | `gemini` | 使用 Gemini 执行任务 |

### 如何使用

1. 在菜单中，进入**任务 → 新建代理任务**。
2. 选择代理（推荐：`opencode-deepseek4`）。
3. 用自然语言描述任务。请尽量具体。
4. 点击**▶ 执行**，在输出区域等待结果。

### 任务示例

```
配置服务器 192.0.2.1：
1. 以 root 身份通过 SSH 访问
2. 安装并配置 MariaDB
3. 创建数据库 "prod_app"
4. 创建用户 "app_user" 并设置安全密码
5. 使用 cron 配置每日备份
```

有关代理的更多详情，请参阅 [README_AGENT.md](README_AGENT.md)。

---

## 使用 Syncthing 进行多机同步

1. 在所有机器上安装 [Syncthing](https://syncthing.net/)。
2. 在每台机器上共享 GLTD Notes 的数据文件夹（`~/gltd_notes_data`）。
3. 完成。笔记会自动同步。

**为什么不会冲突？** 程序使用一种称为"笔记区块链"的特殊格式：每次修改都作为一个新块追加到文件末尾，并带有机器和用户标识。当两人同时编辑同一条笔记时，两个版本都会被保留，并可在历史记录中查看。

---

## 笔记共享

在 GLTD Notes 中，您可以与其他用户共享笔记：

- 私有笔记：仅对您可见。
- 共享笔记：复制到 `shared/` 区域，对所有列出的用户可见。
- 历史记录显示每次修改是由哪个用户和哪台机器生成的。

---

## 文档

| 文件 | 内容 |
|------|------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 存储、区块链和多机同步 |
| [docs/API.md](docs/API.md) | 完整的 REST API 参考 |
| [docs/SECURITY.md](docs/SECURITY.md) | 认证和安全模型 |
| [docs/PACKAGING.md](docs/PACKAGING.md) | 未来计划（.deb、AppImage 等） |
| [README_AGENT.md](README_AGENT.md) | AI 代理任务详细指南 |

---

## 版本管理

版本号遵循 `MAJOR.MINOR.PATCH`（语义化版本）格式：

- **MAJOR**：不兼容的 API 变更或完全重写（当前为 `0` —— 预稳定版）
- **MINOR**：新功能、新子命令、新界面页面（`1`）
- **PATCH**：Bug 修复、小幅改进、文档更新 —— **每次提交自动递增**

补丁号由 `.githooks/pre-commit` 自动管理，该钩子在每次提交前运行 `scripts/bump_version.sh`。版本的规范来源是 `gltd_notes/_version.py` —— 所有其他引用（`pyproject.toml`、API health 端点、`__init__.py`）均由此派生。

---

## 捐赠

如果 GLTD Notes 对您有帮助，请考虑支持其开发：

- **PIX（巴西）**: `1f57a276-dc0e-44a0-a4e0-4a2349833958`
- **Monero（XMR）**: `84pnTEwRrFLPUqSNQdCLFw6X6gjQeQtdNNVxkYAfvgd229DHgNYzzQ9VgpquUG8RfAJJ5Py556KrAiG47PqKYxPM1mzpAtb`

---

## 关于开发

本应用在**人工智能**辅助下开发：

- **Grok**（xAI）—— 原型设计和初始迭代
- **DeepSeek V4**（通过 opencode）—— 最终架构、完善和完成度

代码 100% 开源（MIT 许可证）。请参阅 [LICENSE](LICENSE) 文件。
