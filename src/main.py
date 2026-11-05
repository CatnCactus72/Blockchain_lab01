"""Điểm vào CLI của phần môi trường mô phỏng.

Chế độ thật cần build_node của Người 3 và schedule_workload của Người 2.
Chế độ --smoke-env chỉ kiểm tra mạng/simulator, KHÔNG chứng minh Lab T1-T8.
"""
import argparse
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from .sim.simulator import Simulator
from .net.topology import Topology
from .net.network import Network
from .faults.base import make_behavior
from .logsys.summary import summarize_nodes, save_summary


def deep_merge(base: dict, override: dict) -> dict:
    """Trộn đệ quy: giữ trường cấu hình gốc khi scenario không ghi đè."""
    out = deepcopy(base)
    for key,value in override.items():
        if isinstance(value,dict) and isinstance(out.get(key),dict):
            out[key] = deep_merge(out[key],value)
        else:
            out[key] = deepcopy(value)
    return out


def load_config(config_path: str | Path, root: str | Path = '.') -> dict:
    """Đọc base.json và file scenario; kiểm tra n=3f+1, n>=8."""
    root = Path(root)
    base = json.loads((root/'config/base.json').read_text(encoding='utf-8'))
    scenario = json.loads(Path(config_path).read_text(encoding='utf-8'))
    cfg = deep_merge(base,scenario)
    validate_config(cfg, config_path)
    return cfg


def validate_config(cfg: dict, config_path: str | Path) -> None:
    """Chặn cấu hình sai trước khi tạo node, log hoặc lịch gửi."""
    def integer(value, name, minimum=0):
        if type(value) is not int or value < minimum:
            raise ValueError(f'{name} phải là số nguyên >= {minimum}')

    for key in ('n', 'f', 'gst_ms'):
        integer(cfg.get(key), key)
    if type(cfg.get('seed')) is not int:
        raise ValueError('seed phải là số nguyên')
    if cfg['n'] < 8 or cfg['n'] != 3*cfg['f']+1:
        raise ValueError('Điều kiện lab: n >= 8 và n = 3f + 1')
    for key in ('delta_ms', 'block_interval_ms', 'status_interval_ms',
                'max_text_chars', 'max_tx_bytes', 'max_block_bytes'):
        integer(cfg.get(key), key, 1)
    for section, keys, minimum in (
        ('stop', ('target_height', 'max_virtual_time_ms'), 1),
        ('rate_limit', ('send_per_sec', 'recv_window_ms', 'recv_max', 'block_ms'), 1),
        ('timeouts', ('base_ms', 'step_ms'), 0),
    ):
        values = cfg.get(section)
        if not isinstance(values, dict):
            raise ValueError(f'{section} phải là object cấu hình')
        for key in keys:
            integer(values.get(key), f'{section}.{key}', minimum)
    for section, probabilities in (('pre_gst', ('drop', 'dup')), ('post_gst', ('dup',))):
        values = cfg.get(section)
        if not isinstance(values, dict):
            raise ValueError(f'{section} phải là object cấu hình')
        for key in probabilities:
            value = values.get(key)
            if type(value) not in (int, float) or not 0 <= value <= 1:
                raise ValueError(f'{section}.{key} phải nằm trong [0,1]')
        integer(values.get('extra_delay_max_ms'), f'{section}.extra_delay_max_ms')
    faults = cfg.get('faulty_nodes', [])
    if not isinstance(faults, list) or any(not isinstance(item, dict) or not isinstance(item.get('node'), str) for item in faults):
        raise ValueError('faulty_nodes phải chứa object có ID node dạng chuỗi')
    if len({item['node'] for item in faults}) != len(faults):
        raise ValueError('Node lỗi bị khai báo trùng')
    if len(faults) > cfg['f'] and Path(config_path).name != 'x2_beyond_f.json':
        raise ValueError('Số Byzantine vượt giới hạn f của kịch bản thông thường')
    for item in faults:
        if item.get('type') == 'silent':
            integer(item.get('from_ms', 0), 'silent.from_ms')
        if item.get('type') == 'replay':
            integer(item.get('copies', 3), 'replay.copies', 1)
            integer(item.get('delay_ms', 1000), 'replay.delay_ms')
        make_behavior(item)


def _get_smoke_factory():
    # Mock test CHỈ dùng để kiểm tra cơ sở hạ tầng, không phải blockchain thực.
    from tests.helpers_env import SmokeNode, schedule_smoke_workload
    return SmokeNode, schedule_smoke_workload


