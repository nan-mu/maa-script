# 📱 maa-script

> 一份简单的 `config.toml`，把 MAA 冗长的日志收成可读的信息回报。

maa-script 接管每日运行maa任务执行流程主要功能有**优化终端日志**、**解析 Summary**、**推送到 Telegram**。它类似Auto-MAS。我的配置是MAC mini跑maa，真机跑粥。所以做了一些关注真机运行的优化。理论上maa和maa-script适用于任何linux环境，定时任务依靠cron。

---

## 💡 这个项目解决什么


| 之前 😵                   | 之后 ✨                                      |
| ----------------------- | ----------------------------------------- |
| maa 跑完，不知道完成了什么，需要手动翻日志 | Telegram 一条消息：剿灭、理智、公招、基建一目了然             |
| 不知道 daily 跑没跑完、哪步挂了     | ✅ / ❌ / ⚠️ 状态 + 失败任务列表，必要时附 summary / log |
| crontab、错误处理、超时各自散落     | 一个 `config.toml` 集中配置                     |
| 跑完手机还亮着                 | 自动息屏或 reboot                              |


**主旨**：配置简单，回报清晰。

---

## ✨ 功能

- 📲 **设备** — 从 MAA profile 读 adb / 序列号，唤醒并校验亮度
- 🌐 **网络** — 代理探测 MAA / Telegram 等 URL
- 🤖 **MAA 调度** — `maa run daily`，超时 kill，stdout 落盘 `logs/`
- 📊 **Summary 解析** — 把原始 Summary 收成精简报告
  - ⚔ 剿灭 / 理智作战：关卡、次数、总掉落（`理智 × 1` 不展示）
  - 🎟 公招：招募 / 刷新、星级统计
  - 🏭 基建 · 🛒 购物 · 🎁 奖励：完成标记
- 📬 **Telegram** — 成功 / 失败 / 日志告警分场景推送
- 😴 **收尾** — `reboot`（默认）或 `sleep_only`
- ⏰ **定时** — `install` / `uninstall` 管理 crontab

---



## 📋 环境要求


