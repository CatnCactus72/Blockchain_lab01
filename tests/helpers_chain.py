"""Bộ ghép kiểm thử dùng Core thật; không có consensus, tạo block/certificate từ fixture."""
import json
from copy import deepcopy

from src.core.block import Block
from src.core.header import Header
from src.core.user import create_account_book, User
from src.core.vote import CommitCertificate, Vote
from src.crypto.hashing import tx_root
from src.crypto.signing import derive_validator_keypairs
from src.execution.executor import apply_block
from src.execution.state import State
from src.faults.base import Honest
from src.node.interfaces import Verdict
from src.node.ledger import Ledger
from src.node.sync import SyncManager
from src.node.tx_pool import TxPool
from src.node.validation import validate_proposal, validate_vote
from src.net.network import Network
from src.net.topology import Topology
from src.sim.simulator import Simulator


class ChainRulesNode:
    """Node chỉ cho test TX, wire và sync; không propose hay bỏ phiếu tự động."""
    def __init__(self, node_id, env, config):
        self.node_id, self.env, self.config = node_id, env, config
        self.behavior = Honest()
        self.keys = derive_validator_keypairs(config['seed'], config['n'])
        self.validator_pubkeys = {name: pair[1] for name, pair in self.keys.items()}
        self.account_pubkeys = create_account_book(config['seed'])
        self.state = State()
        self.ledger = Ledger(config['chain_id'], self.validator_pubkeys, 2*config['f']+1)
        self.pool = TxPool(self.account_pubkeys, config['chain_id'])
        self.sync = SyncManager(node_id, self.ledger, self.state, self.pool,
                                self.validator_pubkeys, self.account_pubkeys,
                                config['chain_id'], 2*config['f']+1)
        self.votes = []
        self.received = []

    def on_start(self):
        pass

    def on_timer(self, name):
        for peer, message in self.behavior.on_timer(self, name):
            self.env.send(peer, message)

    def on_message(self, from_peer, message):
        message = self.behavior.on_receive(self, from_peer, message)
        if message is None:
            return Verdict.ignore()
        self.received.append(message)
        kind, payload = message.kind, message.payload
        if kind == 'TX':
            ok, reason = self.pool.add(payload, self.state)
        elif kind == 'STATUS':
            self.sync.handle_status(from_peer, payload, self.env)
            return Verdict.accept()
        elif kind == 'GET_BLOCKS':
            self.sync.handle_get_blocks(from_peer, payload, self.env)
            return Verdict.accept()
        elif kind == 'BLOCKS':
            ok, reason, _ = self.sync.handle_blocks(from_peer, payload, self._on_synced)
        elif kind == 'GET_VOTES':
            self.sync.handle_get_votes(from_peer, payload, self.votes, self.env)
            return Verdict.accept()
        elif kind == 'VOTES':
            ok, reason, _ = self.sync.handle_votes(from_peer, payload, self.votes.append)
        elif kind in ('PREVOTE', 'PRECOMMIT'):
            ok, reason = validate_vote(payload, self.validator_pubkeys, self.config['chain_id'])
            if ok:
                self.votes.append(payload)
        elif kind == 'PROPOSAL':
            ok, reason = validate_proposal(payload, self.validator_pubkeys,
                                           chain_id=self.config['chain_id'], sender_id=message.origin)
        else:
            return Verdict.ignore()
        return Verdict.accept() if ok else Verdict.reject(reason)

    def _on_synced(self, block, certificate, state):
        for tx in block.transactions:
            details = {key: value for key, value in tx.to_dict().items() if key != 'signature'}
            self.env.log('TX_APPLIED', h=block.height,
                         details=json.dumps(details, ensure_ascii=False, sort_keys=True))
        self.env.log('FINALIZE', h=block.height, hash=str(block.block_hash()),
                     state=str(state.state_hash()), details='verified-certificate-fixture')

    def finalized_chain(self):
        return [{'height': block.height, 'hash': str(block.block_hash())}
                for block in self.ledger.all_blocks(include_genesis=False)]

    def final_state_hash(self):
        return str(self.state.state_hash())


def build_chain_simulator(config, root, output_path=None):
    """Ghép 10 node kiểm thử bằng transport thật, state/pool/ledger riêng biệt."""
    topology = Topology.from_file(root/config['topology_file'])
    sim = Simulator(config['seed'], output_path)
    sim.attach_network(Network(topology, sim, config))
    for node_id in topology.node_ids:
        env = sim.create_env(node_id)
        node = ChainRulesNode(node_id, env, config)
        sim.register_with_env(node_id, node, env)
    return sim


def certified_fixture(config):
    """Fixture ký thật 7 PRECOMMIT, không phải kết quả của máy đồng thuận."""
    keypairs = derive_validator_keypairs(config['seed'], config['n'])
    accounts = create_account_book(config['seed'])
    tx = User.from_seed(config['seed'], 'alice', config['chain_id']).make_message('Kiểm tra tích hợp 👋')
    next_state, reason = apply_block(State(), [tx], accounts, config['chain_id'])
    if reason:
        raise ValueError(reason)
    genesis = Block.genesis(config['chain_id'])
    header = Header(config['chain_id'], 1, str(genesis.block_hash()), str(tx_root([tx])),
                    str(next_state.state_hash()), 'N1', 1000)
    header.sign(keypairs['N1'][0])
    block = Block(header, [tx])
    votes = []
    for index in range(2*config['f']+1):
        node_id = f'N{index}'
        vote = Vote(1, 0, 'PRECOMMIT', str(block.block_hash()), node_id)
        vote.sign(keypairs[node_id][0], config['chain_id'])
        votes.append(vote)
    return block, CommitCertificate(1, str(block.block_hash()), votes, 0)


def install_fixture(node, block, certificate):
    """Đưa dữ liệu fixture qua chính SyncManager validation thay vì chép ledger/state."""
    return node.sync.handle_blocks('FIXTURE', [(deepcopy(block), deepcopy(certificate))], node._on_synced)
