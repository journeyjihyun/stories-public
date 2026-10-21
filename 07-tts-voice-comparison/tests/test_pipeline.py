import json
import ast
import subprocess
import sys
import tempfile
import shutil
import unittest
from pathlib import Path
import numpy as np
import soundfile as sf
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from process import boundary, write_review


class PipelineTests(unittest.TestCase):
    def test_review_safe_embedding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'audio.mp3').write_bytes(b'first')
            rows = [dict(id='1', word='</script><script>alert(1)</script>', clip='audio.mp3', pitch_candidate=False)]
            write_review(root, rows)
            first = (root/'index.html').read_text(encoding='utf-8')
            self.assertNotIn(rows[0]['word'], first)
            payload = first.split('type="application/json">')[1].split('</script>')[0]
            self.assertEqual(json.loads(payload)['rows'], rows)
            if shutil.which('node'):
                subprocess.run(['node', str(Path(__file__).with_name('review_ui.cjs'))], input=first, text=True, encoding='utf-8', check=True)
            (root/'audio.mp3').write_bytes(b'second')
            write_review(root, rows)
            self.assertNotEqual(first, (root/'index.html').read_text(encoding='utf-8'))

    def test_algorithm_preserved(self):
        root = Path(__file__).resolve().parents[1]
        def functions(path):
            return {n.name: ast.dump(n, include_attributes=False)
                    for n in ast.parse(path.read_text(encoding='utf-8')).body
                    if isinstance(n, ast.FunctionDef)}
        for current, old, names in [
            ('process.py', 'boundary_core.py', ['boundary']),
            ('process.py', 'analyze_tts_pitch.py', ['semitones', 'measure', 'is_rising_issue']),
            ('generate.py', 'recut_waveform_snap_test.py', ['silent_runs', 'choose_start']),
            ('generate.py', 'generation_core.py', ['save', 'normalized']),
        ]:
            actual, previous = functions(root/current), functions(root/'legacy'/old)
            for name in names:
                self.assertEqual(actual[name], previous[name])

    def test_boundary(self):
        for runs,mode in [([(.93,.98)],'backward'),([(1.09,1.15)],'forward'),([], 'no_boundary_keep'),([(.92,.96),(1.08,1.13)],'ambiguous_keep')]:
            y=np.full(32000,.1)
            for a,b in runs:
                y[round(a*16000):round(b*16000)]=1e-6
            start,detail=boundary(y,16000,1.,.98,1.6,1.)
            self.assertEqual(detail['mode'],mode)
            if mode.endswith('_keep'):
                self.assertEqual(start,1.)

    def test_offline_recut(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);src=root/'source';src.mkdir()
            for folder in ['full','metadata','clips']:
                (src/folder).mkdir()
            sf.write(src/'full/0001.wav',.1*np.sin(2*np.pi*180*np.arange(32000)/16000),16000)
            row=dict(id='0001',word='예시',full='full/0001.wav',clip='clips/0001.wav',timestamp=1.,start=1.,end=1.8)
            (src/'manifest.json').write_text(json.dumps(dict(complete=True,settings={},results=[row])),encoding='utf-8')
            (src/'metadata/0001.json').write_text(json.dumps(dict(words=[dict(start=.5,end=.98),dict(start=1.,end=1.7)])),encoding='utf-8')
            override=root/'override.json';override.write_text(json.dumps({'예시':{'start_seconds':.95}}),encoding='utf-8')
            subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'process.py'),'--input',str(src),'--output',str(root/'result'),'--overrides',str(override)],check=True)
            result=json.loads((root/'result/manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(result['results'][0]['start'],.95)
            self.assertGreater(sf.info(root/'result/clips/0001.mp3').duration,0)
            html = (root/'result/index.html').read_text(encoding='utf-8')
            self.assertIn('처음부터 연속 재생', html)
            self.assertIn('clips/0001.mp3', html)


if __name__=='__main__':
    unittest.main()
