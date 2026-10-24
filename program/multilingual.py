"""Local reference-guided multilingual alignment; never uses source timestamps as narration times."""
import json,math,os,re,subprocess,sys,time,unicodedata
from pathlib import Path
from media import Cancelled,executable
LANGUAGES={'en','ja','fr','de','es','it','ko','pt','zh','id'}
def text_key(text):
    text=re.sub('<[^>]*>','',text)
    return ''.join(c for c in unicodedata.normalize('NFKC',text).casefold() if c.isalnum())
def validate(cues,result,duration,join_subwords=False):
    segments=result.get('segments',[])
    # Some languages are split into different segment counts by the speech model.
    # Repartition word timestamps using the original reference text, not old SRT times.
    if len(segments)!=len(cues):
        all_words=[w for seg in segments for w in seg.get('words',[])]
        reference=''.join(text_key(c[3]) for c in cues)
        observed=''.join(text_key(w.get('word','')) for w in all_words)
        if observed!=reference:
            raise ValueError('定位文本与参考稿不一致，请检查配音和字幕文字。')
        rebuilt=[];pos=0
        for cue in cues:
            target=text_key(cue[3]);selected=[];matched=''
            while len(matched)<len(target) and pos<len(all_words):
                w=all_words[pos];pos+=1;selected.append(w);matched+=text_key(w.get('word',''))
            if matched!=target:
                raise ValueError(f'第{cue[0]}句跨越语音模型词边界，无法安全分句；请检查参考稿。')
            rebuilt.append({'words':selected})
        segments=rebuilt
    aligned=[];rows=[];ids=[];last=0.
    for cue,seg in zip(cues,segments):
        ident,_,_,text=cue
        words=seg.get('words',[])
        if not words or text_key(''.join(w['word'] for w in words))!=text_key(text):raise ValueError(f'第{ident}句未能完整定位文字；请核查这一句的配音与稿件。原SRT的旧时间不需要匹配配音。')
        if join_subwords:
            grouped=[];pending='';pending_start=None
            for w in words:
                a,b=float(w['start']),float(w['end'])
                if not all(map(math.isfinite,(a,b))) or a<0 or b<a or b>duration+.03:raise ValueError('定位时间无效。')
                if b==a:
                    pending+=w['word'];pending_start=a if pending_start is None else min(pending_start,a)
                else:
                    grouped.append(dict(word=pending+w['word'],start=min(a,pending_start) if pending_start is not None else a,end=b));pending='';pending_start=None
            if pending:
                if not grouped:raise ValueError(f'第{ident}句没有有效定位时长，已停止。旧SRT时间不需要匹配配音。')
                grouped[-1]['word']+=pending;grouped[-1]['end']=max(grouped[-1]['end'],pending_start)
            words=grouped
        for w in words:
            a,b=float(w['start']),float(w['end'])
            if not all(map(math.isfinite,(a,b))) or a<last-.001 or a<0 or b<=a or b>duration+.03:raise ValueError(f'第{ident}句的模型定位出现零时长、重叠或越界；旧SRT时间不需要匹配配音，须核查这一句的定位结果。')
            last=b;rows.append(dict(word=w['word'],start=a,end=b));ids.append(ident)
        aligned.append((ident,float(words[0]['start']),float(words[-1]['end']),text))
    return aligned,rows,ids

def _worker_run(request,folder,cancel,progress):
    if cancel.is_set():raise Cancelled()
    log_path=folder/'multilingual.log';status_path=folder/'alignment_progress.txt'
    with log_path.open('w',encoding='utf8') as log:
        env=os.environ.copy();env['PYTHONUTF8']='1';env['PYTHONUNBUFFERED']='1';env['PATH']=str(Path(executable('ffmpeg')).parent)+os.pathsep+env.get('PATH','')
        process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),str(request)],stdout=log,stderr=subprocess.STDOUT,env=env,creationflags=0x08000000 if os.name=='nt' else 0)
        last='';tick=time.monotonic()
        try:
            while process.poll() is None:
                if cancel.is_set():raise Cancelled()
                try:status=status_path.read_text(encoding='utf8')
                except OSError:status='正在准备本地定位组件'
                if status!=last or time.monotonic()-tick>=20:
                    progress(status+'（可停止）');last=status;tick=time.monotonic()
                time.sleep(.2)
        finally:
            if process.poll() is None:
                if os.name=='nt':subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                else:process.terminate()
                process.wait()
    if process.returncode:
        detail=log_path.read_text(encoding='utf8',errors='replace')[-1500:]
        raise RuntimeError('多语言定位未完成；首次需联网下载组件及模型。详细日志：'+str(log_path)+'\n'+detail)

