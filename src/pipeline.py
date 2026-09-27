"""连续的项目转化流程。

把一次路演经历组织为四个阶段：打磨 → 路演 → 验证 → 落地。
项目档案、校内审批、技术证明、路演材料、展示安排以版本化记录互链；
拆分、撤回、回避、重复反馈、意向失效等变化只追加事件并指定后续
责任人，旧记录始终可查。学校以权属、伦理与实际转化结果核对进展，
不以到场人数衡量成效。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .access import AccessControl, is_duplicate_feedback
from .versioning import Event, EventLog, RecordBook, Ref, Versioned

STAGES = ("polishing", "roadshow", "validation", "landing")
STAGE_LABELS = {
    "polishing": "打磨",
    "roadshow": "路演",
    "validation": "验证",
    "landing": "落地",
}

APPROVAL_SCOPES = ("disclosure", "ethics", "ownership")
PROOF_KINDS = ("patent_application", "patent_grant", "tech_report", "ethics_review")

# 学校核对时只认实际转化结果；到场人数、签到量不构成成效证据。
OUTCOME_KINDS = ("signed_contract", "license", "investment_closed", "pilot_adoption", "revenue")
INVALID_OUTCOME_KINDS = ("attendance", "headcount", "sign_in_count")


@dataclass(frozen=True)
class Party:
    id: str
    role: str
    display: str


@dataclass(frozen=True)
class FollowUp:
    id: str
    promised_on: str
    due_on: str
    channel: str
    owner: str
    status: str  # pending | kept | broken | expired


@dataclass(frozen=True)
class Intent:
    id: str
    investor: str
    issued_on: str
    valid_until: str
    status: str  # active | expired | withdrawn


@dataclass(frozen=True)
class UpdateGrant:
    """投资方持续获取更新的授权；意向失效即停止。"""

    investor: str
    granted_on: str
    active: bool
    revoked_on: str | None = None
    revoke_reason: str | None = None


@dataclass(frozen=True)
class UpdateDelivery:
    investor: str
    material: Ref
    on: str


@dataclass(frozen=True)
class SchoolReport:
    """学校核对结论：权属、伦理与实际转化结果。"""

    ownership_clear: bool
    ethics_clear: bool
    outcomes: tuple[str, ...]
    detail: str
    qualifies_landing: bool


class ProjectArchive:
    """单个项目的转化流程档案。"""

    def __init__(self, project_id: str, title: str, created_on: str, members: tuple[str, ...]) -> None:
        self.project_id = project_id
        self.title = title
        self.records = RecordBook()
        self.events = EventLog()
        self.access = AccessControl(self.events)
        self.members: list[str] = list(members)
        self.intents: dict[str, Intent] = {}
        self.follow_ups: dict[str, FollowUp] = {}
        self.update_grants: dict[str, UpdateGrant] = {}
        self.deliveries: list[UpdateDelivery] = []
        self.outcomes: list[dict] = []
        self._stage = "polishing"
        self._profile = self.records.publish(
            "profile",
            project_id,
            {
                "title": title,
                "members": list(members),
                "contribution_shares": {},
                "ip_boundary": "",
                "mentor_conflicts": [],
                "trade_secret_summary": "",
            },
            date=created_on,
            actor=members[0],
            note="项目建档",
        )

    # ---- 基础查询 -------------------------------------------------

    @property
    def stage(self) -> str:
        return self._stage

    @property
    def profile(self) -> Versioned:
        return self.records.head("profile", self.project_id)

    def _head_payload(self, type: str, id: str) -> dict:
        return self.records.head(type, id).payload

    def _head_status(self, type: str, id: str) -> str | None:
        if not self.records.exists(type, id):
            return None
        return self._head_payload(type, id).get("status")

    # ---- 档案与团队 ----------------------------------------------

    def update_profile(
        self,
        *,
        date: str,
        actor: str,
        contribution_shares: dict[str, float] | None = None,
        ip_boundary: str | None = None,
        mentor_conflicts: list[str] | None = None,
        trade_secret_summary: str | None = None,
        note: str = "",
    ) -> Versioned:
        """修订档案；成员贡献、专利边界与导师利益冲突随版本留痕。"""
        payload = dict(self.profile.payload)
        if contribution_shares is not None:
            payload["contribution_shares"] = dict(contribution_shares)
        if ip_boundary is not None:
            payload["ip_boundary"] = ip_boundary
        if mentor_conflicts is not None:
            payload["mentor_conflicts"] = list(mentor_conflicts)
        if trade_secret_summary is not None:
            payload["trade_secret_summary"] = trade_secret_summary
        rec = self.records.publish("profile", self.project_id, payload, date=date, actor=actor, note=note)
        self.events.append("profile_updated", date, actor, {"ref": str(rec.ref), "note": note})
        return rec

    def split_team(self, date: str, actor: str, leaving: list[str], reason: str, handover_owner: str) -> Event:
        """团队拆分：档案续版记录新成员构成，旧版保留，并指定交接责任人。"""
        remaining = [m for m in self.members if m not in leaving]
        if not remaining:
            raise ValueError("拆分后项目至少保留一名成员")
        payload = dict(self.profile.payload)
        payload["members"] = remaining
        shares = dict(payload.get("contribution_shares") or {})
        for m in leaving:
            shares.pop(m, None)
        payload["contribution_shares"] = shares
        rec = self.records.publish(
            "profile", self.project_id, payload, date=date, actor=actor, note=f"团队拆分：{reason}"
        )
        self.members = remaining
        return self.events.append(
            "team_split",
            date,
            actor,
            {"leaving": list(leaving), "remaining": remaining, "reason": reason, "profile": str(rec.ref)},
            follow_up_owner=handover_owner,
            follow_up_due=date,
        )

    # ---- 校内审批与技术证明 ---------------------------------------

    def request_approval(self, scope: str, date: str, actor: str, basis: str) -> Versioned:
        if scope not in APPROVAL_SCOPES:
            raise ValueError(f"未知审批事项：{scope}")
        return self.records.publish(
            "approval",
            f"{self.project_id}-{scope}",
            {"scope": scope, "status": "pending", "basis": basis, "decision": None},
            date=date,
            actor=actor,
        )

    def decide_approval(self, scope: str, date: str, actor: str, approved: bool, comment: str) -> Versioned:
        id = f"{self.project_id}-{scope}"
        if self._head_status("approval", id) != "pending":
            raise ValueError("该审批不在待决状态")
        payload = dict(self._head_payload("approval", id))
        payload["status"] = "approved" if approved else "rejected"
        payload["decision"] = {"by": actor, "on": date, "comment": comment}
        rec = self.records.publish("approval", id, payload, date=date, actor=actor)
        self.events.append(
            "approval_decided", date, actor, {"scope": scope, "approved": approved, "ref": str(rec.ref)}
        )
        return rec

    def approval_ok(self, scope: str) -> bool:
        return self._head_status("approval", f"{self.project_id}-{scope}") == "approved"

    def add_proof(
        self,
        proof_id: str,
        kind: str,
        date: str,
        actor: str,
        summary: str,
        *,
        related_approval: Ref | None = None,
    ) -> Versioned:
        """登记技术证明（专利申请、查新报告、伦理审查等），可关联审批版本。"""
        if kind not in PROOF_KINDS:
            raise ValueError(f"未知证明类型：{kind}")
        links = (related_approval,) if related_approval else ()
        rec = self.records.publish(
            "proof",
            proof_id,
            {"kind": kind, "summary": summary, "status": "valid"},
            date=date,
            actor=actor,
            links=links,
        )
        self.events.append("proof_added", date, actor, {"proof": str(rec.ref), "kind": kind})
        return rec

    def has_proof(self, kind: str) -> bool:
        return any(
            rec.payload.get("kind") == kind and rec.payload.get("status") == "valid"
            for rec in self.records.heads()
            if rec.ref.type == "proof"
        )

    # ---- 路演材料 -------------------------------------------------

    def prepare_material(
        self,
        material_id: str,
        *,
        date: str,
        actor: str,
        content: str,
        contains_trade_secret: bool,
        based_on: tuple[Ref, ...] = (),
    ) -> Versioned:
        """起草路演材料；引用审批与证明的精确版本，含秘密内容须已获披露批准。"""
        if contains_trade_secret and not self.approval_ok("disclosure"):
            raise PermissionError("未获校内披露批准，含商业秘密的材料不能进入路演材料库")
        links = tuple(based_on) + (self.profile.ref,)
        return self.records.publish(
            "material",
            material_id,
            {"content": content, "contains_trade_secret": contains_trade_secret, "status": "draft"},
            date=date,
            actor=actor,
            links=links,
        )

    def publish_material(self, material_id: str, date: str, actor: str) -> Versioned:
        payload = dict(self._head_payload("material", material_id))
        if payload.get("status") == "withdrawn":
            raise ValueError("已撤回的材料不能发布")
        payload["status"] = "published"
        rec = self.records.publish("material", material_id, payload, date=date, actor=actor)
        self.events.append("material_published", date, actor, {"material": str(rec.ref)})
        return rec

    def withdraw_material(self, material_id: str, date: str, actor: str, reason: str, cleanup_owner: str) -> Event:
        """撤回材料：版本链保留可回溯，撤回事件指定清理责任人。"""
        payload = dict(self._head_payload("material", material_id))
        if payload.get("status") == "withdrawn":
            raise ValueError("材料已撤回")
        payload["status"] = "withdrawn"
        payload["withdraw_reason"] = reason
        rec = self.records.publish("material", material_id, payload, date=date, actor=actor, note="撤回")
        return self.events.append(
            "material_withdrawn",
            date,
            actor,
            {"material": str(rec.ref), "reason": reason},
            follow_up_owner=cleanup_owner,
            follow_up_due=date,
        )

    def material_for(self, material_id: str, viewer: str, role: str) -> dict:
        """按查看者身份返回材料内容；未签署约定者看不到商业秘密正文。"""
        head = self.records.head("material", material_id)
        payload = dict(head.payload)
        if payload.get("contains_trade_secret") and not self.access.can_view_secret(viewer, role):
            payload["content"] = "[商业秘密内容已隐藏：需签署披露约定]"
            payload["redacted"] = True
        else:
            payload["redacted"] = False
        return payload

    # ---- 展示安排与评审 -------------------------------------------

    def schedule_arrangement(
        self,
        arrangement_id: str,
        *,
        date: str,
        actor: str,
        session: str,
        slot: str,
        material: Ref,
        judges: tuple[str, ...],
    ) -> Versioned:
        """安排展示场次；锁定到具体材料版本，利益冲突评委不得安排。"""
        material_rec = self.records.get(material)
        if material_rec.payload.get("status") == "withdrawn":
            raise ValueError("不能安排已撤回的材料")
        if material_rec.payload.get("status") != "published":
            raise ValueError("只能安排已发布版本的材料")
        conflicts = set(self.profile.payload.get("mentor_conflicts") or [])
        blocked = [j for j in judges if j in conflicts]
        if blocked:
            raise ValueError(f"评委与项目存在利益冲突，须回避：{blocked}")
        return self.records.publish(
            "arrangement",
            arrangement_id,
            {
                "session": session,
                "slot": slot,
                "material": str(material),
                "judges": list(judges),
                "recused": [],
                "status": "scheduled",
            },
            date=date,
            actor=actor,
            links=(material,),
        )

    def recuse_judge(self, arrangement_id: str, judge: str, date: str, actor: str, reason: str) -> Event:
        """评委回避：安排续版移出评委，回避前评分标记无效但保留可查。"""
        payload = dict(self._head_payload("arrangement", arrangement_id))
        if judge not in payload.get("judges", []):
            raise ValueError(f"{judge} 不在该场次评委名单中")
        payload["judges"] = [j for j in payload["judges"] if j != judge]
        payload["recused"] = list(payload.get("recused", [])) + [judge]
        rec = self.records.publish("arrangement", arrangement_id, payload, date=date, actor=actor, note="评委回避")
        return self.events.append(
            "judge_recused",
            date,
            actor,
            {"arrangement": str(rec.ref), "judge": judge, "reason": reason},
            follow_up_owner=actor,
            follow_up_due=date,
        )

    def _arrangement_recused(self) -> set[str]:
        recused: set[str] = set()
        for rec in self.records.heads():
            if rec.ref.type == "arrangement":
                recused.update(rec.payload.get("recused") or [])
        return recused

    def submit_feedback(
        self,
        arrangement_id: str,
        author: str,
        content: str,
        fingerprint: str,
        date: str,
        triage_owner: str | None = None,
    ) -> Event:
        """记录评委反馈；重复提交标记为重复并指定归并责任人，原记录保留。"""
        arrangement = self._head_payload("arrangement", arrangement_id)
        if author in (arrangement.get("recused") or []):
            raise PermissionError("已回避评委的反馈不再受理")
        if is_duplicate_feedback(self.events.events("feedback"), author, fingerprint):
            return self.events.append(
                "feedback_duplicate",
                date,
                author,
                {"arrangement": arrangement_id, "fingerprint": fingerprint, "content": content},
                follow_up_owner=triage_owner or author,
                follow_up_due=date,
            )
        return self.events.append(
            "feedback",
            date,
            author,
            {"arrangement": arrangement_id, "fingerprint": fingerprint, "content": content},
        )

    def canonical_feedback(self) -> tuple[Event, ...]:
        return self.events.events("feedback")

    # ---- 投资意向、跟进与授权更新 ---------------------------------

    def record_intent(self, intent_id: str, investor: str, issued_on: str, valid_until: str) -> Intent:
        intent = Intent(intent_id, investor, issued_on, valid_until, "active")
        self.intents[intent_id] = intent
        self.events.append(
            "intent_issued",
            issued_on,
            investor,
            {"intent": intent_id, "valid_until": valid_until},
        )
        return intent

    def expire_intents(self, as_of: str) -> tuple[Event, ...]:
        """意向到期未转化即失效；事件指定跟进责任人，授权更新同时停止。"""
        fired: list[Event] = []
        for intent in list(self.intents.values()):
            if intent.status != "active" or intent.valid_until >= as_of:
                continue
            self.intents[intent.id] = Intent(
                intent.id, intent.investor, intent.issued_on, intent.valid_until, "expired"
            )
            self._revoke_update_grant(intent.investor, as_of, f"投资意向 {intent.id} 已失效")
            fired.append(
                self.events.append(
                    "intent_expired",
                    as_of,
                    "system",
                    {"intent": intent.id, "investor": intent.investor},
                    follow_up_owner=self.members[0],
                    follow_up_due=as_of,
                )
            )
        return tuple(fired)

    def withdraw_intent(self, intent_id: str, date: str, actor: str) -> Event:
        intent = self.intents[intent_id]
        if intent.status != "active":
            raise ValueError("意向已不在生效状态")
        self.intents[intent_id] = Intent(intent.id, intent.investor, intent.issued_on, intent.valid_until, "withdrawn")
        self._revoke_update_grant(intent.investor, date, f"投资意向 {intent_id} 已撤回")
        return self.events.append(
            "intent_withdrawn",
            date,
            actor,
            {"intent": intent_id, "investor": intent.investor},
            follow_up_owner=self.members[0],
            follow_up_due=date,
        )

    def _revoke_update_grant(self, investor: str, on: str, reason: str) -> None:
        grant = self.update_grants.get(investor)
        if grant and grant.active:
            self.update_grants[investor] = UpdateGrant(
                investor, grant.granted_on, False, revoked_on=on, revoke_reason=reason
            )

    def grant_updates(self, investor: str, on: str) -> UpdateGrant:
        """授权投资人持续获取更新；须已签署约定且有意向在册。"""
        if not self.access.has_agreement(investor):
            raise PermissionError("未签署披露约定的投资人不能获得持续更新授权")
        if not any(i.investor == investor and i.status == "active" for i in self.intents.values()):
            raise ValueError("该投资人没有生效中的投资意向")
        grant = UpdateGrant(investor, on, True)
        self.update_grants[investor] = grant
        self.events.append("update_granted", on, investor, {"investor": investor})
        return grant

    def push_update(self, investor: str, material_id: str, on: str) -> UpdateDelivery:
        """向被授权投资人推送材料当前版本；授权失效后拒绝。"""
        grant = self.update_grants.get(investor)
        if not grant or not grant.active:
            raise PermissionError(f"{investor} 的更新授权已失效，停止推送")
        head = self.records.head("material", material_id)
        if head.payload.get("status") == "withdrawn":
            raise ValueError("已撤回的材料不再推送")
        delivery = UpdateDelivery(investor, head.ref, on)
        self.deliveries.append(delivery)
        self.events.append(
            "update_delivered", on, "system", {"investor": investor, "material": str(head.ref)}
        )
        return delivery

    def record_follow_up(self, follow_up_id: str, investor: str, promised_on: str, due_on: str, channel: str) -> FollowUp:
        """登记投资人承诺的下一次沟通。"""
        fu = FollowUp(follow_up_id, promised_on, due_on, channel, investor, "pending")
        self.follow_ups[follow_up_id] = fu
        self.events.append(
            "follow_up_promised",
            promised_on,
            investor,
            {"follow_up": follow_up_id, "due_on": due_on, "channel": channel},
            follow_up_owner=self.members[0],
            follow_up_due=due_on,
        )
        return fu

    def follow_up_status(self, follow_up_id: str, as_of: str) -> str:
        """承诺是否兑现：kept / broken / pending / expired。"""
        fu = self.follow_ups[follow_up_id]
        if fu.status == "kept":
            return "kept"
        related_intent = next(
            (i for i in self.intents.values() if i.investor == fu.owner and i.status != "active"),
            None,
        )
        if related_intent is not None:
            return "expired"
        return "broken" if as_of > fu.due_on else "pending"

    def mark_follow_up_kept(self, follow_up_id: str, date: str, actor: str, note: str = "") -> Event:
        fu = self.follow_ups[follow_up_id]
        if fu.status != "pending":
            raise ValueError("该跟进已有结论")
        self.follow_ups[follow_up_id] = FollowUp(
            fu.id, fu.promised_on, fu.due_on, fu.channel, fu.owner, "kept"
        )
        return self.events.append(
            "follow_up_kept", date, actor, {"follow_up": follow_up_id, "note": note}
        )

    # ---- 阶段推进与学校核对 ---------------------------------------

    def gate_check(self, target: str) -> dict[str, bool]:
        """进入目标阶段的前置条件。"""
        if target == "roadshow":
            has_material = any(
                rec.ref.type == "material" and rec.payload.get("status") == "published"
                for rec in self.records.heads()
            )
            has_arrangement = any(
                rec.ref.type == "arrangement" and rec.payload.get("status") == "scheduled"
                for rec in self.records.heads()
            )
            return {
                "披露审批通过": self.approval_ok("disclosure"),
                "伦理审批通过": self.approval_ok("ethics"),
                "材料已发布": has_material,
                "展示已安排": has_arrangement,
            }
        if target == "validation":
            return {
                "路演反馈已归集": len(self.canonical_feedback()) >= 1,
            }
        if target == "landing":
            report = self.school_review()
            return {
                "权属清晰": report.ownership_clear,
                "伦理合规": report.ethics_clear,
                "有实际转化结果": bool(report.outcomes),
            }
        raise ValueError(f"未知目标阶段：{target}")

    def advance(self, target: str, date: str, actor: str) -> Event:
        if target not in STAGES:
            raise ValueError(f"未知阶段：{target}")
        if STAGES.index(target) != STAGES.index(self._stage) + 1:
            raise ValueError(f"只能从{STAGE_LABELS[self._stage]}顺序推进，不能跳到{STAGE_LABELS[target]}")
        checks = self.gate_check(target)
        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            raise PermissionError(f"进入{STAGE_LABELS[target]}的条件未满足：{'、'.join(failed)}")
        self._stage = target
        return self.events.append(
            "stage_advanced", date, actor, {"stage": target, "checks": checks}
        )

    def register_outcome(self, kind: str, date: str, actor: str, detail: str) -> Event:
        """登记实际转化结果；到场人数类指标不予接受。"""
        if kind in INVALID_OUTCOME_KINDS:
            raise ValueError("到场人数不构成成果转化成效，请登记合同、许可、投资或落地应用等实际结果")
        if kind not in OUTCOME_KINDS:
            raise ValueError(f"未知转化结果类型：{kind}")
        self.outcomes.append({"kind": kind, "on": date, "detail": detail})
        return self.events.append("outcome_registered", date, actor, {"kind": kind, "detail": detail})

    def school_review(self) -> SchoolReport:
        """学校核对：权属、伦理与实际转化结果，不采用到场人数。"""
        ownership_clear = self.approval_ok("ownership") and (
            self.has_proof("patent_application") or self.has_proof("patent_grant")
        )
        ethics_clear = self.approval_ok("ethics") and self.has_proof("ethics_review")
        outcomes = tuple(o["kind"] for o in self.outcomes)
        detail_parts = [
            f"权属{'清晰' if ownership_clear else '待补'}",
            f"伦理{'合规' if ethics_clear else '待补'}",
            f"实际转化结果 {len(outcomes)} 项" if outcomes else "尚无实际转化结果",
        ]
        return SchoolReport(
            ownership_clear=ownership_clear,
            ethics_clear=ethics_clear,
            outcomes=outcomes,
            detail="；".join(detail_parts),
            qualifies_landing=ownership_clear and ethics_clear and bool(outcomes),
        )

    # ---- 三方视图 -------------------------------------------------

    def student_view(self, as_of: str) -> dict:
        return {
            "project": self.title,
            "stage": self._stage,
            "stage_label": STAGE_LABELS[self._stage],
            "members": list(self.members),
            "open_follow_ups": [
                {
                    "kind": e.kind,
                    "owner": e.follow_up_owner,
                    "due": e.follow_up_due,
                    "overdue": bool(e.follow_up_due and e.follow_up_due < as_of),
                }
                for e in self.events.open_follow_ups()
            ],
            "next_gate": {
                "target": STAGES[STAGES.index(self._stage) + 1] if self._stage != "landing" else None,
                "checks": self.gate_check(STAGES[STAGES.index(self._stage) + 1])
                if self._stage != "landing"
                else {},
            },
        }

    def investor_view(self, investor: str, as_of: str) -> dict:
        grant = self.update_grants.get(investor)
        deliveries = [d for d in self.deliveries if d.investor == investor]
        follow_ups = [
            {"id": fu.id, "due_on": fu.due_on, "status": self.follow_up_status(fu.id, as_of)}
            for fu in self.follow_ups.values()
            if fu.owner == investor
        ]
        return {
            "stage_label": STAGE_LABELS[self._stage],
            "updates_authorized": bool(grant and grant.active),
            "authorized_until": grant.revoked_on if grant and not grant.active else None,
            "deliveries": [
                {"material": str(d.material), "on": d.on} for d in deliveries
            ],
            "follow_ups": follow_ups,
        }

    def school_view(self) -> dict:
        report = self.school_review()
        return {
            "stage_label": STAGE_LABELS[self._stage],
            "ownership_clear": report.ownership_clear,
            "ethics_clear": report.ethics_clear,
            "outcomes": list(report.outcomes),
            "report": report.detail,
            "metric_note": "以权属、伦理与实际转化结果核对，不采用到场人数",
        }
