"""Stage an explicit runtime allowlist and invoke the official Dify CLI."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--output', required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='mailchannels-dify-') as temporary:
    stage = Path(temporary) / 'mailchannels'
    stage.mkdir()
    for name in ['main.py', 'mail_service.py', 'manifest.yaml', 'requirements.txt',
                 'README.md', 'PRIVACY.md', 'LICENSE']:
        shutil.copy2(root / name, stage / name)
    for name in ['provider', 'tools', '_assets']:
        shutil.copytree(root / name, stage / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    subprocess.run(['dify', 'plugin', 'package', str(stage), '-o', str(Path(args.output).resolve())], check=True)