def english_reference(cues):
    """Use English lines from a separately-lined bilingual reference, without translation."""
    output=[]
    for ident,a,b,text in cues:
        if re.search('[\u3400-\u9fff]',text):
            lines=[line for line in text.splitlines() if re.search('[a-zA-Z]',line) and not re.search('[\u3400-\u9fff]',line)]
            if not lines:raise ValueError(f'第{ident}句没有可单独使用的英文行；请选择与英语配音对应的英文参考稿。无需先改配音时间轴。')
            text='\n'.join(lines)
        output.append((ident,a,b,text))
    return output

def align(cues,audio,folder,cancel,progress,language,duration):
    if language not in LANGUAGES:raise ValueError('此语言尚未接入自动定位，请提供已校对的配音SRT。')
    if language=='en':cues=english_reference(cues)
    folder=Path(folder);request=folder/'alignment_request.json'
    text='\n'.join(re.sub('<[^>]*>','',c[3]).replace('\n',' ').strip() for c in cues)
    if any(not text_key(c[3]) for c in cues):raise ValueError('参考稿含空句。')
    request.write_text(json.dumps(dict(audio=str(Path(audio).resolve()),text=text,language=language),ensure_ascii=False),encoding='utf8')
    _worker_run(request,folder,cancel,progress)
    result=json.loads((folder/'multilingual_result.json').read_text(encoding='utf8'))
    try:
        aligned,rows,ids=validate(cues,result,duration,join_subwords=True)
    except ValueError as exc:
        (folder/'alignment_diagnostics.json').write_text(json.dumps(dict(status='failed',language=language,error=str(exc),reference_times_ignored=True),ensure_ascii=False,indent=2),encoding='utf8')
        raise ValueError(str(exc)+' 定位诊断：'+str(folder/'alignment_diagnostics.json')) from exc
    (folder/'alignment_diagnostics.json').write_text(json.dumps(dict(status='completed',language=language,reference_times_ignored=True,reference_cues=cues,aligned_cues=aligned),ensure_ascii=False,indent=2),encoding='utf8')
    (folder/'words.json').write_text(json.dumps(dict(backend='stable-ts-small-cpu',reference_guided=True,zero_duration_units_grouped=sum(float(w['end'])==float(w['start']) for seg in result.get('segments',[]) for w in seg.get('words',[])),language=language,words=rows,cue_ids=ids),ensure_ascii=False,indent=2),encoding='utf8')
    progress('多语言字词组定位完成，开始分析自然停顿')
    return aligned

def worker(request):
    folder=Path(request).parent
    def status(s):
        tmp=folder/'alignment_progress.writing';tmp.write_text(s,encoding='utf8');tmp.replace(folder/'alignment_progress.txt')
    status('检查多语言本地组件')
    try:import stable_whisper
    except ImportError:
        status('首次安装多语言组件，下载量较大，请保持联网')
        subprocess.run([sys.executable,'-m','pip','install','--disable-pip-version-check','--only-binary=:all:','--no-binary=stable-ts,openai-whisper','stable-ts==2.19.1'],check=True)
        import stable_whisper
    import torch
    torch.set_num_threads(max(1,min(4,os.cpu_count() or 1)))
    data=json.loads(Path(request).read_text(encoding='utf8'))
    cache=Path(os.environ.get('LOCALAPPDATA',Path.home()/'.cache'))/'YangNingStudio'/'models';cache.mkdir(parents=True,exist_ok=True)
    status('加载多语言模型 small；首次下载约460MB，之后复用')
    from model_cache import load_stable_model
    try:
        model=load_stable_model(stable_whisper,'small',cache,device='cpu')
    except (OSError,RuntimeError,ValueError) as exc:
        status('多语言模型加载失败，请查看 multilingual.log')
        raise RuntimeError('Whisper模型加载失败；请检查磁盘空间、模型缓存和网络。原有模型不会被直接删除。') from exc
    def update(done,total):status(f'本地多语言定位 {min(100,round(100*done/max(total,.01)))}%')
    status('正在按参考稿定位配音；电脑速度决定用时')
    result=model.align(data['audio'],data['text'],language=data['language'],original_split=True,regroup=False,verbose=None,progress_callback=update)
    if result is None:raise RuntimeError('未能定位，请检查配音与参考稿。')
    (folder/'multilingual_result.json').write_text(json.dumps(result.to_dict(),ensure_ascii=False),encoding='utf8')
    status('定位完成，检查逐句时间轴')
if __name__=='__main__':worker(sys.argv[1])
