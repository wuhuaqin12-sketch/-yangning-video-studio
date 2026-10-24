"""UI-independent job normalization and explicit task state transitions."""
from pathlib import Path
from engine import prepare,render,Cancelled
from multilingual import LANGUAGES

def normalize(job):
    job=dict(job)
    # Removed features cannot be re-enabled by old queues or imported jobs.
    job.update(denoise=False,separate=False,mute=False)
    job.pop('clean_mode',None)
    if job.get('audio_profile') not in (None,'off','v11','v11_deep'):raise ValueError('未知的声音处理选项。')
    job['audio_separate']=job.get('audio_separate') is True
    job['erase_method']='off';job['shots']='';job.pop('_cleanup_profile',None)
    if not job.get('audio') and job.get('video'):
        job['audio']=job['video']  # Reuse the source video's audio when no replacement is selected.
    job.setdefault('language','en');job.setdefault('alignment','auto')
    if job['alignment'] in ('auto','english'):
        job['alignment']='multi' if job['language'] in LANGUAGES else 'timed'
    if not job.get('target_srt'):
        if job['alignment'] in ('english','multi'):job['target_srt']=job.get('source_srt','')
        else:raise ValueError('已校对时间轴模式或未列出的语言，请在更多设置中选择匹配配音的SRT。')
    for key,label in [('video','原视频'),('audio','目标配音'),('source_srt','原视频SRT'),('target_srt','配音参考SRT')]:
        if not job.get(key) or not Path(job[key]).is_file():raise ValueError('请选择有效的'+label+'文件。')
    if not job.get('output'):raise ValueError('请选择输出文件夹。')
    return job

def execute(job,cancel,emit,export=True):
    """Emit terminal states even if validation/alignment fails. Never requeue failure."""
    ident=job['id']
    def state(label,**extra):emit(('state',ident,label,extra))
    def progress(s):emit(('progress',ident,s))
    state('检查素材',error='',analysis=None,result=None)
    try:
        job=normalize(job)
        if cancel.is_set():raise Cancelled()
        progress('开始检查与分析；任务已启动')
        folder=prepare(job,cancel,progress)
        state('待导出',analysis=folder)
        if export:
            if cancel.is_set():raise Cancelled()
            state('正在导出',analysis=folder)
            render(folder,cancel,progress)
            state('完成·检查通过',analysis=folder,result=folder)
            progress('处理完成：'+str(Path(folder)/'video.mp4'))
        else:progress('分析完成，可试听原配音/优化配音。')
        return folder
    except Cancelled:
        state('已停止',error='用户停止了任务');progress('已停止；原始素材未修改。')
    except Exception as e:
        state('失败',error=str(e));progress('失败：'+str(e))
    return None