def _get_real_factory():
    from .core.user import schedule_workload
    try:
        from .node.node import build_node
    except (ImportError,AttributeError) as err:
        raise RuntimeError('Chưa ghép Người 3: cần src.node.node.build_node (Node/Consensus). '
                           'Workload ký thật src.core.user.schedule_workload đã có; '
                           'dùng --smoke-env để kiểm môi trường hoặc '
                           'python -m tests.check_part1_part2 để kiểm tích hợp không có consensus.') from err
    return build_node, schedule_workload


def run_scenario(config_path: str, out_dir: str = 'logs', seed: int | None = None,
                 faulty_ids: list[str] | None = None, smoke_env: bool = False,
                 root: str = '.') -> tuple[dict,Path]:
    """Hàm API cho kiểm thử: trả summary và đường dẫn log đã ghi."""
    root_path = Path(root)
    config_file = Path(config_path)
    if not config_file.exists():
        config_file = root_path / config_file
    cfg = load_config(config_file,root_path)
    if seed is not None:
        cfg['seed'] = seed
    if faulty_ids is not None:
        template = cfg['faulty_nodes'][0] if cfg.get('faulty_nodes') else {'type':'silent'}
        cfg['faulty_nodes'] = [{**template,'node':f'N{int(node_id)}' if str(node_id).isdigit() else str(node_id)}
                               for node_id in faulty_ids]
    validate_config(cfg, config_file)
    topology = Topology.from_file(root_path/cfg['topology_file'])
    if len(topology.node_ids) != int(cfg['n']):
        raise ValueError('topology_file và n không cùng số node')
    if any(item['node'] not in topology.node_ids for item in cfg['faulty_nodes']):
        raise ValueError('Node lỗi không có trong topology')
    faulty = {item['node']:make_behavior(item) for item in cfg.get('faulty_nodes',[])}
    if len(faulty) != len(cfg.get('faulty_nodes',[])):
        raise ValueError('Node lỗi bị khai báo trùng')
    build_node, schedule_workload = _get_smoke_factory() if smoke_env else _get_real_factory()

    # Thời gian THẬT chỉ được phép nằm trong TÊN file, không bao giờ ghi vào nội dung.
    out = Path(out_dir)
    out.mkdir(parents=True,exist_ok=True)
    case_name = config_file.stem.split('_')[0].upper()
    filename = f'{case_name}_{datetime.now().strftime("%d%m%Y_%H%M%S")}'
    path = out/(filename+'.log')
    run_no = 1
    while path.exists():
        path = out/(filename+f'_run{run_no}.log')
        run_no += 1
    simulator = Simulator(seed=int(cfg['seed']),output_path=path)
    simulator.attach_network(Network(topology,simulator,cfg))
    from .faults.base import Honest
    for node_id in topology.node_ids:
        env = simulator.create_env(node_id)
        behavior = faulty.get(node_id,Honest())
        node = build_node(node_id=node_id,env=env,behavior=behavior,config=cfg)
        simulator.register_with_env(node_id,node,env)
    schedule_workload(simulator, cfg, root_path)
    honest_ids = [nid for nid in topology.node_ids if nid not in faulty]
    simulator.run(max_virtual_time_ms=int(cfg['stop']['max_virtual_time_ms']),
                  target_height=(None if smoke_env else int(cfg['stop']['target_height'])),
                  honest_nodes=honest_ids)
    summary = summarize_nodes(simulator.nodes,simulator.clock.now(),honest_ids)
    # Phân biệt rõ nhãn smoke với run thực để không nhầm test đã PASS.
    summary['mode'] = 'ENV_SMOKE_ONLY' if smoke_env else 'BLOCKCHAIN'
    if smoke_env:
        # Không báo hội tụ blockchain giả khi node mock chỉ chứa chain rỗng.
        summary['converged'] = None
        summary['safety_prefixes'] = None
        summary['environment_ok'] = True
    summary['scenario'] = config_file.stem
    summary_path = out/'summaries'/(path.stem+'.json')
    save_summary(summary,summary_path)
    return summary,path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Mô phỏng blockchain Lab 01')
    parser.add_argument('--config',required=True,help='Đường dẫn scenario JSON')
    parser.add_argument('--seed',type=int,help='Ghi đè seed')
    parser.add_argument('--faulty',nargs='+',help='Ghi đè danh sách ID node lỗi')
    parser.add_argument('--out',default='logs',help='Thư mục ghi log')
    parser.add_argument('--smoke-env',action='store_true',help='Chỉ kiểm tra môi trường; không chạy consensus thật')
    args = parser.parse_args(argv)
    try:
        result,path = run_scenario(args.config,args.out,args.seed,args.faulty,args.smoke_env)
    except (RuntimeError,ValueError,NotImplementedError,FileNotFoundError) as exc:
        parser.exit(2,f'Lỗi chạy: {exc}\n')
    print(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True))
    print(f'Log: {path}')
    return 0 if result.get('environment_ok') or result['converged'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
