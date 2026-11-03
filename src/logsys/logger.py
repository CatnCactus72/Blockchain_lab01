"""Log xác định: giữ trong bộ nhớ và tùy chọn ghi file. Không đọc đồng hồ thật."""
from pathlib import Path
from .event import format_event

class EventLogger:
    def __init__(self, clock, output_path: str | Path | None = None):
        self.clock = clock
        self.lines: list[str] = []
        self.path = Path(output_path) if output_path is not None else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text('', encoding='utf-8')

    def log(self, node: str, ev: str, h: int = -1, **fields) -> str:
        # seq của dòng log KHÁC seq hàng đợi, nhưng cả hai đều tăng ổn định.
        line = format_event(self.clock.now(), len(self.lines), node, ev, h, **fields)
        self.lines.append(line)
        if self.path:
            with self.path.open('a', encoding='utf-8', newline='\n') as file:
                file.write(line + '\n')
        return line

    def bytes(self) -> bytes:
        return (''.join(line + '\n' for line in self.lines)).encode('utf-8')
