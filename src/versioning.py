"""版本化记录与只追加事件日志。

转化流程中的项目档案、审批、技术证明、路演材料、展示安排都通过
``RecordBook`` 保存为不可变版本，版本之间以精确的版本引用互链；
拆分、撤回、回避、去重、失效等动态事实写入 ``EventLog``，只能追加
闭环事件，不能改写旧记录。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Ref:
    """指向某条记录的精确版本。"""

    type: str
    id: str
    version: int

    def __str__(self) -> str:
        return f"{self.type}:{self.id}#v{self.version}"

    @property
    def key(self) -> tuple[str, str]:
        return (self.type, self.id)


@dataclass(frozen=True)
class Versioned:
    ref: Ref
    date: str
    actor: str
    payload: dict
    supersedes: Ref | None = None
    links: tuple[Ref, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class Event:
    seq: int
    date: str
    actor: str
    kind: str
    payload: dict = field(default_factory=dict)
    follow_up_owner: str | None = None
    follow_up_due: str | None = None


class RecordBook:
    """保存同一项目下所有版本化记录，旧版永不删除或覆盖。"""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], list[Versioned]] = {}

    def publish(
        self,
        type: str,
        id: str,
        payload: dict,
        *,
        date: str,
        actor: str,
        supersedes: Ref | None = None,
        links: tuple[Ref, ...] = (),
        note: str = "",
    ) -> Versioned:
        rows = self._rows.setdefault((type, id), [])
        version = len(rows) + 1
        if version == 1:
            if supersedes is not None:
                raise ValueError("首版没有可接替的旧版")
        else:
            head = rows[-1].ref
            if supersedes is None:
                supersedes = head
            elif supersedes != head:
                raise ValueError(f"{id} 必须基于当前最新版 {head} 续版")
        rec = Versioned(
            Ref(type, id, version),
            date,
            actor,
            dict(payload),
            supersedes,
            tuple(links),
            note,
        )
        rows.append(rec)
        return rec

    def get(self, ref: Ref) -> Versioned:
        rows = self._rows.get((ref.type, ref.id))
        if not rows or ref.version < 1 or ref.version > len(rows):
            raise LookupError(f"记录不存在：{ref}")
        return rows[ref.version - 1]

    def head(self, type: str, id: str) -> Versioned:
        rows = self._rows.get((type, id))
        if not rows:
            raise LookupError(f"记录不存在：{type}:{id}")
        return rows[-1]

    def exists(self, type: str, id: str) -> bool:
        return bool(self._rows.get((type, id)))

    def history(self, type: str, id: str) -> tuple[Versioned, ...]:
        return tuple(self._rows.get((type, id), ()))

    def heads(self) -> tuple[Versioned, ...]:
        return tuple(rows[-1] for rows in self._rows.values())

    def lineage(self, ref: Ref) -> dict[Ref, Versioned]:
        """沿版本与互链关系返回可达的全部精确版本。"""
        seen: dict[Ref, Versioned] = {}
        stack = [ref]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            rec = self.get(current)
            seen[current] = rec
            if rec.supersedes is not None:
                stack.append(rec.supersedes)
            stack.extend(rec.links)
        return seen


class EventLog:
    """只追加事件日志；后续责任以闭环事件收尾，旧事件保持可查。"""

    def __init__(self) -> None:
        self._events: list[Event] = []

    def append(
        self,
        kind: str,
        date: str,
        actor: str,
        payload: dict | None = None,
        *,
        follow_up_owner: str | None = None,
        follow_up_due: str | None = None,
    ) -> Event:
        event = Event(
            seq=len(self._events) + 1,
            date=date,
            actor=actor,
            kind=kind,
            payload=dict(payload or {}),
            follow_up_owner=follow_up_owner,
            follow_up_due=follow_up_due,
        )
        self._events.append(event)
        return event

    def close(self, seq: int, date: str, actor: str, note: str = "") -> Event:
        target = self.get(seq)
        if target.follow_up_owner is None:
            raise ValueError(f"事件 #{seq} 没有待办责任，无需闭环")
        if self.is_closed(target):
            raise ValueError(f"事件 #{seq} 已闭环")
        return self.append(
            "follow_up_closed",
            date,
            actor,
            {"closes": seq, "note": note},
        )

    def get(self, seq: int) -> Event:
        if seq < 1 or seq > len(self._events):
            raise LookupError(f"事件不存在：#{seq}")
        return self._events[seq - 1]

    def is_closed(self, event: Event) -> bool:
        return any(
            e.kind == "follow_up_closed" and e.payload.get("closes") == event.seq
            for e in self._events
        )

    def events(self, kind: str | None = None) -> tuple[Event, ...]:
        if kind is None:
            return tuple(self._events)
        return tuple(e for e in self._events if e.kind == kind)

    def open_follow_ups(self) -> tuple[Event, ...]:
        return tuple(
            e
            for e in self._events
            if e.follow_up_owner is not None and not self.is_closed(e)
        )
