"""Deterministic release archives. Only explicitly listed public files are packaged."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'plugins/codex-smart-router'
SKILL = PLUGIN / 'skills/smart-model-routing'
SKILL_FILES = ['SKILL.md','README.md','LICENSE','Start.cmd','launch.ps1',
 'scripts/app.py','scripts/client.py','scripts/routing.py','scripts/resource-check.ps1','scripts/smoke.py',
 'tests/test_router.py','tests/test_ui.py']
PLUGIN_FILES = ['.codex-plugin/plugin.json','README.md','LICENSE','Start.cmd',
 'assets/logo.svg','assets/logo.png','docs/PRIVACY.md','docs/TERMS.md'] + [f'skills/smart-model-routing/{p}' for p in SKILL_FILES]
REPO_FILES = ['.agents/plugins/marketplace.json','.gitignore','README.md','LICENSE',
 'docs/PRIVACY.md','docs/TERMS.md','submission/draft.json','submission/README.md','tools/build_release.py'] + [f'plugins/codex-smart-router/{p}' for p in PLUGIN_FILES]

def public_files():
    for name in REPO_FILES:
        path = ROOT / name
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError(f'Unsafe or missing release file: {name}')
        for parent in path.parents:
            if parent == ROOT:
                break
            if parent.is_symlink():
                raise ValueError(f'Linked release path: {name}')
        yield name, path

def build():
    list(public_files())
    version = json.loads((PLUGIN / '.codex-plugin/plugin.json').read_text(encoding='utf-8'))['version']
    output = ROOT / 'dist'
    output.mkdir(exist_ok=True)
    packages = [
        (f'smart-model-router-{version}-skill.zip', SKILL, 'smart-model-routing', SKILL_FILES),
        (f'smart-model-router-{version}-plugin.zip', PLUGIN, 'codex-smart-router', PLUGIN_FILES),
        (f'smart-model-router-{version}-source.zip', ROOT, 'codex-smart-router', REPO_FILES),
    ]
    sums = []
    for filename, base, prefix, files in packages:
        path = output / filename
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(files):
                info = zipfile.ZipInfo(f'{prefix}/{name}', date_time=(2026,9,14,0,0,0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                info.create_system = 3
                archive.writestr(info, (base/name).read_bytes())
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None
            assert len(archive.namelist()) == len(files)
        sums.append(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + filename)
    (output / 'SHA256SUMS.txt').write_text('\n'.join(sums)+'\n',encoding='utf-8')
    print('\n'.join(sums))

if __name__ == '__main__':
    build()
