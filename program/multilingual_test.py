import json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
import multilingual as m
import workflow
class MultiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.p=Path(self.temp.name);self.f=self.p/'file';self.f.touch()
    def test_languages_reuse_original_srt(self):
        for lang in m.LANGUAGES:
            job=workflow.normalize(dict(language=lang,alignment='auto',source_srt=str(self.f),video=str(self.f),audio=str(self.f),output=str(self.p)))
            self.assertEqual(job['alignment'],'multi');self.assertEqual(job['target_srt'],str(self.f))
    def test_words_and_reference_times(self):
        for text in ('目を覚ましてください。','Réveillez-vous maintenant.','Bitte wachen Sie auf.'):
            cues=[(1,20,30,text)]
            result={'segments':[{'words':[dict(word=text,start=1.,end=2.)]}]}
            a,r,i=m.validate(cues,result,3)
            self.assertEqual(a,[(1,1.,2.,text)]);self.assertEqual(i,[1])
    def test_japanese_subword_groups_preserve_characters(self):
        result={'segments':[{'words':[dict(word='お',start=1,end=1),dict(word='電話',start=1,end=2),dict(word='。',start=2,end=2)]}]}
        a,r,i=m.validate([(1,40,50,'お電話。')],result,3,join_subwords=True)
        self.assertEqual(r,[dict(word='お電話。',start=1,end=2)])
        with self.assertRaises(ValueError):m.validate([(1,0,1,'お')],{'segments':[{'words':[dict(word='お',start=1,end=1)]}]},3,join_subwords=True)
    def test_bad_results_rejected(self):
        cue=[(1,10,20,'Bonjour')]
        for result in ({'segments':[]},{'segments':[{'words':[]}]},{'segments':[{'words':[dict(word='Bonjour',start=0,end=0)]}]},{'segments':[{'words':[dict(word='Bonjour',start=0,end=5)]}]},{'segments':[{'words':[dict(word='wrong',start=0,end=1)]}]},{'segments':[{'words':[dict(word='Bonjour',start=float('nan'),end=1)]}]}):
            with self.assertRaises(ValueError):m.validate(cue,result,3)
    def test_overlap_rejected(self):
        with self.assertRaises(ValueError):m.validate([(1,0,1,'bon jour')],{'segments':[{'words':[dict(word='bon',start=0,end=1),dict(word=' jour',start=.8,end=2)]}]},3)
    def test_wrapper_keeps_japanese_and_ignores_old_times(self):
        def worker(req,folder,cancel,progress):
            data=json.loads(req.read_text(encoding='utf8'));self.assertEqual(data['text'],'おはようございます。')
            (folder/'multilingual_result.json').write_text(json.dumps({'segments':[{'words':[dict(word=data['text'],start=.5,end=2)]}]}))
        with patch.object(m,'_worker_run',side_effect=worker):
            result=m.align([(1,80,90,'おはようございます。')],self.f,self.p,threading.Event(),lambda s:None,'ja',3)
        self.assertEqual(result[0][1:3],(.5,2.));self.assertTrue((self.p/'words.json').exists())
    def test_indonesian_reference_uses_model_not_old_times(self):
        from engine import playback_speed
        def worker(req,folder,cancel,progress):
            data=json.loads(req.read_text(encoding='utf8'))
            self.assertEqual(data['language'],'id')
            self.assertEqual(data['text'],'Pikiran pertama pada dasarnya tenang.')
            self.assertNotIn('start',data)
            (folder/'multilingual_result.json').write_text(json.dumps({'segments':[{'words':[dict(word=data['text'],start=.5,end=3.)]}]}),encoding='utf8')
        job=workflow.normalize(dict(language='id',alignment='auto',source_srt=str(self.f),video=str(self.f),audio=str(self.f),output=str(self.p)))
        self.assertEqual(job['alignment'],'multi');self.assertEqual(job['target_srt'],str(self.f))
        self.assertEqual(playback_speed(job),1.1)
        with patch.object(m,'_worker_run',side_effect=worker):
            result=m.align([(1,60,70,'Pikiran pertama pada dasarnya tenang.')],self.f,self.p,threading.Event(),lambda s:None,'id',4.)
        self.assertEqual(result[0][1:3],(.5,3.))
        self.assertEqual(result[0][3],'Pikiran pertama pada dasarnya tenang.')
        self.assertEqual(json.loads((self.p/'words.json').read_text(encoding='utf8'))['language'],'id')

    def test_french_segment_repartition(self):
        cues=[(1,20,30,'Vous êtes assis ici.'),(2,30,40,'Votre esprit s’arrête.')]
        result={'segments':[{'words':[{'word':'Vous êtes ', 'start':0.2,'end':1.0}]},
            {'words':[{'word':'assis ici.', 'start':1.1,'end':1.8}]},
            {'words':[{'word':'Votre esprit s’arrête.', 'start':2.0,'end':3.1}]}]}
        aligned,_,_=m.validate(cues,result,4)
        self.assertEqual(len(aligned),2)
        self.assertEqual(aligned[1][1:3],(2.0,3.1))

    def test_stop_worker(self):
        stop=threading.Event();stop.set()
        with self.assertRaises(m.Cancelled):m._worker_run(self.f,self.p,stop,lambda s:None)
if __name__=='__main__':unittest.main(verbosity=2)
