"""Host-operated retention cleanup; preview by default, never a model tool."""
import argparse
import os
from pathlib import Path

from .domain import Store


def main():
    parser = argparse.ArgumentParser(description='Preview ink trial projects older than 7 days after trial end')
    parser.add_argument('--apply', action='store_true', help='Delete expired private assets; default only previews')
    args = parser.parse_args()
    if os.environ.get('SFA_INK_TRIAL_MODE') != '1':
        print('试用功能已停用，不执行到期清理。')
        return
    store = Store(os.environ.get('SFA_INK_DATA_DIR') or Path(__file__).resolve().parents[2] / '.ink-demo')
    ids = store.purge(apply=args.apply)
    print(('已清理' if args.apply else '预览到期项目（未删除）') + '：' + str(len(ids)))
    for pid in ids:
        print(pid)


if __name__ == '__main__':
    main()
