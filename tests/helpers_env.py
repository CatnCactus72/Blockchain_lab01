"""Node giả chỉ để test môi trường Người 1: không có consensus, blockchain hay chữ ký."""
from dataclasses import dataclass, replace

@dataclass(frozen=True)
class SmokeMessage:
    kind: str
    origin: str
    msg_id: str
    payload: str
    signature: bytes = b'\x01'*64

class SmokeNode:
    def __init__(self,node_id,env,behavior,config):
        self.node_id,self.env,self.behavior = node_id,env,behavior
        self.observed = []

    def on_start(self):
        pass

    def resign_wrong_domain(self, message):
        # Chữ ký GIẢ phục vụ smoke; chưa thể kiểm chứng domain khi thiếu crypto.
        return replace(message, signature=b'\x02'*64)

    def tamper_signed_message(self, message):
        # Chỉ dùng kiểm tra đường đi lỗi, không thay thế unit test chữ ký thật.
        return replace(message, payload=message.payload+'!')

    def rebuild_wire_message(self, message):
        """ID tổng hợp chỉ dành cho smoke; không thay thế canonical encoding của Core."""
        from hashlib import sha256
        parts = [message.kind.encode(), message.origin.encode(),
                 message.payload.encode(), message.signature]
        packed = b''.join(len(part).to_bytes(4, 'big') + part for part in parts)
        return replace(message, msg_id=sha256(b'ENV_SMOKE_ONLY' + packed).hexdigest())

    def on_message(self,from_peer,message):
        observed = self.behavior.on_receive(self,from_peer,message)
        if observed is None:
            return 'IGNORE'
        self.observed.append((self.env.now(),from_peer,observed.msg_id))
        return 'ACCEPT'

    def on_timer(self,timer_name):
        # Hook fault:replay chạy trong node thử theo cùng hợp đồng Người 3.
        if timer_name.startswith('fault:'):
            for peer,message in self.behavior.on_timer(self,timer_name):
                self.env.send(peer,message)

    def finalized_chain(self):
        return []

    def final_state_hash(self):
        return 'NOT_APPLICABLE_ENV_SMOKE'


def schedule_smoke_workload(sim, cfg, root_path=None):
    """Tạo 4 gói TX giả theo thứ tự ổn định; không khẳng định TX có chữ ký."""
    from hashlib import sha256
    for i in range(4):
        node = f'N{i%len(sim.nodes)}'
        message = SmokeMessage('TX',node,sha256(f'smoke-{i}'.encode()).hexdigest(),f'hello-{i}')
        sim.schedule(1000+i*100,'smoke-tx',sim.network.gossip,node,message)
