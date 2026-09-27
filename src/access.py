"""访问控制：商业秘密仅对签署约定的投资人与产业导师开放。

约定（保密/披露协议）签署后才放行标记为商业秘密的内容；投资人的
持续更新授权与其投资意向绑定，意向失效则停发后续更新，已授权期间
的查看记录仍保留可查。
"""

from __future__ import annotations

from dataclasses import dataclass

from .versioning import Event, EventLog, Ref

ROLES = ("student", "school_ops", "industry_mentor", "investor", "reviewer")

ALLOWED_SECRET_RECIPIENT_ROLES = frozenset({"investor", "industry_mentor"})


@dataclass(frozen=True)
class Agreement:
    party: str
    role: str
    signed_on: str
    scope: str = "商业秘密"
    ref: str | None = None  # 协议文本编号，仓库不保存协议正文


@dataclass(frozen=True)
class AccessGrant:
    """一次内容放行；用于留痕，不代表持续授权。"""

    party: str
    role: str
    target: Ref
    on: str
    reason: str  # agreement | authorized_update | mentor_supervision


class AccessControl:
    def __init__(self, events: EventLog) -> None:
        self._agreements: dict[str, Agreement] = {}
        self.events = events
        self.grants: list[AccessGrant] = []

    def sign_agreement(self, party: str, role: str, on: str, *, ref: str | None = None) -> Agreement:
        if role not in ALLOWED_SECRET_RECIPIENT_ROLES:
            raise PermissionError("仅投资人和产业导师可签署商业秘密披露约定")
        agreement = Agreement(party=party, role=role, signed_on=on, ref=ref)
        self._agreements[party] = agreement
        self.events.append("agreement_signed", on, party, {"role": role, "scope": agreement.scope, "ref": ref})
        return agreement

    def has_agreement(self, party: str) -> bool:
        return party in self._agreements

    def can_view_secret(self, party: str, role: str) -> bool:
        agreement = self._agreements.get(party)
        return agreement is not None and agreement.role == role

    def disclose_secret(self, party: str, role: str, target: Ref, on: str, *, reason: str = "agreement") -> AccessGrant:
        if not self.can_view_secret(party, role):
            raise PermissionError(f"{party} 未签署披露约定，不能查看 {target} 的商业秘密内容")
        grant = AccessGrant(party, role, target, on, reason)
        self.grants.append(grant)
        return grant

    def grants_for(self, target: Ref) -> tuple[AccessGrant, ...]:
        return tuple(g for g in self.grants if g.target == target)


def is_duplicate_feedback(prior: tuple[Event, ...], author: str, content_fingerprint: str) -> bool:
    """同一评委对同一要点的再次提交视为重复反馈。"""
    return any(
        e.kind == "feedback"
        and e.actor == author
        and e.payload.get("fingerprint") == content_fingerprint
        for e in prior
    )
