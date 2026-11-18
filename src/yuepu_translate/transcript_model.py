"""Bounded, session-only paired transcript shared by the Qt view and exporter."""

from dataclasses import dataclass, field
from datetime import datetime

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt


@dataclass
class TranscriptEntry:
    key: int
    source_language: str
    target_language: str
    source: str = ""
    target: str = ""
    status: str = "识别中"
    timestamp: str = ""
    revision: int = 0
    source_confirmed: int = 0
    target_confirmed: int = 0
    # Source versions are live events. Restored rough translations have no version evidence.
    target_current: bool = field(default=False, compare=False)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().strftime("%H:%M:%S")

    @property
    def is_capture_notice(self):
        return self.status == "收音中断" and not self.source_language and not self.target_language

    @property
    def translation_is_final(self):
        return self.status in {"已确认", "已翻译"}

    @property
    def replay_text(self):
        if self.translation_is_final or self.target_current:
            return self.target
        return self.target[: self.target_confirmed]


class TranscriptModel(QAbstractListModel):
    def __init__(self, max_rows=10000, max_chars=2000000):
        super().__init__()
        if max_rows < 1 or max_chars < 1:
            raise ValueError("字幕缓存上限必须大于零")
        self.max_rows, self.max_chars = max_rows, max_chars
        self.items = []
        self.by_key = {}
        self.characters = 0
        self.evicted = 0
        self._positions = {}
        self._first_row = 0

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.items):
            return None
        item = self.items[index.row()]
        if item.is_capture_notice and role in (Qt.AccessibleTextRole, Qt.DisplayRole):
            return f"{item.timestamp}  收音中断\n{item.source}"
        if role == Qt.AccessibleTextRole:
            return (
                f"{item.timestamp}  {item.source}\n{item.target or item.status}\n"
                f"{item.status}；已固定原文 {item.source_confirmed} 字、译文 {item.target_confirmed} 字"
            )
        if role == Qt.DisplayRole:
            return f"{item.timestamp}  {item.source}\n{item.target or item.status}"
        if role == Qt.UserRole:
            return item
        return None

    def append(self, entry):
        if entry.key in self.by_key:
            raise ValueError("重复字幕编号")
        size = len(entry.source) + len(entry.target)
        if size > self.max_chars:
            raise ValueError("单条字幕超出缓存容量")
        row = len(self.items)
        self.beginInsertRows(QModelIndex(), row, row)
        self.items.append(entry)
        self.by_key[entry.key] = entry
        self._positions[entry.key] = self._first_row + row
        self.characters += size
        self.endInsertRows()
        return self._prune()

    def update_entry(self, key, **fields):
        item = self.by_key.get(key)
        if item is None:
            return False
        allowed = {
            "source",
            "target",
            "status",
            "source_confirmed",
            "target_confirmed",
            "target_current",
        }
        if set(fields) - allowed:
            raise ValueError("无效字幕字段")
        if "target_current" in fields and type(fields["target_current"]) is not bool:
            raise ValueError("无效译文版本")
        new_source, new_target = (
            fields.get("source", item.source),
            fields.get("target", item.target),
        )
        if len(new_source) + len(new_target) > self.max_chars:
            raise ValueError("单条字幕超出缓存容量")
        for name, text in (("source_confirmed", new_source), ("target_confirmed", new_target)):
            value = fields.get(name, getattr(item, name))
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= len(text):
                raise ValueError("固定前文长度必须在字幕范围内")
        if new_source != item.source and "target_current" not in fields:
            fields["target_current"] = False
        self.characters += len(new_source) + len(new_target) - len(item.source) - len(item.target)
        for name, value in fields.items():
            setattr(item, name, value)
        item.revision += 1
        row = self._positions[key] - self._first_row
        self.dataChanged.emit(self.index(row), self.index(row))
        self._prune()
        return True

    def _prune(self):
        count = 0
        while len(self.items) > self.max_rows or self.characters > self.max_chars:
            self.beginRemoveRows(QModelIndex(), 0, 0)
            item = self.items.pop(0)
            self.by_key.pop(item.key)
            self._positions.pop(item.key)
            self._first_row += 1
            self.characters -= len(item.source) + len(item.target)
            self.endRemoveRows()
            count += 1
        self.evicted += count
        return count

    def clear(self):
        self.beginResetModel()
        self.items.clear()
        self.by_key.clear()
        self._positions.clear()
        self._first_row = 0
        self.characters = self.evicted = 0
        self.endResetModel()

    def replace_entries(self, entries):
        items = list(entries)
        if len({item.key for item in items}) != len(items):
            raise ValueError("重复字幕编号")
        sizes = [len(item.source) + len(item.target) for item in items]
        if any(size > self.max_chars for size in sizes):
            raise ValueError("单条字幕超出缓存容量")
        start = max(0, len(items) - self.max_rows)
        characters = sum(sizes[start:])
        while characters > self.max_chars:
            characters -= sizes[start]
            start += 1
        items = items[start:]
        self.beginResetModel()
        self.items = items
        self.by_key = {item.key: item for item in items}
        self.characters = characters
        self.evicted = start
        self._positions = {item.key: row for row, item in enumerate(items)}
        self._first_row = 0
        self.endResetModel()

    def export_text(self, entries=None):
        names = {"zh": "普通话", "yue": "粤语", "en": "英文"}
        rows = self.items if entries is None else entries
        lines = []
        for item in rows:
            if item.is_capture_notice:
                lines.append(f"[{item.timestamp}] 收音中断\n{item.source}")
                continue
            source = names.get(item.source_language, item.source_language)
            target = names.get(item.target_language, item.target_language)
            final = item.translation_is_final
            text = f"[{item.timestamp}] {source} → {target}\n原文：{item.source}"
            if item.target and not final and not item.target_current:
                fixed = item.replay_text
                text += f"\n译文：{fixed + ' [仅已固定前文]' if fixed else '[当前原文译文未确认]'}"
                if len(fixed) < len(item.target):
                    text += f"\n此前的译文草稿（与本版原文未核对）：{item.target}"
            else:
                text += f"\n译文：{item.target or '[' + item.status + ']'}"
            if item.target and not final:
                text += f"\n状态：{item.status}"
            lines.append(text)
        return "\n\n".join(lines)
