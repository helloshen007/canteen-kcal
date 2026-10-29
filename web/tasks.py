import json
from pathlib import Path
import shutil

from sqlalchemy import update

from compare.provenance import evaluation_context, load_prediction
from web.config import ROOT, Settings
from web.database import Comparison, database, now
from web.inference import InferenceError, prepare_input, run_a, run_b


def replay(job,method,directory):
    from vlm.run_vlm import to_result
    from web.inference import nutrition
    source = ROOT/'web/examples'/job.sample_id
    expected = __import__('hashlib').sha256((source/'input.jpg').read_bytes()).hexdigest()
    if expected != job.image_sha256:
        raise InferenceError('样例图片与历史记录不匹配')
    result = load_prediction(source/f'{method}.json',evaluation_context())
    if method=='b':
        parsed = to_result(result['raw'],evaluation_context()['vocabulary'],nutrition())
        if any(parsed[k]!=result[k] for k in ('dishes','total')):
            raise InferenceError('历史回复与预测不一致')
    else:
        shutil.copyfile(source/'overlay.jpg',directory/'overlay.jpg')
    result['provenance'] = {'mode':'replay','source':'evidence/revalidated','sample_id':job.sample_id,
                            'model':'YOLO-World + SAM' if method=='a' else result['experiment']['model']}
    return result


def run_comparison(identifier,generation,settings=None):
    settings = settings or Settings()
    engine,sessions = database(settings)
    try:
        with sessions() as session:
            claimed = session.execute(update(Comparison).where(Comparison.id==identifier,
                       Comparison.generation==generation,Comparison.status=='queued').values(status='running',updated_at=now()))
            session.commit()
            if claimed.rowcount != 1:
                return
            job = session.get(Comparison,identifier)
            directory = settings.state_dir/'jobs'/identifier
            try:
                inference_image = directory/'analysis.png'
                if job.mode=='live':
                    prepare_input(settings.state_dir/job.input_path,inference_image)
            except Exception:
                for method in ('a','b'):
                    if getattr(job,f'{method}_status')!='success':
                        setattr(job,f'{method}_status','failed')
                        setattr(job,f'{method}_error','图片预处理失败，请检查图片后重新提交')
                job.status='partial' if 'success' in (job.a_status,job.b_status) else 'failed'
                session.commit()
                return
            for method,runner in (('a',run_a),('b',run_b)):
                session.refresh(job)
                if job.generation != generation or job.status!='running':
                    return
                if getattr(job,f'{method}_status')=='success':
                    continue
                setattr(job,f'{method}_status','running')
                setattr(job,f'{method}_attempts',getattr(job,f'{method}_attempts')+1)
                session.commit()
                try:
                    result = replay(job,method,directory) if job.mode=='replay' else runner(inference_image,directory,settings)
                    # Persist only explicit validated success; exceptions leave result NULL.
                    if result.get('status')!='success':
                        raise InferenceError('推理未返回成功结果')
                    values = {f'{method}_result':result,f'{method}_status':'success',f'{method}_error':None,'updated_at':now()}
                except Exception as exc:
                    message = str(exc) if isinstance(exc,InferenceError) else '推理执行失败，请检查模型配置后重试'
                    values = {f'{method}_result':None,f'{method}_status':'failed',f'{method}_error':message,'updated_at':now()}
                # Generation guard prevents a delayed old worker from overwriting a retry.
                session.execute(update(Comparison).where(Comparison.id==identifier,Comparison.generation==generation,
                                Comparison.status=='running').values(**values))
                session.commit()
            session.refresh(job)
            if job.generation != generation or job.status!='running':
                return
            statuses = (job.a_status,job.b_status)
            job.status = 'succeeded' if statuses==('success','success') else 'partial' if 'success' in statuses else 'failed'
            session.commit()
    finally:
        engine.dispose()
