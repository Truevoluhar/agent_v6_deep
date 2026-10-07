"""Copy legacy shared files to one explicitly chosen existing user.

Checkpoint migration is deliberately excluded: the installed saver schema must be
inspected before any checkpoint writes are rewritten. Legacy transcripts are
archived and cannot be continued as if their model state were present.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.auth.repository import AuthRepository
from shared.user_paths import UserPaths, canonical_uuid


def copy_tree(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    if destination.exists() and any(destination.iterdir()):
        raise RuntimeError(f'Target is not empty: {destination}')
    for item in source.rglob('*'):
        if item.is_symlink():
            raise RuntimeError(f'Legacy symlink requires manual review: {item}')
    shutil.copytree(source,destination,dirs_exist_ok=True)


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument('--user-id',required=True,help='Existing internal UUID to receive legacy data')
    parser.add_argument('--legacy-root',default='/data')
    parser.add_argument('--apply',action='store_true',help='Perform the copy after backup and review')
    args=parser.parse_args()
    user_id=canonical_uuid(args.user_id)
    root=Path(args.legacy_root).resolve()
    paths=UserPaths.for_user(user_id)
    with AuthRepository().connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT 1 FROM app_users WHERE id=%s',(user_id,))
        if not cur.fetchone():
            raise SystemExit('User does not exist')
    entries=[
        (root/'agent_workspace',paths.workspace),
        (root/'session',paths.root/'legacy_sessions'),
        (root/'memory',paths.memory),
        (root/'resources',paths.resources),
        (root/'runs',paths.root/'legacy_runs'),
    ]
    for source,destination in entries:
        print(f'{source} -> {destination}')
    print('Legacy transcripts are archived only; checkpoints remain under old keys.')
    if not args.apply:
        print('Dry run. Create a backup, then rerun with --apply.')
        return
    for source,destination in entries:
        copy_tree(source,destination)


if __name__=='__main__':
    main()
