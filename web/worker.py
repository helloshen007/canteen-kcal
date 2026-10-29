"""One model process per worker; RQ retains queued work in persistent Redis."""
from rq import Queue, SimpleWorker
from web.config import Settings
from web.database import database
from web.queue import connection


def main():
    settings = Settings()
    engine,_ = database(settings)
    engine.dispose()
    redis = connection(settings)
    queue = Queue(settings.queue_name,connection=redis,default_timeout=settings.task_timeout)
    SimpleWorker([queue],connection=redis,log_job_description=False,
                 worker_ttl=settings.task_timeout+120).work(logging_level='INFO')


if __name__=='__main__':
    main()
