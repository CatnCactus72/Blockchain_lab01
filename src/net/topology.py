"""Đọc và xác nhận topology peer-to-peer cố định, không dùng thứ tự set."""
import json
from pathlib import Path


def node_sort_key(node_id: str):
    text = str(node_id)
    return (int(text[1:]), '') if text.startswith('N') and text[1:].isdigit() else (10**9, text)

class Topology:
    def __init__(self, node_ids: list[str], links: list[dict]):
        self.node_ids = sorted([str(x) for x in node_ids], key=node_sort_key)
        if len(self.node_ids) != len(set(self.node_ids)) or not self.node_ids:
            raise ValueError('Danh sách node phải có ít nhất một phần tử và không lặp')
        self._neighbors = {name: {} for name in self.node_ids}
        for item in links:
            a, b, base = str(item['a']), str(item['b']), int(item['base_ms'])
            if a not in self._neighbors or b not in self._neighbors or a == b or base <= 0:
                raise ValueError('Liên kết không hợp lệ')
            if b in self._neighbors[a]:
                raise ValueError(f'Liên kết lặp: {a}-{b}')
            self._neighbors[a][b] = base
            self._neighbors[b][a] = base
        self.links = [dict(a=a,b=b,base_ms=self._neighbors[a][b])
                      for a in self.node_ids for b in self.neighbors(a) if node_sort_key(a) < node_sort_key(b)]
        if not self.is_connected():
            raise ValueError('Topology phải liên thông')

    @classmethod
    def from_file(cls, path: str | Path) -> 'Topology':
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        return cls(data['nodes'], data['links'])

    def neighbors(self, node_id: str) -> list[str]:
        return sorted(self._neighbors[str(node_id)], key=node_sort_key)

    def base_delay(self, a: str, b: str) -> int:
        return self._neighbors[str(a)][str(b)]

    def is_connected(self) -> bool:
        seen = {self.node_ids[0]}
        queue = [self.node_ids[0]]
        while queue:
            here = queue.pop(0)
            for neighbor in self.neighbors(here):
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        return len(seen) == len(self.node_ids)
