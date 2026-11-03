"""Vòng lặp mô phỏng xác định và cầu nối NodeEnv cho người làm consensus."""
from .clock import VirtualClock
from .event_queue import EventQueue
from .rng import SeededRNG
from ..logsys.logger import EventLogger
from ..net.topology import node_sort_key

class SimNodeEnv:
    """Giao diện duck-typed, Node chỉ biết Env, KHÔNG import sim/net.

    Hợp đồng cho Người 3:
    build_node(node_id, env, behavior, config) trả một node có
      on_start(), on_message(from_peer, message), on_timer(timer_name)
      finalized_chain(), final_state_hash().
    on_message trả ACCEPT/REJECT/IGNORE hoặc Verdict(status=...).
    """
    def __init__(self, simulator, node_id: str):
        self.sim = simulator
        self.node_id = node_id
        self._timers: dict[int, bool] = {}
        self._timer_seq = 0
        self._rng_streams = {}

    def now(self) -> int:
        return self.sim.clock.now()

    @property
    def peers(self) -> list[str]:
        return self.sim.network.topology.neighbors(self.node_id)

    def rng(self, *labels):
        child = self.sim.rng.child('node', self.node_id, *labels)
        if child.seed not in self._rng_streams:
            self._rng_streams[child.seed] = child.stream()
        return self._rng_streams[child.seed]

    def send(self, peer: str, message, h: int = -1, r: int | None = None) -> None:
        self.sim.network.send(self.node_id, peer, message, h=h, r=r)

    def gossip(self, message, h: int = -1, r: int | None = None) -> None:
        self.sim.network.gossip(self.node_id, message, h=h, r=r)

    def log(self, ev: str, h: int = -1, **fields) -> str:
        return self.sim.logger.log(self.node_id, ev, h=h, **fields)

    def set_timer(self, name: str, delay_ms: int) -> int:
        if not isinstance(delay_ms,int) or delay_ms < 0:
            raise ValueError('Thời gian timer phải là số nguyên >= 0')
        self._timer_seq += 1
        token = self._timer_seq
        self._timers[token] = True
        self.sim.schedule(self.now()+delay_ms, 'node-timer', self._fire_timer, token, name)
        return token

    def cancel_timer(self, token: int) -> None:
        self._timers.pop(token, None)

    def _fire_timer(self, token: int, name: str) -> None:
        if self._timers.pop(token, False):
            self.sim.nodes[self.node_id].on_timer(name)

class Simulator:
    def __init__(self, seed: int, output_path=None):
        self.clock = VirtualClock()
        self.queue = EventQueue()
        self.rng = SeededRNG(seed)
        self.logger = EventLogger(self.clock, output_path)
        self.nodes: dict[str,object] = {}
        self.environments: dict[str,SimNodeEnv] = {}
        self.network = None
        self._started = False

    def attach_network(self, network) -> None:
        self.network = network

    def add_node(self, node_id: str, node) -> SimNodeEnv:
        if self._started or self.network is None:
            raise RuntimeError('Gắn mạng trước khi đăng ký node và trước lúc chạy')
        if node_id in self.nodes:
            raise ValueError('Node bị đăng ký trùng')
        env = SimNodeEnv(self,node_id)
        self.nodes[node_id],self.environments[node_id] = node,env
        self.network.register(node_id,node.on_message)
        return env

    def create_env(self, node_id: str) -> SimNodeEnv:
        if self.network is None:
            raise RuntimeError('Chưa khởi tạo Network')
        return SimNodeEnv(self,node_id)

    def register_with_env(self, node_id: str, node, env: SimNodeEnv) -> None:
        if self._started or self.network is None:
            raise RuntimeError('Đăng ký node sau khi gắn mạng và trước lúc chạy')
        if env.sim is not self or env.node_id != node_id:
            raise ValueError('Env không thuộc simulator hoặc node được đăng ký')
        if node_id in self.nodes:
            raise ValueError('Node đã đăng ký')
        self.nodes[node_id],self.environments[node_id] = node,env
        self.network.register(node_id,node.on_message)

    def schedule(self, at_ms: int, name: str, callback, *args, **kwargs):
        if at_ms < self.clock.now():
            raise ValueError('Sự kiện không thể xảy ra trong quá khứ')
        return self.queue.push(at_ms,name,callback,*args,**kwargs)

    def _reached_height(self, target_height: int, correct_nodes: list[str]) -> bool:
        if not correct_nodes:
            return False
        for node_id in correct_nodes:
            node = self.nodes[node_id]
            if not callable(getattr(node,'finalized_chain',None)):
                return False
            if len(node.finalized_chain()) < target_height:
                return False
        return True

    def run(self, max_virtual_time_ms: int, target_height: int | None = None,
            honest_nodes: list[str] | None = None) -> str:
        if self.network is None:
            raise RuntimeError('Simulator chưa gắn Network')
        if self._started:
            raise RuntimeError('Không chạy lại cùng instance simulator')
        if type(max_virtual_time_ms) is not int or max_virtual_time_ms < self.clock.now():
            raise ValueError('Giới hạn thời gian phải là số nguyên không nhỏ hơn đồng hồ')
        if target_height is not None and (type(target_height) is not int or target_height < 0):
            raise ValueError('Height đích phải là số nguyên không âm')
        self._started = True
        ids = sorted(self.nodes,key=node_sort_key)
        honest = sorted(honest_nodes if honest_nodes is not None else ids,key=node_sort_key)
        self.logger.log('SIM','SIM_START',details=f'nodes:{len(ids)}')
        for node_id in ids:
            self.nodes[node_id].on_start()
        stop_reason = 'QUEUE_EMPTY'
        while self.queue:
            if target_height is not None and self._reached_height(target_height,honest):
                stop_reason = 'TARGET_HEIGHT'
                break
            current = self.queue.peek()
            if current.at_ms > max_virtual_time_ms:
                self.clock.advance_to(max_virtual_time_ms)
                stop_reason = 'MAX_TIME'
                break
            event = self.queue.pop()
            self.clock.advance_to(event.at_ms)
            event.callback(*event.args,**event.kwargs)
        else:
            if target_height is not None and self._reached_height(target_height,honest):
                stop_reason = 'TARGET_HEIGHT'
        self.logger.log('SIM','SIM_END',details=f'reason:{stop_reason};duration_ms:{self.clock.now()}')
        return stop_reason
