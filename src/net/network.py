"""Mạng P2P mô phỏng. Mạng không import consensus hay đọc trạng thái node."""
from .gossip import GOSSIP_KINDS, GossipTracker, message_kind, message_origin, message_id, normalize_verdict
from .link import Link
from .rate_limit import OutboundRateLimiter, InboundRateLimiter

class Network:
    def __init__(self, topology, simulator, config: dict):
        self.topology, self.sim = topology, simulator
        self.config = config
        self.gst_ms = int(config.get('gst_ms', 0))
        self.tracker = GossipTracker()
        rate = config.get('rate_limit', {})
        self.outbound = {nid: OutboundRateLimiter(int(rate.get('send_per_sec', 300))) for nid in topology.node_ids}
        self.inbound = InboundRateLimiter(int(rate.get('recv_window_ms', 1000)),
                                          int(rate.get('recv_max', 200)), int(rate.get('block_ms', 3000)))
        self.handlers = {}
        self.links = {}
        pre = config.get('pre_gst', {})
        post = config.get('post_gst', {})
        for item in topology.links:
            a,b = item['a'],item['b']
            # Mỗi chiều có RNG riêng; gói gửi N1->N2 không ảnh hưởng chiều ngược lại.
            for source,dest in ((a,b),(b,a)):
                self.links[(source,dest)] = Link(
                    base_ms=int(item['base_ms']), rng=simulator.rng.child('link', source, dest),
                    delta_ms=int(config.get('delta_ms',500)),
                    pre_gst_drop=float(pre.get('drop',0.30)),
                    pre_gst_dup=float(pre.get('dup',0.15)),
                    pre_gst_extra_delay_max_ms=int(pre.get('extra_delay_max_ms',4000)),
                    post_gst_dup=float(post.get('dup',0.0)),
                    post_gst_extra_delay_max_ms=int(post.get('extra_delay_max_ms',0)))

    def register(self, node_id: str, handler):
        if node_id not in self.topology.node_ids:
            raise ValueError(f'Node không tồn tại: {node_id}')
        self.handlers[node_id] = handler

    def log(self, node: str, ev: str, **kwargs):
        return self.sim.logger.log(node, ev, **kwargs)

    def send(self, source: str, dest: str, message, h: int = -1, r: int | None = None) -> None:
        # Áp dụng hook lỗi CẢ KHI network tự forward gossip, không chỉ lần gửi đầu.
        node = self.sim.nodes.get(source)
        behavior = getattr(node,'behavior',None)
        if behavior is not None:
            for target,modified in behavior.on_send(node,dest,message):
                self._send_one(source,target,modified,h,r)
        else:
            self._send_one(source,dest,message,h,r)

    def _send_one(self, source: str, dest: str, message, h: int, r: int | None) -> None:
        if (source,dest) not in self.links:
            raise ValueError(f'{source} và {dest} không phải peer trực tiếp')
        when = self.outbound[source].reserve(self.sim.clock.now())
        if when > self.sim.clock.now():
            self.log(source,'DELAY',h=h,r=r,msg=message_id(message)[:6],kind=message_kind(message),
                     origin=message_origin(message),via=source,reason='RATE_LIMIT',details=f'until:{when}')
        self.sim.schedule(when, 'net-send', self._transmit,source,dest,message,h,r)

    def gossip(self, source: str, message, exclude: str | None = None,
               h: int = -1, r: int | None = None) -> None:
        if message_kind(message) not in GOSSIP_KINDS:
            raise ValueError('Chỉ TX, PROPOSAL, PREVOTE, PRECOMMIT được gossip')
        self.tracker.mark_seen(source,message)
        for peer in self.topology.neighbors(source):
            if peer != exclude:
                self.send(source,peer,message,h=h,r=r)

    def _transmit(self, source: str, dest: str, message, h: int, r: int | None):
        msgid, kind, origin = message_id(message)[:6], message_kind(message), message_origin(message)
        self.log(source,'SEND',h=h,r=r,msg=msgid,kind=kind,origin=origin,via=source,details=f'to:{dest}')
        results = self.links[(source,dest)].deliveries(self.sim.clock.now(),self.gst_ms)
        if not results:
            self.log(source,'DROP',h=h,r=r,msg=msgid,kind=kind,origin=origin,via=source,details=f'to:{dest}')
        for item in results:
            if item.is_duplicate:
                self.log(source,'DUP',h=h,r=r,msg=msgid,kind=kind,origin=origin,via=source,details='link-copy')
            if item.delay_ms > self.topology.base_delay(source,dest):
                self.log(source,'DELAY',h=h,r=r,msg=msgid,kind=kind,origin=origin,via=source,details=f'{item.delay_ms}ms')
            self.sim.schedule(self.sim.clock.now()+item.delay_ms,'net-deliver',
                              self._deliver,source,dest,message,h,r)

    def _unblock(self, receiver: str, sender: str, until_ms: int):
        if self.inbound.clear_block(receiver,sender,until_ms,self.sim.clock.now()):
            self.log(receiver,'UNBLOCK',details=f'peer:{sender}')

    def _deliver(self, source: str, dest: str, message, h: int, r: int | None):
        msgid, kind, origin = message_id(message)[:6], message_kind(message),message_origin(message)
        status, until = self.inbound.receive(dest,source,self.sim.clock.now())
        if status == 'BLOCK':
            self.log(dest,'BLOCK',h=h,r=r,msg=msgid,kind=kind,origin=origin,via=source,details=f'peer:{source}')
            self.sim.schedule(until,'net-unblock',self._unblock,dest,source,until)
            return
        if status == 'PEER_BLOCKED':
            self.log(dest,'DROP',h=h,r=r,msg=msgid,kind=kind,origin=origin,via=source,reason='PEER_BLOCKED')
            return
        first = True
        if kind in GOSSIP_KINDS:
            first = self.tracker.mark_seen(dest,message)
        self.log(dest,'RECV',h=h,r=r,msg=msgid,kind=kind,origin=origin,via=source,first=first)
        if not first:
            self.log(dest,'DUP',h=h,r=r,msg=msgid,kind=kind,origin=origin,via=source,reason='DUPLICATE_MSG')
            return
        if dest not in self.handlers:
            raise RuntimeError(f'Node chưa đăng ký callback: {dest}')
        raw_verdict = self.handlers[dest](source,message)
        result = normalize_verdict(raw_verdict)
        if result == 'REJECT':
            reason = getattr(raw_verdict,'reason',None)
            if reason is not None:
                self.log(dest,'REJECT',h=h,r=r,msg=msgid,kind=kind,origin=origin,via=source,reason=reason)
        if kind in GOSSIP_KINDS and result == 'ACCEPT':
            # Forward đúng sau khi validator trả ACCEPT, không forward gói REJECT.
            for peer in self.topology.neighbors(dest):
                if peer != source:
                    self.send(dest,peer,message,h=h,r=r)
