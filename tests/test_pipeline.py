import unittest
from datetime import datetime

from src.pipeline import (
    ACTIVE,
    INTENT_EXPIRED,
    INTENT_FULFILLED,
    SUPERSEDED,
    WITHDRAWN,
    ArtifactKind,
    ConfidentialityAgreement,
    EventKind,
    OversightReview,
    Project,
    Stage,
)

T0 = datetime(2026, 9, 20, 9, 0)
T1 = datetime(2026, 9, 21, 9, 0)
T2 = datetime(2026, 9, 22, 9, 0)
SATURDAY = datetime(2026, 9, 26, 14, 0)  # 路演当天
AFTER = datetime(2026, 9, 28, 9, 0)


def ready_project() -> Project:
    """披露确认完成、审批到展示安排齐备的项目。"""
    p = Project("p-1", "柔性传感贴片")
    p.checklist.disclosure_approved = True
    p.checklist.contributions_recorded = True
    p.checklist.patent_filed = True
    p.checklist.advisor_conflicts_declared = True
    p.publish(ArtifactKind.ARCHIVE, "arc-1", "项目档案初版", "队长", T0)
    p.publish(ArtifactKind.APPROVAL, "app-1", "成果披露审批通过", "学院科研办", T0)
    p.publish(ArtifactKind.CERTIFICATION, "cer-1", "检测报告", "实验室", T1)
    p.publish(ArtifactKind.MATERIAL, "mat-1", "路演PPT初版", "队长", T1)
    p.publish(ArtifactKind.SCHEDULE, "sch-1", "周六下午路演时段", "运营人员", T2)
    return p


class VersionChainTest(unittest.TestCase):
    def test_versions_link_across_artifacts(self):
        p = ready_project()
        material = p.get("mat-1")
        self.assertEqual(material.basis[ArtifactKind.ARCHIVE], "arc-1")
        self.assertEqual(material.basis[ArtifactKind.APPROVAL], "app-1")
        self.assertEqual(material.basis[ArtifactKind.CERTIFICATION], "cer-1")
        schedule = p.get("sch-1")
        self.assertEqual(schedule.basis[ArtifactKind.MATERIAL], "mat-1")

    def test_new_version_supersedes_and_keeps_history(self):
        p = ready_project()
        v2 = p.publish(ArtifactKind.MATERIAL, "mat-2", "路演PPT修订版", "队长", T2)
        self.assertEqual(v2.version, 2)
        self.assertEqual(v2.supersedes, "mat-1")
        self.assertEqual(p.get("mat-1").status, SUPERSEDED)
        self.assertEqual(p.current(ArtifactKind.MATERIAL).record_id, "mat-2")
        self.assertEqual(len(p.history(ArtifactKind.MATERIAL)), 2)

    def test_dependencies_are_enforced(self):
        p = Project("p-2", "空项目")
        with self.assertRaises(ValueError):
            p.publish(ArtifactKind.CERTIFICATION, "cer-x", "无审批的证明", "实验室", T0)
        with self.assertRaises(ValueError):
            p.publish(ArtifactKind.MATERIAL, "mat-x", "无档案的材料", "队长", T0)

    def test_schedule_requires_completed_checklist(self):
        p = Project("p-3", "未确认披露的项目")
        p.publish(ArtifactKind.ARCHIVE, "arc-1", "档案", "队长", T0)
        p.publish(ArtifactKind.APPROVAL, "app-1", "审批", "科研办", T0)
        p.publish(ArtifactKind.CERTIFICATION, "cer-1", "证明", "实验室", T0)
        p.publish(ArtifactKind.MATERIAL, "mat-1", "材料", "队长", T0)
        with self.assertRaises(ValueError):
            p.publish(ArtifactKind.SCHEDULE, "sch-1", "安排", "运营", T0)

    def test_withdrawal_keeps_old_record_and_assigns_follow_up(self):
        p = ready_project()
        p.withdraw("mat-1", "队长", T2, follow_up_owner="运营人员", reason="含未披露参数")
        record = p.get("mat-1")
        self.assertEqual(record.status, WITHDRAWN)
        self.assertIsNone(p.current(ArtifactKind.MATERIAL))
        self.assertIn(record, p.history(ArtifactKind.MATERIAL))
        events = p.events_of(EventKind.MATERIAL_WITHDRAWN)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].follow_up_owner, "运营人员")
        self.assertEqual(events[0].refs, ("mat-1",))
        with self.assertRaises(ValueError):
            p.withdraw("mat-1", "队长", T2, follow_up_owner="运营人员")


