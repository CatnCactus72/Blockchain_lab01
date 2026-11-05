"""Kiểm thử riêng cho phần Người 1, dùng unittest không cần consensus của Người 3."""
import json
import tempfile
import unittest
from dataclasses import dataclass, replace
from pathlib import Path

from src.main import deep_merge, load_config, run_scenario, validate_config
from src.sim.clock import VirtualClock
from src.sim.event_queue import EventQueue
from src.sim.rng import SeededRNG
from src.sim.simulator import Simulator
from src.net.topology import Topology
from src.net.network import Network
from src.net.link import Link
from src.net.rate_limit import OutboundRateLimiter, InboundRateLimiter
from src.logsys.event import format_event
from src.logsys.logger import EventLogger
from src.faults.base import make_behavior
from src.faults.bad_signature import BadSignatureBehavior
from src.faults.equivocate import EquivocateBehavior
from src.faults.invalid_block import InvalidBlockBehavior
from tests.helpers_env import SmokeMessage, SmokeNode

ROOT = Path(__file__).resolve().parents[2]

class EnvironmentTests(unittest.TestCase):
    def _simulation(self, config=None):
        cfg = config or load_config(ROOT/'config/scenarios/t1_normal.json', ROOT)
        sim = Simulator(seed=cfg['seed'])
        topology = Topology.from_file(ROOT/'config/topology.json')
        sim.attach_network(Network(topology, sim, cfg))
        for nid in topology.node_ids:
            env = sim.create_env(nid)
            sim.register_with_env(nid, SmokeNode(nid, env, make_behavior({}), cfg), env)
        return sim

    def test_env_rng_preserves_stream_state(self):
        import random
        sim = self._simulation()
        env = sim.environments['N0']
        expected = SeededRNG(42).child('node', 'N0', 'workload').stream()
        stream = env.rng('workload')
        self.assertIsInstance(stream, random.Random)
        self.assertIs(stream, env.rng('workload'))
        draws = []
        for _ in range(8):
            env.rng('other').randint(0, 10000)
            draws.append(env.rng('workload').randint(0, 10000))
        self.assertEqual(draws, [expected.randint(0, 10000) for _ in range(8)])

    def test_timer_cancellation_and_same_time_order(self):
        sim = self._simulation()
        env = sim.environments['N0']
        fired = []
        sim.nodes['N0'].on_timer = fired.append
        cancelled = env.set_timer('cancelled', 20)
        env.set_timer('first', 20)
        env.set_timer('second', 20)
        env.cancel_timer(cancelled)
        env.cancel_timer(cancelled)
        sim.run(100)
        self.assertEqual(fired, ['first', 'second'])

    def test_target_height_stops_before_future_timeout(self):
        sim = self._simulation()
        chain = []
        sim.nodes['N0'].finalized_chain = lambda: chain[:]
        sim.schedule(25, 'finalize', chain.append, {'height': 1, 'hash': 'test'})
        sim.schedule(5000, 'future-timeout', lambda: self.fail('Không được chạy quá height đích'))
        self.assertEqual(sim.run(1000, 1, ['N0']), 'TARGET_HEIGHT')
        self.assertEqual(sim.clock.now(), 25)

    def test_max_time_and_past_scheduling(self):
        sim = self._simulation()
        sim.schedule(200, 'late', lambda: self.fail('Vượt giới hạn thời gian'))
        self.assertEqual(sim.run(100), 'MAX_TIME')
        self.assertEqual(sim.clock.now(), 100)
        with self.assertRaises(ValueError):
            sim.schedule(99, 'past', lambda: None)
        with self.assertRaises(RuntimeError):
            env = sim.create_env('N0')
            sim.register_with_env('N0', sim.nodes['N0'], env)

    def test_rejected_and_ignored_gossip_not_forwarded(self):
        for verdict in ('REJECT', 'IGNORE'):
            with self.subTest(verdict=verdict):
                sim = self._simulation()
                sim.network.handlers['N1'] = lambda peer, msg: verdict
                message = SmokeMessage('TX', 'N0', 'blocked-forward', 'hi')
                sim.network.send('N0', 'N1', message)
                sim.run(1000)
                self.assertFalse(any('node=N1 ev=SEND' in line for line in sim.logger.lines))
                self.assertFalse(any(sim.nodes[nid].observed for nid in sim.nodes))

    def test_direct_body_not_gossiped_or_deduplicated(self):
        sim = self._simulation()
        message = SmokeMessage('BODY', 'N0', 'same-body', 'body')
        for _ in range(2):
            sim.network.send('N0', 'N1', message)
        with self.assertRaises(ValueError):
            sim.network.gossip('N0', message)
        sim.run(1000)
        self.assertEqual(len(sim.nodes['N1'].observed), 2)
        self.assertFalse(any('node=N1 ev=SEND' in line for line in sim.logger.lines))

    def test_network_outbound_rate_limit_delays_and_logs(self):
        cfg = load_config(ROOT/'config/scenarios/t1_normal.json', ROOT)
        cfg['rate_limit']['send_per_sec'] = 2
        sim = self._simulation(cfg)
        for i in range(5):
            sim.network.send('N0', 'N1', SmokeMessage('STATUS', 'N0', f'rate-{i}', ''))
        sim.run(5000)
        sends = [line.split()[0] for line in sim.logger.lines if 'node=N0 ev=SEND' in line]
        self.assertEqual(sends, ['00:00:000']*2 + ['00:01:000']*2 + ['00:02:000'])
        self.assertEqual(sum('reason=RATE_LIMIT' in line for line in sim.logger.lines), 3)

    def test_invalid_link_configuration_rejected_before_delivery(self):
        for kwargs in ({'post_gst_extra_delay_max_ms': 450}, {'pre_gst_extra_delay_max_ms': -1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Link(80, SeededRNG(1), **kwargs)

    def test_wire_id_required_and_enum_verdict_supported(self):
        from enum import Enum
        from src.net.gossip import message_id, normalize_verdict
        class Status(Enum):
            ACCEPT = 'ACCEPT'
        @dataclass
        class Verdict:
            status: Status
        self.assertEqual(normalize_verdict(Verdict(Status.ACCEPT)), 'ACCEPT')
        self.assertEqual(message_id({'msg_id': b'\xaa\xbb'}), 'aabb')
        with self.assertRaises(ValueError):
            message_id({'kind': 'TX', 'origin': 'N0'})

    def test_bad_signature_rebuilds_wire_id_once(self):
        sim = self._simulation()
        node = sim.nodes['N0']
        behavior = BadSignatureBehavior('bad_key')
        original = SmokeMessage('PREVOTE', 'N0', 'original-id', 'vote')
        created = behavior.on_make_vote(node, original)[0][1]
        self.assertEqual(created, original)
        altered = behavior.on_send(node, 'N1', created)[0][1]
        self.assertNotEqual(altered.msg_id, original.msg_id)
        self.assertNotEqual(altered.signature, original.signature)
        self.assertEqual(behavior.on_send(node, 'N2', created)[0][1], altered)
        self.assertEqual(behavior.on_send(node, 'N1', altered)[0][1], altered)
        self.assertEqual(original.signature, b'\x01'*64)

    def test_mutation_refuses_stale_wire_id_without_core_adapter(self):
        from src.faults.base import refresh_wire_message
        message = SmokeMessage('TX', 'N0', 'old-id', 'payload')
        modified = replace(message, payload='changed')
        with self.assertRaises(NotImplementedError):
            refresh_wire_message(object(), message, modified)
        class BrokenNode:
            def rebuild_wire_message(self, msg):
                return msg
        with self.assertRaises(ValueError):
            refresh_wire_message(BrokenNode(), message, modified)

    def test_fault_callbacks_remain_pending_without_node_core(self):
        for behavior, hook in ((EquivocateBehavior(), 'on_make_vote'),
                               (EquivocateBehavior(), 'on_make_proposal'),
                               (InvalidBlockBehavior(), 'on_make_proposal')):
            with self.subTest(hook=hook), self.assertRaises(NotImplementedError):
                getattr(behavior, hook)(object(), 'signed-object')
        for mode in ('wrong_domain', 'tamper'):
            with self.subTest(mode=mode), self.assertRaises(NotImplementedError):
                BadSignatureBehavior(mode)._corrupt(object(), 'signed-object')

    def test_all_scenarios_and_invalid_config(self):
        for path in sorted((ROOT/'config/scenarios').glob('*.json')):
            with self.subTest(path=path.name):
                self.assertEqual(load_config(path, ROOT)['n'], 10)
        base = load_config(ROOT/'config/scenarios/t1_normal.json', ROOT)
        for patch in ({'gst_ms': -1}, {'seed': '42'}, {'stop': {'target_height': 0}},
                      {'pre_gst': {'drop': 1.1}}, {'faulty_nodes': [{'node': 'N0'}, {'node': 'N0'}]}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                validate_config(deep_merge(base, patch), 't1_normal.json')

    def test_faulty_override_numeric_and_unknown_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary, _ = run_scenario(str(ROOT/'config/scenarios/t1_normal.json'),
                                      tmp, faulty_ids=['2', '5', '8'], smoke_env=True, root=str(ROOT))
            self.assertEqual(summary['mode'], 'ENV_SMOKE_ONLY')
            self.assertIsNone(summary['converged'])
            self.assertTrue(all(nid not in summary['honest_nodes'] for nid in ('N2', 'N5', 'N8')))
            with self.assertRaises(ValueError):
                run_scenario(str(ROOT/'config/scenarios/t1_normal.json'),
                             tmp, faulty_ids=['N99'], smoke_env=True, root=str(ROOT))

    def test_clock_monotonic(self):
        clock = VirtualClock()
        clock.advance_to(1200)
        self.assertEqual(clock.now(),1200)
        with self.assertRaises(ValueError):
            clock.advance_to(1100)

    def test_queue_tie_breaker(self):
        q = EventQueue()
        order = []
        for i in range(6):
            q.push(500,'same-time',lambda x=i:order.append(x))
        while q:
            e = q.pop()
            e.callback(*e.args,**e.kwargs)
        self.assertEqual(order,list(range(6)))

    def test_child_rng_independent_and_repeatable(self):
        first = SeededRNG(42).child('network','N1','N2')
        second = SeededRNG(42).child('network','N1','N2')
        self.assertEqual([first.randint(0,1000) for _ in range(10)],
                         [second.randint(0,1000) for _ in range(10)])
        self.assertNotEqual(SeededRNG(42).child('A').randint(0,10**10),
                            SeededRNG(42).child('B').randint(0,10**10))

    def test_topology_ring_plus_two(self):
        topology = Topology.from_file(ROOT/'config/topology.json')
        self.assertEqual(len(topology.node_ids),10)
        self.assertEqual(len(topology.links),20)
        self.assertTrue(topology.is_connected())
        for nid in topology.node_ids:
            self.assertEqual(len(topology.neighbors(nid)),4)

    def test_link_after_gst_bounded(self):
        link = Link(80,SeededRNG(7),post_gst_dup=0.5,post_gst_extra_delay_max_ms=100)
        for _ in range(200):
            outcomes = link.deliveries(1000,1000)
            self.assertGreaterEqual(len(outcomes),1)
            self.assertTrue(all(0 < d.delay_ms <= 500 for d in outcomes))
        before = Link(80,SeededRNG(7),pre_gst_drop=1.0)
        self.assertEqual(before.deliveries(0,1000),[])

    def test_rate_limits_and_unblock(self):
        outgoing = OutboundRateLimiter(2)
        self.assertEqual([outgoing.reserve(0) for _ in range(4)],[0,0,1000,1000])
        incoming = InboundRateLimiter(1000,2,3000)
        self.assertEqual(incoming.receive('N1','N2',100)[0],'ALLOW')
        self.assertEqual(incoming.receive('N1','N2',101)[0],'ALLOW')
        status,until = incoming.receive('N1','N2',102)
        self.assertEqual(status,'BLOCK')
        self.assertEqual(incoming.receive('N1','N2',500)[0],'PEER_BLOCKED')
        self.assertTrue(incoming.clear_block('N1','N2',until,until))
        self.assertEqual(incoming.receive('N1','N2',until)[0],'ALLOW')

    def test_logger_deterministic(self):
        c = VirtualClock()
        logger = EventLogger(c)
        logger.log('SIM','SIM_START')
        c.advance_to(1250)
        logger.log('N3','RECV',h=1,r=0,msg='deadbe',kind='TX',origin='N0',via='N1',first=True)
        self.assertIn('00:01:250 seq=00001',logger.lines[1])
        self.assertIn('first=true',logger.lines[1])
        self.assertEqual(logger.lines[0],format_event(0,0,'SIM','SIM_START'))
        with self.assertRaises(ValueError):
            logger.log('N3','REJECT',reason='RANDOM_REASON')

    def test_network_gossip_delivers_unique_at_nodes(self):
        base = load_config(ROOT/'config/scenarios/t1_normal.json',ROOT)
        topo = Topology.from_file(ROOT/'config/topology.json')
        sim = Simulator(seed=42)
        sim.attach_network(Network(topo,sim,base))
        for nid in topo.node_ids:
            env = sim.create_env(nid)
            sim.register_with_env(nid,SmokeNode(nid,env,make_behavior({}),base),env)
        message = SmokeMessage('TX','N0','aabbccddeeff','hi')
        sim.schedule(1,'tx',sim.network.gossip,'N0',message)
        sim.run(max_virtual_time_ms=10000)
        self.assertEqual(len(sim.nodes['N0'].observed),0)
        self.assertTrue(all(len(sim.nodes[nid].observed)==1 for nid in topo.node_ids if nid!='N0'))

    def test_config_merge_keeps_nested(self):
        merged = deep_merge({'a':{'x':1,'y':2}}, {'a':{'x':3}})
        self.assertEqual(merged,{'a':{'x':3,'y':2}})
        self.assertEqual(load_config(ROOT/'config/scenarios/t7_byzantine_equivocate.json',ROOT)['n'],10)

    def test_fault_factory_and_sign_corruption(self):
        self.assertEqual(make_behavior({'type':'silent'}).on_receive(type('X',(),{'env':type('E',(),{'now':lambda _:0})()})(),None,'hi'),None)
        @dataclass(frozen=True)
        class Vote:
            signature: bytes
        fault = BadSignatureBehavior('bad_key')
        altered = fault._corrupt(None,Vote(b'\x01'*64))
        self.assertNotEqual(altered.signature,b'\x01'*64)
        self.assertEqual(len(altered.signature),64)

    def test_equivocation_requires_valid_resign(self):
        class FakeEnv:
            peers = ['N1','N2','N3','N4']
        class FakeNode:
            env = FakeEnv()
            def make_conflicting_vote(self,original): return 'second-valid-signed-vote'
        result = EquivocateBehavior('vote').on_make_vote(FakeNode(),'first-valid-signed-vote')
        self.assertEqual(len(result),2)
        self.assertEqual(result[0][0],['N1','N2'])
        self.assertEqual(result[1][1],'second-valid-signed-vote')


    def test_network_block_and_automatic_unblock_events(self):
        config = load_config(ROOT/'config/scenarios/t1_normal.json',ROOT)
        config['rate_limit'] = {**config['rate_limit'], 'recv_max':2,'block_ms':250}
        sim = Simulator(seed=99)
        topology = Topology.from_file(ROOT/'config/topology.json')
        sim.attach_network(Network(topology,sim,config))
        for nid in topology.node_ids:
            env = sim.create_env(nid)
            sim.register_with_env(nid,SmokeNode(nid,env,make_behavior({}),config),env)
        for i in range(4):
            m = SmokeMessage('STATUS','N0',f'block-check-{i}','')
            sim.network.send('N0','N1',m)
        sim.run(5000)
        events = [line.split(' ev=')[1].split(' ')[0] for line in sim.logger.lines if 'node=N1 ' in line]
        self.assertIn('BLOCK',events)
        self.assertIn('UNBLOCK',events)

    def test_replay_timer_does_not_recurse(self):
        from src.faults.replay import ReplayBehavior
        class Env:
            def __init__(self):self.timers=[]
            def set_timer(self,name,delay):self.timers.append((name,delay))
        class Node:
            def __init__(self):self.env=Env()
        node = Node()
        behavior = ReplayBehavior(copies=3,delay_ms=100)
        message = SmokeMessage('TX','N0','replay-check','text')
        first = behavior.on_send(node,'N1',message)
        self.assertEqual(len(first),3)
        name,_ = node.env.timers[0]
        replayed = behavior.on_timer(node,name)
        self.assertEqual(len(replayed),1)
        self.assertEqual(len(behavior.on_send(node,*replayed[0])),1)
        self.assertEqual(len(node.env.timers),1)

if __name__ == '__main__':
    unittest.main()
