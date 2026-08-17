from maa_runner.parse import parse_summary

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
Mfg(PureGold) with operators: unknown
Mfg(CombatRecord) with operators: unknown
Mfg(CombatRecord) with operators: unknown
Trade(Money) with operators: unknown
Trade(Money) with operators: unknown
----------------------------------------
[Mall] 16:29:52 - 16:33:39 (3m 47s) Completed
----------------------------------------
[Award] 16:33:40 - 16:34:41 (1m 1s) Completed
----------------------------------------
[Roguelike] 16:34:42 - 16:34:42 (0s) Completed
----------------------------------------
[Reclamation] 16:34:42 - 16:34:42 (0s) Completed
"""


def test_gold_sample_all_completed():
    parsed = parse_summary(GOLD_SUMMARY)
    names = [task.name for task in parsed.tasks]
    assert names == [
        "StartUp",
        "剿灭",
        "理智作战",
        "Recruit",
        "Infrast",
        "Mall",
        "Award",
        "Roguelike",
        "Reclamation",
    ]
    assert parsed.all_completed
    assert parsed.completed_count == 9
    assert "Fight TO-5 14 times, drops:" in parsed.summary_text
    assert "Detected tags:" in parsed.summary_text


def test_zero_second_completed_is_success():
    text = (
        "Summary\n"
        "----------------------------------------\n"
        "[Roguelike] 16:34:42 - 16:34:42 (0s) Completed\n"
        "----------------------------------------\n"
        "[Reclamation] 16:34:42 - 16:34:42 (0s) Completed\n"
    )
    parsed = parse_summary(text)
    assert parsed.all_completed
    assert [task.status for task in parsed.tasks] == ["Completed", "Completed"]


def test_non_completed_fails_assertion():
    text = GOLD_SUMMARY.replace(
        "[理智作战] 16:11:02 - 16:17:11 (6m 8s) Completed",
        "[理智作战] 16:11:02 - 16:17:11 (6m 8s) Error",
        1,
    )
    parsed = parse_summary(text)
    assert not parsed.all_completed
    failed = [task for task in parsed.tasks if task.status != "Completed"]
    assert [(task.name, task.status) for task in failed] == [("理智作战", "Error")]


def test_no_task_lines_is_not_all_completed():
    parsed = parse_summary("Summary\n----------------------------------------\n")
    assert parsed.tasks == ()
    assert not parsed.all_completed


def test_ignores_duration_and_keeps_original_summary():
    parsed = parse_summary(GOLD_SUMMARY)
    assert parsed.summary_text.startswith("Summary")
    assert "[剿灭] 16:10:27 - 16:11:02 (34s) Completed" in parsed.summary_text


def test_extracts_summary_from_stdout_preamble():
    stdout = "verbose log line\n[StartUp] not a summary line\n\n" + GOLD_SUMMARY
    parsed = parse_summary(stdout)
    assert parsed.summary_text.startswith("Summary")
    assert parsed.all_completed
    assert len(parsed.tasks) == 9
