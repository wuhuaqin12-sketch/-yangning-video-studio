"""Style logic, Unicode safety and an actual FFmpeg colour/cover export."""
import json,re,tempfile,threading,unittest
from pathlib import Path
from publish_style import *
from publish import make_ass,layout,compose,preview_cover,canvas_style
from media import run,executable,probe,parse_srt

class StyleTests(unittest.TestCase):
    def test_vertical_offset_bounds_and_persistence(self):
        stream={'width':854,'height':480}
        default=layout(normalize_style({}),stream,1080,1920)
        moved=layout(normalize_style({'subtitle_offset_y':100}),stream,1080,1920)
        self.assertAlmostEqual(moved[-1]-default[-1],100)
        for offset in (-400,400):
            vw,vh,vx,vy,sw,sh,sx,sy=layout(normalize_style({'subtitle_offset_y':offset}),stream,1080,1920)
            self.assertGreaterEqual(sy-sh/2,vy+vh+12)
            self.assertLessEqual(sy+sh/2,1920*.9)
        for invalid in (-401,401,float('nan'),float('inf'),'abc'):
            with self.assertRaises(ValueError):normalize_style({'subtitle_offset_y':invalid})
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'style.json';save_preset(path,{'subtitle_offset_y':110})
            self.assertEqual(load_preset(path)['subtitle_offset_y'],110)
            path.write_text(json.dumps({'format':'YangNingPublishStyle','version':1,'settings':{'subtitle_y':76}}))
            self.assertEqual(load_preset(path)['subtitle_offset_y'],0)

    def test_background_area_keeps_two_lines_below_teacher(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'below.ass'
            for stream in ({'width':854,'height':480},{'width':640,'height':480}):
                for text in ('本当の自由と無我を理解する。'*4,
                             'Keep both lines entirely below the teacher video. '*5):
                    make_ass(p,[(1,0,8,text)],{},stream,8,1080,1920)
                    report=json.loads((p.parent/'layout_report.json').read_text())
                    vx,vy,vw,vh=report['video_box'];left,top,right,bottom=report['subtitle_box']
                    self.assertGreaterEqual(top,vy+vh+38)
                    self.assertLessEqual(bottom,1920*.9)
                    self.assertEqual(report['subtitle_center'][0],540)
                    cues=parse_srt(p.parent/'publish_subtitles.srt')
                    self.assertTrue(any(len(t.splitlines())==2 for _,a,b,t in cues))
                    self.assertTrue(all(len(t.splitlines())<=2 for _,a,b,t in cues))
                    self.assertIn(r'\clip(',p.read_text(encoding='utf-8-sig'))

    def test_old_background_preset_migrates_and_no_background_stays_inline(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            bg=Path(d)/'bg.png';Image.new('RGB',(108,192),'black').save(bg)
            stream={'width':854,'height':480}
            old=normalize_style(dict(background=str(bg),subtitle_area='video',subtitle_y=76))
            opts,w,h=canvas_style({**old,'background':str(bg)},stream)
            self.assertEqual(opts['subtitle_area'],'below_video')
            opts,w,h=canvas_style({**old,'background':''},stream)
            self.assertEqual(opts['subtitle_area'],'video')
            self.assertEqual((w,h),(854,480))
            layout(opts,stream,w,h)
            with self.assertRaisesRegex(ValueError,'下方不足'):
                layout(normalize_style({}),{'width':1080,'height':1920},1080,1920)

    def test_defaults_and_colour_conversion(self):
        self.assertEqual(DEFAULTS['subtitle_font_size'],70)
        self.assertEqual(DEFAULTS['title_font_size'],230)
        self.assertEqual(DEFAULTS['title_font'],'Yuji Boku')
        self.assertEqual(DEFAULTS['font'],'Noto Serif CJK JP')
        self.assertEqual(ass_colour('#123456'),'&H00563412')
        self.assertEqual(ass_colour('#123456',True),'&H563412&')
    def test_literal_keywords_and_longest_match(self):
        o=normalize_style(dict(keywords='空=#FF0000\n空性=#00FF00\na.b=#0000FF'))
        colours=matched_colours('空性 空 a.b axb',o)
        self.assertEqual(colours[0],'#00FF00');self.assertEqual(colours[1],'#00FF00')
        self.assertNotIn(10,colours)
    def test_keyword_spans_survive_wrapping(self):
        o=normalize_style(dict(keywords='無我=#E53935'))
        text='無我';lines=line_parts(text,1)
        styled=styled_lines(text,lines,o)
        self.assertEqual(styled.count(r'\1c&H3539E5&'),2)
        self.assertIn(r'\N',styled)
        self.assertEqual(re.sub(r'\{[^}]+\}','',styled).replace(r'\N',''),text)
    def test_case_and_optional_whole_words(self):
        o=normalize_style(dict(keywords='mind=#00FF00',keyword_whole_words=True))
        c=matched_colours('Mind remind MIND',o)
        self.assertIn(0,c);self.assertNotIn(7,c);self.assertIn(12,c)
        o['keyword_ignore_case']=False
        self.assertNotIn(0,matched_colours('Mind',o))
    def test_multilingual_text_and_combining_marks(self):
        for text in ['日本語 無我','中文 空性','Français déjà','bahasa Indonesia','한국어','العربية','हिन्दी']:
            o=normalize_style(dict(keywords=text+'=#FF0000'))
            size,lines=fit_lines(text,47,900,400)
            result=styled_lines(text,lines,o)
            plain=re.sub(r'\{[^}]+\}','',result).replace(r'\N','')
            self.assertEqual(plain,text)
        self.assertEqual(len(clusters('e\u0301')),1)
        self.assertEqual(len(clusters('क्\u200dष')),1)
    def test_bad_colours_and_ass_injection(self):
        for c in ['red','#FF0000,evil','#12345','&HFFFFFF&']:
            with self.assertRaises(ValueError):normalize_style(dict(subtitle_color=c))
        o=normalize_style(dict(auto_fit='False',keywords='無我=#E53935'))
        self.assertFalse(o['auto_fit'])
        t=clean(r'{\pos(0,0)}無我');_,lines=fit_lines(t,20,900,400)
        result=styled_lines(t,lines,o)
        self.assertNotIn(r'{\pos',result)
        with self.assertRaises(ValueError):normalize_style(dict(keywords='無我=invalid'))
    def test_preset_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'样式.json';save_preset(p,dict(title='本来の姿',subtitle_color='#f0aabb',keywords='無我=#E53935'))
            o=load_preset(p);self.assertEqual(o['title'],'本来の姿');self.assertEqual(o['subtitle_color'],'#F0AABB')
            self.assertEqual(o['keywords'],'無我=#E53935')
    def test_fixed_size_rejects_overflow(self):
        with self.assertRaises(ValueError):fit_lines('A'*200,47,200,50,False)
    def test_long_title_fits_without_changing_subtitle_size(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'long_title.ass'
            make_ass(p,[(1,1,4,'本当の姿')],dict(title='本来の姿を見つめる 心を静める',title_font_size=230,auto_fit=False),{'width':854,'height':480},5,1080,1920)
            report=json.loads((p.parent/'layout_report.json').read_text())
            self.assertEqual(report['subtitle_actual_px'],[70])
            self.assertLessEqual(report['title_actual_px'],230)
            self.assertGreaterEqual(report['title_actual_px'],10)
            self.assertIn('本来の姿',p.read_text(encoding='utf-8-sig'))

    def test_long_multilingual_cues_split_two_lines_without_shrinking(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'test.ass'
            for language,text in [('ja','心を静めて集中する'*22),('en','Focus your attention inward and stay still. '*12),('fr','Concentrez votre esprit vers l’intérieur. '*12),('id','Tenangkan pikiran dan pusatkan perhatian. '*12)]:
                make_ass(path,[(1,0,12,text)],dict(),{'width':854,'height':480},12,1080,1920)
                report=json.loads((path.parent/'layout_report.json').read_text())
                self.assertEqual(report['subtitle_actual_px'],[70],language)
                self.assertEqual(report['shrunk_cues'],[],language)
                self.assertGreater(report['display_cue_count'],1,language)
                cues=parse_srt(path.parent/'publish_subtitles.srt')
                self.assertTrue(all(len(t.splitlines())<=2 for _,a,b,t in cues),language)
                self.assertAlmostEqual(cues[0][1],0,delta=.01)
                self.assertAlmostEqual(cues[-1][2],12,delta=.01)

    def test_position_size_and_all_languages_share_style(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'p.ass'
            for language in ['ja','en','fr','de','es','it','ko','pt','zh','id','other']:
                opts=normalize_style(dict(title='本来の姿',title_y=25,subtitle_x=45,subtitle_width=70,subtitle_color='#11AAFF',language=language))
                make_ass(p,[(1,.1,1.,'無我')],opts,{'width':854,'height':480},2,1080,1920)
                report=json.loads((p.parent/'layout_report.json').read_text())
                self.assertEqual(report['title_actual_px'],230)
                self.assertEqual(report['subtitle_actual_px'],[70])
                self.assertEqual(report['subtitle_center'][0],540)
                self.assertGreater(report['subtitle_box'][1],sum(report['video_box'][1::2]))
                self.assertEqual(report['video_box'][2],1080)

class RenderTests(unittest.TestCase):
    def test_actual_vertical_shift_preserves_two_lines_and_teacher(self):
        import numpy as np
        from PIL import Image
        with tempfile.TemporaryDirectory(prefix='yn-offset-') as d:
            p=Path(d);cancel=threading.Event()
            run([executable('ffmpeg'),'-v','error','-y','-f','lavfi','-i','color=c=0x555555:s=640x360:r=10:d=1','-f','lavfi','-i','sine=frequency=440:duration=1','-c:v','libx264','-threads','2','-c:a','aac','-shortest',str(p/'in.mp4')],cancel)
            Image.new('RGB',(1080,1920),'black').save(p/'bg.png')
            (p/'in.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\nKeep both subtitle lines below the teacher video, safely on the black background.\n')
            opts=dict(video=str(p/'in.mp4'),srt=str(p/'in.srt'),background=str(p/'bg.png'),output=str(p),font='DejaVu Sans',preview_time=.5)
            previous=None;glyph_tops={}
            for offset in (0,100,-400,400):
                preview=Path(compose({**opts,'subtitle_offset_y':offset},cancel,preview=True))
                with Image.open(preview) as image:pixels=np.asarray(image.convert('RGB'))
                report=json.loads((preview.parent/'layout_report.json').read_text())
                vx,vy,vw,vh=report['video_box'];teacher=pixels[vy:vy+vh,vx:vx+vw]
                if previous is not None:self.assertTrue(np.array_equal(previous,teacher))
                previous=teacher.copy()
                ys,xs=np.where((pixels[:,:,0]>200)&(pixels[:,:,1]>200)&(pixels[:,:,2]>200))
                self.assertGreater(ys.min(),vy+vh)
                self.assertLess(ys.max(),1920*.9)
                rows=np.unique(ys);self.assertEqual(1+np.count_nonzero(np.diff(rows)>1),2)
                glyph_tops[offset]=ys.min()
            self.assertAlmostEqual(glyph_tops[100]-glyph_tops[0],100,delta=1)

    def test_actual_render_highlights_and_cover(self):
        import numpy as np
        from PIL import Image
        with tempfile.TemporaryDirectory(prefix='yn-style-') as d:
            p=Path(d);c=threading.Event();ff=executable('ffmpeg')
            run([ff,'-v','error','-y','-f','lavfi','-i','color=c=0x303030:size=512x288:rate=24:duration=2','-f','lavfi','-i','sine=frequency=440:sample_rate=24000:duration=2','-c:v','libx264','-threads','2','-c:a','aac','-shortest',str(p/'input.mp4')],c)
            Image.new('RGB',(540,960),(240,230,210)).save(p/'background.png')
            text='1\n00:00:00,100 --> 00:00:00,950\n無我と空性\nMind is calm\n\n2\n00:00:01,050 --> 00:00:01,900\n本来の姿 / Français / Indonesia\n'
            (p/'final.srt').write_text(text,encoding='utf8')
            opts=dict(video=str(p/'input.mp4'),srt=str(p/'final.srt'),background=str(p/'background.png'),output=str(p/'output'),title='本来の姿',title_y=25,keywords='無我=#E53935\n空性=#00FF00\nMind=#0000FF',preview_time=.5,cover_mode='frame',cover_time=.5)
            preview=Path(compose(opts,c,preview=True))
            report=json.loads((preview.parent/'layout_report.json').read_text())
            left,top,right,bottom=map(round,report['subtitle_box'])
            pixels=np.asarray(Image.open(preview).convert('RGB'))[top:bottom,left:right]
            self.assertGreater(((pixels[:,:,0]>140)&(pixels[:,:,1]<100)&(pixels[:,:,2]<120)).sum(),20)
            self.assertGreater(((pixels[:,:,1]>140)&(pixels[:,:,0]<100)&(pixels[:,:,2]<120)).sum(),20)
            self.assertGreater(((pixels[:,:,2]>140)&(pixels[:,:,0]<100)&(pixels[:,:,1]<120)).sum(),20)
            video=Path(compose(opts,c));self.assertTrue((video.parent/'cover.png').is_file())
            self.assertEqual((video.parent/'subtitles.srt').read_bytes(),(p/'final.srt').read_bytes())
            info=probe(video,c);self.assertAlmostEqual(float(info['format']['duration']),2,delta=.1)
            for source,name in [(p/'input.mp4','before.aac'),(video,'after.aac')]:
                run([ff,'-v','error','-y','-i',str(source),'-map','0:a:0','-c:a','copy',str(p/name)],c)
            self.assertEqual((p/'before.aac').read_bytes(),(p/'after.aac').read_bytes())
            self.assertEqual(Image.open(video.parent/'cover.png').size,(1080,1920))
            upload=preview_cover(dict(output=str(p/'cover_output'),cover_mode='upload',cover_image=str(p/'background.png')),c)
            self.assertEqual(Image.open(upload).size,(1080,1920))
            bad={**opts,'cover_time':3}
            with self.assertRaises(ValueError):compose(bad,c,preview=True)
            print('STYLE_RENDER_PASS: red/green/blue keywords, cover frame/upload, unchanged SRT/audio and duration')

if __name__=='__main__':unittest.main(verbosity=2)
