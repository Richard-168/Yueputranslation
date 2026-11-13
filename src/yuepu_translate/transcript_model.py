"""Bounded, session-only paired transcript shared by the Qt view and exporter."""

from dataclasses import dataclass
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

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().strftime("%H:%M:%S")


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

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.items):
            return None
        item = self.items[index.row()]
        if role in (Qt.DisplayRole, Qt.AccessibleTextRole):
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
        self.characters += size
        self.endInsertRows()
        return self._prune()

    def update_entry(self, key, **fields):
        item = self.by_key.get(key)
        if item is None:
            return False
        allowed = {"source", "target", "status"}
        if set(fields) - allowed:
            raise ValueError("无效字幕字段")
        new_source, new_target = (
            fields.get("source", item.source),
            fields.get("target", item.target),
        )
        if len(new_source) + len(new_target) > self.max_chars:
            raise ValueError("单条字幕超出缓存容量")
        self.characters += len(new_source) + len(new_target) - len(item.source) - len(item.target)
        for name, value in fields.items():
            setattr(item, name, value)
        item.revision += 1
        row = self.items.index(item)
        self.dataChanged.emit(self.index(row), self.index(row))
        self._prune()
        return True

    def _prune(self):
        count = 0
        while len(self.items) > self.max_rows or self.characters > self.max_chars:
            self.beginRemoveRows(QModelIndex(), 0, 0)
            item = self.items.pop(0)
            self.by_key.pop(item.key)
            self.characters -= len(item.source) + len(item.target)
            self.endRemoveRows()
            count += 1
        self.evicted += count
        return count

    def clear(self):
        self.beginResetModel()
        self.items.clear()
        self.by_key.clear()
        self.characters = self.evicted = 0
        self.endResetModel()

    def export_text(self, entries=None):
        names = {"zh": "普通话", "yue": "粤语", "en": "英文"}
        rows = self.items if entries is None else entries
        return "\n\n".join(
            f"[{item.timestamp}] {names.get(item.source_language, item.source_language)} → {names.get(item.target_language, item.target_language)}\n"
            f"原文：{item.source}\n译文：{item.target or '[' + item.status + ']'}"
            for item in rows
        )
