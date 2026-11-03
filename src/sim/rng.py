"""Nguồn ngẫu nhiên tái lập; mỗi thành phần có RNG riêng, độc lập thứ tự gọi nơi khác."""
import hashlib
import random
import unicodedata

class SeededRNG:
    def __init__(self, seed: int):
        if not isinstance(seed, int):
            raise TypeError("seed phải là số nguyên")
        self.seed = seed
        self._rng = random.Random(seed)

    def child(self, *names: object) -> "SeededRNG":
        """Tạo RNG con từ hash SHA-256 trên tên thành phần có mã hóa độ dài."""
        parts = [str(self.seed), *(unicodedata.normalize('NFC', str(s)) for s in names)]
        packed = b''.join(len(s.encode('utf-8')).to_bytes(4, 'big') + s.encode('utf-8') for s in parts)
        derived = int.from_bytes(hashlib.sha256(b'PART1-RNG' + packed).digest(), 'big')
        return SeededRNG(derived)

    def randint(self, a: int, b: int) -> int:
        return self._rng.randint(a, b)

    def stream(self) -> random.Random:
        """Trả bộ sinh chuẩn đang giữ trạng thái của luồng này."""
        return self._rng

    def random(self) -> float:
        return self._rng.random()

    def choice(self, items):
        return self._rng.choice(items)

    def shuffle(self, items: list) -> None:
        self._rng.shuffle(items)

    def uniform(self, a: float, b: float) -> float:
        return self._rng.uniform(a, b)
