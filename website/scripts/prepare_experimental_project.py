#!/usr/bin/env python3
"""Make a portable, renamed copy of an owner-supplied experimental project.

Usage: python website/scripts/prepare_experimental_project.py INPUT.fitproj
Numeric arrays, fitted models, uncertainty samples and history are preserved.
The original file is never modified. Review the output before publishing it.
"""
import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_NAME = 'experimental-fluorescence'
SERIES = [f'Sample {letter}' for letter in 'ABCDEFGHIJK'] + [
    'Reference filters', 'Sample G · band trends', 'Sample I · band trends']


def prepare(source: Path, output: Path):
    with zipfile.ZipFile(source) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        project = manifest['project']
        replacements = {project['name']: 'Experimental fluorescence study'}
        for index, series in enumerate(project['series']):
            replacements[series['name']] = SERIES[index]
            for number, cid in enumerate(series['curve_ids'], 1):
                curve = project['curves'][cid]
                label = f'{SERIES[index]} · measurement {number:02d}'
                if index in (12, 13):
                    label = f'{SERIES[index]} · band {number}'
                replacements[curve['name']] = label
                replacements[curve['name'].split(':')[0].strip().replace('_normalizzato', '')] = label
                original_source = curve.get('source')
                if original_source:
                    replacements[original_source] = f'measurement-{index+1:02d}-{number:02d}.dat'
                imported = curve.get('metadata', {}).get('import', {})
                if imported.get('file_name'):
                    replacements[imported['file_name']] = f'measurement-{index+1:02d}-{number:02d}.dat'
        # All replacements are applied in one pass, including history snapshots.
        pattern = re.compile('|'.join(re.escape(x) for x in sorted(replacements, key=len, reverse=True)))

        def clean(value):
            if isinstance(value, dict):
                return {k: clean(v) for k, v in value.items()}
            if isinstance(value, list):
                return [clean(v) for v in value]
            if not isinstance(value, str):
                return value
            value = pattern.sub(lambda match: replacements[match.group()], value)
            value = re.sub(r'pico_carba(?:\.fitproj)?', PUBLIC_NAME + '.fitproj', value, flags=re.I)
            value = re.sub(r'carb[av]', 'sample', value, flags=re.I)
            value = re.sub(r'/(?:home|Users|mnt|media)/[^\s\"\x27\n]+', 'local-source-removed', value)
            return value.replace('wavelenght-(nm)', 'Wavelength (nm)')

        manifest = clean(manifest)
        p = manifest['project']
        p['name'] = 'Experimental fluorescence study'
        for cid, curve in p['curves'].items():
            original = project['curves'][cid]
            curve['x_label'] = original.get('x_label', '').replace('wavelenght-(nm)', 'Wavelength (nm)')
            curve['y_label'] = 'Normalized intensity' if original.get('y_label') == 'I-fluo' else original.get('y_label', '')
        p['path'] = None
        p['recovery'] = {'display_name': p['name'], 'source_file': PUBLIC_NAME + '.fitproj'}
        p['ui_state'].pop('recovery_source_file', None)
        translations = {
            'curve_e85711944969': 'Detector saturation was observed. Check the acquisition limits before interpreting the peak shape.',
            'curve_7dcaf267956e': 'Long acquisition-time window. Possible delayed fluorescence was noted; this is an observation to investigate, not an established assignment.',
            'curve_1f1e6fec4e04': 'Acquired with a new optical filter cutting near 380 nm.',
            'series_d2ac6e3a3f9a': 'The spectra were difficult to fit independently. Band centres were fixed using Sample G at matching pressures, or values extrapolated from its pressure-dependent band trends. Only the band areas were fitted. These centres are imposed modelling assumptions, not independently estimated peak positions.',
        }
        for entry in p['notebook']['descriptions']:
            if entry['object_id'] in translations:
                entry['text'] = translations[entry['object_id']]
        original_notes = p['notebook']['notes']
        p['notebook']['notes'] = '''EXPERIMENTAL FLUORESCENCE STUDY
Public copy of a real working project. Sample and measurement names have been changed.

ACQUISITION AND QUALITY CONTROL
Measurements compare fluorescence spectra across pressure cycles and repeated acquisitions. The original log records excitation conditions, attenuation filters, alignment checks, detector saturation and repeat measurements.

SERIES AND MODEL TRANSFER
Sample G contains the extended pressure cycle. Its band positions were used as a reference for Sample I. In Sample I, band centres were imposed from matching pressures or extrapolated trends; only band areas were fitted. See the series description for this modelling assumption.

UNCERTAINTY AND REVIEW
Saved residual-bootstrap and block-bootstrap analyses accompany the fitted spectra. The project also retains a sequential-fit pause requiring review after a worsening residual and a large change in a fitted width. Bootstrap interval stability does not validate a model.

OBJECT-SPECIFIC NOTES
A saturated acquisition, a long-time-window measurement and a change of optical filter are documented beside their spectra.

ORIGINAL LABORATORY LOG (renamed; Italian)
''' + original_notes
        manifest['portable'] = True
        payloads = {}
        for info in archive.infolist():
            if info.filename == 'manifest.json':
                continue
            data = archive.read(info)
            if info.filename.endswith('.jsonl'):
                rows = [clean(json.loads(line)) for line in data.decode().splitlines() if line.strip()]
                data = ('\n'.join(json.dumps(row, ensure_ascii=False, separators=(',', ':')) for row in rows) + '\n').encode()
            payloads[info.filename] = data
        manifest['checksums'] = {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as target:
            for name, data in payloads.items():
                target.writestr(name, data)
            target.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, separators=(',', ':')))
        # Numerical contents must remain byte-for-byte identical.
        with zipfile.ZipFile(output) as target:
            for info in archive.infolist():
                if info.filename.endswith('.npy'):
                    assert archive.read(info) == target.read(info.filename), info.filename
            text = target.read('manifest.json').decode() + target.read('history.jsonl').decode()
            assert not re.search(r'/home/|/Users/|pico_carba|carba|carva', text, re.I)
        print(f'Prepared {output}: {len(p["series"])} series, {len(p["curves"])} curves; numerical arrays preserved.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'projects' / (PUBLIC_NAME + '.fitproj'))
    args = parser.parse_args()
    prepare(args.input, args.output)
