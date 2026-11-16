"""Detached, read-only milestone watcher. Never submits, holds, or stops campaign jobs."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

from collect import TARGET, collect, digest, freeze, load, read_sample, require, save, select_entries, verify_commit

# Executed in the remote conda environment: only stdlib and small commit/status files.
PROBE = '''import hashlib,json,pathlib,sys,time
root=pathlib.Path(sys.argv[1]); entries=[]; observed=time.time()
if not (root/'rows').is_dir(): raise FileNotFoundError(root/'rows')
for path in sorted((root/'rows').glob('sample_*/commit.json')):
 raw=path.read_bytes(); d=json.loads(raw)
 entries.append({'sample':d['sample'],'rows':d['rows'],'committed_unix':d['committed_unix'],
                 'commit_sha256':hashlib.sha256(raw).hexdigest(),'source':str(path.parent)})
status=root/'driver_status.json'
samples=json.loads(status.read_text()).get('samples',{}) if status.exists() else {}
for path in root.glob('sample_*_status.json'):
 samples[str(int(path.name.split('_')[1]))]=json.loads(path.read_text())
print(json.dumps({'entries':entries,'observed_unix':observed,
 'quarantined_samples':[int(k) for k,v in samples.items() if v['phase']=='quarantined']}))
'''


def command(argv, **kwargs):
    return subprocess.run(argv, check=True, text=True, capture_output=True, timeout=600, **kwargs).stdout


def ssh_args(front):
    return ['ssh', '-o', 'BatchMode=yes', '-o', 'ProxyCommand=false', '-o', 'ControlMaster=no',
            '-o', 'ControlPath=' + front['socket'], '-p', str(front.get('port', 22))]


def socket_identity(front):
    stat = Path(front['socket']).stat()
    return [stat.st_dev, stat.st_ino, stat.st_ctime_ns]


def inventory(front, blocks):
    if 'host' not in front:
        return json.loads(command([sys.executable, '-c', PROBE, front['root']]))
    identity = socket_identity(front)
    require(blocks.get(front['name'], {}).get('socket') != identity,
            'connection suspended until a replacement master socket or operator reset')
    args = ssh_args(front)
    command(args + ['-O', 'check', front['host']])
    try:
        value = json.loads(command(args + [front['host'],
                   shlex.join(front['python_command'] + ['-c', PROBE, front['root']])]))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        blocks[front['name']] = {'socket': identity, 'error': str(error), 'time': time.time()}
        raise
    blocks.pop(front['name'], None)
    return value


def mirror(entry, front, root):
    destination = root / 'mirrors' / front['name'] / f"sample_{entry['sample']:03d}"
    result = {**entry, 'front': front['name'], 'mirror': str(destination)}
    if destination.exists():
        require(digest(destination / 'commit.json') == entry['commit_sha256'], 'mirrored commit changed')
        return result
    incoming = destination.with_name(destination.name + '.incoming')
    incoming.mkdir(parents=True, exist_ok=True)
    args = ['rsync', '-a', '--checksum', '--timeout=60']
    source = entry['source'] + '/'
    if 'host' in front:
        args += ['-e', shlex.join(ssh_args(front))]
        source = front['host'] + ':' + source
    command(args + [source, str(incoming) + '/'])
    verify_commit(incoming, result)
    read_sample(incoming, entry['sample'])
    os.replace(incoming, destination)
    return result


def progress(inventories, now):
    entries = [dict(e, front=name) for name, item in inventories.items() for e in item['entries']]
    full = [e for e in entries if e['rows'] == 1677]
    require(len({e['sample'] for e in full}) == len(full), 'overlapping front commits')
    rates = {name: sum(e['rows'] == 1677 and now - 6 * 3600 <= e['committed_unix'] <= now
                      for e in item['entries']) / 6 for name, item in inventories.items()}
    rate = sum(rates.values())
    return {'target': TARGET, 'complete': len(full), 'remaining': max(0, TARGET - len(full)),
            'quarantined_partials': {name: item['quarantined_samples'] for name, item in inventories.items()},
            'rate_window_hours': 6, 'complete_samples_per_hour': rates,
            'conditional_hours_at_observed_rate': max(0, TARGET - len(full)) / rate if rate else None,
            'eta_caveat': 'Conditional extrapolation, not a queue forecast. Stokes owns only 000-059; '
                          '100 requires another front. Zero-commit fronts have no measured throughput.',
            'fronts': {name: {'complete': sum(e['rows'] == 1677 for e in item['entries']),
                              'observed_unix': item['observed_unix']} for name, item in inventories.items()}}


def cycle(config, root):
    blocks_path = root / 'blocked_connections.json'
    blocks = load(blocks_path) if blocks_path.exists() else {}
    inventories, errors = {}, {}
    for front in config['fronts']:
        try:
            inventories[front['name']] = inventory(front, blocks)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            errors[front['name']] = str(error)
    save(blocks_path, blocks)
    status = {'updated_unix': time.time(), 'pid': os.getpid(), 'errors': errors,
              **progress(inventories, time.time()), 'phase': 'waiting_for_commits'}
    save(root / 'status.json', status)
    if errors:
        status['phase'] = 'waiting_for_front_inventory'
        save(root / 'status.json', status)
        return False
    entries = [dict(e, front=name) for name, data in inventories.items() for e in data['entries']]
    watermark = min(item['observed_unix'] for item in inventories.values())
    chosen = select_entries([e for e in entries if e['committed_unix'] <= watermark])
    status['complete_inventory_through_unix'] = watermark
    front_by_name = {f['name']: f for f in config['fronts']}
    mirrored = [mirror(e, front_by_name[e['front']], root) for e in chosen]
    save(root / 'verified_inventory.json', {'samples': mirrored, 'observed_unix': time.time()})
    status['verified_complete'] = len(mirrored)
    if len(mirrored) < TARGET:
        save(root / 'status.json', status)
        return False
    snapshot = root / 'snapshot_partial100.json'
    freeze(snapshot, mirrored)
    status['phase'] = 'collecting'
    save(root / 'status.json', status)
    staging = root / 'partial100.building'
    collect(snapshot, staging)
    with (root / 'plot.log').open('a') as log:
        subprocess.run(config['plot_command'] + ['--input', str(staging)],
                       check=True, stdout=log, stderr=subprocess.STDOUT, timeout=900)
    save(staging / 'artifact_sha256.json', {
        str(p.relative_to(staging)): digest(p) for p in sorted(staging.rglob('*')) if p.is_file() and p.name != 'artifact_sha256.json'})
    os.replace(staging, root / 'partial100')
    status.update(phase='figures_ready', finished_unix=time.time(), output=str(root / 'partial100'),
                  snapshot_sha256=digest(snapshot))
    save(root / 'status.json', status)
    return True


def notify(config, root, status):
    previous = root / 'report_delivery.json'
    last = load(previous) if previous.exists() else {}
    ready = status['phase'] == 'figures_ready'
    if (not ready and last.get('delivered') and
            time.time() - last['time'] < config['report_seconds']):
        return True
    lines = [f"T99 milestone100: {status['complete']}/100 full samples; "
             f"quarantined partials separate: {status['quarantined_partials']}.",
             f"Measured last6h commits/hour: {status['complete_samples_per_hour']}."]
    if status['errors']:
        lines.append(f"Inventory incomplete: {status['errors']}; no ETA or cohort freeze until all fronts are fresh.")
    else:
        hours = status['conditional_hours_at_observed_rate']
        lines.append(f"Conditional hours at observed rate: {hours}. {status['eta_caveat']}")
    if ready:
        lines.append(f"Figures ready: {status['output']}; frozen cohort: {root / 'snapshot_partial100.json'}. "
                     "Campaign continues; no pause or scheduler action.")
    else:
        lines.append(f"Watcher: {status['phase']}; status: {root / 'status.json'}. Campaign continues.")
    message = '\n'.join(lines) + '\n\nMeow...\n'
    (root / 'latest_report.txt').write_text(message)
    try:
        result = subprocess.run(config['report_command'], input=message, text=True,
                                capture_output=True, timeout=30)
        delivery = {'delivered': result.returncode == 0, 'stdout': result.stdout, 'stderr': result.stderr}
    except (OSError, subprocess.SubprocessError) as error:
        delivery = {'delivered': False, 'error': str(error)}
    save(previous, {'time': time.time(), 'phase': status['phase'], **delivery})
    return delivery['delivered']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    config = load(args.config)
    root = Path(config['root'])
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'watch.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            try:
                done = (root / 'partial100/artifact_sha256.json').exists()
                if not done:
                    done = cycle(config, root)
                status = load(root / 'status.json')
                print(json.dumps(status), flush=True)
                delivered = notify(config, root, status)
            except Exception as error:
                save(root / 'status.json', {'phase': 'error', 'error': repr(error),
                                            'pid': os.getpid(), 'updated_unix': time.time()})
                raise
            if (done and delivered) or args.once:
                break
            time.sleep(config['poll_seconds'])
