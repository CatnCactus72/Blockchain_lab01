"""Kiểm thử điểm ghép bằng chữ ký, Message, pool và sync thật; không chứng minh BFT."""
import tempfile
import unittest
from collections import Counter
from copy import deepcopy
from pathlib import Path

from src.core.proposal import Proposal
from src.core.user import User, schedule_workload
from src.core.vote import Vote
from src.core.wire import Envelope, Message, make_blocks_message, make_tx_message, make_vote_message
from src.crypto.encoding import enc_bytes, enc_str
from src.faults.bad_signature import BadSignatureBehavior
from src.faults.equivocate import EquivocateBehavior
from src.faults.signed import SignedFaultAdapter
from src.main import load_config
from src.node.interfaces import NodeCallbacks, NodeEnv, Verdict
from src.node.ledger import Ledger
from tests.check_part1_part2 import run_case
from tests.helpers_chain import build_chain_simulator, certified_fixture
from tests.tools.show_chat import LogLedgerView, format_chat_output, reconstruct_node_from_log
from tests.tools.show_state import format_state_output

ROOT = Path(__file__).resolve().parents[2]


class Part1Part2IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT/'config/scenarios/t1_normal.json', ROOT)

    def simulation(self):
        return build_chain_simulator(self.config, ROOT)

    def test_real_tx_gossip_and_per_node_state_isolation(self):
        sim = self.simulation()
        tx = User.from_seed(42, 'alice').make_message('Xin chào 👋')
        message = make_tx_message('N0', tx)
        sim.schedule(1, 'inject-real-tx', sim.inject_message, 'N0', message)
        sim.run(3000)
        self.assertTrue(all(node.pool.has_tx(tx) for node in sim.nodes.values()))
        self.assertTrue(all(len(node.pool) == 1 for node in sim.nodes.values()))
        self.assertEqual(len({id(node.state) for node in sim.nodes.values()}), 10)
        self.assertTrue(all(node.state.to_dict() == {} for node in sim.nodes.values()))
        stored = sim.nodes['N1'].pool.get_tx(str(tx.tx_id()))
        stored.value = 'Nội dung chỉ sửa tại N1'
        self.assertEqual(sim.nodes['N2'].pool.get_tx(str(tx.tx_id())).value, 'Xin chào 👋')
        self.assertEqual(message.payload.value, 'Xin chào 👋')

    def test_envelope_hops_and_canonical_roundtrip_keep_message_id(self):
        original = make_tx_message('N0', User.from_seed(42, 'alice').make_message('NFC 👋'))
        first = Envelope(original, 'N0', 'N1', 10)
        second = first.forward('N1', 'N2', 30)
        self.assertEqual(first.msg_id, second.msg_id)
        decoded, end = Message.decode(original.encode())
        self.assertEqual(end, len(original.encode()))
        self.assertEqual(decoded.msg_id, original.msg_id)
        self.assertEqual(decoded.payload.verify_signature(User.from_seed(42,'alice').pk), (True,None))

    def test_sender_mutation_after_send_cannot_change_queued_message(self):
        sim = self.simulation()
        message = Message('STATUS', 'N0', {'height': 0, 'last_hash': 'original'})
        sim.network.send('N0', 'N1', message)
        message.payload['last_hash'] = 'mutated'
        sim.run(1000)
        received = next(msg for msg in sim.nodes['N1'].received if msg.kind == 'STATUS')
        self.assertEqual(received.payload['last_hash'], 'original')

    def test_receiver_mutation_does_not_change_forwarded_payload(self):
        sim = self.simulation()
        def mutate(peer, message):
            message.payload.value = 'Sửa trong callback'
            return Verdict.accept()
        sim.network.handlers['N1'] = mutate
        original = make_tx_message('N0', User.from_seed(42,'alice').make_message('Không đổi'))
        sim.network.send('N0', 'N1', original)
        sim.run(3000)
        self.assertTrue(sim.nodes['N3'].pool.has_tx(original.payload))
        self.assertEqual(original.payload.value, 'Không đổi')

    def test_bad_signature_corrupts_real_nested_tx_vote_and_proposal(self):
        sim = self.simulation()
        node = sim.nodes['N1']
        block, _ = certified_fixture(self.config)
        proposal = Proposal(1,0,str(block.block_hash()),-1,block.header)
        proposal.sign(node.keys['N1'][0])
        vote = Vote(1,0,'PREVOTE',str(block.block_hash()),'N1')
        vote.sign(node.keys['N1'][0])
        messages = [make_tx_message('N1',User.from_seed(42,'alice').make_message('TX thật')),
                    make_vote_message('N1',vote), Message('PROPOSAL','N1',proposal)]
        for message in messages:
            with self.subTest(kind=message.kind):
                before = message.encode()
                modified = BadSignatureBehavior().on_send(node,'N2',message)[0][1]
                self.assertNotEqual(modified.msg_id, message.msg_id)
                self.assertEqual(message.encode(), before)
                if message.kind == 'TX':
                    result = modified.payload.verify_signature(node.account_pubkeys['alice'])
                elif message.kind == 'PROPOSAL':
                    result = modified.payload.verify_proposal_sig(node.validator_pubkeys['N1'])
                else:
                    result = modified.payload.verify_signature(node.validator_pubkeys['N1'])
                self.assertEqual(result, (False,'BAD_SIGNATURE'))

    def test_wrong_domain_and_tamper_use_actual_ed25519(self):
        sim = self.simulation()
        node = sim.nodes['N2']
        adapter = SignedFaultAdapter('N2', node.keys['N2'][0], self.config['chain_id'])
        node.resign_wrong_domain = adapter.resign_wrong_domain
        node.tamper_signed_message = adapter.tamper_signed_message
        vote = Vote(1,0,'PREVOTE','a'*64,'N2')
        vote.sign(node.keys['N2'][0])
        original = make_vote_message('N2',vote)
        for mode, reason in [('wrong_domain','WRONG_DOMAIN'),('tamper','BAD_SIGNATURE')]:
            with self.subTest(mode=mode):
                modified = BadSignatureBehavior(mode).on_send(node,'N1',original)[0][1]
                self.assertNotEqual(modified.msg_id, original.msg_id)
                self.assertEqual(modified.payload.verify_signature(node.validator_pubkeys['N2']), (False,reason))
        self.assertEqual(vote.verify_signature(node.validator_pubkeys['N2']), (True,None))

    def test_equivocation_has_two_conflicting_valid_signatures(self):
        sim = self.simulation()
        node = sim.nodes['N1']
        adapter = SignedFaultAdapter('N1', node.keys['N1'][0], self.config['chain_id'])
        node.make_conflicting_vote = adapter.make_conflicting_vote
        vote = Vote(1,0,'PREVOTE','a'*64,'N1')
        vote.sign(node.keys['N1'][0])
        outputs = EquivocateBehavior('vote').on_make_vote(node, vote)
        self.assertNotEqual(outputs[0][1].block_hash, outputs[1][1].block_hash)
        self.assertEqual(sorted(outputs[0][0]+outputs[1][0]), sorted(node.env.peers))
        for _, value in outputs:
            self.assertEqual(value.verify_signature(node.validator_pubkeys['N1']), (True,None))
        with self.assertRaises(ValueError):
            SignedFaultAdapter('N2', node.keys['N2'][0], self.config['chain_id']).make_conflicting_vote(vote)

    def test_proposal_equivocation_keeps_header_and_proposal_signatures_valid(self):
        sim = self.simulation()
        node = sim.nodes['N1']
        block, _ = certified_fixture(self.config)
        proposal = Proposal(1,0,str(block.block_hash()),-1,block.header)
        proposal.sign(node.keys['N1'][0])
        adapter = SignedFaultAdapter('N1',node.keys['N1'][0],self.config['chain_id'])
        node.make_conflicting_proposal = adapter.make_conflicting_proposal
        outputs = EquivocateBehavior('proposal').on_make_proposal(node, proposal)
        self.assertNotEqual(outputs[0][1].block_hash,outputs[1][1].block_hash)
        for _, value in outputs:
            self.assertEqual(value.verify_proposer_and_sig(node.validator_pubkeys), (True,None))
            self.assertEqual(value.header.verify_signature(node.validator_pubkeys['N1']), (True,None))

    def test_sync_fixture_via_network_validates_certificate_and_preserves_log_unicode(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp)/'integration.log'
            result = run_case(42,log)
            self.assertTrue(result['converged'])
            self.assertFalse(result['consensus_verified'])
            for node_id in result['nodes']:
                ledger, state, query = reconstruct_node_from_log(log,node_id)
                self.assertIsInstance(ledger, LogLedgerView)
                self.assertNotIsInstance(ledger, Ledger)
                self.assertEqual(str(state.state_hash()),result['nodes'][node_id]['state_hash'])
                self.assertIn('Kiểm tra tích hợp 👋',format_chat_output(query,node_id))
                self.assertIn('Kiểm tra tích hợp 👋',format_state_output(query,node_id))

    def test_sync_rejects_missing_forged_or_truncated_certificates(self):
        node = self.simulation().nodes['N0']
        block, certificate = certified_fixture(self.config)
        forged = deepcopy(certificate)
        forged.votes[0].signature = b'\x00'*64
        malformed = [
            {'entries':[{'block':block,'certificate':None}]},
            {'entries':[(block,forged)]},
            {'blocks':[block],'certificates':[]},
        ]
        for payload in malformed:
            with self.subTest(payload_type=list(payload)):
                ok, reason, applied = node.sync.handle_blocks('N1',payload)
                self.assertFalse(ok)
                self.assertEqual(reason,'BAD_SIGNATURE')
                self.assertEqual(applied,[])
                self.assertEqual(node.ledger.latest_height,0)
                self.assertEqual(node.state.to_dict(),{})

    def test_sync_without_keybooks_cannot_trust_peer_certificate(self):
        node = self.simulation().nodes['N0']
        block, certificate = certified_fixture(self.config)
        node.sync.validator_pubkeys = None
        self.assertEqual(node.sync.handle_blocks('N1',[(block,certificate)]), (False,'BAD_SIGNATURE',[]))
        self.assertEqual(node.sync.handle_votes('N1',{'votes':[certificate.votes[0]]}), (False,'BAD_SIGNATURE',[]))

    def test_get_votes_and_votes_travel_point_to_point(self):
        sim = self.simulation()
        vote = Vote(1,0,'PREVOTE','a'*64,'N0')
        vote.sign(sim.nodes['N0'].keys['N0'][0])
        sim.nodes['N0'].votes.append(vote)
        sim.nodes['N1'].sync.request_votes(1,0,sim.nodes['N1'].env,['N0'])
        sim.run(1000)
        self.assertEqual(len(sim.nodes['N1'].votes),1)
        self.assertEqual(sim.nodes['N1'].votes[0].signature,vote.signature)
        self.assertFalse(sim.nodes['N2'].votes)
        self.assertEqual(sim.nodes['N1'].sync.handle_votes('N0',{'votes':[None]}), (False,'BAD_SIGNATURE',[]))

    def test_real_wire_drop_before_gst_and_duplicate_after_gst(self):
        self.config['gst_ms'] = 1000
        self.config['pre_gst']['drop'] = 1.0
        self.config['post_gst']['dup'] = 1.0
        self.config['post_gst']['extra_delay_max_ms'] = 100
        sim = self.simulation()
        message = Message('STATUS','N0',{'height':0,'last_hash':'a'*64})
        sim.network.send('N0','N1',message)
        sim.schedule(1000,'after-gst',sim.network.send,'N0','N1',message)
        sim.run(2000)
        self.assertEqual(len(sim.nodes['N1'].received),2)
        self.assertTrue(any('ev=DROP' in line for line in sim.logger.lines))
        self.assertTrue(any('ev=DUP' in line for line in sim.logger.lines))

    def test_wire_decoder_rejects_unconsumed_payload_bytes(self):
        tx = User.from_seed(42,'alice').make_message('Đủ byte')
        raw = enc_str('TX')+enc_str('N0')+enc_bytes(tx.encode()+b'extra')+enc_bytes(b'')
        with self.assertRaises(ValueError):
            Message.decode(raw)

    def test_real_messages_reorder_without_losing_identity(self):
        self.config['post_gst']['extra_delay_max_ms'] = 200
        sim = self.simulation()
        messages = [Message('STATUS','N0',{'height':0,'last_hash':f'{index:064x}'}) for index in range(8)]
        for message in messages:
            sim.network.send('N0','N1',message)
        sim.run(1000)
        sent = [str(message.msg_id) for message in messages]
        received = [str(message.msg_id) for message in sim.nodes['N1'].received]
        self.assertCountEqual(received,sent)
        self.assertNotEqual(received,sent)

    def test_signed_workload_burst_and_replay(self):
        for mode, stop, count in [('burst',7000,114),('replay_alice',2000,5)]:
            with self.subTest(mode=mode):
                self.config['stop']['max_virtual_time_ms'] = stop
                self.config['workload_mode'] = mode
                sim = self.simulation()
                emitted = []
                sim.inject_message = lambda node_id,msg: emitted.append((sim.clock.now(),node_id,msg))
                schedule_workload(sim,self.config,ROOT)
                sim.run(stop)
                self.assertEqual(len(emitted),count)
                for _,_,message in emitted:
                    self.assertEqual(message.payload.verify_signature(sim.nodes['N0'].account_pubkeys[message.payload.account]),(True,None))
                if mode == 'replay_alice':
                    ids = Counter(str(msg.payload.tx_id()) for _,_,msg in emitted)
                    self.assertEqual(ids[str(emitted[0][2].payload.tx_id())],2)

    def test_node_protocol_contract_and_reject_reason(self):
        node = self.simulation().nodes['N0']
        self.assertIsInstance(node.env,NodeEnv)
        self.assertIsInstance(node,NodeCallbacks)
        with self.assertRaises(ValueError):
            Verdict.reject('UNSPECIFIED')


if __name__ == '__main__':
    unittest.main()