class ConfidentialAccessTest(unittest.TestCase):
    def setUp(self):
        self.p = ready_project()
        self.p.publish(
            ArtifactKind.MATERIAL, "mat-9", "含核心配方的材料", "队长", T2, confidential=True
        )
        self.secret = self.p.get("mat-9")

    def test_investor_with_valid_agreement_can_view(self):
        self.p.add_agreement(
            ConfidentialityAgreement("某创投", "投资机构", signed_at=T1, expires_at=AFTER)
        )
        self.assertTrue(self.p.can_view(self.secret, "某创投", SATURDAY))

    def test_unsigned_or_wrong_role_cannot_view(self):
        self.assertFalse(self.p.can_view(self.secret, "某创投", SATURDAY))
        self.p.add_agreement(ConfidentialityAgreement("路人", "学生创业团队", signed_at=T1))
        self.assertFalse(self.p.can_view(self.secret, "路人", SATURDAY))

    def test_mentor_can_view_but_not_after_revoke_or_expiry(self):
        agreement = ConfidentialityAgreement(
            "王导师", "产业导师", signed_at=T1, expires_at=SATURDAY
        )
        self.p.add_agreement(agreement)
        self.assertTrue(self.p.can_view(self.secret, "王导师", T2))
        self.assertFalse(self.p.can_view(self.secret, "王导师", AFTER))
        agreement.revoked_at = T2
        self.assertFalse(self.p.can_view(self.secret, "王导师", T2))

    def test_authorized_updates_filter_by_agreement(self):
        self.p.publish_update("up-1", "公开进展：完成打样", T1)
        self.p.publish_update("up-2", "机密进展：工艺参数", T2, confidential=True)
        self.assertEqual([u.update_id for u in self.p.authorized_updates("某创投", T2)], ["up-1"])
        self.p.add_agreement(ConfidentialityAgreement("某创投", "投资机构", signed_at=T1))
        self.assertEqual(
            [u.update_id for u in self.p.authorized_updates("某创投", T2)], ["up-1", "up-2"]
        )


class StageFlowTest(unittest.TestCase):
    def test_stage_advances_step_by_step(self):
        p = Project("p-4", "新项目")
        with self.assertRaises(ValueError):
            p.advance_to(Stage.ROADSHOW, T0)  # 披露与安排未就绪
        p = ready_project()
        with self.assertRaises(ValueError):
            p.advance_to(Stage.VALIDATION, T0)  # 不能跳级
        p.advance_to(Stage.ROADSHOW, SATURDAY)
        with self.assertRaises(ValueError):
            p.advance_to(Stage.VALIDATION, SATURDAY)  # 路演尚未举行
        p.mark_showcase_held("sch-1", SATURDAY)
        p.advance_to(Stage.VALIDATION, AFTER)
        with self.assertRaises(ValueError):
            p.advance_to(Stage.LANDING, AFTER)  # 学校核对未通过
        p.add_oversight_review(
            OversightReview(
                reviewer="学校成果转化中心",
                at=AFTER,
                ownership_clear=True,
                ethics_passed=True,
                conversion_evidence="许可合同 HT-2026-118",
            )
        )
        p.advance_to(Stage.LANDING, AFTER)
        self.assertEqual(p.stage, Stage.LANDING)
        self.assertEqual([s for s, _ in p.stage_history],
                         [Stage.ROADSHOW, Stage.VALIDATION, Stage.LANDING])

    def test_oversight_requires_real_conversion_not_attendance(self):
        review = OversightReview(
            reviewer="学校成果转化中心",
            at=AFTER,
            ownership_clear=True,
            ethics_passed=True,
            conversion_evidence="",
            note="路演到场人数众多",
        )
        self.assertFalse(review.passed())


