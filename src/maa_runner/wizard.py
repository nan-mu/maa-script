from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import questionary
import requests
from questionary import Choice

from maa_runner.config import project_root
from maa_runner.maa_paths import TASK_EXTENSIONS

DEFAULT_EXTRA_ARGS = ["-vv", "--batch", "--log-file"]
DEFAULT_PROXY = "http://127.0.0.1:7890"
DEFAULT_PROBE_URLS = (
    "https://github.com",
    "https://api.maa.plus",
    "https://api.telegram.org",
)
DEFAULT_TIMEOUT_SEC = 3600
DEFAULT_BOOT_TIMEOUT_SEC = 180
DEFAULT_CRON = "0 5 * * *"
DEFAULT_PROFILE = "default"
DEFAULT_LOG_DIR = "logs"


class WizardError(Exception):
    """Interactive init aborted or failed."""


@dataclass
class WizardResult:
    maa_bin: str
    task: str
    extra_args: list[str]
    timeout_sec: int
    bot_token: str
    chat_id: str
    cleanup_mode: str
    boot_timeout_sec: int
    proxy: str
    cron: str = DEFAULT_CRON
    profile: str = DEFAULT_PROFILE
    log_dir: str = DEFAULT_LOG_DIR
    probe_timeout_sec: int = 10


def _which_maa() -> str | None:
    found = shutil.which("maa")
    return str(Path(found).resolve()) if found else None


