"""Turn the tested beta documentation into a matching stable release edition."""
from __future__ import annotations

import re
from pathlib import Path

FILES = ('README.md', 'docs/manual.md', 'docs/quick-start.md', 'docs/python-api.md',
         'docs/workflows.md', 'docs/ai-python-audit.md', 'docs/ai-yaml-audit.md',
         'docs/releasing.md', 'examples/folder_workflow.yml')


def stable_text(text: str, version: str) -> str:
    text = re.sub(r'\*\*Stable API baseline:.*?\*\*',
                  f'**Stable API baseline: CurveMole {version}.**', text)
    text = re.sub(r'\*\*Stable baseline:.*?\*\*',
                  f'**Stable baseline: CurveMole {version}.**', text)
    text = re.sub(r'\*\*Current testing behavior\.\*\*.*?(?=\n\n)',
                  '**Current release behavior.** This edition includes the November 2026 scientific\n'
                  'and data-integrity corrections. Use the documents matching your installed release;\n'
                  'these corrections are not implied for older executables.', text, flags=re.S)
    text = re.sub(r'\*\*Testing edition for CurveMole .*?\*\*.*?(?=\n\n)',
                  f'**Stable edition for CurveMole {version}.** This release includes the workflow\n'
                  'features documented in Appendices F/G and the scientific and data-integrity\n'
                  'corrections summarized in Appendices I/J. Earlier executables can differ;\n'
                  'keep the matching manual and automation references with your analysis.', text, flags=re.S)
    text = text.replace('This testing edition documents the current local testing code on top of that\n'
                        'baseline; it does not claim that all testing behavior is present in the stable release.',
                        'This release edition documents the released scientific engine and application.')
    text = re.sub(r'Applies to Python \*\*3\.12\+\*\*\. This testing edition.*?results\.',
                  'Applies to Python **3.12+**. This release documents the GUI-independent scientific\n'
                  'engine: imports, arguments, return values, side effects and limits. Private names\n'
                  'beginning with `_` and GUI classes are outside this scripting contract.\n'
                  'Record the installed version and scientific dependency versions with your results.',
                  text, flags=re.S)
    text = re.sub(r'This testing edition documents both the stable baseline.*?This is the runner contract, not every desktop action\.',
                  f'This reference documents CurveMole {version}, including folder/pattern imports,\n'
                  'templates, shared selectors, preprocessing, validation and output controls.\n'
                  'Use `schema_version: 3` for these workflow fields. Schemas 1 and 2 retain\n'
                  'their legacy fields; older executables can reject newer recipes.\n'
                  'This is the runner contract, not every desktop action.', text, flags=re.S)
    text = re.sub(r'new beta operations choose a `[^`]+` wheel, where N is the actual published beta\n'
                  r'sequence; a `1\.1\.0` wheel supports only the stable baseline\.',
                  f'the current operations install the `{version}` wheel; older wheels may support\n'
                  'only a subset of this interface.', text)
    text = text.replace('The latest testing-source editions are also available here:',
                        'The exact stable-source editions are also available here:')
    text = re.sub(r'These convenience URLs follow `testing`,.*?with your analysis\.',
                  'These URLs are pinned to this stable tag. Keep the matching documents with your\n'
                  'analysis; historical editions remain available at their original release tags.',
                  text, flags=re.S)
    text = text.replace('https://raw.githubusercontent.com/SebRoLENS/curvemole/testing/docs/',
                        f'https://raw.githubusercontent.com/SebRoLENS/curvemole/v{version}/docs/')
    text = text.replace('Use the stable baseline only for Stable 1.1.0;\n'
                        '  testing-only additions and corrected behavior require the matching testing/beta build.',
                        f'Target the documented Stable {version} release; earlier versions may lack\n'
                        '  the newer operations and scientific corrections.')
    text = text.replace('Workflow schema is **2** in the stable baseline and **3** for',
                        'Workflow schema is **2** in 1.1.0 and **3** from')
    text = re.sub(r'Install the \d+\.\d+\.\d+ wheel in a Python environment',
                  f'Install the {version} wheel in a Python environment', text)
    text = text.replace('Using the attached CurveMole 1.1.0 Python audit',
                        f'Using the attached CurveMole {version} Python audit')
    text = text.replace('1.1.0 stable or exact '+version+' beta build', version+' stable')
    text = re.sub(r'\*\*Stable edition for CurveMole \d+\.\d+\.\d+\.\*\*',
                  f'**Stable edition for CurveMole {version}.**', text)
    text = text.replace(version+'\nbeta,', version+',')
    text = text.replace(version+' beta', version)
    text = text.replace('**Beta workflow schema:', '**Workflow schema:')
    for old, new in (
        ('; beta only', f'; {version}+'),
        ('; beta', f'; {version}+'),
        ('beta also accepts', f'{version} also accepts'),
        ('a beta addition', f'an addition in {version}'),
        ('In beta,', f'In {version},'),
        ('In beta batch', 'In batch'),
        ('beta workflows', 'current workflows'),
        ('Beta dumping', 'Current dumping'),
        ('the beta validator', 'the validator'),
        ('The beta validator', 'The validator'),
        ('the beta `glob`', 'the `glob`'),
        ('current testing edition', 'current release edition'),
        ('Scientific corrections (testing,', 'Scientific corrections (release,'),
        ('your exact beta build', 'your exact release build'),
        ('your exact beta download', 'your exact release download'),
        ('the exact beta build', 'the exact release build'),
        ('the exact beta release', 'the exact release'),
        ('new beta workflows', 'new workflows'),
        ('marked beta-only YAML keys', 'new YAML keys'),
        ('beta YAML runner', 'YAML runner'),
        ('This testing edition', 'This release edition'),
        ('this testing edition', 'this release edition'),
        ('in this testing edition', 'in this release edition'),
        ('Testing edition: integrity', 'Release integrity'),
    ):
        text = text.replace(old, new)
    text = re.sub(r'target is `[^`]+`, producing `[^`]+` / `[^`]+` while stable remains `[^`]+`\.',
                  'target is recorded in `.github/release-target.json`; after a stable promotion,\n'
                  'testing starts the next patch cycle unless a newer target is selected.', text)
    return text


