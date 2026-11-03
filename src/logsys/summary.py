"""Tổng hợp kết quả; KHÔNG tự suy đoán khi thành viên 2/3 chưa cung cấp state."""
import json
from pathlib import Path


def summarize_nodes(nodes: dict, duration_ms: int, honest_ids: list[str] | None = None) -> dict:
    """Node phải cung cấp finalized_chain() và final_state_hash() qua giao diện ghép."""
    per_node = {}
    for node_id in sorted(nodes, key=lambda s: (int(str(s).lstrip('N')) if str(s).lstrip('N').isdigit() else 10**9, str(s))):
        node = nodes[node_id]
        if not callable(getattr(node, 'finalized_chain', None)) or not callable(getattr(node, 'final_state_hash', None)):
            raise NotImplementedError('Node cần cài finalized_chain() và final_state_hash() để tạo summary thật')
        per_node[str(node_id)] = {
            'chain': node.finalized_chain(),
            'state_hash': node.final_state_hash()
        }
    # Không lấy các node Byzantine làm điều kiện hội tụ của node trung thực.
    honest = list(per_node) if honest_ids is None else list(honest_ids)
    if not honest or any(n not in per_node for n in honest):
        raise ValueError('Summary cần ít nhất một node trung thực đã đăng ký')
    chains = [per_node[n]['chain'] for n in honest]
    hashes = [per_node[n]['state_hash'] for n in honest]
    # Node chậm có thể có prefix; muốn ghi 'converged' thì các chain phải bằng nhau.
    prefixes = all(a == b[:len(a)] or b == a[:len(b)] for a in chains for b in chains)
    converged = len({json.dumps(c, sort_keys=True, ensure_ascii=False) for c in chains}) <= 1 and len(set(hashes)) <= 1
    return {'duration_ms': duration_ms, 'nodes': per_node, 'honest_nodes': honest, 'safety_prefixes': prefixes, 'converged': converged}


def save_summary(summary: dict, path: str | Path) -> None:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf-8')
