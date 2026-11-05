"""Đọc log và truy vết lộ trình một wire message (theo 6 ký tự hex đầu)."""
import argparse
from collections import Counter
from pathlib import Path
from urllib.parse import unquote


def parse_line(line: str) -> dict:
    fields = {'time':line.split(' ',1)[0]}
    for part in line.strip().split(' ')[1:]:
        if '=' in part:
            key,value = part.split('=',1)
            fields[key] = unquote(value)
    return fields


def trace(log_path: str,msg_prefix: str) -> dict:
    events = []
    for line in Path(log_path).read_text(encoding='utf-8').splitlines():
        e = parse_line(line)
        if e.get('msg','').startswith(msg_prefix):
            events.append(e)
    hop_edges = []
    received = Counter()
    duplicates = Counter()
    for e in events:
        if e.get('ev') == 'RECV':
            received[e.get('node')] += 1
            hop_edges.append((e.get('via'),e.get('node'),e['time']))
        elif e.get('ev') == 'DUP':
            duplicates[e.get('node')] += 1
    return {'events':events,'hops':hop_edges,'received':dict(received),
            'duplicates':dict(duplicates)}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Truy vết gói tin theo msg_id')
    parser.add_argument('--log',required=True)
    parser.add_argument('--msg',required=True,help='6 ký tự hex đầu msg_id')
    args = parser.parse_args(argv)
    result = trace(args.log,args.msg)
    if not result['events']:
        print('Không có sự kiện nào khớp msg_id')
        return 1
    print(f'Gói {args.msg}: {len(result["events"])} sự kiện')
    origins = sorted({event['origin'] for event in result['events'] if 'origin' in event})
    print(f'  origin: {", ".join(origins)}')
    for a,b,t in result['hops']:
        print(f'  {t}: {a} -> {b}')
    for nid,count in sorted(result['duplicates'].items()):
        print(f'  DUP tại {nid}: {count} lần')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
