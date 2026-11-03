"""Một liên kết mô phỏng: quyết định mất/trùng/trễ gói bằng RNG riêng."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Delivery:
    delay_ms: int
    is_duplicate: bool = False

class Link:
    def __init__(self, base_ms: int, rng, delta_ms: int = 500,
                 pre_gst_drop: float = 0.30, pre_gst_dup: float = 0.15,
                 pre_gst_extra_delay_max_ms: int = 4000,
                 post_gst_dup: float = 0.0, post_gst_extra_delay_max_ms: int = 0):
        if base_ms <= 0 or delta_ms < base_ms + base_ms // 5:
            raise ValueError('Delta phải bao phủ độ trễ cơ bản và jitter sau GST')
        for p in (pre_gst_drop, pre_gst_dup, post_gst_dup):
            if not 0 <= p <= 1:
                raise ValueError('Xác suất phải nằm trong [0,1]')
        for delay in (pre_gst_extra_delay_max_ms, post_gst_extra_delay_max_ms):
            if type(delay) is not int or delay < 0:
                raise ValueError('Trễ bổ sung phải là số nguyên không âm')
        if base_ms + base_ms // 5 + post_gst_extra_delay_max_ms > delta_ms:
            raise ValueError('Cấu hình sau GST vượt quá Delta')
        self.base_ms, self.delta_ms, self.rng = base_ms, delta_ms, rng
        self.pre_gst_drop, self.pre_gst_dup = pre_gst_drop, pre_gst_dup
        self.pre_gst_extra_delay_max_ms = pre_gst_extra_delay_max_ms
        self.post_gst_dup, self.post_gst_extra_delay_max_ms = post_gst_dup, post_gst_extra_delay_max_ms

    def deliveries(self, now_ms: int, gst_ms: int) -> list[Delivery]:
        """Kết quả là 0, 1 hoặc 2 lần giao; thời điểm tính từ lúc phát."""
        before_gst = now_ms < gst_ms
        # Rút RNG theo thứ tự: drop, dup, extra delay, sau đó jitter.
        drop = self.rng.random() < self.pre_gst_drop if before_gst else False
        dup = self.rng.random() < (self.pre_gst_dup if before_gst else self.post_gst_dup)
        extra_max = self.pre_gst_extra_delay_max_ms if before_gst else self.post_gst_extra_delay_max_ms
        extra = self.rng.randint(0, extra_max) if extra_max > 0 else 0
        jitter = self.rng.randint(0, self.base_ms // 5)
        if drop:
            return []
        delay = self.base_ms + jitter + extra
        if not before_gst and delay > self.delta_ms:
            raise ValueError('Cấu hình sau GST vượt quá Delta')
        result = [Delivery(delay)]
        if dup:
            # Bản sao giữ nguyên message; chỉ khác thời điểm đến.
            jitter2 = self.rng.randint(0, self.base_ms // 5)
            second = self.base_ms + jitter2 + extra
            if not before_gst and second > self.delta_ms:
                raise ValueError('Gói trùng sau GST vượt Delta')
            result.append(Delivery(second, True))
        return result
