# 📱 maa-script

> 一份简单的 `config.toml`，把 MAA 冗长的日志收成可读的信息回报。

maa-script 接管 MAA daily 的执行流程：**优化终端日志**、**解析 Summary**、**推送到 Telegram**。思路类似 [Auto-MAS](https://github.com/AUTO-MAS-Project/AUTO-MAS)——无人托管，在外层把「跑完以后怎么办」做好。

典型用法：**Mac mini 跑 maa + maa-script，adb 连真机跑粥**。因此做了亮屏 / 息屏、reboot 收尾等真机向优化。定时任务走 cron；Pixi 环境目前声明支持 **macOS**（`osx-arm64` / `osx-64`），其他平台需自行适配。

---

## 💡 这个项目解决什么

| 之前 😵 | 之后 ✨ |
|---------|---------|
| maa 跑完，不知道完成了什么，要手动翻日志 | Telegram 一条消息：剿灭、理智、公招、基建一目了然 |
| 不知道 daily 跑没跑完、哪步挂了 | ✅ / ❌ / ⚠️ 状态 + 失败任务列表，必要时附 summary / log |
| crontab、错误处理、超时各自散落 | 一个 `config.toml` 集中配置 |
| 跑完手机还亮着 | 自动息屏或 reboot |

**主旨**：配置简单，回报清晰。

---

## 🏗 典型部署

```text
  Mac mini                         Android 真机
 ┌─────────────┐    adb / 代理     ┌─────────────┐
 │ maa-cli     │ ───────────────► │ 明日方舟      │
 │ maa-script  │                  │             │
 │ cron        │                  └─────────────┘
 └──────┬──────┘
        │ Telegram
        ▼
   📬 手机 / 电脑收报告
```

MAA 的 adb 路径、设备序列号写在 MAA profile 里；maa-script 的 `config.toml` 只管 runner 行为（代理、超时、通知、清理、定时）。

---

## ✨ 功能

- 📲 **真机设备** — 从 MAA profile 读 adb / 序列号；唤醒、亮度检测、息屏 / reboot
- 🌐 **网络** — 代理探测 MAA / Telegram 等 URL，失败提前告警
- 🤖 **MAA 调度** — `maa run daily`，超时 kill，stdout 落盘 `logs/<timestamp>.summary.txt`
- 📊 **Summary 解析** — 原始 Summary → 精简报告
  - ⚔ 剿灭 / 理智作战：关卡、次数、总掉落（`理智 × 1` 不展示）
  - 🎟 公招：招募 / 刷新、星级统计
  - 🏭 基建 · 🛒 购物 · 🎁 奖励：完成标记
- 📬 **Telegram** — 成功 / 失败 / 日志告警分场景推送
- 😴 **收尾** — `reboot`（默认，重启后息屏）或 `sleep_only`
- ⏰ **定时** — `install` / `uninstall` 管理带 `MAA_RUNNER_MANAGED` 标记的 crontab 行

---

## 📋 环境要求

| 依赖 | 说明 |
|------|------|
| 🍎 macOS | Pixi 当前平台：`osx-arm64` / `osx-64` |
| 📦 [Pixi](https://pixi.sh) | 依赖与任务管理 |
| 🎮 [MAA](https://github.com/MaaAssistantArknights/MaaAssistantArknights) | 已安装 `maa`，且在 `[maa].bin` 或 PATH 中 |
| 🔌 adb | 由 MAA profile 的 `connection.adb_path` 指定 |
| 📱 Android 设备 | MAA profile 已配好连接 |
| 💬 Telegram Bot | **必需**（`doctor` / `daily` 会校验） |

---

## 🚀 快速开始

```bash
git clone <repo-url> maa-script
cd maa-script

pixi install
pixi run init          # config.example.toml → config.toml
# 编辑 config.toml（见下方最小示例）

pixi run doctor        # 预检 MAA / Telegram / 网络 / 设备
pixi run notify-test   # 测试 Telegram
pixi run daily         # 手动跑一轮

pixi run install       # 写入 crontab（需 doctor 通过）
pixi run uninstall     # 移除 crontab 行
```

### 最小配置示例

```toml
[network]
proxy = "http://127.0.0.1:7890"
probe_timeout_sec = 10
probe_urls = ["https://api.maa.plus", "https://api.telegram.org"]

[maa]
bin = "/path/to/maa"
task = "daily"
profile = "default"
extra_args = ["-vv", "--batch", "--log-file"]
timeout_sec = 3600
log_dir = "logs"

[telegram]
enabled = true
bot_token = "YOUR_BOT_TOKEN"
chat_id = "YOUR_CHAT_ID"

[cleanup]
mode = "reboot"
boot_timeout_sec = 180

[schedule]
cron = "0 5,17 * * *"
```

> ⚠️ `config.toml` 已在 `.gitignore` 中，**勿提交** Bot Token。完整字段见 `config.example.toml`。

---

## ⚙️ 配置说明

### 🌐 `[network]`

| 键 | 说明 |
|----|------|
| `proxy` | HTTP 代理；留空则直连 |
| `probe_timeout_sec` | 探测超时 |
| `probe_urls` | 预检 URL 列表 |

MAA 子进程与 Telegram 请求均走此代理。

### 🤖 `[maa]`

| 键 | 说明 |
|----|------|
| `bin` | `maa` 可执行文件路径 |
| `task` | 任务名，默认 `daily` |
| `profile` | MAA profile，默认 `default` |
| `extra_args` | 建议 `-vv`、`--batch`、`--log-file` |
| `timeout_sec` | 超时秒数，到期 SIGTERM 杀进程组 |
| `log_dir` | runner 日志目录（相对项目根） |

adb / 设备序列号**不在** `config.toml`，运行时从 `$(maa dir config)/profiles/<profile>.json` 的 `connection` 读取。

### 💬 `[telegram]`

| 键 | 说明 |
|----|------|
| `enabled` | 须为 `true` |
| `bot_token` | Bot Token |
| `chat_id` | Chat ID |

### 😴 `[cleanup]`

| 键 | 说明 |
|----|------|
| `mode` | `reboot`（默认）或 `sleep_only` |
| `boot_timeout_sec` | reboot 后等待 `sys.boot_completed` 的超时 |

Phase 1 / 2 失败时强制 `sleep_only`（不 reboot），避免设备离线时误重启。

### ⏰ `[schedule]`

| 键 | 说明 |
|----|------|
| `cron` | crontab 表达式，如 `0 5,17 * * *` |

`install` 写入的行会 `cd` 到项目目录、追加输出到 `logs/cron.log`。

### 📲 `[device]`（可选）

真机亮灭屏参数，省略则用默认值：

| 键 | 默认 | 说明 |
|----|------|------|
| `wake_key` | 224 | KEYCODE_WAKEUP |
| `sleep_key` | 223 | KEYCODE_SLEEP |
| `wake_retries` | 5 | 唤醒重试次数 |
| `luma_black` | 10.0 | 低于此平均亮度视为黑屏 |
| `wake_interval_sec` | 1.5 | 唤醒间隔 |

---

## 🛠 命令

| 命令 | 作用 |
|------|------|
| `pixi run init` | 生成 `config.toml` |
| `pixi run doctor` | 预检 MAA / Telegram / 代理 / 设备 |
| `pixi run daily` | 执行完整五阶段流程 |
| `pixi run install` | 写入 crontab |
| `pixi run uninstall` | 移除 crontab 行 |
| `pixi run notify-test` | 发送测试消息 |
| `pixi run test` | 运行 pytest |

无 CLI 参数，一切通过 `config.toml` 配置。

---

## 🔄 执行流程

```text
[1/5] 📲 设备校验   adb 在线 → 唤醒 → 亮度检测
[2/5] 🌐 网络       代理探测 probe_urls
[3/5] 🤖 MAA 调度   maa run daily → logs/<timestamp>.summary.txt
[4/5] 📊 解析与回传  Summary → Telegram
[5/5] 😴 后置清理   reboot + 息屏，或 sleep_only
```

| 情况 | 行为 |
|------|------|
| Phase 1/2 失败 | 📬 Telegram 告警 → 息屏 → 退出码 2 |
| Phase 3 超时 / 崩溃 | 仍解析已有 Summary 并发送 |
| Phase 5 失败 | 📬 Telegram 告警 |
| Ctrl+C | 告警 + 尽力息屏 → 退出码 130 |

---

## 📬 信息回报示例

原始 Summary 几十行，Telegram 收成：

```text
✅ MAA daily 完成 · 9/9
🕐 05:04:03 → 05:25:23 · 耗时 21m 20s

⚔ 剿灭 · 拉特兰 × 5 收获：初级作战记录 × 49 • 合成玉 × 1800 • 龙门币 × 1240
⚔ 理智作战 · LS-6 × 3 收获：中级作战记录 × 6 • 高级作战记录 × 12 • 龙门币 × 1296
🎟 公招：招募 4 · 刷新 1 3★ × 4
🏭 基建 · 🛒 购物 · 🎁 奖励 · 完成
```

- 任务名跟随 MAA daily 的 `name`（`剿灭`、`理智作战` 等，中英文均可）
- 剿灭 / 理智无 Fight 掉落块 → 不显示该行
- 任一条任务非 `Completed` → ❌ 失败报告 + 附 summary 文件
- maa 日志含 WARN / ERROR → ⚠️ 完成但告警 + 附 maa 日志

终端 Phase 日志保持分阶段输出（`[1/5]` …），便于 cron 排错时看 `logs/cron.log`。

---

## 📝 日志文件

| 路径 | 内容 |
|------|------|
| `logs/<timestamp>.summary.txt` | MAA stdout（含 Summary 原文） |
| `logs/cron.log` | crontab 触发的终端输出 |
| MAA 自身 log | `--log-file` 写入 MAA 日志目录，runner 按时间戳匹配并附送 |

---

## 🚦 退出码

| 码 | 含义 |
|----|------|
| 0 | ✅ 成功 |
| 1 | ⚙️ 配置 / doctor 失败 |
| 2 | 💥 阶段失败（设备、网络、任务未全 Completed、清理失败等） |
| 3 | ⏱ MAA 超时 |
| 4 | 📬 流程 OK 但 Telegram 发送失败 |
| 130 | 🛑 Ctrl+C 中断 |

---

## 📁 项目结构

```text
maa-script/
  config.example.toml
  pixi.toml
  src/maa_runner/
    cli.py          # 命令入口 + crontab
    pipeline.py     # 五阶段主流程 + 退出码
    parse.py        # Summary 解析
    report.py       # Telegram 报告
    maa.py          # MAA 调度 + profile / 日志路径
    adb.py          # 真机 adb + 亮灭屏
    config.py       # 配置加载
    notify.py       # Telegram
    net.py          # 代理探测
    schedule.py     # crontab 工具（cli 调用）
  tests/
  logs/
```

---

## 🧪 开发

```bash
pixi run test
```

---

## 📄 许可

尚未指定 License；发布前请自行添加。
