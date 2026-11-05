"""Chạy tích hợp chữ ký/wire/sync thật; consensus vẫn PENDING, certificate đến từ fixture."""
import argparse
from pathlib import Path

from src.core.user import schedule_workload
from src.logsys.summary import save_summary, summarize_nodes
from src.main import load_config
from tests.helpers_chain import build_chain_simulator, certified_fixture, install_fixture

ROOT = Path(__file__).resolve().parents[1]


def run_case(seed, log_path):
    config = load_config(ROOT/'config/scenarios/t1_normal.json', ROOT)
    config['seed'] = seed
    config['stop']['max_virtual_time_ms'] = 4000
    sim = build_chain_simulator(config, ROOT, log_path)
    schedule_workload(sim, config, ROOT)
    block, certificate = certified_fixture(config)
    sim.schedule(4500, 'install-signed-fixture', install_fixture, sim.nodes['N0'], block, certificate)
    for at_ms in (5000, 6000, 7000):
        for node in sim.nodes.values():
            sim.schedule(at_ms, 'fixture-status', node.sync.broadcast_status, node.env)
    sim.run(10000)
    summary = summarize_nodes(sim.nodes, sim.clock.now())
    summary['mode'] = 'PART1_PART2_CERTIFICATE_FIXTURE_ONLY'
    summary['consensus_verified'] = False
    summary['accepted_transactions'] = {node_id: len(node.pool) for node_id, node in sim.nodes.items()}
    if any(node.ledger.latest_height != 1 for node in sim.nodes.values()) or not summary['converged']:
        raise AssertionError('Các node chưa đồng bộ được fixture có certificate hợp lệ')
    save_summary(summary, Path(log_path).parent/'summaries'/(Path(log_path).stem+'.json'))
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--out', default='logs')
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    # Chọn tên không trùng để bảo toàn các lần kiểm tra trước.
    run_no = 1
    while (out/f'PART1_PART2_run{run_no}_a.log').exists():
        run_no += 1
    logs = [out/f'PART1_PART2_run{run_no}_{label}.log' for label in ('a','b','c')]
    a = run_case(args.seed, logs[0])
    b = run_case(args.seed, logs[1])
    run_case(args.seed+1, logs[2])
    exact_log = logs[0].read_bytes() == logs[1].read_bytes()
    exact_state = a['nodes'] == b['nodes']
    changed_seed = logs[0].read_bytes() != logs[2].read_bytes()
    print('mode: PART1_PART2_CERTIFICATE_FIXTURE_ONLY; consensus: PENDING')
    print(f'byte-identical logs: {exact_log}')
    print(f'same finalized state hashes: {exact_state}')
    print(f'different seed changes logs: {changed_seed}')
    print(f'signed fixture synchronized to 10 nodes: {a["converged"]}')
    print(f'Log: {logs[0]}')
    return 0 if exact_log and exact_state and changed_seed else 1


if __name__ == '__main__':
    raise SystemExit(main())