| 依赖                                                                           | 说明                                       |
| ---------------------------------------------------------------------------- | ---------------------------------------- |
| 🍎 macOS                                                                     | `pixi.toml` 支持 `osx-arm64` / `osx-64`    |
| 📦 [Pixi](https://pixi.sh)                                                   | 依赖与任务管理                                  |
| 🎮 [maa-cli](https://github.com/MaaAssistantArknights/MaaAssistantArknights) | `maa` 在 PATH 或写进 `[maa].bin`             |
| 🔌 adb                                                                       | 由 MAA profile 的 `connection.adb_path` 指定 |
| 📱 Android 设备 / 模拟器                                                          | MAA profile 已配好                          |
| 💬 Telegram Bot                                                              | 推荐；`doctor` 会校验                          |


---



## 🚀 快速开始

```bash
git clone <repo-url> maa-script
cd maa-script

pixi install
pixi run init          # 📄 config.example.toml → config.toml
# ✏️ 编辑 config.toml

pixi run doctor        # 🩺 预检
pixi run notify-test   # 💬 测 Telegram
pixi run daily         # ▶️ 手动跑一轮

pixi run install       # ⏰ 写入 crontab
pixi run uninstall     # 🗑️ 移除 crontab
```

---



## ⚙️ 配置

复制 `config.example.toml` → `config.toml`，改这一份文件即可。

### 🌐 `[network]`

代理与探测 URL。MAA 子进程和 Telegram 都走 `proxy`（留空则直连）。

### 🤖 `[maa]`


| 键             | 说明                              |
| ------------- | ------------------------------- |
| `bin`         | `maa` 可执行文件路径                   |
| `task`        | 任务名，默认 `daily`                  |
| `profile`     | MAA profile，默认 `default`        |
| `extra_args`  | 建议 `-vv`、`--batch`、`--log-file` |
| `timeout_sec` | 超时秒数                            |
| `log_dir`     | runner 日志目录                     |


> 💡 adb / 设备序列号**不在** `config.toml`，运行时从 MAA profile 的 `connection` 读取。



### 💬 `[telegram]`


| 键           | 说明        |
| ----------- | --------- |
| `enabled`   | 须为 `true` |
| `bot_token` | Bot Token |
| `chat_id`   | Chat ID   |




### 😴 `[cleanup]`


| 键                  | 说明                         |
| ------------------ | -------------------------- |
| `mode`             | `reboot`（默认）或 `sleep_only` |
| `boot_timeout_sec` | reboot 后等待开机的超时            |




### ⏰ `[schedule]`


| 键      | 说明               |
| ------ | ---------------- |
| `cron` | 如 `0 5,17 * * *` |




### 📲 `[device]`（可选）

唤醒 / 息屏参数：`wake_key`、`sleep_key`、`luma_black` 等，省略用默认值。

---



## 🛠 命令


| 命令                     | 作用                  |
| ---------------------- | ------------------- |
| `pixi run init`        | 📄 生成 `config.toml` |
| `pixi run doctor`      | 🩺 预检               |
| `pixi run daily`       | ▶️ 完整流程             |
| `pixi run install`     | ⏰ 写入 crontab        |
| `pixi run uninstall`   | 🗑️ 移除 crontab      |
| `pixi run notify-test` | 💬 测试推送             |
| `pixi run test`        | 🧪 pytest           |


无 CLI 参数，一切走 `config.toml`。

---



## 🔄 执行流程

```
[1/5] 📲 设备校验   adb → 唤醒 → 亮度
[2/5] 🌐 网络       代理探测
[3/5] 🤖 MAA 调度   maa run daily → logs/<timestamp>.summary.txt
[4/5] 📊 解析与回传  Summary → Telegram
[5/5] 😴 后置清理   reboot / sleep_only
```

- Phase 1/2 失败 → 📬 告警，息屏，退出码 2
- Phase 3 超时 / 崩溃 → 仍解析已有 Summary 并发送
- Phase 5 失败 → 📬 告警

---



## 📬 信息回报示例

原始 Summary 几十行，Telegram 收成这样：

```text
✅ MAA daily 完成 · 9/9
🕐 05:04:03 → 05:25:23 · 耗时 21m 20s

⚔ 剿灭 · 拉特兰 × 5 收获：初级作战记录 × 49 • 合成玉 × 1800 • 龙门币 × 1240
⚔ 理智作战 · LS-6 × 3 收获：中级作战记录 × 6 • 高级作战记录 × 12 • 龙门币 × 1296
🎟 公招：招募 4 · 刷新 1 3★ × 4
🏭 基建 · 🛒 购物 · 🎁 奖励 · 完成
```

- 任务名跟 MAA daily 的 `name` 走（`剿灭`、`理智作战` 等）
- 剿灭 / 理智无掉落块 → 不显示该行
- 有任务非 `Completed` → ❌ 失败报告 + 附 summary
- maa log 有 WARN/ERROR → ⚠️ 完成但告警 + 附 log

---



## 🚦 退出码


| 码   | 含义                     |
| --- | ---------------------- |
| 0   | ✅ 成功                   |
| 1   | ⚙️ 配置 / doctor 失败      |
| 2   | 💥 阶段失败                |
| 3   | ⏱ MAA 超时               |
| 4   | 📬 流程 OK 但 Telegram 失败 |
| 130 | 🛑 Ctrl+C 中断           |


---



## 📁 项目结构

```text
maa-script/
  config.example.toml    # ⚙️ 配置模板（复制即用）
  pixi.toml
  src/maa_runner/
    parse.py             # 📊 Summary 解析
    report.py            # 📬 报告生成
    pipeline.py          # 🔄 主流程
    ...
  logs/                  # 📝 运行时日志
```

---



## 🧪 开发

```bash
pixi run test
```

---



## 📄 许可

尚未指定 License；发布前请自行添加。