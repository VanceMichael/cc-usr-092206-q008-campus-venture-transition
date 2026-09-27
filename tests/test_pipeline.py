import unittest

from src.pipeline import ProjectArchive
from src.versioning import Ref


class PipelineTest(unittest.TestCase):
    def setUp(self):
        # 周六路演前：学生团队建档，成员两人，产业导师陈岳与项目存在利益关系
        self.p = ProjectArchive("p-2026-017", "低功耗传感标签", "2026-09-14", ("林晓", "周然"))
        self.p.update_profile(
            date="2026-09-14",
            actor="林晓",
            contribution_shares={"林晓": 0.6, "周然": 0.4},
            ip_boundary="标签低功耗唤醒电路为职务发明，学校与团队按校内办法约定权属",
            mentor_conflicts=["陈岳"],
            trade_secret_summary="唤醒电路工艺参数为商业秘密",
            note="建档：贡献、专利边界与导师利益关系",
        )

    def _approve_and_prove(self):
        # 校内三项审批 + 技术证明：披露、伦理、权属；专利申请与伦理审查
        self.p.request_approval("disclosure", "2026-09-15", "林晓", "周六路演拟披露技术指标")
        self.p.decide_approval("disclosure", "2026-09-16", "科研处", True, "同意披露脱敏指标，工艺参数按秘密管理")
        self.p.request_approval("ethics", "2026-09-15", "林晓", "涉人体佩戴测试")
        self.p.decide_approval("ethics", "2026-09-16", "伦理委员会", True, "通过")
        ethics = self.p.add_proof("pr-ethics-01", "ethics_review", "2026-09-16", "伦理委员会", "人体佩戴测试审查通过")
        self.p.request_approval("ownership", "2026-09-15", "林晓", "确认职务发明归属")
        self.p.decide_approval("ownership", "2026-09-17", "技术转移办", True, "权属按校内办法清晰")
        patent = self.p.add_proof(
            "pr-patent-01",
            "patent_application",
            "2026-09-17",
            "林晓",
            "低功耗唤醒电路专利申请已受理",
            related_approval=self.p.records.head("approval", "p-2026-017-ownership").ref,
        )
        return ethics, patent

    def test_secret_only_open_to_signed_parties(self):
        self._approve_and_prove()
        material = self.p.prepare_material(
            "m-deck",
            date="2026-09-17",
            actor="林晓",
            content="路演PPT：含唤醒电路工艺参数",
            contains_trade_secret=True,
        )
        self.p.publish_material("m-deck", "2026-09-17", "林晓")

        # 未签署约定的投资人看到的是脱敏内容
        view = self.p.material_for("m-deck", "启航基金-赵投", "investor")
        self.assertTrue(view["redacted"])
        self.assertIn("隐藏", view["content"])

        # 签署披露约定后放行，且留痕
        self.p.access.sign_agreement("启航基金-赵投", "investor", "2026-09-18", ref="NDA-2026-0918")
        self.p.access.disclose_secret("启航基金-赵投", "investor", material.ref, "2026-09-18")
        view = self.p.material_for("m-deck", "启航基金-赵投", "investor")
        self.assertFalse(view["redacted"])
        self.assertEqual(view["content"], "路演PPT：含唤醒电路工艺参数")
        self.assertEqual(len(self.p.access.grants_for(material.ref)), 1)

        # 其他角色不能以"签署约定"名义获取商业秘密
        with self.assertRaises(PermissionError):
            self.p.access.sign_agreement("路人甲", "reviewer", "2026-09-18")

    def test_secret_material_blocked_before_disclosure_approval(self):
        # 未获披露批准前，含商业秘密的材料不能入库
        with self.assertRaises(PermissionError):
            self.p.prepare_material(
                "m-early",
                date="2026-09-15",
                actor="林晓",
                content="未审批的工艺参数",
                contains_trade_secret=True,
            )

    def test_conflicted_judge_blocked_and_recusal_kept(self):
        self._approve_and_prove()
        self.p.prepare_material(
            "m-deck", date="2026-09-17", actor="林晓", content="路演PPT", contains_trade_secret=False
        )
        self.p.publish_material("m-deck", "2026-09-17", "林晓")
        material_head = self.p.records.head("material", "m-deck").ref

        # 与项目有利益关系的导师不得担任评委
        with self.assertRaises(ValueError):
            self.p.schedule_arrangement(
                "a-sat",
                date="2026-09-17",
                actor="高校运营-小钱",
                session="周六主路演厅",
                slot="14:00",
                material=material_head,
                judges=("陈岳", "吴评"),
            )

        arrangement = self.p.schedule_arrangement(
            "a-sat",
            date="2026-09-17",
            actor="高校运营-小钱",
            session="周六主路演厅",
            slot="14:00",
            material=material_head,
            judges=("吴评", "郑评"),
        )
        # 临场发现郑评与团队有其他关联，启动回避
        event = self.p.recuse_judge("a-sat", "郑评", "2026-09-19", "高校运营-小钱", "郑评为团队成员亲属")
        self.assertEqual(event.follow_up_owner, "高校运营-小钱")
        head = self.p.records.head("arrangement", "a-sat")
        self.assertNotIn("郑评", head.payload["judges"])
        self.assertIn("郑评", head.payload["recused"])
        # 回避前的安排版本仍可查
        self.assertEqual(arrangement.payload["judges"], ["吴评", "郑评"])

        # 已回避评委的反馈不再受理；同一要点重复提交被标记并指定归并责任
        with self.assertRaises(PermissionError):
            self.p.submit_feedback("a-sat", "郑评", "补充意见", "fp-zheng-1", "2026-09-19")
        self.p.submit_feedback("a-sat", "吴评", "建议补充功耗实测", "fp-wu-1", "2026-09-19")
        dup = self.p.submit_feedback(
            "a-sat", "吴评", "建议补充功耗实测！", "fp-wu-1", "2026-09-20", triage_owner="林晓"
        )
        self.assertEqual(dup.kind, "feedback_duplicate")
        self.assertEqual(dup.follow_up_owner, "林晓")
        # 规范反馈只有一条，重复记录仍保留
        self.assertEqual(len(self.p.canonical_feedback()), 1)
        self.assertEqual(len(self.p.events.events("feedback_duplicate")), 1)

    def test_version_lineage_links_exact_versions(self):
        _, patent = self._approve_and_prove()
        draft = self.p.prepare_material(
            "m-deck",
            date="2026-09-17",
            actor="林晓",
            content="v1",
            contains_trade_secret=False,
            based_on=(patent.ref,),
        )
        self.p.publish_material("m-deck", "2026-09-17", "林晓")
        published = self.p.records.head("material", "m-deck").ref
        arrangement = self.p.schedule_arrangement(
            "a-sat",
            date="2026-09-18",
            actor="高校运营-小钱",
            session="周六路演",
            slot="14:00",
            material=published,
            judges=("吴评",),
        )
        lineage = self.p.records.lineage(arrangement.ref)
        refs = {str(r) for r in lineage}
        # 安排 → 材料已发布版 → 草稿旧版 → 专利证明 → 档案 v1，均为精确版本
        self.assertIn("material:m-deck#v2", refs)
        self.assertIn("material:m-deck#v1", refs)
        self.assertIn("proof:pr-patent-01#v1", refs)
        self.assertIn("profile:p-2026-017#v1", refs)
        self.assertEqual(draft.ref.version + 1, published.version)

    def test_full_flow_stage_gates_and_views(self):
        self._approve_and_prove()
        self.p.prepare_material(
            "m-deck", date="2026-09-17", actor="林晓", content="路演PPT", contains_trade_secret=False
        )
        self.p.publish_material("m-deck", "2026-09-17", "林晓")
        self.p.schedule_arrangement(
            "a-sat",
            date="2026-09-18",
            actor="高校运营-小钱",
            session="周六主路演厅",
            slot="14:00",
            material=self.p.records.head("material", "m-deck").ref,
            judges=("吴评",),
        )
        # 进入路演阶段
        self.p.advance("roadshow", "2026-09-19", "高校运营-小钱")
        self.assertEqual(self.p.student_view("2026-09-19")["stage_label"], "路演")

        self.p.submit_feedback("a-sat", "吴评", "建议验证量产良率", "fp-wu-2", "2026-09-19")
        self.p.advance("validation", "2026-09-20", "林晓")
        self.assertEqual(self.p.student_view("2026-09-20")["stage_label"], "验证")

        # 路演后：投资人签约定、给意向、承诺下一次沟通，并获得持续更新授权
        self.p.access.sign_agreement("启航基金-赵投", "investor", "2026-09-19", ref="NDA-2026-0918")
        self.p.record_intent("intent-01", "启航基金-赵投", "2026-09-19", "2026-10-10")
        self.p.grant_updates("启航基金-赵投", "2026-09-20")
        delivery = self.p.push_update("启航基金-赵投", "m-deck", "2026-09-25")
        self.assertEqual(str(delivery.material), "material:m-deck#v2")

        self.p.record_follow_up("fu-01", "启航基金-赵投", "2026-09-19", "2026-09-26", "线下尽调会")
        # 承诺期内显示待兑现；按期沟通后标记兑现
        self.assertEqual(self.p.follow_up_status("fu-01", "2026-09-24"), "pending")
        self.p.mark_follow_up_kept("fu-01", "2026-09-26", "启航基金-赵投", "尽调会如期举行")
        self.assertEqual(self.p.follow_up_status("fu-01", "2026-09-27"), "kept")

        view = self.p.investor_view("启航基金-赵投", "2026-09-27")
        self.assertTrue(view["updates_authorized"])
        self.assertEqual(view["follow_ups"][0]["status"], "kept")

    def test_broken_promise_is_visible(self):
        self._approve_and_prove()
        self.p.access.sign_agreement("启航基金-赵投", "investor", "2026-09-19")
        self.p.record_intent("intent-01", "启航基金-赵投", "2026-09-19", "2026-10-10")
        self.p.record_follow_up("fu-02", "启航基金-赵投", "2026-09-19", "2026-09-23", "电话会")
        # 过了约定日期仍未沟通 → 承诺未兑现
        self.assertEqual(self.p.follow_up_status("fu-02", "2026-09-27"), "broken")

    def test_intent_expiry_revokes_updates_but_records_remain(self):
        self._approve_and_prove()
        self.p.prepare_material(
            "m-deck", date="2026-09-17", actor="林晓", content="路演PPT", contains_trade_secret=False
        )
        self.p.publish_material("m-deck", "2026-09-17", "林晓")
        self.p.access.sign_agreement("启航基金-赵投", "investor", "2026-09-19")
        self.p.record_intent("intent-01", "启航基金-赵投", "2026-09-19", "2026-10-10")
        self.p.grant_updates("启航基金-赵投", "2026-09-20")
        self.p.push_update("启航基金-赵投", "m-deck", "2026-09-25")

        # 10月11日意向到期未转化：失效留痕、授权停止、后续责任明确
        fired = self.p.expire_intents("2026-10-11")
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0].follow_up_owner, "林晓")
        self.assertEqual(self.p.intents["intent-01"].status, "expired")
        with self.assertRaises(PermissionError):
            self.p.push_update("启航基金-赵投", "m-deck", "2026-10-12")
        view = self.p.investor_view("启航基金-赵投", "2026-10-12")
        self.assertFalse(view["updates_authorized"])
        self.assertEqual(view["authorized_until"], "2026-10-11")
        # 失效前已推送的更新记录仍可查
        self.assertEqual(len(view["deliveries"]), 1)

    def test_team_split_leaves_old_profile_and_assigns_handover(self):
        before = self.p.profile.ref
        event = self.p.split_team(
            "2026-10-05", "林晓", ["周然"], "方向分歧，周然带走另一应用设想", handover_owner="林晓"
        )
        self.assertEqual(self.p.members, ["林晓"])
        # 旧版档案仍可查，新版记录拆分后的贡献
        old = self.p.records.get(before)
        self.assertIn("周然", old.payload["members"])
        self.assertNotIn("周然", self.p.profile.payload["members"])
        self.assertEqual(self.p.profile.supersedes, before)
        # 交接责任出现在待办中，闭环后消失
        self.assertIn(event, self.p.events.open_follow_ups())
        self.p.events.close(event.seq, "2026-10-08", "林晓", "资料与物料交接完成")
        self.assertNotIn(event, self.p.events.open_follow_ups())

    def test_withdrawn_material_blocked_but_history_reachable(self):
        self._approve_and_prove()
        self.p.prepare_material(
            "m-deck", date="2026-09-17", actor="林晓", content="路演PPT", contains_trade_secret=False
        )
        self.p.publish_material("m-deck", "2026-09-17", "林晓")
        v2 = self.p.records.head("material", "m-deck").ref
        event = self.p.withdraw_material(
            "m-deck", "2026-09-18", "林晓", "发现一处数据未脱敏", cleanup_owner="周然"
        )
        self.assertEqual(event.follow_up_owner, "周然")
        self.assertEqual(self.p.records.head("material", "m-deck").payload["status"], "withdrawn")
        # 撤回前发布版本仍可查，且不能再被安排展示或推送
        self.assertEqual(self.p.records.get(v2).payload["status"], "published")
        with self.assertRaises(ValueError):
            self.p.schedule_arrangement(
                "a-x",
                date="2026-09-18",
                actor="高校运营-小钱",
                session="加场",
                slot="16:00",
                material=self.p.records.head("material", "m-deck").ref,
                judges=("吴评",),
            )

    def test_school_review_uses_real_outcomes_not_attendance(self):
        self._approve_and_prove()
        # 到场人数不能作为成效登记
        with self.assertRaises(ValueError):
            self.p.register_outcome("attendance", "2026-09-19", "高校运营-小钱", "到场300人")

        # 缺实际转化结果时不能进入落地
        self.p.prepare_material(
            "m-deck", date="2026-09-17", actor="林晓", content="路演PPT", contains_trade_secret=False
        )
        self.p.publish_material("m-deck", "2026-09-17", "林晓")
        self.p.schedule_arrangement(
            "a-sat",
            date="2026-09-18",
            actor="高校运营-小钱",
            session="周六路演",
            slot="14:00",
            material=self.p.records.head("material", "m-deck").ref,
            judges=("吴评",),
        )
        self.p.advance("roadshow", "2026-09-19", "高校运营-小钱")
        self.p.submit_feedback("a-sat", "吴评", "可进入试点", "fp-wu-3", "2026-09-19")
        self.p.advance("validation", "2026-09-20", "林晓")
        with self.assertRaises(PermissionError):
            self.p.advance("landing", "2026-10-20", "技术转移办")

        # 登记真实转化结果：试点采用 + 专利许可
        self.p.register_outcome("pilot_adoption", "2026-10-15", "林晓", "两家园区完成试点部署")
        self.p.register_outcome("license", "2026-11-02", "技术转移办", "唤醒电路专利非独占许可")
        report = self.p.school_review()
        self.assertTrue(report.ownership_clear)
        self.assertTrue(report.ethics_clear)
        self.assertEqual(set(report.outcomes), {"pilot_adoption", "license"})
        self.assertTrue(report.qualifies_landing)

        self.p.advance("landing", "2026-11-05", "技术转移办")
        school = self.p.school_view()
        self.assertEqual(school["stage_label"], "落地")
        self.assertIn("不采用到场人数", school["metric_note"])


if __name__ == "__main__":
    unittest.main()
