import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np
import soundfile as sf
from boundary_core import boundary


class PipelineTests(unittest.TestCase):
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
            subprocess.run([sys.executable,str(Path(__file__).with_name('pipeline.py')),'recut','--input',str(src),'--output',str(root/'result'),'--overrides',str(override)],check=True)
            result=json.loads((root/'result/manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(result['results'][0]['start'],.95)
            self.assertGreater(sf.info(root/'result/clips/0001.mp3').duration,0)


if __name__=='__main__':
    unittest.main()
