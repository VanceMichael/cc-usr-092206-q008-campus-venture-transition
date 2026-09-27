"""项目转化流程：档案、审批、证明、材料与安排之间的版本联系及多方协作规则。

规则要点：
- 五类材料各自形成版本链，新版本记录被取代版本，并快照所依据的其他材料版本；
- 标记为商业秘密的内容仅向签署有效保密约定的投资机构与产业导师开放；
- 团队拆分、材料撤回、评委回避、重复反馈、投资意向失效只追加记录，旧记录仍可查，
  每条事件都写明后续责任人；
- 阶段沿打磨、路演、验证、落地单向推进，落地须通过权属、伦理与实际成果转化核对。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Stage(Enum):
    """项目所处阶段。"""

    POLISHING = "打磨"
    ROADSHOW = "路演"
    VALIDATION = "验证"
    LANDING = "落地"


STAGE_ORDER = [Stage.POLISHING, Stage.ROADSHOW, Stage.VALIDATION, Stage.LANDING]


class ArtifactKind(Enum):
    """参与版本联系的五类材料。"""

    ARCHIVE = "项目档案"
    APPROVAL = "校内审批"
    CERTIFICATION = "技术证明"
    MATERIAL = "路演材料"
    SCHEDULE = "展示安排"


class EventKind(Enum):
    TEAM_SPLIT = "团队拆分"
    MATERIAL_WITHDRAWN = "材料撤回"
    JUDGE_RECUSED = "评委回避"
    DUPLICATE_FEEDBACK = "重复反馈"
    INTENT_EXPIRED = "投资意向失效"


ACTIVE = "在效"
SUPERSEDED = "已取代"
WITHDRAWN = "已撤回"

INTENT_ACTIVE = "进行中"
INTENT_FULFILLED = "已兑现"
INTENT_EXPIRED = "已失效"

# 商业秘密仅向这两类签署约定的参与方开放
CONFIDENTIAL_ROLES = {"投资机构", "产业导师"}


@dataclass
class ArtifactVersion:
    """某类材料的一个版本；supersedes 指向前一版本，basis 快照所依据的其他材料版本。"""

    record_id: str
    kind: ArtifactKind
    version: int
    summary: str
    created_by: str
    created_at: datetime
    supersedes: str | None = None
    basis: dict[ArtifactKind, str] = field(default_factory=dict)
    confidential: bool = False
    status: str = ACTIVE
    held_at: datetime | None = None  # 仅展示安排：路演实际举行时间


@dataclass
class DisclosureChecklist:
    """路演前的披露确认：成果能否公开、贡献、专利与导师利益关系。"""

    disclosure_approved: bool = False  # 实验室成果对外披露已获校内批准
    contributions_recorded: bool = False  # 成员贡献已登记
    patent_filed: bool = False  # 专利申请已提交
    advisor_conflicts_declared: bool = False  # 导师利益关系已申报

    def complete(self) -> bool:
        return (
            self.disclosure_approved
            and self.contributions_recorded
            and self.patent_filed
            and self.advisor_conflicts_declared
        )


@dataclass
class ConfidentialityAgreement:
    """保密约定；只有投资机构与产业导师签署后才可查看商业秘密。"""

    party: str
    role: str
    signed_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None

    def valid_at(self, at: datetime) -> bool:
        if self.role not in CONFIDENTIAL_ROLES:
            return False
        if self.signed_at > at:
            return False
        if self.revoked_at is not None and self.revoked_at <= at:
            return False
        if self.expires_at is not None and self.expires_at < at:
            return False
        return True


@dataclass
class Event:
    """只增不删的协作事件；follow_up_owner 为后续责任人。"""

    event_id: str
    kind: EventKind
    at: datetime
    actor: str
    detail: str
    follow_up_owner: str
    refs: tuple[str, ...] = ()


@dataclass
class Contribution:
    member: str
    description: str
    at: datetime


@dataclass
class AdvisorInterest:
    """导师申报的利益关系，如持有项目股权或在校外企业任职。"""

    advisor: str
    description: str
    at: datetime


@dataclass
class Feedback:
    feedback_id: str
    author: str
    content: str
    at: datetime
    duplicate_of: str | None = None


@dataclass
class JudgeScore:
    judge: str
    score: float
    at: datetime
    excluded: bool = False
    exclusion_reason: str = ""


@dataclass
class InvestmentIntent:
    """投资意向；promised_contact_at 为投资人承诺的下一次沟通时间。"""

    intent_id: str
    investor: str
    promised_contact_at: datetime
    note: str = ""
    status: str = INTENT_ACTIVE
    fulfilled_at: datetime | None = None
    expired_at: datetime | None = None


@dataclass
class ProjectUpdate:
    """面向投资方的项目进展更新。"""

    update_id: str
    summary: str
    at: datetime
    confidential: bool = False


@dataclass
class OversightReview:
    """学校核对：权属、伦理与实际成果转化；不以到场人数论成效。"""

    reviewer: str
    at: datetime
    ownership_clear: bool  # 权属清晰
    ethics_passed: bool  # 伦理审查通过
    conversion_evidence: str  # 实际成果转化证据，如许可合同或作价投资凭证
    note: str = ""

    def passed(self) -> bool:
        return (
            self.ownership_clear
            and self.ethics_passed
            and bool(self.conversion_evidence.strip())
        )


class Project:
    """一个学生项目的转化流程档案。"""

    def __init__(self, project_id: str, title: str, predecessor_id: str | None = None):
        self.project_id = project_id
        self.title = title
        self.predecessor_id = predecessor_id  # 团队拆分时指向原项目
        self.stage = Stage.POLISHING
        self.stage_history: list[tuple[Stage, datetime]] = []
        self.checklist = DisclosureChecklist()
        self.contributions: list[Contribution] = []
        self.advisor_interests: list[AdvisorInterest] = []
        self.agreements: list[ConfidentialityAgreement] = []
        self.events: list[Event] = []
        self.feedback: list[Feedback] = []
        self.scores: list[JudgeScore] = []
        self.intents: list[InvestmentIntent] = []
        self.updates: list[ProjectUpdate] = []
        self.oversight_reviews: list[OversightReview] = []
        self._artifacts: dict[ArtifactKind, list[ArtifactVersion]] = {
            kind: [] for kind in ArtifactKind
        }

    # ---- 版本联系 ----

    def publish(
        self,
        kind: ArtifactKind,
        record_id: str,
        summary: str,
        created_by: str,
        created_at: datetime,
        confidential: bool = False,
    ) -> ArtifactVersion:
        """发布某类材料的新版本，自动链接被取代版本与所依据的其他材料版本。"""
        if self.get(record_id) is not None:
            raise ValueError(f"记录编号重复：{record_id}")
        if kind is ArtifactKind.CERTIFICATION and self.current(ArtifactKind.APPROVAL) is None:
            raise ValueError("技术证明须以在效的校内审批为依据")
        if kind is ArtifactKind.MATERIAL and (
            self.current(ArtifactKind.ARCHIVE) is None
            or self.current(ArtifactKind.CERTIFICATION) is None
        ):
            raise ValueError("路演材料须以在效的项目档案与技术证明为依据")
        if kind is ArtifactKind.SCHEDULE:
            if not self.checklist.complete():
                raise ValueError("披露确认未完成，不能安排展示")
            if self.current(ArtifactKind.APPROVAL) is None or self.current(
                ArtifactKind.MATERIAL
            ) is None:
                raise ValueError("展示安排须以在效的校内审批与路演材料为依据")
        chain = self._artifacts[kind]
        head = chain[-1] if chain else None
        if head is not None and head.status == ACTIVE:
            head.status = SUPERSEDED
        basis = {}
        for other in ArtifactKind:
            if other is not kind:
                current = self.current(other)
                if current is not None:
                    basis[other] = current.record_id
        record = ArtifactVersion(
            record_id=record_id,
            kind=kind,
            version=(head.version + 1) if head else 1,
            summary=summary,
            created_by=created_by,
            created_at=created_at,
            supersedes=head.record_id if head else None,
            basis=basis,
            confidential=confidential,
        )
        chain.append(record)
        return record

    def current(self, kind: ArtifactKind) -> ArtifactVersion | None:
        """该类材料的在效版本；被取代或已撤回的版本不算。"""
        chain = self._artifacts[kind]
        if chain and chain[-1].status == ACTIVE:
            return chain[-1]
        return None

    def history(self, kind: ArtifactKind) -> list[ArtifactVersion]:
        """该类材料的全部版本，含已取代与已撤回的旧记录。"""
        return list(self._artifacts[kind])

    def get(self, record_id: str) -> ArtifactVersion | None:
        for chain in self._artifacts.values():
            for record in chain:
                if record.record_id == record_id:
                    return record
        return None

    def withdraw(
        self,
        record_id: str,
        actor: str,
        at: datetime,
        follow_up_owner: str,
        reason: str = "",
    ) -> ArtifactVersion:
        """撤回材料版本；旧版本保留可查，并登记后续责任人。"""
        record = self.get(record_id)
        if record is None:
            raise ValueError(f"找不到记录：{record_id}")
        if record.status != ACTIVE:
            raise ValueError("只能撤回在效版本")
        record.status = WITHDRAWN
        self._log(
            EventKind.MATERIAL_WITHDRAWN,
            at,
            actor,
            f"撤回{record.kind.value}第{record.version}版：{reason}",
            follow_up_owner,
            refs=(record_id,),
        )
        return record

    def mark_showcase_held(self, record_id: str, at: datetime) -> None:
        record = self.get(record_id)
        if record is None or record.kind is not ArtifactKind.SCHEDULE:
            raise ValueError("只能登记展示安排的举行时间")
        record.held_at = at

    # ---- 商业秘密访问 ----

    def add_agreement(self, agreement: ConfidentialityAgreement) -> None:
        self.agreements.append(agreement)

    def can_view(self, item: ArtifactVersion | ProjectUpdate, party: str, at: datetime) -> bool:
        if not item.confidential:
            return True
        return any(a.party == party and a.valid_at(at) for a in self.agreements)

    def authorized_updates(self, party: str, at: datetime) -> list[ProjectUpdate]:
        """投资方持续获取的、其被授权可见的更新。"""
        return [u for u in self.updates if self.can_view(u, party, at)]

    def publish_update(
        self, update_id: str, summary: str, at: datetime, confidential: bool = False
    ) -> ProjectUpdate:
        update = ProjectUpdate(update_id, summary, at, confidential)
        self.updates.append(update)
        return update

    # ---- 披露确认、贡献与利益关系 ----

    def record_contribution(self, member: str, description: str, at: datetime) -> None:
        self.contributions.append(Contribution(member, description, at))

    def declare_advisor_interest(self, advisor: str, description: str, at: datetime) -> None:
        self.advisor_interests.append(AdvisorInterest(advisor, description, at))

    def ready_for_roadshow(self) -> bool:
        return (
            self.checklist.complete()
            and self.current(ArtifactKind.APPROVAL) is not None
            and self.current(ArtifactKind.SCHEDULE) is not None
        )

    # ---- 阶段流转 ----

    def advance_to(self, stage: Stage, at: datetime) -> None:
        current_idx = STAGE_ORDER.index(self.stage)
        if STAGE_ORDER.index(stage) != current_idx + 1:
            raise ValueError("阶段只能沿打磨、路演、验证、落地逐级前进")
        if stage is Stage.ROADSHOW and not self.ready_for_roadshow():
            raise ValueError("披露确认、校内审批或展示安排未就绪，不能进入路演")
        if stage is Stage.VALIDATION and not any(
            r.held_at is not None for r in self._artifacts[ArtifactKind.SCHEDULE]
        ):
            raise ValueError("路演尚未举行，不能进入验证")
        if stage is Stage.LANDING and not any(r.passed() for r in self.oversight_reviews):
            raise ValueError("权属、伦理与实际成果转化核对未通过，不能进入落地")
        self.stage = stage
        self.stage_history.append((stage, at))

    # ---- 事件（只增不删） ----

    def _log(
        self,
        kind: EventKind,
        at: datetime,
        actor: str,
        detail: str,
        follow_up_owner: str,
        refs: tuple[str, ...] = (),
    ) -> Event:
        event = Event(
            event_id=f"ev-{len(self.events) + 1}",
            kind=kind,
            at=at,
            actor=actor,
            detail=detail,
            follow_up_owner=follow_up_owner,
            refs=refs,
        )
        self.events.append(event)
        return event

    def events_of(self, kind: EventKind) -> list[Event]:
        return [e for e in self.events if e.kind is kind]

    def split_team(
        self,
        new_project_id: str,
        new_title: str,
        departing: list[str],
        ip_note: str,
        at: datetime,
        follow_up_owner: str,
    ) -> Project:
        """团队拆分：原项目保留全部记录，新项目链接原项目并继承贡献记录。"""
        child = Project(new_project_id, new_title, predecessor_id=self.project_id)
        child.contributions = list(self.contributions)
        detail = f"成员{','.join(departing)}分出；知识产权约定：{ip_note}"
        self._log(EventKind.TEAM_SPLIT, at, follow_up_owner, detail, follow_up_owner,
                  refs=(new_project_id,))
        child._log(EventKind.TEAM_SPLIT, at, follow_up_owner,
                   f"自{self.project_id}分出；{detail}", follow_up_owner,
                   refs=(self.project_id,))
        return child

    # ---- 评审 ----

    def add_score(self, judge: str, score: float, at: datetime) -> None:
        self.scores.append(JudgeScore(judge, score, at))

    def recuse_judge(self, judge: str, reason: str, at: datetime, follow_up_owner: str) -> Event:
        """评委回避：其评分不计入，但记录保留可查。"""
        for s in self.scores:
            if s.judge == judge and not s.excluded:
                s.excluded = True
                s.exclusion_reason = reason
        return self._log(EventKind.JUDGE_RECUSED, at, judge, reason, follow_up_owner)

    def active_scores(self) -> list[JudgeScore]:
        return [s for s in self.scores if not s.excluded]

    def add_feedback(
        self, feedback_id: str, author: str, content: str, at: datetime, follow_up_owner: str
    ) -> Feedback:
        """登记反馈；与同一作者已有反馈内容重复的标记为重复并登记事件。"""
        duplicate_of = None
        for existing in self.feedback:
            if (
                existing.duplicate_of is None
                and existing.author == author
                and existing.content.strip() == content.strip()
            ):
                duplicate_of = existing.feedback_id
                break
        item = Feedback(feedback_id, author, content, at, duplicate_of)
        self.feedback.append(item)
        if duplicate_of is not None:
            self._log(
                EventKind.DUPLICATE_FEEDBACK,
                at,
                author,
                f"反馈{feedback_id}与{duplicate_of}重复",
                follow_up_owner,
                refs=(feedback_id, duplicate_of),
            )
        return item

    # ---- 投资意向 ----

    def add_intent(
        self, intent_id: str, investor: str, promised_contact_at: datetime, note: str = ""
    ) -> InvestmentIntent:
        intent = InvestmentIntent(intent_id, investor, promised_contact_at, note)
        self.intents.append(intent)
        return intent

    def _intent(self, intent_id: str) -> InvestmentIntent:
        for intent in self.intents:
            if intent.intent_id == intent_id:
                return intent
        raise ValueError(f"找不到投资意向：{intent_id}")

    def record_contact(self, intent_id: str, at: datetime) -> InvestmentIntent:
        """登记投资人的实际沟通；在承诺时间之前则记为已兑现。"""
        intent = self._intent(intent_id)
        if intent.status != INTENT_ACTIVE:
            raise ValueError(f"意向已{intent.status}，不能再登记沟通")
        if at > intent.promised_contact_at:
            raise ValueError("已超过承诺的下一次沟通时间，请先处理失效")
        intent.status = INTENT_FULFILLED
        intent.fulfilled_at = at
        return intent

    def expire_intents(self, at: datetime, follow_up_owner: str) -> list[InvestmentIntent]:
        """承诺沟通未兑现且已过期的意向记为失效；旧记录保留并写明后续责任人。"""
        expired = []
        for intent in self.intents:
            if intent.status == INTENT_ACTIVE and intent.promised_contact_at < at:
                intent.status = INTENT_EXPIRED
                intent.expired_at = at
                expired.append(intent)
                self._log(
                    EventKind.INTENT_EXPIRED,
                    at,
                    intent.investor,
                    f"意向{intent.intent_id}承诺的{intent.promised_contact_at.isoformat()}沟通未兑现",
                    follow_up_owner,
                    refs=(intent.intent_id,),
                )
        return expired

    # ---- 学校核对 ----

    def add_oversight_review(self, review: OversightReview) -> None:
        self.oversight_reviews.append(review)