def appendix(text: str, title: str) -> str:
    result = []
    fenced = False
    for line in text.splitlines():
        if re.match(r'^\s*(```|~~~)', line):
            fenced = not fenced
        elif not fenced:
            if line.startswith('# '):
                line = title
            elif re.match(r'^#{2,6}\s', line):
                line = '#'+line
        result.append(line)
    return '\n'.join(result).strip()


def promote(root: Path, version: str) -> None:
    for name in FILES:
        path = root / name
        if path.exists():
            path.write_text(stable_text(path.read_text(encoding='utf-8'), version), encoding='utf-8')
    for target, source, marker in (
        ('ai-python-audit.md', 'python-api.md', '## Complete scripting contract'),
        ('ai-yaml-audit.md', 'workflows.md', '## Complete implementation contract'),
    ):
        destination, reference = root/'docs'/target, root/'docs'/source
        if destination.exists() and reference.exists():
            prefix = destination.read_text().split(marker, 1)[0]
            destination.write_text(prefix+marker+'\n\n'+reference.read_text().split('\n', 1)[1].lstrip())
    manual = root/'docs/manual.md'
    if not manual.exists():
        return
    text = manual.read_text()
    for name, marker, title in (
        ('python-api.md', 'PYTHON SCRIPTING REFERENCE', '## Appendix F. Python scripting reference'),
        ('workflows.md', 'YAML WORKFLOW REFERENCE', '## Appendix G. YAML workflow reference'),
    ):
        reference = root/'docs'/name
        start = f'<!-- BEGIN {marker} (docs/{name}) -->'
        end = f'<!-- END {marker} -->'
        if reference.exists() and start in text and end in text:
            before, rest = text.split(start, 1)
            _, after = rest.split(end, 1)
            text = before+start+'\n\n'+appendix(reference.read_text(), title)+'\n\n'+end+after
    manual.write_text(text)
