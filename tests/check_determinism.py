"""T8: chạy cùng seed hai lần; so byte log và final state hash."""
import argparse
import tempfile
from pathlib import Path
from src.main import run_scenario


def check_case(config: str,seed: int = 42,smoke_env: bool = False) -> bool:
    with tempfile.TemporaryDirectory(prefix='lab01_t8_') as tmp:
        a,log_a = run_scenario(config,out_dir=str(Path(tmp)/'a'),seed=seed,smoke_env=smoke_env)
        b,log_b = run_scenario(config,out_dir=str(Path(tmp)/'b'),seed=seed,smoke_env=smoke_env)
        exact_log = log_a.read_bytes() == log_b.read_bytes()
        exact_hashes = ([entry['state_hash'] for entry in a['nodes'].values()] == [entry['state_hash'] for entry in b['nodes'].values()]) if not smoke_env else None
        # Seed khác phải sinh log khác để tránh 'deterministic' giả bằng log hằng số.
        c,log_c = run_scenario(config,out_dir=str(Path(tmp)/'c'),seed=seed+1,smoke_env=smoke_env)
        different_seed = log_a.read_bytes() != log_c.read_bytes()
        print(f'byte-identical logs: {exact_log}')
        hash_result = exact_hashes if not smoke_env else 'NOT_APPLICABLE_ENV_SMOKE'
        print(f'same final state hash: {hash_result}')
        print(f'different seed changes logs: {different_seed}')
        return exact_log and (exact_hashes if not smoke_env else True) and different_seed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Kiểm tra determinism')
    parser.add_argument('--config',required=True)
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--smoke-env',action='store_true',help='Chỉ kiểm thử hạ tầng')
    args = parser.parse_args(argv)
    return 0 if check_case(args.config,args.seed,args.smoke_env) else 1

if __name__ == '__main__':
    raise SystemExit(main())
