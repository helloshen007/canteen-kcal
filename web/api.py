from contextlib import asynccontextmanager
from datetime import timezone
import hashlib
import io
from pathlib import Path
import shutil
import uuid

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from web.config import ROOT, Settings
from web.database import Comparison, User, database, now
from web.queue import connection, enqueue, terminal_failure
from web.security import COOKIE, current_user, db_session, password_hash, password_matches, token_for


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r'^[a-zA-Z0-9_\-]+$')
    password: str = Field(min_length=8, max_length=128)


class UpdateComparison(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    note: str = Field(default='', max_length=2000)


class SampleRequest(BaseModel):
    sample_id: str
    mode: str = Field(default='replay', pattern=r'^(live|replay)$')


def samples():
    return __import__('json').loads((ROOT / 'web/examples/catalog.json').read_text())


def stamp(value):
    return value.replace(tzinfo=timezone.utc).isoformat()


def serialize(job, detail=True):
    out = {key:getattr(job,key) for key in ('id','filename','title','note','mode','sample_id','status',
                                           'a_status','b_status','a_error','b_error','a_attempts','b_attempts','generation','image_sha256')}
    out.update(created_at=stamp(job.created_at), updated_at=stamp(job.updated_at),
               image_url=f'/api/jobs/{job.id}/image', overlay_url=f'/api/jobs/{job.id}/overlay' if job.a_status=='success' else None)
    if detail:
        out.update(a_result=job.a_result,b_result=job.b_result)
    return out


def owned(session, job_id, user):
    job = session.get(Comparison,job_id)
    if job is None or job.owner_id != user.id:
        raise HTTPException(404,'记录不存在')
    return job


def interrupted(job):
    for method in ('a','b'):
        if getattr(job,f'{method}_status') in {'pending','running'}:
            setattr(job,f'{method}_status','failed')
            setattr(job,f'{method}_error','任务执行中断或未能进入队列，请重试')
    job.status = 'partial' if 'success' in (job.a_status,job.b_status) else 'failed'
    job.updated_at = now()


def publish(request, session, job):
    try:
        request.app.state.enqueue(job.id,job.generation)
    except Exception:
        interrupted(job)
        session.commit()
        # 保留记录及图片，服务恢复后可重试；不伪造成功结果。
    return serialize(job)


def create_record(request, session, user, content, filename, *, mode='live', sample_id=None):
    settings = request.app.state.settings
    if not content or len(content) > settings.max_upload_bytes:
        raise HTTPException(413,'图片不能为空且须小于 10 MiB')
    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.format not in {'JPEG','PNG','WEBP'} or image.width * image.height > settings.max_image_pixels:
                raise ValueError('unsupported image')
            extension = {'JPEG':'jpg','PNG':'png','WEBP':'webp'}[image.format]
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            image.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(422,'请上传可解码的 JPG、PNG 或 WebP 图片，像素总数不超过 1600 万') from None
    active = session.scalar(select(func.count()).select_from(Comparison).where(
        Comparison.owner_id==user.id, Comparison.status.in_(['queued','running'])))
    if active >= 3:
        raise HTTPException(429,'最多同时处理 3 个任务，请等待已有任务完成')
    identifier = uuid.uuid4().hex
    directory = settings.state_dir / 'jobs' / identifier
    target = directory / f'input.{extension}'
    try:
        directory.mkdir(parents=True)
        target.write_bytes(content)
    except OSError:
        shutil.rmtree(directory,ignore_errors=True)
        raise HTTPException(507,'图片保存失败，请检查服务器存储空间及目录权限') from None
    filename = Path(filename.replace('\\','/')).name[:120] or '餐盘图片'
    job = Comparison(id=identifier, owner_id=user.id, filename=filename, title=filename[:80],
                     input_path=target.relative_to(settings.state_dir).as_posix(),
                     image_sha256=hashlib.sha256(content).hexdigest(), mode=mode, sample_id=sample_id)
    session.add(job)
    try:
        session.commit()
    except Exception:
        session.rollback()
        shutil.rmtree(directory)
        raise
    return publish(request,session,job)


def create_app(settings=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        engine,sessions = database(settings)
        app.state.sessions = sessions
        app.state.secret = settings.secret()
        app.state.settings = settings
        app.state.enqueue = lambda identifier,generation: enqueue(settings,identifier,generation)
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(title='Canteen Lab 餐盘对比 API',version='3.0.0',lifespan=lifespan)

    @app.middleware('http')
    async def headers(request, call_next):
        if request.method not in {'GET','HEAD','OPTIONS'}:
            origin = request.headers.get('origin')
            if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
                raise_error = Response('跨来源写入已拒绝',status_code=403)
                return raise_error
        response = await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Content-Security-Policy']="default-src 'self'; img-src 'self' blob: data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        if request.url.path in {'/docs','/redoc'}:
            response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; img-src 'self' data: https://fastapi.tiangolo.com; connect-src 'self'; frame-ancestors 'none'"
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control']='no-store'
        return response

    @app.get('/api/health',tags=['系统'])
    def health(request: Request, session=Depends(db_session)):
        session.execute(select(1))
        try:
            from rq import Worker
            redis = connection(settings)
            redis.ping()
            workers = len(Worker.all(connection=redis,queue=None))
            queue_ready = True
        except Exception:
            queue_ready, workers = False,0
        from vlm.client import resolve_model_name
        import os
        configured = bool(os.getenv('VLM_API_KEY') and os.getenv('VLM_MODEL'))
        return {'status':'ok' if queue_ready and workers else 'degraded','database':True,
                'queue':queue_ready,'workers':workers,'vlm_configured':configured,
                'model':resolve_model_name(os.getenv('VLM_MODEL','')) if configured else None,
                'local_models':all((settings.model_dir/name).is_file() for name in ('yolov8s-worldv2.pt','sam_b.pt','clip/ViT-B-32.pt'))}

    def login_response(user, response, request):
        token = token_for(user,request.app.state.secret,settings.token_hours)
        response.set_cookie(COOKIE,token,httponly=True,samesite='strict',secure=settings.cookie_secure,
                            max_age=settings.token_hours*3600,path='/')
        return {'id':user.id,'username':user.username}

    @app.post('/api/auth/register',status_code=201,tags=['认证'])
    def register(data: Credentials,response: Response,request: Request,session=Depends(db_session)):
        user = User(username=data.username.lower(),password_hash=password_hash(data.password))
        session.add(user)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(409,'用户名已被使用') from None
        return login_response(user,response,request)

    @app.post('/api/auth/login',tags=['认证'])
    def login(data: Credentials,response: Response,request: Request,session=Depends(db_session)):
        user = session.scalar(select(User).where(User.username==data.username.lower()))
        if not user or not password_matches(data.password,user.password_hash):
            raise HTTPException(401,'用户名或密码错误')
        return login_response(user,response,request)

    @app.get('/api/auth/me',tags=['认证'])
    def me(user=Depends(current_user)):
        return {'id':user.id,'username':user.username}

    @app.post('/api/auth/logout',tags=['认证'])
    def logout(response: Response,user=Depends(current_user),session=Depends(db_session)):
        user.token_version += 1
        session.commit()
        response.delete_cookie(COOKIE,path='/')
        return {'ok':True}

    @app.get('/api/samples',tags=['样例'])
    def list_samples():
        return [{'id':s['id'],'title':s['title'],'description':s['description'],
                 'image_url':f"/api/samples/{s['id']}/image"} for s in samples()]

    @app.get('/api/samples/{sample_id}/image',tags=['样例'])
    def sample_image(sample_id: str):
        if sample_id not in {s['id'] for s in samples()}:
            raise HTTPException(404,'样例不存在')
        return FileResponse(ROOT/'web/examples'/sample_id/'input.jpg',media_type='image/jpeg')

    @app.post('/api/jobs/from-sample',status_code=202,tags=['对比任务'])
    def from_sample(data: SampleRequest,request: Request,user=Depends(current_user),session=Depends(db_session)):
        sample = next((s for s in samples() if s['id']==data.sample_id),None)
        if sample is None:
            raise HTTPException(404,'样例不存在')
        content = (ROOT/'web/examples'/sample['id']/'input.jpg').read_bytes()
        return create_record(request,session,user,content,f"{sample['title']}.jpg",mode=data.mode,sample_id=sample['id'])

    @app.post('/api/jobs',status_code=202,tags=['对比任务'])
    async def upload(request: Request,file: UploadFile=File(...),user=Depends(current_user),session=Depends(db_session)):
        content = await file.read(settings.max_upload_bytes+1)
        await file.close()
        return create_record(request,session,user,content,file.filename or '上传图片')

    @app.get('/api/jobs',tags=['对比任务'])
    def history(limit: int=Query(20,ge=1,le=100),offset: int=Query(0,ge=0),
                user=Depends(current_user),session=Depends(db_session)):
        selection = select(Comparison).where(Comparison.owner_id==user.id)
        total = session.scalar(select(func.count()).select_from(Comparison).where(Comparison.owner_id==user.id))
        jobs = session.scalars(selection.order_by(Comparison.created_at.desc()).limit(limit).offset(offset)).all()
        return {'items':[serialize(j,detail=False) for j in jobs],'total':total,'limit':limit,'offset':offset}

    @app.get('/api/jobs/{job_id}',tags=['对比任务'])
    def detail(job_id: str,user=Depends(current_user),session=Depends(db_session)):
        job = owned(session,job_id,user)
        if job.status in {'queued','running'} and terminal_failure(settings,job.id,job.generation):
            interrupted(job)
            session.commit()
        return serialize(job)

    @app.patch('/api/jobs/{job_id}',tags=['对比任务'])
    def update(job_id: str,data: UpdateComparison,user=Depends(current_user),session=Depends(db_session)):
        job = owned(session,job_id,user)
        if not data.title.strip():
            raise HTTPException(422,'标题不能为空')
        job.title,job.note = data.title.strip(),data.note
        session.commit()
        return serialize(job)

    @app.delete('/api/jobs/{job_id}',tags=['对比任务'])
    def delete(job_id: str,user=Depends(current_user),session=Depends(db_session)):
        job = owned(session,job_id,user)
        if job.status in {'queued','running'}:
            raise HTTPException(409,'任务执行中，完成后可删除')
        session.delete(job)
        session.commit()
        shutil.rmtree(settings.state_dir/'jobs'/job.id,ignore_errors=True)
        return {'ok':True}

    @app.post('/api/jobs/{job_id}/retry',status_code=202,tags=['对比任务'])
    def retry(job_id: str,request: Request,user=Depends(current_user),session=Depends(db_session)):
        job = owned(session,job_id,user)
        if job.status not in {'failed','partial'}:
            raise HTTPException(409,'仅失败或部分失败的任务可以重试')
        from sqlalchemy import update as sql_update
        generation = job.generation
        updated = session.execute(sql_update(Comparison).where(Comparison.id==job.id,Comparison.generation==generation,
                    Comparison.status.in_(['failed','partial'])).values(status='queued',generation=generation+1,
                    a_status='success' if job.a_status=='success' else 'pending',
                    b_status='success' if job.b_status=='success' else 'pending',a_error=None,b_error=None,updated_at=now()))
        if updated.rowcount != 1:
            session.rollback()
            raise HTTPException(409,'任务状态已变化，请刷新')
        session.commit()
        session.refresh(job)
        return publish(request,session,job)

    @app.get('/api/jobs/{job_id}/image',tags=['对比任务'])
    def image(job_id: str,user=Depends(current_user),session=Depends(db_session)):
        job = owned(session,job_id,user)
        return FileResponse(settings.state_dir/job.input_path)

    @app.get('/api/jobs/{job_id}/overlay',tags=['对比任务'])
    def overlay(job_id: str,user=Depends(current_user),session=Depends(db_session)):
        job = owned(session,job_id,user)
        path = settings.state_dir/'jobs'/job.id/'overlay.jpg'
        if job.a_status!='success' or not path.is_file():
            raise HTTPException(404,'检测结果尚未生成')
        return FileResponse(path,media_type='image/jpeg')

    app.mount('/static',StaticFiles(directory=ROOT/'web/static'),name='static')

    @app.get('/',include_in_schema=False)
    def index():
        return FileResponse(ROOT/'web/static/index.html')

    return app


app = create_app()