class EventLedgerTest(unittest.TestCase):
    def test_team_split_preserves_contributions_and_links_projects(self):
        p = ready_project()
        p.record_contribution("甲", "传感算法", T0)
        p.record_contribution("乙", "结构设计", T0)
        child = p.split_team("p-1b", "医疗方向拆分", ["乙"], "共有专利按方向划分",
                             AFTER, follow_up_owner="学院科研办")
        self.assertEqual(child.predecessor_id, "p-1")
        self.assertEqual(len(child.contributions), 2)  # 贡献记录不随拆分丢失
        for project in (p, child):
            events = project.events_of(EventKind.TEAM_SPLIT)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].follow_up_owner, "学院科研办")

    def test_judge_recusal_excludes_scores_but_keeps_records(self):
        p = ready_project()
        p.declare_advisor_interest("钱教授", "持有项目公司股权", T0)
        p.add_score("钱教授", 90, SATURDAY)
        p.add_score("孙评委", 75, SATURDAY)
        p.recuse_judge("钱教授", "与项目存在股权利益关系", SATURDAY,
                       follow_up_owner="赛事组委会")
        self.assertEqual([s.judge for s in p.active_scores()], ["孙评委"])
        self.assertEqual(len(p.scores), 2)  # 旧评分仍可查
        self.assertTrue(p.scores[0].excluded)
        events = p.events_of(EventKind.JUDGE_RECUSED)
        self.assertEqual(events[0].follow_up_owner, "赛事组委会")

    def test_duplicate_feedback_flagged_and_retained(self):
        p = ready_project()
        p.add_feedback("fb-1", "周投资人", "建议补充成本测算", SATURDAY, "运营人员")
        dup = p.add_feedback("fb-2", "周投资人", "建议补充成本测算", SATURDAY, "运营人员")
        self.assertEqual(dup.duplicate_of, "fb-1")
        self.assertEqual(len(p.feedback), 2)  # 重复反馈也保留
        events = p.events_of(EventKind.DUPLICATE_FEEDBACK)
        self.assertEqual(events[0].refs, ("fb-2", "fb-1"))


class InvestmentIntentTest(unittest.TestCase):
    def test_promised_contact_fulfilled(self):
        p = ready_project()
        p.add_intent("in-1", "某创投", promised_contact_at=AFTER)
        intent = p.record_contact("in-1", SATURDAY)
        self.assertEqual(intent.status, INTENT_FULFILLED)
        self.assertEqual(intent.fulfilled_at, SATURDAY)

    def test_overdue_intent_expires_with_follow_up_owner(self):
        p = ready_project()
        p.add_intent("in-1", "某创投", promised_contact_at=SATURDAY)
        expired = p.expire_intents(AFTER, follow_up_owner="运营人员")
        self.assertEqual([i.intent_id for i in expired], ["in-1"])
        intent = p.intents[0]
        self.assertEqual(intent.status, INTENT_EXPIRED)
        self.assertIsNotNone(intent.expired_at)  # 旧意向仍可查
        events = p.events_of(EventKind.INTENT_EXPIRED)
        self.assertEqual(events[0].follow_up_owner, "运营人员")
        with self.assertRaises(ValueError):
            p.record_contact("in-1", AFTER)  # 已失效的意向不能再登记沟通

    def test_late_contact_before_expiry_check_is_rejected(self):
        p = ready_project()
        p.add_intent("in-1", "某创投", promised_contact_at=SATURDAY)
        with self.assertRaises(ValueError):
            p.record_contact("in-1", AFTER)


if __name__ == "__main__":
    unittest.main()
