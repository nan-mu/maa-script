from datetime import datetime
from pathlib import Path

from maa_runner.report import build_report, scan_log_levels
from maa_runner.maa_paths import find_maa_log
from maa_runner.parse import parse_fight, parse_recruit, parse_summary

GOLD_SUMMARY = """Summary
----------------------------------------
[StartUp] 16:08:59 - 16:10:27 (1m 27s) Completed
----------------------------------------
[剿灭] 16:10:27 - 16:11:02 (34s) Completed
----------------------------------------
[理智作战] 16:11:02 - 16:17:11 (6m 8s) Completed
Fight TO-5 14 times, drops:
1. 沿途的点滴 × 120, 装置 × 8, 酮凝集 × 4, 龙门币 × 1440
2. 沿途的点滴 × 48, 装置 × 2, 酮凝集 × 1, 龙门币 × 576
total drops: 沿途的点滴 × 168, 装置 × 10, 酮凝集 × 5, 龙门币 × 2016
----------------------------------------
[Recruit] 16:17:12 - 16:17:56 (44s) Completed
Detected tags:
1. ★★★ 术师干员, 先锋干员, 新手, 医疗干员, 群攻, Refreshed
2. ★★★ 术师干员, 新手, 生存, 近卫干员, 输出, Refreshed
3. ★★★ 重装干员, 医疗干员, 辅助干员, 术师干员, 近战位, Recruited
4. ★★★ 医疗干员, 近战位, 治疗, 狙击干员, 群攻, Recruited
5. ★★★ 重装干员, 辅助干员, 群攻, 狙击干员, 术师干员, Recruited
6. ★★★ 医疗干员, 新手, 费用回复, 生存, 减速, Recruited
Recruited 4 times
Refreshed 2 times
----------------------------------------
[Infrast] 16:17:57 - 16:29:51 (11m 54s) Completed
Mfg(PureGold) with operators: unknown
----------------------------------------
[Mall] 16:29:52 - 16:33:39 (3m 47s) Completed
----------------------------------------
[Award] 16:33:40 - 16:34:41 (1m 1s) Completed
----------------------------------------
[Roguelike] 16:34:42 - 16:34:42 (0s) Completed
----------------------------------------
[Reclamation] 16:34:42 - 16:34:42 (0s) Completed
"""


def test_success_report_matches_design():
    parsed = parse_summary(GOLD_SUMMARY)
    report = build_report(
        parsed,
        process_ok=True,
        timed_out=False,
        returncode=0,
        anomaly=scan_log_levels(""),
    )
    text = report.text
    assert text.startswith("✅ MAA daily 完成 · 9/9")
    assert "🕐 16:08:59 → 16:34:42 · 耗时" in text
    assert "⚔ 理智作战 · TO-5 × 14 收获：" in text
    assert "沿途的点滴 × 168" in text
    assert "🎟 公招：招募 4 · 刷新 2 3★ × 4" in text
    assert "🏭 基建 · 🛒 购物 · 🎁 奖励 · 完成" in text
    assert "StartUp" not in text
    assert "Roguelike" not in text
    assert "剿灭" not in text
    assert not report.attach_summary
    assert not report.attach_maa_log


def test_log_warning_option_b_attaches_log_keeps_ok():
    parsed = parse_summary(GOLD_SUMMARY)
    anomaly = scan_log_levels(
        "[2026-08-12 22:50:01 ERROR] boom\n"
        "[2026-08-12 22:50:02 WARN] careful\n"
        "[2026-08-12 22:50:03 INFO] ok\n"
    )
    report = build_report(
        parsed,
        process_ok=True,
        timed_out=False,
        returncode=0,
        anomaly=anomaly,
    )
    assert report.tasks_ok
    assert report.log_warned
    assert report.attach_maa_log
    assert not report.attach_summary
    assert "⚠️ MAA daily 完成 · 9/9 · 有日志告警" in report.text
    assert "ERROR × 1" in report.text
    assert "WARN × 1" in report.text


def test_failure_lists_non_completed_and_attaches():
    text = GOLD_SUMMARY.replace(
        "[理智作战] 16:11:02 - 16:17:11 (6m 8s) Completed",
        "[理智作战] 16:11:02 - 16:17:11 (6m 8s) Error",
        1,
    )
    parsed = parse_summary(text)
    report = build_report(
        parsed,
        process_ok=False,
        timed_out=False,
        returncode=2,
        anomaly=scan_log_levels(""),
    )
    assert not report.tasks_ok
    assert report.attach_summary
    assert report.attach_maa_log
    assert "❌ MAA daily 失败" in report.text
    assert "• [理智作战] Error" in report.text


def test_parse_fight_and_recruit_helpers():
    parsed = parse_summary(GOLD_SUMMARY)
    fight = parsed.find("理智作战")
    assert fight is not None
    stage, times, total = parse_fight(fight.body)
    assert stage == "TO-5"
    assert times == 14
    assert "沿途的点滴 × 168" in (total or "")

    recruit = parsed.find("Recruit")
    assert recruit is not None
    recruited, refreshed, stars = parse_recruit(recruit.body)
    assert recruited == 4
    assert refreshed == 2
    assert stars == {3: 4}


def test_find_maa_log_prefers_exact_timestamp(tmp_path: Path):
    started = datetime(2026, 8, 12, 22, 43, 28)
    day = tmp_path / "2026" / "08" / "12"
    day.mkdir(parents=True)
    exact = day / "22:43:28.log"
    exact.write_text("x", encoding="utf-8")
    (day / "22:43:30.log").write_text("y", encoding="utf-8")
    assert find_maa_log(tmp_path, started) == exact