def _maa_dir(maa_bin: str, kind: str) -> Path:
    proc = subprocess.run(
        [maa_bin, "dir", kind],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise WizardError(f"maa dir {kind} failed: {err or proc.returncode}")
    text = (proc.stdout or "").strip().splitlines()
    if not text:
        raise WizardError(f"maa dir {kind} returned empty path")
    return Path(text[0].strip())


def list_task_names(config_dir: Path) -> list[str]:
    tasks_dir = config_dir / "tasks"
    if not tasks_dir.is_dir():
        return []
    names: set[str] = set()
    for path in tasks_dir.iterdir():
        if path.is_file() and path.suffix.lower() in TASK_EXTENSIONS:
            names.add(path.stem)
    return sorted(names)


def _parse_extra_args(raw: str) -> list[str]:
    raw = raw.strip()
    if not raw:
        raise WizardError("maa 参数不能为空")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WizardError(f"maa 参数必须是 JSON 数组: {exc}") from exc
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise WizardError("maa 参数必须是字符串 JSON 数组，例如 [\"-vv\", \"--batch\"]")
    return value


def _toml_str(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_str_list(values: list[str]) -> str:
    inner = ", ".join(_toml_str(v) for v in values)
    return f"[{inner}]"


def render_user_toml(data: WizardResult) -> str:
    """User-facing config.toml body (no hidden [device] overrides)."""
    urls = ",\n".join(f"  {_toml_str(u)}" for u in DEFAULT_PROBE_URLS)
    return f"""[network]
proxy = {_toml_str(data.proxy)}
probe_timeout_sec = {data.probe_timeout_sec}
probe_urls = [
{urls},
]

[maa]
bin = {_toml_str(data.maa_bin)}
task = {_toml_str(data.task)}
profile = {_toml_str(data.profile)}
extra_args = {_toml_str_list(data.extra_args)}
timeout_sec = {data.timeout_sec}
log_dir = {_toml_str(data.log_dir)}

[telegram]
enabled = true
bot_token = {_toml_str(data.bot_token)}
chat_id = {_toml_str(data.chat_id)}

[cleanup]
mode = {_toml_str(data.cleanup_mode)}
boot_timeout_sec = {data.boot_timeout_sec}

[schedule]
cron = {_toml_str(data.cron)}
"""


def _proxies(proxy: str) -> dict[str, str] | None:
    proxy = proxy.strip()
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


def _tg_api(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def verify_bot_token(token: str, proxy: str) -> dict:
    try:
        response = requests.get(
            _tg_api(token, "getMe"),
            proxies=_proxies(proxy),
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
    except requests.RequestException as exc:
        raise WizardError(f"Telegram getMe 失败: {exc}") from exc
    if not body.get("ok"):
        raise WizardError(body.get("description") or "getMe failed")
    return body["result"]


def fetch_chats(token: str, proxy: str) -> list[dict]:
    try:
        response = requests.get(
            _tg_api(token, "getUpdates"),
            proxies=_proxies(proxy),
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
    except requests.RequestException as exc:
        raise WizardError(f"Telegram getUpdates 失败: {exc}") from exc
    if not body.get("ok"):
        raise WizardError(body.get("description") or "getUpdates failed")

    seen: dict[str, dict] = {}
    for update in body.get("result") or []:
        for key in ("message", "edited_message", "my_chat_member", "channel_post"):
            obj = update.get(key) or {}
            chat = obj.get("chat") if isinstance(obj, dict) else None
            if not chat or chat.get("id") is None:
                continue
            chat_id = str(chat["id"])
            seen[chat_id] = {
                "id": chat_id,
                "type": chat.get("type") or "",
                "title": chat.get("title") or "",
                "username": chat.get("username") or "",
                "first_name": chat.get("first_name") or "",
                "last_name": chat.get("last_name") or "",
            }
    return list(seen.values())


def _format_chat(chat: dict) -> str:
    bits = [f"id={chat['id']}", f"type={chat['type'] or '?'}"]
    if chat.get("username"):
        bits.append(f"@{chat['username']}")
    name = chat.get("title") or " ".join(
        x for x in (chat.get("first_name"), chat.get("last_name")) if x
    )
    if name:
        bits.append(name)
    return " · ".join(bits)


def backup_existing(root: Path) -> list[str]:
    """If config.toml exists, rename it and rename logs/ when present."""
    notes: list[str] = []
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    config_path = root / "config.toml"
    if config_path.exists():
        dest = root / f"config.toml.bak-{stamp}"
        config_path.rename(dest)
        notes.append(f"已备份配置 → {dest.name}")
        logs = root / "logs"
        if logs.exists():
            logs_dest = root / f"logs.bak-{stamp}"
            logs.rename(logs_dest)
            notes.append(f"已重命名日志目录 → {logs_dest.name}")
            logs.mkdir(parents=True, exist_ok=True)
            (logs / ".gitkeep").write_text("", encoding="utf-8")
    return notes


def run_wizard() -> WizardResult:
    print("MAA Runner 初始化向导")
    print("（可用方向键选择；也可直接输入。Ctrl+C 取消）\n")

    proxy = questionary.text(
        "网络代理（Telegram / 探测用，可留空）",
        default=DEFAULT_PROXY,
    ).ask()
    if proxy is None:
        raise WizardError("已取消")
    proxy = proxy.strip()

    default_maa = _which_maa() or ""
    maa_bin = questionary.path(
        "maa 可执行文件路径",
        default=default_maa or None,
    ).ask()
    if maa_bin is None:
        raise WizardError("已取消")
    maa_bin = str(Path(maa_bin).expanduser())
    if not Path(maa_bin).is_file():
        # still allow if which found a path that resolves
        if not shutil.which(maa_bin):
            confirm = questionary.confirm(
                f"未找到文件 {maa_bin}，仍要使用？",
                default=False,
            ).ask()
            if not confirm:
                raise WizardError("已取消")

    try:
        config_dir = _maa_dir(maa_bin, "config")
    except WizardError:
        raise
    except Exception as exc:
        raise WizardError(f"无法读取 maa 配置目录: {exc}") from exc

    tasks = list_task_names(config_dir)
    print(f"\n已从 {config_dir / 'tasks'} 发现 {len(tasks)} 个任务文件")
    if tasks:
        choices = [Choice(title=name, value=name) for name in tasks]
        choices.append(Choice(title="（手动输入其它名称）", value="__custom__"))
        selected = questionary.select(
            "选择 task（↑↓ 选择，Enter 确认）",
            choices=choices,
        ).ask()
        if selected is None:
            raise WizardError("已取消")
        if selected == "__custom__":
            task = questionary.text("输入 task 名称").ask()
        else:
            task = selected
    else:
        print("未发现任务文件，请手动输入 task 名称（对应 tasks/<name>.toml|json|yml）")
        task = questionary.text("task 名称", default="daily").ask()
    if not task or not str(task).strip():
        raise WizardError("task 名称不能为空")
    task = str(task).strip()

    default_args_json = json.dumps(DEFAULT_EXTRA_ARGS, ensure_ascii=False)
    print("\nmaa 参数默认为：", default_args_json)
    print("直接回车确认；若要覆盖，请输入完整 JSON 数组。")
    raw_args = questionary.text("maa extra_args", default=default_args_json).ask()
    if raw_args is None:
        raise WizardError("已取消")
    extra_args = _parse_extra_args(raw_args)
    if extra_args != DEFAULT_EXTRA_ARGS:
        print("将使用以下参数：")
        print(" ", json.dumps(extra_args, ensure_ascii=False))
        ok = questionary.confirm("确认覆盖默认参数？", default=True).ask()
        if not ok:
            raise WizardError("已取消")

    print("\n—— Telegram ——")
    print("1. 在 @BotFather 创建 bot，复制 token")
    print("2. 用手机 Telegram 打开你的 bot，先发送任意消息（例如 /start）")
    print("3. 再回到这里继续，否则无法解析 chat_id\n")
    bot_token = questionary.password("bot_token").ask()
    if bot_token is None or not bot_token.strip():
        raise WizardError("bot_token 不能为空")
    bot_token = bot_token.strip()

    me = verify_bot_token(bot_token, proxy)
    username = me.get("username") or me.get("id")
    print(f"Bot 已验证：@{username}")

    questionary.press_any_key_to_continue(
        "请确认已向 bot 发送过消息，然后按 Enter 拉取 chat 列表…"
    ).ask()

    chats = fetch_chats(bot_token, proxy)
    while not chats:
        print("还没有会话。请打开 Telegram，向 bot 发一条消息后重试。")
        retry = questionary.confirm("重新拉取 getUpdates？", default=True).ask()
        if not retry:
            raise WizardError("未获取到 chat_id")
        chats = fetch_chats(bot_token, proxy)

    if len(chats) == 1:
        chat = chats[0]
        print("找到唯一会话：", _format_chat(chat))
        ok = questionary.confirm("使用该 chat_id？", default=True).ask()
        if not ok:
            raise WizardError("已取消")
        chat_id = chat["id"]
    else:
        print(f"找到 {len(chats)} 个会话，请选择接收通知的目标：")
        chat_id = questionary.select(
            "chat_id",
            choices=[Choice(title=_format_chat(c), value=c["id"]) for c in chats],
        ).ask()
        if chat_id is None:
            raise WizardError("已取消")

    print("\n—— 清理与超时 ——")
    cleanup_mode = questionary.select(
        "cleanup.mode（结束后如何处理设备）",
        choices=[
            Choice("reboot — 重启设备并确认息屏", "reboot"),
            Choice("sleep_only — 仅息屏，不重启", "sleep_only"),
        ],
        default="reboot",
    ).ask()
    if cleanup_mode is None:
        raise WizardError("已取消")

    timeout_raw = questionary.text(
        "maa 运行超时（秒）",
        default=str(DEFAULT_TIMEOUT_SEC),
    ).ask()
    boot_raw = questionary.text(
        "重启后等待开机超时 boot_timeout_sec（秒）",
        default=str(DEFAULT_BOOT_TIMEOUT_SEC),
    ).ask()
    if timeout_raw is None or boot_raw is None:
        raise WizardError("已取消")
    try:
        timeout_sec = int(timeout_raw)
        boot_timeout_sec = int(boot_raw)
    except ValueError as exc:
        raise WizardError("超时必须是整数秒") from exc
    if timeout_sec <= 0 or boot_timeout_sec <= 0:
        raise WizardError("超时必须为正整数")

    return WizardResult(
        maa_bin=str(Path(maa_bin).expanduser()),
        task=task,
        extra_args=extra_args,
        timeout_sec=timeout_sec,
        bot_token=bot_token,
        chat_id=str(chat_id),
        cleanup_mode=cleanup_mode,
        boot_timeout_sec=boot_timeout_sec,
        proxy=proxy,
    )


def write_confirmed_config(root: Path | None = None) -> Path:
    root = (root or project_root()).resolve()
    data = run_wizard()
    text = render_user_toml(data)
    print("\n======= 将写入的 config.toml =======")
    print(text)
    print("===================================")
    ok = questionary.confirm("确认写入？", default=True).ask()
    if not ok:
        raise WizardError("已取消，未写入")

    notes = backup_existing(root)
    for note in notes:
        print(note)

    dest = root / "config.toml"
    dest.write_text(text, encoding="utf-8")
    (root / "logs").mkdir(parents=True, exist_ok=True)
    return dest
